#!/usr/bin/env python3
"""
saturn_kit.py — Generate a Saturn Sound Kit (TON + SF2).

Creates a curated set of instruments optimized for the Saturn's 512KB
sound RAM, using single-cycle waveforms and short samples.

The TON file ships with the game.  The SF2 file is loaded into any
DAW for composing MIDI against — it previews how the music will sound
on actual hardware.

Usage:
  python3 saturn_kit.py                      # Generate with defaults
  python3 saturn_kit.py -o mykit             # Output mykit.ton + mykit.sf2
  python3 saturn_kit.py --config kit.json    # Custom instrument config

The kit is fully customizable by editing the instrument definitions below
or providing a JSON config file.
"""

import struct
import math
import json
import sys
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ── Waveform Generators ─────────────────────────────────────────────

SAMPLE_RATE = 22050  # Good balance of quality vs size for Saturn


def gen_sine(n_samples, harmonics=None):
    """Generate a single-cycle sine (or additive harmonics).
    harmonics: list of (harmonic_number, amplitude) pairs.
    Default: pure sine."""
    if harmonics is None:
        harmonics = [(1, 1.0)]
    samples = []
    for i in range(n_samples):
        t = i / n_samples
        val = sum(amp * math.sin(2 * math.pi * h * t) for h, amp in harmonics)
        samples.append(val)
    # Normalize
    peak = max(abs(s) for s in samples) or 1
    return [s / peak for s in samples]


def gen_sawtooth(n_samples):
    """Single-cycle sawtooth via additive synthesis (band-limited)."""
    harmonics = [(h, (-1) ** (h + 1) / h) for h in range(1, 16)]
    return gen_sine(n_samples, harmonics)


def gen_square(n_samples, duty=0.5):
    """Single-cycle square/pulse via additive synthesis."""
    harmonics = [(h, 1.0 / h) for h in range(1, 16, 2)]
    return gen_sine(n_samples, harmonics)


def gen_triangle(n_samples):
    """Single-cycle triangle via additive synthesis."""
    harmonics = [(h, ((-1) ** ((h - 1) // 2)) / (h * h)) for h in range(1, 16, 2)]
    return gen_sine(n_samples, harmonics)


def gen_pulse(n_samples, duty=0.25):
    """Single-cycle pulse wave."""
    samples = []
    for i in range(n_samples):
        t = i / n_samples
        samples.append(1.0 if t < duty else -1.0)
    return samples


def gen_organ(n_samples):
    """Organ: drawbar-style additive harmonics."""
    harmonics = [
        (1, 1.0), (2, 0.8), (3, 0.6), (4, 0.3),
        (6, 0.2), (8, 0.15), (10, 0.1)
    ]
    return gen_sine(n_samples, harmonics)


def gen_brass(n_samples):
    """Brass-like: strong odd harmonics with slight even."""
    harmonics = [
        (1, 1.0), (2, 0.3), (3, 0.7), (4, 0.15),
        (5, 0.5), (6, 0.1), (7, 0.3), (9, 0.15)
    ]
    return gen_sine(n_samples, harmonics)


def gen_strings(n_samples):
    """String-like: sawtooth with rolled-off highs."""
    harmonics = [(h, 1.0 / (h ** 1.2)) for h in range(1, 20)]
    return gen_sine(n_samples, harmonics)


def gen_flute(n_samples):
    """Flute-like: fundamental + weak 2nd harmonic."""
    return gen_sine(n_samples, [(1, 1.0), (2, 0.15), (3, 0.05)])


def gen_piano(n_samples):
    """Piano-like: harmonics with inharmonicity."""
    harmonics = [
        (1, 1.0), (2, 0.7), (3, 0.4), (4, 0.25),
        (5, 0.15), (6, 0.1), (7, 0.08), (8, 0.05)
    ]
    return gen_sine(n_samples, harmonics)


def gen_bass(n_samples):
    """Bass: strong fundamental + sub-harmonics."""
    harmonics = [(1, 1.0), (2, 0.5), (3, 0.2), (4, 0.1)]
    return gen_sine(n_samples, harmonics)


def gen_noise_burst(n_samples):
    """White noise burst (for drums). Uses deterministic LFSR."""
    import random
    rng = random.Random(42)
    return [rng.uniform(-1, 1) for _ in range(n_samples)]


def gen_kick(sample_rate=SAMPLE_RATE):
    """Kick drum: sine sweep from ~150Hz down to ~50Hz with decay."""
    dur = 0.15
    n = int(sample_rate * dur)
    samples = []
    for i in range(n):
        t = i / sample_rate
        env = max(0, 1.0 - t / dur) ** 2
        freq = 150 * math.exp(-t * 20) + 50
        samples.append(env * math.sin(2 * math.pi * freq * t))
    return samples


def gen_snare(sample_rate=SAMPLE_RATE):
    """Snare: short tonal + noise burst."""
    import random
    rng = random.Random(123)
    dur = 0.12
    n = int(sample_rate * dur)
    samples = []
    for i in range(n):
        t = i / sample_rate
        env = max(0, 1.0 - t / dur) ** 1.5
        tone = 0.4 * math.sin(2 * math.pi * 200 * t)
        noise = 0.6 * rng.uniform(-1, 1)
        samples.append(env * (tone + noise))
    return samples


def gen_hihat(sample_rate=SAMPLE_RATE):
    """Hi-hat: filtered noise, very short."""
    import random
    rng = random.Random(456)
    dur = 0.06
    n = int(sample_rate * dur)
    samples = []
    for i in range(n):
        t = i / sample_rate
        env = max(0, 1.0 - t / dur) ** 3
        samples.append(env * rng.uniform(-1, 1) * 0.7)
    return samples


def gen_crash(sample_rate=SAMPLE_RATE):
    """Crash cymbal: long noise with slow decay."""
    import random
    rng = random.Random(789)
    dur = 0.5
    n = int(sample_rate * dur)
    samples = []
    for i in range(n):
        t = i / sample_rate
        env = max(0, 1.0 - t / dur) ** 1.2
        samples.append(env * rng.uniform(-1, 1) * 0.6)
    return samples


def gen_tom(sample_rate=SAMPLE_RATE):
    """Tom: sine sweep with decay."""
    dur = 0.15
    n = int(sample_rate * dur)
    samples = []
    for i in range(n):
        t = i / sample_rate
        env = max(0, 1.0 - t / dur) ** 2
        freq = 200 * math.exp(-t * 10) + 80
        samples.append(env * math.sin(2 * math.pi * freq * t))
    return samples


# ── Instrument Definitions ──────────────────────────────────────────

WAVEFORM_GENERATORS = {
    'sine': gen_sine,
    'sawtooth': gen_sawtooth,
    'square': gen_square,
    'triangle': gen_triangle,
    'pulse': gen_pulse,
    'organ': gen_organ,
    'brass': gen_brass,
    'strings': gen_strings,
    'flute': gen_flute,
    'piano': gen_piano,
    'bass': gen_bass,
    'kick': gen_kick,
    'snare': gen_snare,
    'hihat': gen_hihat,
    'crash': gen_crash,
    'tom': gen_tom,
}

def midi_to_freq(note):
    """MIDI note to frequency in Hz."""
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def cycle_length_for_note(base_note):
    """Compute single-cycle waveform length so it plays at the correct
    pitch on the SCSP at 44100 Hz (OCT=0, FNS=0)."""
    return round(44100.0 / midi_to_freq(base_note))


# Default cycle length for A4 (will be overridden per instrument)
CYCLE_LENGTH = cycle_length_for_note(69)  # 100 samples


@dataclass
class FMOperator:
    """One FM operator (modulator or carrier)."""
    freq_ratio: float = 1.0   # frequency ratio to base note
    level: float = 1.0        # output level (0.0-1.0 → maps to TL)
    ar: int = 31
    d1r: int = 0
    dl: int = 0
    d2r: int = 0
    rr: int = 14
    mdl: int = 0              # modulation depth (0-15, 0-4=off)
    mod_source: int = -1      # which operator (layer index) modulates this one
    feedback: float = 0.0     # self-feedback (0.0-1.0)
    is_carrier: bool = True   # carrier=audible, modulator=silent


@dataclass
class InstrumentDef:
    """Definition of an instrument in the Saturn kit."""
    name: str
    program: int           # GM program number (0-127)
    waveform: str          # key into WAVEFORM_GENERATORS
    base_note: int = 69    # MIDI note for unity pitch (A4)
    loop: bool = True      # whether to loop
    cycle_length: int = CYCLE_LENGTH  # samples per cycle (for single-cycle waves)
    # SCSP envelope (used for single-layer PCM instruments)
    ar: int = 31           # attack rate (31 = instant)
    d1r: int = 0
    dl: int = 0
    d2r: int = 0
    rr: int = 14           # release rate
    tl: int = 0            # total level (0 = loudest)
    disdl: int = 7         # direct send level (7 = max)
    # For drum samples (non-looped, generated at sample_rate)
    is_drum: bool = False
    drum_note: int = 60    # fixed MIDI note for this drum
    # FM synthesis: if fm_ops is set, this instrument uses FM instead of PCM
    fm_ops: Optional[List[FMOperator]] = None


# Default kit: 16 programs covering basic GM-like instruments + drums
# Program numbers = voice indices in the TON file. The Saturn sound
# driver maps MIDI program number directly to TON voice index.
# Musicians use these program numbers in their DAW.
#
# FM instruments use 2 layers (modulator + carrier) sharing a single
# sine wave sample. PCM instruments use 1 layer with a custom waveform.
DEFAULT_KIT = [
    # ── FM instruments (2-op, share one sine wave sample) ──
    InstrumentDef('Piano',      0, 'sine', fm_ops=[
        FMOperator(freq_ratio=2.0, level=0.9, ar=31, d1r=12, dl=8, rr=14,
                   is_carrier=False),                               # modulator
        FMOperator(freq_ratio=1.0, level=0.8, ar=31, d1r=6, dl=2, rr=12,
                   mdl=9, mod_source=0),                            # carrier
    ]),
    InstrumentDef('E.Piano',    1, 'sine', fm_ops=[
        FMOperator(freq_ratio=14.0, level=0.4, ar=31, d1r=14, dl=12, rr=16,
                   is_carrier=False),
        FMOperator(freq_ratio=1.0, level=0.7, ar=31, d1r=10, dl=6, rr=14,
                   is_carrier=False, mdl=8, mod_source=0),
        FMOperator(freq_ratio=1.0, level=0.8, ar=31, d1r=4, dl=2, rr=12,
                   mdl=9, mod_source=1),
    ]),
    InstrumentDef('Organ',      2, 'sine', fm_ops=[
        FMOperator(freq_ratio=1.0, level=0.7, ar=31, d1r=0, dl=0, rr=20,
                   is_carrier=False, feedback=0.6),
        FMOperator(freq_ratio=1.0, level=0.8, ar=31, d1r=0, dl=0, rr=20,
                   mdl=8, mod_source=0),
    ]),
    InstrumentDef('Strings',    3, 'sine', fm_ops=[
        FMOperator(freq_ratio=1.002, level=0.5, ar=20, d1r=0, dl=0, rr=16,
                   is_carrier=False),
        FMOperator(freq_ratio=1.0, level=0.7, ar=18, d1r=0, dl=0, rr=14,
                   mdl=7, mod_source=0),
    ]),
    InstrumentDef('Brass',      4, 'sine', fm_ops=[
        FMOperator(freq_ratio=1.0, level=0.8, ar=24, d1r=4, dl=2, rr=14,
                   is_carrier=False, feedback=0.3),
        FMOperator(freq_ratio=1.0, level=0.8, ar=22, d1r=2, dl=0, rr=14,
                   mdl=9, mod_source=0),
    ]),
    InstrumentDef('Bass',       8, 'sine', base_note=45, fm_ops=[
        FMOperator(freq_ratio=1.0, level=0.9, ar=31, d1r=14, dl=10, rr=14,
                   is_carrier=False, feedback=0.2),
        FMOperator(freq_ratio=1.0, level=0.9, ar=31, d1r=6, dl=4, rr=14,
                   mdl=10, mod_source=0),
    ]),
    # ── PCM instruments (single-cycle waveforms, 1 layer each) ──
    InstrumentDef('Flute',      5, 'flute',   base_note=69, ar=28, d1r=0, dl=0, rr=18),
    InstrumentDef('Saw Lead',   6, 'sawtooth',base_note=69, ar=31, d1r=0, dl=0, rr=16),
    InstrumentDef('Sq Lead',    7, 'square',  base_note=69, ar=31, d1r=0, dl=0, rr=16),
    InstrumentDef('Syn Bass',   9, 'sawtooth',base_note=45, ar=31, d1r=8, dl=6, rr=14),
    InstrumentDef('Pad',       10, 'strings', base_note=69, ar=16, d1r=0, dl=0, rr=12),
    InstrumentDef('Triangle',  11, 'triangle',base_note=69, ar=31, d1r=0, dl=0, rr=16),
    # ── Drum sounds (one-shot PCM, 1 layer each) ──
    InstrumentDef('Kick',      12, 'kick',  is_drum=True, drum_note=36, loop=False, ar=31, rr=31),
    InstrumentDef('Snare',     13, 'snare', is_drum=True, drum_note=38, loop=False, ar=31, rr=31),
    InstrumentDef('Hi-Hat',    14, 'hihat', is_drum=True, drum_note=42, loop=False, ar=31, rr=31),
    InstrumentDef('Crash',     15, 'crash', is_drum=True, drum_note=49, loop=False, ar=31, rr=31),
]

# PCM-only kit: all single-cycle waveforms, no FM.
# Same program numbers as the FM kit for compatibility.
PCM_KIT = [
    InstrumentDef('Piano',      0, 'piano',   base_note=69, ar=31, d1r=8, dl=4, rr=12),
    InstrumentDef('E.Piano',    1, 'sine',    base_note=69, ar=31, d1r=10, dl=6, rr=14),
    InstrumentDef('Organ',      2, 'organ',   base_note=69, ar=31, d1r=0, dl=0, rr=20),
    InstrumentDef('Strings',    3, 'strings', base_note=69, ar=20, d1r=0, dl=0, rr=16),
    InstrumentDef('Brass',      4, 'brass',   base_note=69, ar=24, d1r=4, dl=2, rr=14),
    InstrumentDef('Flute',      5, 'flute',   base_note=69, ar=28, d1r=0, dl=0, rr=18),
    InstrumentDef('Saw Lead',   6, 'sawtooth',base_note=69, ar=31, d1r=0, dl=0, rr=16),
    InstrumentDef('Sq Lead',    7, 'square',  base_note=69, ar=31, d1r=0, dl=0, rr=16),
    InstrumentDef('Bass',       8, 'bass',    base_note=45, ar=31, d1r=6, dl=4, rr=14),
    InstrumentDef('Syn Bass',   9, 'sawtooth',base_note=45, ar=31, d1r=8, dl=6, rr=14),
    InstrumentDef('Pad',       10, 'strings', base_note=69, ar=16, d1r=0, dl=0, rr=12),
    InstrumentDef('Triangle',  11, 'triangle',base_note=69, ar=31, d1r=0, dl=0, rr=16),
    InstrumentDef('Kick',      12, 'kick',  is_drum=True, drum_note=36, loop=False, ar=31, rr=31),
    InstrumentDef('Snare',     13, 'snare', is_drum=True, drum_note=38, loop=False, ar=31, rr=31),
    InstrumentDef('Hi-Hat',    14, 'hihat', is_drum=True, drum_note=42, loop=False, ar=31, rr=31),
    InstrumentDef('Crash',     15, 'crash', is_drum=True, drum_note=49, loop=False, ar=31, rr=31),
]


# ── TON Builder ─────────────────────────────────────────────────────

def float_to_int16(samples, amplitude=0.9):
    """Convert float [-1,1] to int16, big-endian bytes."""
    pcm = bytearray()
    for s in samples:
        val = max(-32768, min(32767, int(s * amplitude * 32767)))
        pcm += struct.pack('>h', val)
    return pcm


def _make_layer(sa_offset, lsa, lea, loop, base_note, ar, d1r, dl, d2r, rr,
                tl=0, disdl=7, mdl=0, fmcb=False, fm_layer=-1):
    """Build a 32-byte TON layer entry."""
    layer = bytearray(0x20)
    layer[0x00] = 0            # start_note
    layer[0x01] = 127          # end_note
    lpctl = 1 if loop else 0
    # byte 2: FMCB at bit 5
    if fmcb:
        layer[0x02] |= (1 << 5)
    layer[0x03] = (lpctl << 5) | ((sa_offset >> 16) & 0xF)
    struct.pack_into('>H', layer, 0x04, sa_offset & 0xFFFF)
    struct.pack_into('>H', layer, 0x06, lsa)
    struct.pack_into('>H', layer, 0x08, lea)
    layer[0x0A] = (d2r & 0x1F) << 3 | (d1r >> 2) & 0x7
    layer[0x0B] = (d1r & 0x3) << 6 | (ar & 0x1F)
    layer[0x0C] = (0 << 3) | (dl >> 3) & 0x3
    layer[0x0D] = (dl & 0x7) << 5 | (rr & 0x1F)
    layer[0x0F] = tl & 0xFF
    # byte 10: MDL and MDXSL/MDYSL (set to 0 here, driver computes from fm_layer)
    layer[0x10] = (mdl & 0xF) << 4
    # byte 17: ISEL=0, IMXL=7 (for DSP effect routing)
    layer[0x17] = (0 << 3) | 7
    layer[0x18] = (disdl & 0x7) << 5  # DIPAN=0 (center)
    layer[0x19] = base_note & 0x7F
    layer[0x1A] = 0  # fine_tune
    # byte 1B: FM generator/layer links
    if fm_layer >= 0:
        layer[0x1B] = (1 << 7) | (fm_layer & 0x7F)  # fm_gen1=1, fm_layer1
    return bytes(layer)


def build_ton(instruments: List[InstrumentDef]) -> bytes:
    """Build a TON file from instrument definitions."""
    voices = []
    pcm_chunks = []
    pcm_offset = 0  # adjusted later to include header

    # All FM instruments share a single sine wave sample
    sine_cl = cycle_length_for_note(69)  # A4 base, ~100 samples
    sine_samples = gen_sine(sine_cl)
    sine_pcm = float_to_int16(sine_samples)
    sine_pcm_offset = None  # set on first FM instrument

    for inst in instruments:
        if inst.fm_ops:
            # ── FM instrument: multi-layer voice ──
            # All operators use the same shared sine wave sample.
            # First FM instrument allocates the sine PCM.
            if sine_pcm_offset is None:
                sine_pcm_offset = pcm_offset
                pcm_chunks.append(sine_pcm)
                pcm_offset += len(sine_pcm)

            layers_data = []
            n_ops = len(inst.fm_ops)

            for oi, op in enumerate(inst.fm_ops):
                # Compute base_note for this operator's frequency ratio.
                # The sine sample is tuned to A4 (note 69). The ratio shifts pitch.
                # base_note tells the driver what note this layer plays at unity.
                # A ratio of 2.0 = one octave up = base_note - 12
                if op.freq_ratio > 0:
                    ratio_semitones = round(12 * math.log2(op.freq_ratio))
                    op_base_note = max(0, min(127, 69 - ratio_semitones))
                else:
                    op_base_note = 69

                # TL from level (0.0=loudest → TL=0, lower level → higher TL)
                tl = max(0, min(255, int((1.0 - op.level) * 128)))

                # Find modulator layer index for fm_layer1 field
                fm_layer_idx = -1
                if op.mod_source is not None and op.mod_source >= 0:
                    fm_layer_idx = op.mod_source

                layer = _make_layer(
                    sa_offset=sine_pcm_offset,
                    lsa=0, lea=sine_cl, loop=True,
                    base_note=op_base_note,
                    ar=op.ar, d1r=op.d1r, dl=op.dl, d2r=op.d2r, rr=op.rr,
                    tl=tl,
                    disdl=7 if op.is_carrier else 0,  # modulators are silent
                    mdl=op.mdl,
                    fmcb=op.is_carrier,
                    fm_layer=fm_layer_idx,
                )
                layers_data.append(layer)

            # Voice header (4 bytes) + all layers
            voice_hdr = bytearray(4)
            voice_hdr[0] = 2  # bend_range = 2
            voice_hdr[2] = struct.pack('b', n_ops - 1)[0]  # nlayers - 1
            voices.append(bytes(voice_hdr) + b''.join(layers_data))

        elif inst.is_drum:
            # ── Drum: one-shot PCM ──
            gen = WAVEFORM_GENERATORS[inst.waveform]
            samples_float = gen(SAMPLE_RATE)
            pcm = float_to_int16(samples_float)
            n_samples = len(samples_float)

            layer = _make_layer(
                sa_offset=pcm_offset, lsa=0, lea=n_samples, loop=False,
                base_note=inst.drum_note,
                ar=inst.ar, d1r=inst.d1r, dl=inst.dl, d2r=inst.d2r, rr=inst.rr,
                tl=inst.tl, disdl=inst.disdl,
            )
            voice_hdr = bytearray(4)
            voice_hdr[0] = 2
            voice_hdr[2] = 0
            voices.append(bytes(voice_hdr) + layer)
            pcm_chunks.append(pcm)
            pcm_offset += len(pcm)

        else:
            # ── Melodic PCM: single-cycle waveform ──
            cl = cycle_length_for_note(inst.base_note)
            gen = WAVEFORM_GENERATORS[inst.waveform]
            samples_float = gen(cl)
            pcm = float_to_int16(samples_float)

            layer = _make_layer(
                sa_offset=pcm_offset, lsa=0, lea=cl, loop=inst.loop,
                base_note=inst.base_note,
                ar=inst.ar, d1r=inst.d1r, dl=inst.dl, d2r=inst.d2r, rr=inst.rr,
                tl=inst.tl, disdl=inst.disdl,
            )
            voice_hdr = bytearray(4)
            voice_hdr[0] = 2
            voice_hdr[2] = 0
            voices.append(bytes(voice_hdr) + layer)
            pcm_chunks.append(pcm)
            pcm_offset += len(pcm)

    # VL table (from mechs.ton — known good)
    vl = struct.pack('bbBbbBbbBb', 25, 16, 54, 9, 49, 102, 19, 93, 122, 43)
    # Mixer: 18 bytes controlling EFSDL/EFPAN for EFREG[0-15] + EXTS[0-1].
    # EFSDL routes DSP effect output to speakers. Without this, DSP runs
    # but output is muted.  Format per byte: [7:5]=EFSDL, [4:0]=EFPAN.
    # Channels 0,2 = left (EFPAN=0x1F), channels 1,3 = right (EFPAN=0x0F).
    mixer = bytearray(0x12)
    mixer[0] = (7 << 5) | 0x1F   # EFREG0 → left, full level
    mixer[1] = (7 << 5) | 0x0F   # EFREG1 → right, full level
    peg = bytes([0x00] * 0x0A)
    plfo = bytes([0x00] * 0x04)

    # Calculate offsets
    header_size = 8 + len(voices) * 2
    mixer_off = header_size
    vl_off = mixer_off + len(mixer)
    peg_off = vl_off + len(vl)
    plfo_off = peg_off + len(peg)

    voice_off = plfo_off + len(plfo)
    voice_offsets = []
    cur = voice_off
    for v in voices:
        voice_offsets.append(cur)
        cur += len(v)

    pcm_base = cur

    # Adjust SA in each voice layer to include pcm_base
    adjusted_voices = []
    for i, v in enumerate(voices):
        va = bytearray(v)
        nlayers = struct.unpack('b', bytes([va[2]]))[0] + 1
        for li in range(nlayers):
            loff = 4 + li * 0x20
            old_sa = ((va[loff + 0x03] & 0xF) << 16) | struct.unpack('>H', va[loff + 0x04:loff + 0x06])[0]
            new_sa = pcm_base + old_sa
            va[loff + 0x03] = (va[loff + 0x03] & 0xF0) | ((new_sa >> 16) & 0xF)
            struct.pack_into('>H', va, loff + 0x04, new_sa & 0xFFFF)
        adjusted_voices.append(bytes(va))

    # Build header
    hdr = bytearray()
    hdr += struct.pack('>H', mixer_off)
    hdr += struct.pack('>H', vl_off)
    hdr += struct.pack('>H', peg_off)
    hdr += struct.pack('>H', plfo_off)
    for off in voice_offsets:
        hdr += struct.pack('>H', off)

    # Assemble
    ton = bytearray()
    ton += hdr
    ton += mixer
    ton += vl
    ton += peg
    ton += plfo
    for v in adjusted_voices:
        ton += v
    for p in pcm_chunks:
        ton += p

    return bytes(ton)


# ── SF2 Builder ─────────────────────────────────────────────────────

def write_sf2_chunk(tag, data):
    padded = data + (b'\x00' if len(data) % 2 else b'')
    return tag.encode() + struct.pack('<I', len(data)) + padded


def write_sf2_list(list_type, *chunks):
    inner = b''.join(chunks)
    return write_sf2_chunk('LIST', list_type.encode() + inner)


def build_sf2(instruments: List[InstrumentDef]) -> bytes:
    """Build a matching SF2 for DAW preview."""

    # Generate all samples (LE for SF2)
    smpl_data = bytearray()
    sample_infos = []

    for inst in instruments:
        start = len(smpl_data) // 2

        if inst.is_drum:
            gen = WAVEFORM_GENERATORS[inst.waveform]
            samples = gen(SAMPLE_RATE)
            base_note = inst.drum_note
        else:
            cl = cycle_length_for_note(inst.base_note)
            gen = WAVEFORM_GENERATORS[inst.waveform]
            samples = gen(cl)
            base_note = inst.base_note

        for s in samples:
            val = max(-32768, min(32767, int(s * 0.9 * 32767)))
            smpl_data += struct.pack('<h', val)

        end = len(smpl_data) // 2
        loop_start = start
        loop_end = end - 1

        # SF2 requires 46 zero samples after each sample
        smpl_data += b'\x00\x00' * 46

        sample_infos.append({
            'name': inst.name, 'start': start, 'end': end + 46,
            'loop_start': loop_start, 'loop_end': loop_end,
            'rate': SAMPLE_RATE, 'root': base_note,
            'loop': inst.loop,
        })

    # shdr
    shdr = bytearray()
    for si in sample_infos:
        name = si['name'].encode()[:20].ljust(20, b'\x00')
        shdr += name + struct.pack('<IIIIIBbHH',
                                    si['start'], si['end'],
                                    si['loop_start'], si['loop_end'],
                                    si['rate'], si['root'], 0, 1, 0)
    shdr += b'EOS\x00'.ljust(20, b'\x00') + struct.pack('<IIIIIBbHH', 0, 0, 0, 0, 0, 0, 0, 0, 0)

    # igen
    igen = bytearray()
    igen_per_inst = []
    for i, inst in enumerate(instruments):
        start_idx = len(igen) // 4
        igen += struct.pack('<HH', 43, 0x7F00)  # keyRange 0-127
        loop_mode = 1 if inst.loop else 0
        igen += struct.pack('<HH', 54, loop_mode)  # sampleModes
        # Envelope (timecents approximation)
        ar_tc = -12000 if inst.ar >= 31 else int(-8000 + inst.ar * 200)
        dr_tc = -12000 if inst.d1r == 0 else int(-6000 + inst.d1r * 300)
        rr_tc = int(-6000 + inst.rr * 200)
        sustain_cb = inst.dl * 32  # rough mapping
        igen += struct.pack('<Hh', 34, ar_tc)
        igen += struct.pack('<Hh', 36, dr_tc)
        igen += struct.pack('<Hh', 37, sustain_cb)
        igen += struct.pack('<Hh', 38, rr_tc)
        igen += struct.pack('<HH', 53, i)  # sampleID
        end_idx = len(igen) // 4
        igen_per_inst.append((start_idx, end_idx))

    # ibag
    ibag = bytearray()
    for start_idx, end_idx in igen_per_inst:
        ibag += struct.pack('<HH', start_idx, 0)
    ibag += struct.pack('<HH', len(igen) // 4, 0)

    # inst
    inst_data = bytearray()
    for i, inst in enumerate(instruments):
        name = inst.name.encode()[:20].ljust(20, b'\x00')
        inst_data += name + struct.pack('<H', i)
    inst_data += b'EOI\x00'.ljust(20, b'\x00') + struct.pack('<H', len(instruments))

    # presets — SF2 spec: phdr has N+1 entries, pbag has N+1 entries,
    # each preset has 1 zone with 1 generator (instrument ref).
    n = len(instruments)

    # pgen: one generator per preset (instrument index)
    pgen = bytearray()
    for i in range(n):
        pgen += struct.pack('<HH', 41, i)   # genOper=instrument, amount=index

    # pbag: one bag per preset + terminal.  Each bag has gen_idx, mod_idx.
    pbag = bytearray()
    for i in range(n):
        pbag += struct.pack('<HH', i, 0)    # gen_idx=i, mod_idx=0
    pbag += struct.pack('<HH', n, 0)        # terminal bag

    # phdr: one entry per preset + EOP terminal.  Each has bag_idx.
    phdr = bytearray()
    for i, inst in enumerate(instruments):
        name = inst.name.encode()[:20].ljust(20, b'\x00')
        phdr += name
        phdr += struct.pack('<HH', inst.program, 0)  # preset, bank
        phdr += struct.pack('<H', i)                  # bag_idx
        phdr += struct.pack('<III', 0, 0, 0)            # library, genre, morphology
    # EOP terminal
    phdr += b'EOP\x00'.ljust(20, b'\x00')
    phdr += struct.pack('<HH', 255, 0)                # preset=255, bank=0
    phdr += struct.pack('<H', n)                       # bag_idx = n (terminal)
    phdr += struct.pack('<III', 0, 0, 0)

    # Assemble SF2
    sdta = write_sf2_list('sdta', write_sf2_chunk('smpl', bytes(smpl_data)))
    pdta = write_sf2_list('pdta',
                          write_sf2_chunk('phdr', bytes(phdr)),
                          write_sf2_chunk('pbag', bytes(pbag)),
                          write_sf2_chunk('pmod', b''),
                          write_sf2_chunk('pgen', bytes(pgen)),
                          write_sf2_chunk('inst', bytes(inst_data)),
                          write_sf2_chunk('ibag', bytes(ibag)),
                          write_sf2_chunk('imod', b''),
                          write_sf2_chunk('igen', bytes(igen)),
                          write_sf2_chunk('shdr', bytes(shdr)))
    info = write_sf2_list('INFO',
                          write_sf2_chunk('ifil', struct.pack('<HH', 2, 1)),
                          write_sf2_chunk('isng', b'EMU8000\x00'),
                          write_sf2_chunk('INAM', b'Saturn Sound Kit\x00\x00'))

    sfbk = b'sfbk' + info + sdta + pdta
    return b'RIFF' + struct.pack('<I', len(sfbk)) + sfbk


# ── Config File Support ─────────────────────────────────────────────

def load_config(path: str) -> List[InstrumentDef]:
    """Load instrument definitions from a JSON config file."""
    with open(path) as f:
        cfg = json.load(f)

    instruments = []
    for item in cfg.get('instruments', []):
        instruments.append(InstrumentDef(
            name=item['name'],
            program=item.get('program', len(instruments)),
            waveform=item.get('waveform', 'sine'),
            base_note=item.get('base_note', 69),
            loop=item.get('loop', True),
            cycle_length=item.get('cycle_length', CYCLE_LENGTH),
            ar=item.get('ar', 31),
            d1r=item.get('d1r', 0),
            dl=item.get('dl', 0),
            d2r=item.get('d2r', 0),
            rr=item.get('rr', 14),
            tl=item.get('tl', 0),
            disdl=item.get('disdl', 7),
            is_drum=item.get('is_drum', False),
            drum_note=item.get('drum_note', 60),
        ))
    return instruments


def save_config(instruments: List[InstrumentDef], path: str):
    """Save instrument definitions to a JSON config file."""
    cfg = {'instruments': []}
    for inst in instruments:
        item = {
            'name': inst.name,
            'program': inst.program,
            'waveform': inst.waveform,
            'base_note': inst.base_note,
            'loop': inst.loop,
            'cycle_length': inst.cycle_length,
            'ar': inst.ar, 'd1r': inst.d1r, 'dl': inst.dl,
            'd2r': inst.d2r, 'rr': inst.rr,
            'tl': inst.tl, 'disdl': inst.disdl,
        }
        if inst.is_drum:
            item['is_drum'] = True
            item['drum_note'] = inst.drum_note
        cfg['instruments'].append(item)

    with open(path, 'w') as f:
        json.dump(cfg, f, indent=2)


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Generate a Saturn Sound Kit (TON + SF2)')
    parser.add_argument('-o', '--output', default='saturn_kit',
                        help='Output base name (produces NAME.ton + NAME.sf2)')
    parser.add_argument('--mode', choices=['pcm', 'fm'], default='fm',
                        help='Kit mode: pcm=single-cycle waveforms only, fm=FM synthesis + PCM drums (default: fm)')
    parser.add_argument('--config', help='JSON config file for custom instruments')
    parser.add_argument('--save-config', help='Save default instrument config to JSON')
    parser.add_argument('--list-waveforms', action='store_true',
                        help='List available waveform generators')
    args = parser.parse_args()

    if args.list_waveforms:
        print("Available waveforms:")
        for name in sorted(WAVEFORM_GENERATORS.keys()):
            print(f"  {name}")
        return

    if args.save_config:
        kit = PCM_KIT if args.mode == 'pcm' else DEFAULT_KIT
        save_config(kit, args.save_config)
        print(f"[config] Saved {args.mode} config to {args.save_config}")
        print(f"  Edit this file to customize, then: python3 saturn_kit.py --config {args.save_config}")
        return

    # Load instruments
    if args.config:
        instruments = load_config(args.config)
        print(f"[config] Loaded {len(instruments)} instruments from {args.config}")
    elif args.mode == 'pcm':
        instruments = PCM_KIT
        print(f"[kit] Using PCM kit ({len(instruments)} instruments, single-cycle waveforms)")
    else:
        instruments = DEFAULT_KIT
        print(f"[kit] Using FM kit ({len(instruments)} instruments, FM synthesis + PCM drums)")

    # Build TON
    ton_data = build_ton(instruments)
    ton_path = args.output + '.ton'
    with open(ton_path, 'wb') as f:
        f.write(ton_data)

    # Build SF2
    sf2_data = build_sf2(instruments)
    sf2_path = args.output + '.sf2'
    with open(sf2_path, 'wb') as f:
        f.write(sf2_data)

    # Summary
    print(f"\n[ton] {ton_path} ({len(ton_data)} bytes)")
    print(f"[sf2] {sf2_path} ({len(sf2_data)} bytes)")
    print(f"\nInstruments ({len(instruments)}):")
    for inst in instruments:
        drum_str = f" (drum, note={inst.drum_note})" if inst.is_drum else ""
        print(f"  Program {inst.program:3d}: {inst.name:12s}  "
              f"waveform={inst.waveform:10s}  "
              f"AR={inst.ar} D1R={inst.d1r} DL={inst.dl} RR={inst.rr}{drum_str}")

    print(f"\nUsage:")
    print(f"  1. Load {sf2_path} in your DAW")
    print(f"  2. Compose MIDI using the program numbers above")
    print(f"  3. Export as Format 0 MIDI")
    print(f"  4. Convert: ./mid2seq input.mid output.seq")
    print(f"  5. Ship {ton_path} + output.seq + CUSTOM.MAP with your game")
    print(f"\n  Preview samples: python3 tonview.py {ton_path}")


if __name__ == '__main__':
    main()
