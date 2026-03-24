#!/usr/bin/env python3
"""
dx7_to_saturn.py — Convert DX7 SysEx patches to Saturn SCSP FM instruments.

Reads a DX7 32-voice bank dump (.syx) and converts the FM patches to
FMOperator definitions compatible with saturn_kit.py. Can also render
patches to WAV via the FM simulator.

The DX7's 6 operators are mapped to SCSP slots. By default, only the
most important operators are kept (2-4 ops) to conserve the Saturn's
32-slot budget.

Usage:
  python3 dx7_to_saturn.py patches.syx                    # List all 32 patches
  python3 dx7_to_saturn.py patches.syx --patch 0          # Show patch 0 details
  python3 dx7_to_saturn.py patches.syx --render 0         # Render patch 0 to WAV
  python3 dx7_to_saturn.py patches.syx --render-all       # Render all 32 patches
  python3 dx7_to_saturn.py patches.syx --export kit.json  # Export as saturn_kit config
  python3 dx7_to_saturn.py patches.syx --export kit.json --patches 0,5,12,31

DX7 SysEx format reference:
  https://homepages.abdn.ac.uk/d.j.benson/pages/dx7/sysex-format.txt
"""

import struct
import math
import sys
import os
import json
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ── DX7 SysEx Parser ───────────────────────────────────────────────

# DX7 32 algorithms: for each algorithm, which operators are carriers
# and which modulate which. Operators numbered 1-6 (DX7 convention).
# Format: list of (modulator, carrier) pairs + list of carrier ops.
# DX7 ops are numbered 6→1 in the SysEx (op 6 is first in data).
DX7_ALGORITHMS = {
    # Algorithm 0-31. Each entry: (carriers, connections)
    # connections: list of (modulator_op, carrier_op) pairs
    # Simplified to capture the essential topology.
    0:  ([1],       [(6,5), (5,4), (4,3), (3,2), (2,1)]),  # Serial chain
    1:  ([1],       [(6,5), (5,4), (4,3), (2,3), (3,1)]),  # 2+3→1
    2:  ([1],       [(6,5), (5,4), (3,2), (4,1), (2,1)]),
    3:  ([1],       [(6,5), (5,4), (4,3), (3,1)]),
    4:  ([1,3],     [(6,5), (5,4), (4,3), (2,1)]),          # Two carriers
    5:  ([1],       [(6,5), (5,4), (5,3), (5,2), (5,1)]),
    6:  ([1],       [(6,5), (5,4), (5,3), (5,1)]),
    7:  ([1],       [(6,5), (4,3), (3,1)]),
    8:  ([1],       [(6,5), (4,3), (3,2), (2,1)]),
    9:  ([1],       [(6,5), (3,2), (2,1)]),
    10: ([1],       [(6,5), (4,3), (3,1)]),
    11: ([1],       [(6,5), (5,4), (4,3), (3,2), (2,1)]),
    12: ([1],       [(6,5), (3,2), (2,1)]),
    13: ([1],       [(6,5), (5,4), (3,2), (2,1)]),
    14: ([1],       [(6,5), (5,4), (4,3), (2,1)]),
    15: ([1],       [(6,5), (2,1)]),
    16: ([1],       [(6,5), (5,4), (3,1)]),
    17: ([1],       [(6,5), (3,1), (2,1)]),
    18: ([1],       [(6,5), (5,3), (3,1)]),
    19: ([1,4,5],   [(6,5), (6,4), (3,2), (2,1)]),          # Three carriers
    20: ([1,3],     [(6,5), (2,1), (2,3)]),
    21: ([1,3,4,5], [(6,5), (6,4), (6,3), (2,1)]),
    22: ([1,3,4,5], [(6,5), (2,1)]),
    23: ([1,3,4,5], [(6,5), (2,1)]),
    24: ([1,3,4,5], [(2,1)]),
    25: ([1,3,4,5], [(2,1)]),
    26: ([1,4,5],   [(6,5), (3,2), (2,1)]),
    27: ([1,4],     [(6,5), (3,2), (2,1)]),
    28: ([1,3,6],   [(5,4), (4,3), (2,1)]),
    29: ([1,5,6],   [(4,3), (3,2), (2,1)]),
    30: ([1,5,6],   [(4,3), (3,2)]),
    31: ([1,2,3,4,5,6], []),                                  # All carriers (additive)
}


@dataclass
class DX7Operator:
    """One DX7 operator (parsed from SysEx)."""
    eg_rates: Tuple[int, int, int, int] = (99, 99, 99, 99)
    eg_levels: Tuple[int, int, int, int] = (99, 99, 99, 0)
    kbd_lev_scl_brk_pt: int = 0
    kbd_lev_scl_l_depth: int = 0
    kbd_lev_scl_r_depth: int = 0
    kbd_lev_scl_l_curve: int = 0
    kbd_lev_scl_r_curve: int = 0
    osc_rate_scale: int = 0
    amp_mod_sens: int = 0
    key_vel_sens: int = 0
    output_level: int = 99      # 0-99
    osc_mode: int = 0           # 0=ratio, 1=fixed
    freq_coarse: int = 1        # 0-31
    freq_fine: int = 0          # 0-99
    osc_detune: int = 7         # 0-14 (7=center)

    @property
    def freq_ratio(self) -> float:
        """Compute frequency ratio from coarse + fine."""
        if self.osc_mode == 1:
            # Fixed frequency mode: compute actual Hz, convert to ratio
            # Coarse selects decade: 0=1Hz, 1=10Hz, 2=100Hz, 3=1000Hz
            decade = 10.0 ** min(self.freq_coarse, 3)
            freq_hz = decade * (1.0 + self.freq_fine * 0.0099)
            # Express as ratio to A4 (440Hz) — but this isn't really
            # a ratio, it's a fixed frequency. Flag it.
            return freq_hz / 440.0
        else:
            # Ratio mode
            if self.freq_coarse == 0:
                coarse = 0.5
            else:
                coarse = float(self.freq_coarse)
            fine = coarse * self.freq_fine / 100.0
            return coarse + fine

    @property
    def is_fixed_freq(self) -> bool:
        return self.osc_mode == 1

    @property
    def level_fraction(self) -> float:
        """Output level as 0.0-1.0 fraction."""
        return self.output_level / 99.0


@dataclass
class DX7Voice:
    """A complete DX7 voice (6 operators + parameters)."""
    name: str = ""
    operators: List[DX7Operator] = field(default_factory=list)  # ops 1-6
    algorithm: int = 0          # 0-31
    feedback: int = 0           # 0-7
    osc_key_sync: int = 0
    # Pitch EG
    pitch_eg_rates: Tuple[int, int, int, int] = (99, 99, 99, 99)
    pitch_eg_levels: Tuple[int, int, int, int] = (50, 50, 50, 50)
    # LFO
    lfo_speed: int = 0
    lfo_delay: int = 0
    lfo_pmd: int = 0
    lfo_amd: int = 0
    lfo_sync: int = 0
    lfo_wave: int = 0
    transpose: int = 24        # C3 = 24


def parse_dx7_sysex(data: bytes) -> List[DX7Voice]:
    """Parse a DX7 32-voice bank dump (.syx file)."""
    voices = []

    # Find the voice data start
    # Standard header: F0 43 00 09 20 00 (6 bytes)
    start = 0
    if len(data) > 6 and data[0] == 0xF0:
        start = 6
    elif len(data) >= 4096:
        # Raw voice data without SysEx wrapper
        start = 0
    else:
        # Try to find the header
        for i in range(len(data) - 6):
            if data[i] == 0xF0 and data[i+1] == 0x43:
                start = i + 6
                break

    for vi in range(32):
        offset = start + vi * 128
        if offset + 128 > len(data):
            break

        vdata = data[offset:offset + 128]
        voice = DX7Voice()

        # Parse 6 operators (packed format: 17 bytes each)
        # DX7 SysEx order: op6 first, op1 last
        ops = []
        for oi in range(6):
            ooff = oi * 17
            od = vdata[ooff:ooff + 17]

            op = DX7Operator(
                eg_rates=(od[0], od[1], od[2], od[3]),
                eg_levels=(od[4], od[5], od[6], od[7]),
                kbd_lev_scl_brk_pt=od[8],
                kbd_lev_scl_l_depth=od[9],
                kbd_lev_scl_r_depth=od[10],
                kbd_lev_scl_l_curve=od[11] & 0x03,
                kbd_lev_scl_r_curve=(od[11] >> 2) & 0x03,
                osc_rate_scale=(od[12] >> 3) & 0x07,
                osc_detune=od[12] & 0x07,
                amp_mod_sens=(od[13] >> 4) & 0x03,
                key_vel_sens=od[13] & 0x07,
                output_level=od[14],
                osc_mode=(od[15] >> 3) & 0x01,
                freq_coarse=od[15] & 0x07 | ((od[15] >> 1) & 0x18),
                freq_fine=od[16],
            )
            ops.append(op)

        # Reverse: SysEx has op6 first, we want op1 first
        ops.reverse()
        voice.operators = ops

        # Voice parameters (bytes 102-127)
        vp = vdata[102:]
        voice.pitch_eg_rates = (vp[0], vp[1], vp[2], vp[3])
        voice.pitch_eg_levels = (vp[4], vp[5], vp[6], vp[7])
        voice.algorithm = vp[8] & 0x1F
        voice.feedback = vp[9] & 0x07
        voice.osc_key_sync = (vp[9] >> 3) & 0x01
        voice.lfo_speed = vp[10]
        voice.lfo_delay = vp[11]
        voice.lfo_pmd = vp[12]
        voice.lfo_amd = vp[13]
        voice.lfo_sync = vp[14] & 0x01
        voice.lfo_wave = (vp[14] >> 1) & 0x07
        voice.transpose = vp[15]
        voice.name = bytes(vp[16:26]).decode('ascii', errors='replace').strip()

        voices.append(voice)

    return voices


# ── DX7 → SCSP Conversion ──────────────────────────────────────────

def dx7_eg_to_scsp(rates, levels) -> dict:
    """Convert DX7 envelope (4 rates + 4 levels) to SCSP AR/D1R/DL/D2R/RR.

    DX7 EG: L4→L1 at R1, L1→L2 at R2, L2→L3 at R3, L3→L4 at R4 (release)
    SCSP EG: 0→max at AR, max→DL at D1R, DL→0 at D2R, release at RR
    """
    r1, r2, r3, r4 = rates
    l1, l2, l3, l4 = levels

    # AR from R1 (DX7 rate 0-99 → SCSP 0-31)
    ar = min(31, max(0, int(r1 * 31 / 99)))

    # D1R from R2 (decay rate from peak to sustain)
    d1r = min(31, max(0, int((99 - r2) * 28 / 99)))

    # DL: sustain level relative to peak.
    # DX7 L1=peak (usually 99), L2=sustain after first decay.
    # SCSP DL: 0=sustain at full volume, 31=sustain at silence.
    # If L2 is close to L1, the sound sustains (DL near 0).
    # If L2 is 0, the sound decays to silence (DL near 31).
    if l1 > 0:
        sustain_ratio = min(l2, l3) / l1
    else:
        sustain_ratio = 0
    dl = min(31, max(0, int((1.0 - sustain_ratio) * 31)))

    # D2R from R3 (sustain-to-zero decay)
    d2r = min(31, max(0, int((99 - r3) * 20 / 99)))

    # RR from R4
    rr = min(31, max(0, int(r4 * 31 / 99)))

    return {'ar': ar, 'd1r': d1r, 'dl': dl, 'd2r': d2r, 'rr': rr}


def dx7_level_to_tl(output_level: int) -> int:
    """Convert DX7 output level (0-99) to SCSP TL (0=loud, 255=silent)."""
    # DX7 level is roughly logarithmic
    if output_level >= 99:
        return 0
    if output_level <= 0:
        return 255
    # Approximate: DX7 uses ~0.75 dB/step, SCSP TL uses ~0.375 dB/step
    return max(0, min(255, int((99 - output_level) * 1.5)))


def dx7_voice_to_fm_ops(voice: DX7Voice, max_ops: int = 4) -> list:
    """Convert a DX7 voice to a list of FMOperator dicts for saturn_kit."""
    alg_info = DX7_ALGORITHMS.get(voice.algorithm, ([1], []))
    carriers, connections = alg_info

    # Determine which DX7 operators to keep (prioritize carriers + their modulators)
    active_ops = set()
    for c in carriers:
        active_ops.add(c)
    for mod, car in connections:
        if car in active_ops:
            active_ops.add(mod)

    # Sort and limit to max_ops
    active_list = sorted(active_ops)
    if len(active_list) > max_ops:
        # Keep carriers and their direct modulators
        essential = set(carriers)
        for mod, car in connections:
            if car in carriers:
                essential.add(mod)
        active_list = sorted(essential)[:max_ops]

    # Build operator index mapping (DX7 op number → layer index)
    op_to_layer = {}
    for idx, op_num in enumerate(active_list):
        op_to_layer[op_num] = idx

    # Detect octave-shifted carriers and compute pitch correction.
    # Many DX7 patches have all carriers at ratio 2.0 (one octave up).
    # This is a DX7 convention — we normalize carriers to ratio 1.0
    # and adjust modulators accordingly so the patch plays at the
    # expected pitch.
    carrier_ratios = [voice.operators[c - 1].freq_ratio for c in carriers if c in active_ops]
    if carrier_ratios and all(r >= 1.5 for r in carrier_ratios):
        # Find the lowest carrier ratio and normalize everything to it
        base_carrier_ratio = min(carrier_ratios)
        pitch_correction = base_carrier_ratio
    else:
        pitch_correction = 1.0

    # Build FMOperator list
    fm_ops = []
    for op_num in active_list:
        dx_op = voice.operators[op_num - 1]  # DX7 ops are 1-indexed
        is_carrier = op_num in carriers

        # Find modulation source
        mod_source = -1
        for mod, car in connections:
            if car == op_num and mod in op_to_layer:
                mod_source = op_to_layer[mod]
                break

        # Compute MDL from modulator's output level.
        # DX7 output level 0-99 maps to SCSP MDL 5-10.
        # MDL 5 is the minimum audible modulation, MDL 10 is already very strong.
        # Above MDL 10, the sound becomes metallic/noisy rapidly.
        mdl = 0
        if mod_source >= 0:
            mod_op_num = active_list[mod_source]
            mod_level = voice.operators[mod_op_num - 1].output_level
            mdl = max(0, min(10, 5 + int(mod_level * 5 / 99)))

        # Feedback: DX7 range 0-7 → SCSP 0.0-0.35
        # DX7 feedback is subtle; even max feedback shouldn't overwhelm
        feedback = 0.0
        if op_num == active_list[0] and voice.feedback > 0:
            feedback = voice.feedback / 7.0 * 0.35

        # Convert envelope
        env = dx7_eg_to_scsp(dx_op.eg_rates, dx_op.eg_levels)

        # Convert level
        level = dx_op.level_fraction

        # Apply pitch correction (normalize carrier ratios)
        corrected_ratio = dx_op.freq_ratio / pitch_correction

        fm_ops.append({
            'freq_ratio': round(corrected_ratio, 3),
            'level': round(level, 2),
            'ar': env['ar'],
            'd1r': env['d1r'],
            'dl': env['dl'],
            'd2r': env['d2r'],
            'rr': env['rr'],
            'mdl': mdl,
            'mod_source': mod_source,
            'feedback': round(feedback, 2),
            'is_carrier': is_carrier,
        })

    return fm_ops


def dx7_voice_to_kit_entry(voice: DX7Voice, program: int, max_ops: int = 4) -> dict:
    """Convert a DX7 voice to a saturn_kit.py instrument config entry."""
    fm_ops = dx7_voice_to_fm_ops(voice, max_ops)
    return {
        'name': voice.name.strip() or f'DX7 Patch {program}',
        'program': program,
        'waveform': 'sine',
        'base_note': 69,
        'loop': True,
        'fm_ops': fm_ops,
    }


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Convert DX7 SysEx to Saturn FM instruments')
    parser.add_argument('sysex', help='DX7 .syx file (32-voice bank dump)')
    parser.add_argument('--patch', type=int, help='Show details for a specific patch (0-31)')
    parser.add_argument('--render', type=int, help='Render a patch to WAV')
    parser.add_argument('--render-all', action='store_true', help='Render all patches to WAV')
    parser.add_argument('--demo', action='store_true',
                        help='Render musical demo (staccato + sustained) instead of single note')
    parser.add_argument('--export', help='Export selected patches as saturn_kit JSON config')
    parser.add_argument('--patches', help='Comma-separated patch indices for export (default: all)')
    parser.add_argument('--max-ops', type=int, default=4, help='Max operators per voice (default: 4)')
    parser.add_argument('--note', type=int, default=60, help='MIDI note for rendering (default: 60)')
    args = parser.parse_args()

    with open(args.sysex, 'rb') as f:
        data = f.read()

    voices = parse_dx7_sysex(data)
    print(f"[dx7] Loaded {len(voices)} voices from {args.sysex}")

    if args.patch is not None:
        # Show details for one patch
        v = voices[args.patch]
        print(f"\n=== Patch {args.patch}: {v.name} ===")
        print(f"  Algorithm: {v.algorithm}")
        print(f"  Feedback: {v.feedback}")
        alg = DX7_ALGORITHMS.get(v.algorithm, ([1], []))
        print(f"  Carriers: ops {alg[0]}")
        print(f"  Connections: {alg[1]}")
        for i, op in enumerate(v.operators):
            print(f"  Op{i+1}: ratio={op.freq_ratio:.3f} level={op.output_level} "
                  f"EG_R={op.eg_rates} EG_L={op.eg_levels}")
        print(f"\n  → SCSP conversion ({args.max_ops} ops max):")
        fm_ops = dx7_voice_to_fm_ops(v, args.max_ops)
        for i, op in enumerate(fm_ops):
            role = "carrier" if op['is_carrier'] else "mod"
            mod_str = f"src=op{op['mod_source']}" if op['mod_source'] >= 0 else ""
            fb_str = f"fb={op['feedback']:.1f}" if op['feedback'] > 0 else ""
            mdl_str = f"MDL={op['mdl']}" if op['mdl'] >= 5 else ""
            print(f"    Op{i}: {role:7s} ratio={op['freq_ratio']:.3f} "
                  f"level={op['level']:.2f} AR={op['ar']} D1R={op['d1r']} "
                  f"DL={op['dl']} RR={op['rr']} {mdl_str} {mod_str} {fb_str}")
        return

    if args.render is not None or args.render_all:
        # Import FM simulator
        sys.path.insert(0, os.path.dirname(__file__))
        from fm_sim import FMPatch, Operator, render_note, render_demo, write_wav

        indices = range(len(voices)) if args.render_all else [args.render]
        outdir = 'dx7_renders'
        os.makedirs(outdir, exist_ok=True)

        for vi in indices:
            v = voices[vi]
            fm_ops = dx7_voice_to_fm_ops(v, args.max_ops)

            # Convert to fm_sim Operator objects
            sim_ops = []
            for op in fm_ops:
                sim_ops.append(Operator(
                    freq_ratio=op['freq_ratio'],
                    level=op['level'],
                    ar=op['ar'], d1r=op['d1r'], dl=op['dl'],
                    d2r=op['d2r'], rr=op['rr'],
                    mdl=op['mdl'],
                    mod_source=op['mod_source'],
                    feedback=op['feedback'],
                    is_carrier=op['is_carrier'],
                ))

            patch = FMPatch(name=v.name, operators=sim_ops)
            if args.demo:
                samples = render_demo(patch, args.note)
            else:
                samples = render_note(patch, args.note, 1.5, 0.5)
            safe_name = v.name.strip().replace(' ', '_').replace('/', '_') or f'patch_{vi}'
            wav_path = os.path.join(outdir, f'{vi:02d}_{safe_name}.wav')
            write_wav(samples, wav_path)
            print(f"  [{vi:2d}] {wav_path:40s}  {v.name}")

        print(f"\nRendered to {outdir}/")
        return

    if args.export:
        # Export as saturn_kit config
        if args.patches:
            indices = [int(x) for x in args.patches.split(',')]
        else:
            # Export all non-empty patches
            indices = [i for i, v in enumerate(voices)
                       if any(op.output_level > 0 for op in v.operators)]

        instruments = []
        for prog, vi in enumerate(indices[:16]):  # max 16 programs
            v = voices[vi]
            entry = dx7_voice_to_kit_entry(v, prog, args.max_ops)
            instruments.append(entry)

        config = {'instruments': instruments}
        with open(args.export, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"\n[export] {args.export}: {len(instruments)} instruments")
        for inst in instruments:
            n_ops = len(inst.get('fm_ops', []))
            print(f"  Program {inst['program']:2d}: {inst['name']:16s} ({n_ops} ops)")
        print(f"\nUse with: python3 tools/saturn_kit.py --config {args.export}")
        return

    # Default: list all patches
    print()
    for i, v in enumerate(voices):
        alg = DX7_ALGORITHMS.get(v.algorithm, ([1], []))
        n_carriers = len(alg[0])
        active = sum(1 for op in v.operators if op.output_level > 0)
        print(f"  [{i:2d}] {v.name:12s}  alg={v.algorithm:2d} fb={v.feedback} "
              f"carriers={n_carriers} active_ops={active}")


if __name__ == '__main__':
    main()
