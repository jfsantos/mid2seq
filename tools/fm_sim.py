#!/usr/bin/env python3
"""
fm_sim.py — SCSP FM synthesis simulator.

Renders FM patches to WAV files using the same phase modulation math
as the Saturn's YMF292 (SCSP) sound chip. Useful for auditioning patches
before committing to hardware.

Usage:
  python3 fm_sim.py                          # Render all preset patches
  python3 fm_sim.py --patch epiano           # Render one patch
  python3 fm_sim.py --config patch.json      # Render custom patch
  python3 fm_sim.py --list                   # List available presets
  python3 fm_sim.py --patch epiano --note 60 --duration 2.0 --wav out.wav

The simulator models:
  - Phase modulation (carrier address offset by modulator output)
  - SCSP ADSR envelope (AR/D1R/DL/D2R/RR with hardware rate tables)
  - MDL scaling (exponential modulation depth)
  - Self-feedback (operator reads its own previous output)
  - Multi-operator topologies (2-op, 4-op, arbitrary wiring)
"""

import math
import struct
import sys
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

SAMPLE_RATE = 44100

# ── SCSP ADSR Envelope ─────────────────────────────────────────────

# Attack times in ms (from MAME, indexed by rate value 0-31)
AR_TIMES = [
    100000, 100000, 8100.0, 6900.0, 6000.0, 4800.0, 4000.0, 3400.0,
    3000.0, 2400.0, 2000.0, 1700.0, 1500.0, 1200.0, 1000.0, 860.0,
    760.0, 600.0, 500.0, 430.0, 380.0, 300.0, 250.0, 220.0,
    190.0, 150.0, 130.0, 110.0, 95.0, 76.0, 63.0, 55.0,
]

# Decay/release times in ms (from MAME, indexed by rate value 0-31)
DR_TIMES = [
    100000, 100000, 118200.0, 101300.0, 88600.0, 70900.0, 59100.0, 50700.0,
    44300.0, 35500.0, 29600.0, 25300.0, 22200.0, 17700.0, 14800.0, 12700.0,
    11100.0, 8900.0, 7400.0, 6300.0, 5500.0, 4400.0, 3700.0, 3200.0,
    2800.0, 2200.0, 1800.0, 1600.0, 1400.0, 1100.0, 920.0, 790.0,
]


class SCSPEnvelope:
    """SCSP hardware envelope generator."""

    def __init__(self, ar=31, d1r=0, dl=0, d2r=0, rr=14):
        # Convert hardware rates to per-sample increments
        # Attack: ramps from 0.0 to 1.0
        ar_ms = AR_TIMES[min(ar, 31)]
        self.attack_rate = 1.0 / max(1, ar_ms * SAMPLE_RATE / 1000)

        # Decay 1: ramps from 1.0 to sustain level
        d1r_ms = DR_TIMES[min(d1r, 31)] if d1r > 0 else 100000
        self.decay1_rate = 1.0 / max(1, d1r_ms * SAMPLE_RATE / 1000)
        self.sustain_level = 1.0 - (dl / 31.0) if dl < 31 else 0.0

        # Decay 2: ramps from sustain to 0
        d2r_ms = DR_TIMES[min(d2r, 31)] if d2r > 0 else 100000
        self.decay2_rate = 1.0 / max(1, d2r_ms * SAMPLE_RATE / 1000)

        # Release: ramps to 0 after note-off
        rr_ms = DR_TIMES[min(rr, 31)]
        self.release_rate = 1.0 / max(1, rr_ms * SAMPLE_RATE / 1000)

        self.level = 0.0
        self.phase = 'attack'

    def note_off(self):
        self.phase = 'release'

    def tick(self):
        if self.phase == 'attack':
            self.level += self.attack_rate
            if self.level >= 1.0:
                self.level = 1.0
                self.phase = 'decay1'

        elif self.phase == 'decay1':
            self.level -= self.decay1_rate
            if self.level <= self.sustain_level:
                self.level = self.sustain_level
                self.phase = 'decay2'

        elif self.phase == 'decay2':
            self.level -= self.decay2_rate
            if self.level <= 0.0:
                self.level = 0.0
                self.phase = 'off'

        elif self.phase == 'release':
            self.level -= self.release_rate
            if self.level <= 0.0:
                self.level = 0.0
                self.phase = 'off'

        return self.level


# ── FM Operator ─────────────────────────────────────────────────────

@dataclass
class Operator:
    """One FM operator (corresponds to one SCSP slot)."""
    freq_ratio: float = 1.0     # frequency ratio to fundamental
    freq_fixed: float = 0.0     # fixed frequency in Hz (0 = use ratio)
    level: float = 1.0          # output level (0.0-1.0, maps to TL)
    # SCSP envelope
    ar: int = 31
    d1r: int = 0
    dl: int = 0
    d2r: int = 0
    rr: int = 14
    # Modulation
    mdl: int = 0                # modulation depth (0-15, 0-4=off)
    mod_source: int = -1        # which operator modulates this one (-1=none)
    feedback: float = 0.0       # self-feedback level (0.0-1.0)
    # Output
    is_carrier: bool = True     # carrier outputs to speakers, modulator doesn't


@dataclass
class FMPatch:
    """A complete FM patch (multiple operators)."""
    name: str = "FM Patch"
    operators: List[Operator] = field(default_factory=list)


# ── Simulator ───────────────────────────────────────────────────────

def render_note(patch: FMPatch, note: int = 69, duration: float = 1.0,
                release: float = 0.5, sample_rate: int = SAMPLE_RATE) -> list:
    """Render an FM patch as a single note to float samples."""

    fundamental = 440.0 * (2.0 ** ((note - 69) / 12.0))
    total_samples = int((duration + release) * sample_rate)
    note_off_sample = int(duration * sample_rate)

    n_ops = len(patch.operators)

    # Sine wave table (one cycle, 1024 samples for precision)
    TABLE_SIZE = 1024
    sine_table = [math.sin(2 * math.pi * i / TABLE_SIZE) for i in range(TABLE_SIZE)]

    # Per-operator state
    phases = [0.0] * n_ops
    envelopes = []
    prev_outputs = [0.0] * n_ops
    freq_steps = []

    for op in patch.operators:
        envelopes.append(SCSPEnvelope(op.ar, op.d1r, op.dl, op.d2r, op.rr))
        if op.freq_fixed > 0:
            freq = op.freq_fixed
        else:
            freq = fundamental * op.freq_ratio
        freq_steps.append(freq * TABLE_SIZE / sample_rate)

    output = []

    for i in range(total_samples):
        if i == note_off_sample:
            for env in envelopes:
                env.note_off()

        # Process operators in order (lower index = processed first)
        op_outputs = [0.0] * n_ops

        for oi, op in enumerate(patch.operators):
            env_level = envelopes[oi].tick()

            # Phase modulation from source operator
            mod_offset = 0.0
            if op.mod_source >= 0 and op.mod_source < n_ops and op.mdl >= 5:
                # SCSP MDL scaling: exponential, each step ~doubles depth
                # mdl_scale maps MDL 5-15 to useful modulation indices
                mdl_scale = 2.0 ** (op.mdl - 10)  # MDL 10 ≈ 1.0 modulation index
                mod_value = op_outputs[op.mod_source] if op.mod_source < oi else prev_outputs[op.mod_source]
                mod_offset = mod_value * mdl_scale * TABLE_SIZE

            # Self-feedback
            if op.feedback > 0:
                mod_offset += prev_outputs[oi] * op.feedback * TABLE_SIZE * 0.5

            # Read from sine table with phase modulation
            read_pos = phases[oi] + mod_offset
            idx = int(read_pos) % TABLE_SIZE
            frac = read_pos - int(read_pos)
            # Linear interpolation
            s0 = sine_table[idx % TABLE_SIZE]
            s1 = sine_table[(idx + 1) % TABLE_SIZE]
            sample = s0 + (s1 - s0) * frac

            # Apply envelope and level
            op_outputs[oi] = sample * env_level * op.level

            # Advance phase
            phases[oi] += freq_steps[oi]

        # Store for next iteration's feedback/cross-modulation
        prev_outputs = list(op_outputs)

        # Mix carrier outputs
        mix = sum(op_outputs[oi] for oi, op in enumerate(patch.operators) if op.is_carrier)
        output.append(mix)

    # Normalize
    peak = max(abs(s) for s in output) or 1.0
    if peak > 1.0:
        output = [s / peak * 0.9 for s in output]

    return output


def write_wav(samples, filename, sample_rate=SAMPLE_RATE):
    """Write float samples to a 16-bit WAV file."""
    import wave
    with wave.open(filename, 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        for s in samples:
            val = max(-32768, min(32767, int(s * 32000)))
            w.writeframes(struct.pack('<h', val))


# ── Preset Patches ──────────────────────────────────────────────────

PRESETS = {
    'sine': FMPatch('Sine', [
        Operator(freq_ratio=1.0, level=0.8, ar=31, d1r=0, rr=14),
    ]),

    'epiano': FMPatch('Electric Piano', [
        # Modulator: 2:1 ratio, decaying envelope
        Operator(freq_ratio=2.0, level=0.9, ar=31, d1r=12, dl=8, rr=14,
                 is_carrier=False),
        # Carrier: fundamental, modulated by op 0
        Operator(freq_ratio=1.0, level=0.8, ar=31, d1r=6, dl=2, rr=14,
                 mdl=9, mod_source=0),
    ]),

    'epiano2': FMPatch('Electric Piano 2 (DX7-like)', [
        # Modulator 1: 14:1 ratio (inharmonic brightness)
        Operator(freq_ratio=14.0, level=0.4, ar=31, d1r=14, dl=12, rr=16,
                 is_carrier=False),
        # Modulator 2: 1:1 ratio (warmth)
        Operator(freq_ratio=1.0, level=0.7, ar=31, d1r=10, dl=6, rr=14,
                 is_carrier=False, mdl=8, mod_source=0),
        # Carrier
        Operator(freq_ratio=1.0, level=0.8, ar=31, d1r=4, dl=2, rr=12,
                 mdl=9, mod_source=1),
    ]),

    'bell': FMPatch('Bell', [
        # Modulator: inharmonic ratio for bell-like partials
        Operator(freq_ratio=3.5, level=0.9, ar=31, d1r=4, dl=2, rr=8,
                 is_carrier=False),
        # Carrier: sustained with slow decay
        Operator(freq_ratio=1.0, level=0.7, ar=31, d1r=2, dl=0, rr=6,
                 mdl=11, mod_source=0),
    ]),

    'brass': FMPatch('Brass', [
        # Modulator: 1:1 ratio, moderate attack
        Operator(freq_ratio=1.0, level=0.8, ar=24, d1r=4, dl=2, rr=14,
                 is_carrier=False, feedback=0.3),
        # Carrier
        Operator(freq_ratio=1.0, level=0.8, ar=22, d1r=2, dl=0, rr=14,
                 mdl=9, mod_source=0),
    ]),

    'organ': FMPatch('Organ', [
        # Modulator: feedback creates sawtooth-like spectrum
        Operator(freq_ratio=1.0, level=0.7, ar=31, d1r=0, dl=0, rr=20,
                 is_carrier=False, feedback=0.6),
        # Carrier
        Operator(freq_ratio=1.0, level=0.8, ar=31, d1r=0, dl=0, rr=20,
                 mdl=8, mod_source=0),
    ]),

    'bass': FMPatch('FM Bass', [
        # Modulator: 1:1, fast decay for punch
        Operator(freq_ratio=1.0, level=0.9, ar=31, d1r=14, dl=10, rr=14,
                 is_carrier=False, feedback=0.2),
        # Carrier
        Operator(freq_ratio=1.0, level=0.9, ar=31, d1r=6, dl=4, rr=14,
                 mdl=10, mod_source=0),
    ]),

    'strings': FMPatch('FM Strings', [
        # Modulator: slight detuning for chorus effect
        Operator(freq_ratio=1.002, level=0.5, ar=20, d1r=0, dl=0, rr=16,
                 is_carrier=False),
        # Carrier
        Operator(freq_ratio=1.0, level=0.7, ar=18, d1r=0, dl=0, rr=14,
                 mdl=7, mod_source=0),
    ]),

    'clav': FMPatch('Clavinet', [
        # Modulator: 3:1 ratio, fast decay
        Operator(freq_ratio=3.0, level=0.9, ar=31, d1r=16, dl=14, rr=18,
                 is_carrier=False),
        # Carrier
        Operator(freq_ratio=1.0, level=0.8, ar=31, d1r=10, dl=6, rr=16,
                 mdl=10, mod_source=0),
    ]),

    'marimba': FMPatch('Marimba', [
        # Modulator: 4:1, very fast decay (just the attack transient)
        Operator(freq_ratio=4.0, level=0.8, ar=31, d1r=18, dl=16, rr=20,
                 is_carrier=False),
        # Carrier: moderate decay
        Operator(freq_ratio=1.0, level=0.8, ar=31, d1r=8, dl=4, rr=12,
                 mdl=9, mod_source=0),
    ]),

    'metallic': FMPatch('Metallic', [
        # Two modulators with inharmonic ratios
        Operator(freq_ratio=1.414, level=0.6, ar=31, d1r=6, dl=3, rr=10,
                 is_carrier=False, feedback=0.4),
        Operator(freq_ratio=3.82, level=0.5, ar=31, d1r=8, dl=4, rr=12,
                 is_carrier=False),
        # Carrier modulated by both
        Operator(freq_ratio=1.0, level=0.7, ar=31, d1r=4, dl=2, rr=10,
                 mdl=10, mod_source=0),
    ]),

    '4op_epiano': FMPatch('4-Op Electric Piano', [
        # Algorithm: [op0] → [op1] → [op2] → [op3 carrier]
        #            op0 has self-feedback
        Operator(freq_ratio=5.0, level=0.3, ar=31, d1r=16, dl=14, rr=16,
                 is_carrier=False, feedback=0.2),
        Operator(freq_ratio=1.0, level=0.5, ar=31, d1r=12, dl=8, rr=14,
                 is_carrier=False, mdl=7, mod_source=0),
        Operator(freq_ratio=1.0, level=0.7, ar=31, d1r=8, dl=4, rr=12,
                 is_carrier=False, mdl=8, mod_source=1),
        Operator(freq_ratio=1.0, level=0.8, ar=31, d1r=4, dl=2, rr=12,
                 mdl=9, mod_source=2),
    ]),
}


# ── Config File Support ─────────────────────────────────────────────

def load_patch(path: str) -> FMPatch:
    with open(path) as f:
        cfg = json.load(f)
    ops = []
    for op_cfg in cfg.get('operators', []):
        ops.append(Operator(**op_cfg))
    return FMPatch(name=cfg.get('name', 'Custom'), operators=ops)


def save_patch(patch: FMPatch, path: str):
    cfg = {
        'name': patch.name,
        'operators': [
            {k: v for k, v in op.__dict__.items()} for op in patch.operators
        ]
    }
    with open(path, 'w') as f:
        json.dump(cfg, f, indent=2)


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='SCSP FM synthesis simulator')
    parser.add_argument('--patch', help='Preset name or JSON file')
    parser.add_argument('--list', action='store_true', help='List preset patches')
    parser.add_argument('--note', type=int, default=60, help='MIDI note (default: 60/C4)')
    parser.add_argument('--duration', type=float, default=1.0, help='Note duration in seconds')
    parser.add_argument('--release', type=float, default=0.5, help='Release time after note-off')
    parser.add_argument('--wav', help='Output WAV file')
    parser.add_argument('--all', action='store_true', help='Render all presets')
    parser.add_argument('--save-config', help='Save patch as JSON config')
    args = parser.parse_args()

    if args.list:
        print("Available FM presets:")
        for name, patch in PRESETS.items():
            n_ops = len(patch.operators)
            carriers = sum(1 for op in patch.operators if op.is_carrier)
            mods = n_ops - carriers
            print(f"  {name:16s}  {patch.name:24s}  {n_ops}-op ({mods}mod+{carriers}car)")
        return

    if args.save_config and args.patch:
        patch = PRESETS.get(args.patch)
        if patch:
            save_patch(patch, args.save_config)
            print(f"Saved {args.patch} config to {args.save_config}")
        return

    if args.all:
        outdir = 'fm_renders'
        os.makedirs(outdir, exist_ok=True)
        for name, patch in PRESETS.items():
            samples = render_note(patch, args.note, args.duration, args.release)
            wav_path = os.path.join(outdir, f'{name}.wav')
            write_wav(samples, wav_path)
            print(f"  {wav_path:30s}  {patch.name}")
        print(f"\nRendered {len(PRESETS)} patches to {outdir}/")
        return

    if args.patch:
        if os.path.isfile(args.patch):
            patch = load_patch(args.patch)
        elif args.patch in PRESETS:
            patch = PRESETS[args.patch]
        else:
            print(f"Unknown patch: {args.patch}")
            print(f"Available: {', '.join(PRESETS.keys())}")
            return
    else:
        patch = PRESETS['epiano']

    wav_path = args.wav or f'{patch.name.lower().replace(" ", "_")}.wav'

    note_name = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    freq = 440.0 * (2.0 ** ((args.note - 69) / 12.0))

    print(f"[fm] Rendering: {patch.name}")
    print(f"  Note: {note_name[args.note % 12]}{args.note // 12 - 1} "
          f"(MIDI {args.note}, {freq:.1f} Hz)")
    print(f"  Duration: {args.duration}s + {args.release}s release")
    print(f"  Operators: {len(patch.operators)}")
    for i, op in enumerate(patch.operators):
        role = "carrier" if op.is_carrier else "modulator"
        mod_str = f"mod_src=op{op.mod_source}" if op.mod_source >= 0 else ""
        fb_str = f"fb={op.feedback:.1f}" if op.feedback > 0 else ""
        mdl_str = f"MDL={op.mdl}" if op.mdl >= 5 else ""
        extras = " ".join(filter(None, [mod_str, mdl_str, fb_str]))
        print(f"    Op{i}: {role:9s} ratio={op.freq_ratio:.3f} "
              f"level={op.level:.1f} AR={op.ar} D1R={op.d1r} DL={op.dl} "
              f"RR={op.rr} {extras}")

    samples = render_note(patch, args.note, args.duration, args.release)
    write_wav(samples, wav_path)
    print(f"  Output: {wav_path} ({len(samples)} samples, "
          f"{len(samples)/SAMPLE_RATE:.2f}s)")


if __name__ == '__main__':
    main()
