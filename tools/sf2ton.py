#!/usr/bin/env python3
"""
sf2ton.py — Convert a SoundFont (.sf2) to Sega Saturn .TON + .MAP files.

The .TON file contains instrument definitions (voices/layers mapping to SCSP
slot parameters) plus embedded PCM sample data.  The .MAP file tells the
Saturn sound driver where to load the tone bank in the SCSP's 512KB sound RAM.

Usage:
  python3 sf2ton.py input.sf2 [-o output.ton] [--map output.map]
                               [--base-addr 0x30000] [--bank 0]

References:
  - kingshriek's ssfinfo.py/tonext.py (VGMToolbox) — TON format documentation
  - VGMTrans SegSatInstrSet — ADSR conversion tables (from MAME SCSP)
  - Sega Sound Driver Implementation Manual (ST-241)
"""

import struct
import sys
import os
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ── SF2 Parser (minimal, handles what we need) ──────────────────────

def read_sf2_chunks(data: bytes) -> dict:
    """Parse RIFF/SF2 into a dict of chunk name → data."""
    chunks = {}
    if data[:4] != b'RIFF' or data[8:12] != b'sfbk':
        raise ValueError("Not a valid SF2 file")
    pos = 12
    while pos < len(data):
        chunk_id = data[pos:pos+4].decode('ascii', errors='replace')
        chunk_size = struct.unpack('<I', data[pos+4:pos+8])[0]
        if chunk_id == 'LIST':
            list_type = data[pos+8:pos+12].decode('ascii', errors='replace')
            # Recurse into LIST
            inner = read_sf2_chunks_flat(data[pos+12:pos+8+chunk_size])
            chunks.update(inner)
        else:
            chunks[chunk_id] = data[pos+8:pos+8+chunk_size]
        pos += 8 + chunk_size + (chunk_size & 1)  # pad to even
    return chunks


def read_sf2_chunks_flat(data: bytes) -> dict:
    """Parse inner LIST chunks."""
    chunks = {}
    pos = 0
    while pos < len(data):
        chunk_id = data[pos:pos+4].decode('ascii', errors='replace')
        chunk_size = struct.unpack('<I', data[pos+4:pos+8])[0]
        if chunk_id == 'LIST':
            list_type = data[pos+8:pos+12].decode('ascii', errors='replace')
            inner = read_sf2_chunks_flat(data[pos+12:pos+8+chunk_size])
            chunks.update(inner)
        else:
            chunks[chunk_id] = data[pos+8:pos+8+chunk_size]
        pos += 8 + chunk_size + (chunk_size & 1)
    return chunks


@dataclass
class SF2Sample:
    name: str
    start: int      # offset in smpl chunk (in samples)
    end: int
    loop_start: int
    loop_end: int
    sample_rate: int
    original_key: int
    pitch_correction: int  # cents
    sample_type: int       # 1=mono, 2=right, 4=left, 8=linked


@dataclass
class SF2Zone:
    """An instrument zone (key/vel range → sample + generators)."""
    key_lo: int = 0
    key_hi: int = 127
    vel_lo: int = 0
    vel_hi: int = 127
    sample_id: int = -1
    # Generator values (SF2 spec)
    attenuation: float = 0.0    # cB (centibels)
    pan: float = 0.0            # -500..500 (% × 10)
    sample_modes: int = 0       # 0=no loop, 1=loop, 3=loop+release
    root_key: int = -1          # override (-1 = use sample header)
    fine_tune: int = 0          # cents
    coarse_tune: int = 0        # semitones
    # Envelope (in timecents, 1200tc = 1 second)
    vol_attack: float = -12000  # timecents
    vol_decay: float = -12000
    vol_sustain: float = 0      # cB attenuation (0 = max sustain)
    vol_release: float = -12000


def parse_sf2_samples(shdr_data: bytes) -> List[SF2Sample]:
    """Parse shdr chunk into sample list."""
    samples = []
    entry_size = 46
    count = len(shdr_data) // entry_size
    for i in range(count - 1):  # last entry is EOS
        off = i * entry_size
        name = shdr_data[off:off+20].split(b'\x00')[0].decode('ascii', errors='replace')
        start, end, ls, le, sr, key, corr, stype, link = struct.unpack(
            '<IIIIIBbHH', shdr_data[off+20:off+46])
        samples.append(SF2Sample(name, start, end, ls, le, sr, key, corr, stype))
    return samples


# SF2 generator enum values we care about
GEN_KEY_RANGE = 43
GEN_VEL_RANGE = 44
GEN_SAMPLE_ID = 53
GEN_ATTENUATION = 48
GEN_PAN = 17
GEN_SAMPLE_MODES = 54
GEN_ROOT_KEY = 58
GEN_FINE_TUNE = 52
GEN_COARSE_TUNE = 51
GEN_VOL_ATTACK = 34
GEN_VOL_DECAY = 36
GEN_VOL_SUSTAIN = 37
GEN_VOL_RELEASE = 38
GEN_INSTRUMENT = 41


def parse_generators(data: bytes) -> List[List[Tuple[int, int]]]:
    """Parse a bag+gen pair into zones, each with a list of (gen_id, value)."""
    # This is simplified — a full parser would handle bags properly
    gens = []
    entry_size = 4  # genOper(2) + genAmount(2)
    count = len(data) // entry_size
    zone = []
    for i in range(count):
        gen_id, amount = struct.unpack('<HH', data[i*4:i*4+4])
        if gen_id == 0 and amount == 0 and i > 0:
            # New zone marker (heuristic)
            pass
        zone.append((gen_id, amount))
    return zone


def parse_sf2_instruments(chunks: dict, samples: List[SF2Sample]) -> List[List[SF2Zone]]:
    """Parse instruments from SF2 chunks. Returns list of instruments,
    each being a list of zones."""
    # Get instrument headers
    inst_data = chunks.get('inst', b'')
    ibag_data = chunks.get('ibag', b'')
    igen_data = chunks.get('igen', b'')

    if not inst_data or not ibag_data or not igen_data:
        raise ValueError("Missing instrument chunks in SF2")

    # Parse inst headers
    inst_count = len(inst_data) // 22
    insts = []
    for i in range(inst_count - 1):  # last is EOI
        off = i * 22
        name = inst_data[off:off+20].split(b'\x00')[0].decode('ascii', errors='replace')
        bag_idx = struct.unpack('<H', inst_data[off+20:off+22])[0]
        next_bag = struct.unpack('<H', inst_data[off+22+20:off+22+22])[0]
        insts.append((name, bag_idx, next_bag))

    # Parse ibag entries (each is gen_idx + mod_idx, 4 bytes)
    bag_count = len(ibag_data) // 4
    bags = []
    for i in range(bag_count):
        gen_idx, mod_idx = struct.unpack('<HH', ibag_data[i*4:i*4+4])
        bags.append(gen_idx)

    # Parse igen entries (each is gen_oper + gen_amount, 4 bytes)
    gen_count = len(igen_data) // 4
    gens = []
    for i in range(gen_count):
        gen_oper, gen_amount = struct.unpack('<Hh', igen_data[i*4:i*4+4])
        gens.append((gen_oper, gen_amount))

    # Build zones for each instrument
    instruments = []
    for name, bag_start, bag_end in insts:
        zones = []
        for bag_i in range(bag_start, bag_end):
            gen_start = bags[bag_i]
            gen_end = bags[bag_i + 1] if bag_i + 1 < len(bags) else gen_count
            zone = SF2Zone()
            has_sample = False
            for gi in range(gen_start, gen_end):
                gen_id, val = gens[gi]
                uval = val & 0xFFFF  # unsigned interpretation
                if gen_id == GEN_KEY_RANGE:
                    zone.key_lo = uval & 0xFF
                    zone.key_hi = (uval >> 8) & 0xFF
                elif gen_id == GEN_VEL_RANGE:
                    zone.vel_lo = uval & 0xFF
                    zone.vel_hi = (uval >> 8) & 0xFF
                elif gen_id == GEN_SAMPLE_ID:
                    zone.sample_id = uval
                    has_sample = True
                elif gen_id == GEN_ATTENUATION:
                    zone.attenuation = val  # cB
                elif gen_id == GEN_PAN:
                    zone.pan = val
                elif gen_id == GEN_SAMPLE_MODES:
                    zone.sample_modes = uval
                elif gen_id == GEN_ROOT_KEY:
                    zone.root_key = uval
                elif gen_id == GEN_FINE_TUNE:
                    zone.fine_tune = val
                elif gen_id == GEN_COARSE_TUNE:
                    zone.coarse_tune = val
                elif gen_id == GEN_VOL_ATTACK:
                    zone.vol_attack = val
                elif gen_id == GEN_VOL_DECAY:
                    zone.vol_decay = val
                elif gen_id == GEN_VOL_SUSTAIN:
                    zone.vol_sustain = val
                elif gen_id == GEN_VOL_RELEASE:
                    zone.vol_release = val
            if has_sample:
                zones.append(zone)
        instruments.append(zones)
    return instruments


def parse_sf2_presets(chunks: dict) -> List[Tuple[str, int, int, int]]:
    """Parse preset headers. Returns (name, preset_num, bank, inst_idx)."""
    phdr = chunks.get('phdr', b'')
    pbag = chunks.get('pbag', b'')
    pgen = chunks.get('pgen', b'')
    if not phdr:
        return []

    presets = []
    count = len(phdr) // 38
    for i in range(count - 1):  # last is EOP
        off = i * 38
        name = phdr[off:off+20].split(b'\x00')[0].decode('ascii', errors='replace')
        preset_num = struct.unpack('<H', phdr[off+20:off+22])[0]
        bank = struct.unpack('<H', phdr[off+22:off+24])[0]
        bag_idx = struct.unpack('<H', phdr[off+24:off+26])[0]

        # Find which instrument this preset references
        if pbag and pgen:
            next_bag = struct.unpack('<H', phdr[off+38+24:off+38+26])[0] if i + 1 < count - 1 else len(pbag) // 4
            gen_start = struct.unpack('<HH', pbag[bag_idx*4:bag_idx*4+4])[0]
            gen_end = struct.unpack('<HH', pbag[next_bag*4:next_bag*4+4])[0] if next_bag < len(pbag)//4 else len(pgen)//4
            inst_idx = -1
            for gi in range(gen_start, min(gen_end, len(pgen)//4)):
                gen_id, val = struct.unpack('<Hh', pgen[gi*4:gi*4+4])
                if gen_id == GEN_INSTRUMENT:
                    inst_idx = val & 0xFFFF
            presets.append((name, preset_num, bank, inst_idx))
        else:
            presets.append((name, preset_num, bank, i))

    return presets


# ── SCSP ADSR Conversion ────────────────────────────────────────────

# Attack rate times in ms (from MAME SCSP, indexed by AR*2)
AR_TIMES = [
    100000,100000,8100.0,6900.0,6000.0,4800.0,4000.0,3400.0,3000.0,2400.0,
    2000.0,1700.0,1500.0,1200.0,1000.0,860.0,760.0,600.0,500.0,430.0,
    380.0,300.0,250.0,220.0,190.0,150.0,130.0,110.0,95.0,76.0,
    63.0,55.0,47.0,38.0,31.0,27.0,24.0,19.0,15.0,13.0,
    12.0,9.4,7.9,6.8,6.0,4.7,3.8,3.4,3.0,2.4,
    2.0,1.8,1.6,1.3,1.1,0.93,0.85,0.65,0.53,0.44,
    0.40,0.35,0.0,0.0
]

# Decay/release rate times in ms
DR_TIMES = [
    100000,100000,118200.0,101300.0,88600.0,70900.0,59100.0,50700.0,
    44300.0,35500.0,29600.0,25300.0,22200.0,17700.0,14800.0,12700.0,
    11100.0,8900.0,7400.0,6300.0,5500.0,4400.0,3700.0,3200.0,
    2800.0,2200.0,1800.0,1600.0,1400.0,1100.0,920.0,790.0,
    690.0,550.0,460.0,390.0,340.0,270.0,230.0,200.0,
    170.0,140.0,110.0,98.0,85.0,68.0,57.0,49.0,
    43.0,34.0,28.0,25.0,22.0,18.0,14.0,12.0,
    11.0,8.5,7.1,6.1,5.4,4.3,3.6,3.1
]


def timecents_to_ms(tc: float) -> float:
    """Convert SF2 timecents to milliseconds."""
    if tc <= -12000:
        return 0.0
    return 1000.0 * (2.0 ** (tc / 1200.0))


def ms_to_ar(ms: float) -> int:
    """Find the closest SCSP attack rate for a given time in ms."""
    # AR=0,1 are essentially infinite, AR=31 is instant
    if ms <= 0:
        return 31
    # VGMTrans applies a 0.625 factor: attack_time = ARTimes[ar*2] * 0.625
    ms_adjusted = ms / 0.625
    best = 2
    best_diff = abs(AR_TIMES[2] - ms_adjusted)
    for i in range(2, 62):
        diff = abs(AR_TIMES[i] - ms_adjusted)
        if diff < best_diff:
            best_diff = diff
            best = i
    # AR register value = index / 2
    return max(2, min(31, best // 2))


def ms_to_dr(ms: float) -> int:
    """Find the closest SCSP decay/release rate for a given time in ms."""
    if ms <= 0:
        return 31
    if ms > 100000:
        return 0
    best = 2
    best_diff = abs(DR_TIMES[2] - ms)
    for i in range(2, 64):
        diff = abs(DR_TIMES[i] - ms)
        if diff < best_diff:
            best_diff = diff
            best = i
    return max(0, min(31, best // 2))


def cb_to_tl(cb: float) -> int:
    """Convert centibels attenuation to SCSP Total Level (0-255).
    TL ≈ 0.375 dB/step, so 1 cB = 0.1 dB ≈ 0.267 TL steps."""
    if cb <= 0:
        return 0
    tl = int(round(cb * 0.1 / 0.375))
    return max(0, min(255, tl))


def sf2_pan_to_dipan(pan: float) -> int:
    """Convert SF2 pan (-500..+500) to SCSP DIPAN (0-31).
    DIPAN: bit4=direction, bits3:0=attenuation.
    0x00=full left, 0x0F=center-ish, 0x1F=full right... actually
    DIPAN 0=center, 0x0F=hard left attenuated, 0x1F=hard right attenuated.
    This is a simplification."""
    # Simple linear mapping
    if pan <= -500:
        return 0x1F  # full left
    if pan >= 500:
        return 0x0F  # full right
    # Center = 0
    if abs(pan) < 50:
        return 0
    if pan < 0:
        atten = int((-pan / 500.0) * 15)
        return 0x10 | min(15, atten)
    else:
        atten = int((pan / 500.0) * 15)
        return min(15, atten)


def sustain_cb_to_dl(cb: float) -> int:
    """Convert SF2 sustain attenuation (cB) to SCSP Decay Level (0-31).
    DL=0 means sustain at max volume, DL=31 means sustain at silence."""
    if cb <= 0:
        return 0  # max sustain
    if cb >= 1000:
        return 31  # silence
    return min(31, int(cb / 32.0))


# ── TON Builder ─────────────────────────────────────────────────────

@dataclass
class TonLayer:
    """32-byte layer entry matching SCSP slot parameters."""
    start_note: int = 0
    end_note: int = 127
    base_note: int = 60
    fine_tune: int = 0
    # SCSP slot params
    sa: int = 0            # 20-bit sample start address (byte offset)
    lsa: int = 0           # loop start (samples from SA)
    lea: int = 0           # loop end (samples from SA)
    pcm8b: int = 0         # 0=16-bit, 1=8-bit
    lpctl: int = 0         # 0=no loop, 1=forward
    ar: int = 31           # attack rate (0-31)
    d1r: int = 0           # decay 1 rate
    d2r: int = 0           # decay 2 rate
    dl: int = 0            # decay level (sustain)
    rr: int = 14           # release rate
    tl: int = 0            # total level (attenuation)
    krs: int = 0           # key rate scaling
    disdl: int = 7         # direct send level
    dipan: int = 0         # direct pan
    # Unused for basic conversion
    sbctl: int = 0
    ssctl: int = 0
    mdl: int = 0
    mdxsl: int = 0
    mdysl: int = 0
    oct: int = 0
    fns: int = 0
    isel: int = 0
    imxl: int = 0
    velocity_id: int = 0
    peg_id: int = 0
    plfo_id: int = 0

    def pack(self) -> bytes:
        """Pack into 32 bytes matching TON layer format."""
        b = bytearray(0x20)
        b[0x00] = self.start_note & 0xFF
        b[0x01] = self.end_note & 0xFF
        # byte 2: PEON=0, PLON=0, FMCB=0, SBCTL, SSCTL high
        b[0x02] = (self.sbctl & 3) << 1 | (self.ssctl >> 1) & 1
        # byte 3: SSCTL low, LPCTL, PCM8B, SA high
        b[0x03] = ((self.ssctl & 1) << 7) | ((self.lpctl & 3) << 5) | \
                  ((self.pcm8b & 1) << 4) | ((self.sa >> 16) & 0xF)
        struct.pack_into('>H', b, 0x04, self.sa & 0xFFFF)
        struct.pack_into('>H', b, 0x06, self.lsa & 0xFFFF)
        struct.pack_into('>H', b, 0x08, self.lea & 0xFFFF)
        # byte A: D2R[4:0] << 3 | D1R[4:2]
        b[0x0A] = ((self.d2r & 0x1F) << 3) | ((self.d1r >> 2) & 0x7)
        # byte B: D1R[1:0] << 6 | EGHOLD << 5 | AR[4:0]
        b[0x0B] = ((self.d1r & 0x3) << 6) | (self.ar & 0x1F)
        # byte C: LPSLNK << 6 | KRS << 3 | DL[4:3]
        b[0x0C] = ((self.krs & 0x7) << 3) | ((self.dl >> 3) & 0x3)
        # byte D: DL[2:0] << 5 | RR[4:0]
        b[0x0D] = ((self.dl & 0x7) << 5) | (self.rr & 0x1F)
        # byte E: MWH=0, MWE=0, MWL=0, STWINH=0, SDIR=0
        b[0x0E] = 0
        b[0x0F] = self.tl & 0xFF
        # bytes 10-11: MDL, MDXSL, MDYSL
        b[0x10] = (self.mdl << 4) | ((self.mdxsl >> 2) & 0xF)
        b[0x11] = ((self.mdxsl & 3) << 6) | (self.mdysl & 0x3F)
        # bytes 12-13: OCT, FNS (pitch — 0 for base note, driver adjusts per key)
        b[0x12] = (self.oct & 0xF) << 3
        b[0x13] = 0
        # bytes 14-15: LFO (all zero for basic conversion)
        b[0x14] = 0
        b[0x15] = 0
        b[0x16] = 0
        # byte 17: ISEL, IMXL
        b[0x17] = ((self.isel & 0xF) << 3) | (self.imxl & 0x7)
        # byte 18: DISDL, DIPAN
        b[0x18] = ((self.disdl & 0x7) << 5) | (self.dipan & 0x1F)
        b[0x19] = self.base_note & 0xFF
        b[0x1A] = struct.pack('b', max(-128, min(127, self.fine_tune)))[0]
        # bytes 1B-1C: FM (unused)
        b[0x1B] = 0
        b[0x1C] = 0
        b[0x1D] = self.velocity_id
        b[0x1E] = self.peg_id
        b[0x1F] = self.plfo_id
        return bytes(b)


@dataclass
class TonVoice:
    """Voice entry: header + layers."""
    bend_range: int = 2
    portamento: int = 0
    volume_bias: int = 0
    layers: List[TonLayer] = field(default_factory=list)

    def pack(self) -> bytes:
        hdr = bytearray(4)
        hdr[0] = self.bend_range & 0xF
        hdr[1] = self.portamento
        hdr[2] = struct.pack('b', len(self.layers) - 1)[0]
        hdr[3] = struct.pack('b', self.volume_bias)[0]
        return bytes(hdr) + b''.join(l.pack() for l in self.layers)


def build_ton(voices: List[TonVoice], pcm_data: bytes) -> bytes:
    """Build a complete .TON file."""
    # Default mixer: all channels at EFSDL=0 (no DSP effect send)
    mixer = bytes([0x00] * 0x12)

    # Default velocity table: maps MIDI velocity to TL attenuation.
    # The VL table is a piecewise-linear curve with 4 segments:
    #   (slope0, point0, level0, slope1, point1, level1, slope2, point2, level2, slope3)
    # 'level' = TL attenuation (0=loudest, 127=silent).
    # This curve matches mechs.ton: low velocity→moderate atten, high velocity→low atten.
    vl = struct.pack('bbBbbBbbBb', 25, 16, 54, 9, 49, 102, 19, 93, 122, 43)

    # Default PEG: no pitch envelope
    peg = bytes([0x00] * 0x0A)

    # Default PLFO: no pitch LFO
    plfo = bytes([0x00] * 0x04)

    # Calculate offsets
    header_size = 8 + len(voices) * 2  # 4 fixed offsets + voice offsets
    mixer_offset = header_size
    vl_offset = mixer_offset + len(mixer)
    peg_offset = vl_offset + len(vl)
    plfo_offset = peg_offset + len(peg)

    # Pack voices and calculate their offsets
    voice_offset = plfo_offset + len(plfo)
    voice_data = []
    voice_offsets = []
    cur_offset = voice_offset
    for v in voices:
        voice_offsets.append(cur_offset)
        packed = v.pack()
        voice_data.append(packed)
        cur_offset += len(packed)

    # PCM data follows voices
    pcm_offset = cur_offset

    # Build header
    hdr = bytearray()
    hdr += struct.pack('>H', mixer_offset)
    hdr += struct.pack('>H', vl_offset)
    hdr += struct.pack('>H', peg_offset)
    hdr += struct.pack('>H', plfo_offset)
    for off in voice_offsets:
        hdr += struct.pack('>H', off)

    # Assemble file
    ton = bytearray()
    ton += hdr
    ton += mixer
    ton += vl
    ton += peg
    ton += plfo
    for vd in voice_data:
        ton += vd
    ton += pcm_data

    return bytes(ton)


def build_map_entry(entry_type: int, bank: int, addr: int, size: int) -> bytes:
    """Build a single 8-byte MAP entry."""
    entry = bytearray(8)
    entry[0] = ((entry_type & 0xF) << 4) | (bank & 0xF)
    entry[1:4] = struct.pack('>I', addr)[1:]      # 24-bit address
    entry[4] = 0x80                                # transfer complete
    entry[5:8] = struct.pack('>I', size)[1:]       # 24-bit size
    return bytes(entry)


def build_map(tone_addr: int, tone_size: int,
              seq_addr: int, seq_size: int, bank: int = 1) -> bytes:
    """Build a .MAP file compatible with Saturn SGL sound driver.

    The SGL driver (sddrvs) expects bank 0 to hold its default tone/seq
    data at fixed addresses.  User music goes in bank 1+.

    The SaturnRingLib SEQ sample uses:
      MAP_CMD_SEQ = 0x11 (SEQ bank 1)
      MAP_CMD_TON = 0x01 (TONE bank 1)
    """
    entries = bytearray()

    # Bank 0 defaults (required by SGL sound driver)
    # These addresses match the standard SGL layout
    entries += build_map_entry(3, 0, 0x00C000, 0x010040)  # DSP_RAM
    entries += build_map_entry(2, 0, 0x01C040, 0x000540)  # DSP_PROG
    entries += build_map_entry(1, 0, 0x024580, 0x00016E)  # SEQ bank 0
    entries += build_map_entry(0, 0, 0x0246EE, 0x0088EC)  # TONE bank 0

    # User music (bank 1)
    entries += build_map_entry(1, bank, seq_addr, seq_size)   # SEQ
    entries += build_map_entry(0, bank, tone_addr, tone_size)  # TONE

    # Terminator
    entries += b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF'

    return bytes(entries)


# ── Conversion Logic ────────────────────────────────────────────────

def convert_sample(raw_16le: bytes, start: int, end: int,
                   loop_start: int, loop_end: int,
                   sample_rate: int) -> Tuple[bytes, int, int, int]:
    """Convert SF2 sample data (16-bit LE) to Saturn format (16-bit BE).
    Returns (pcm_data, lsa_samples, lea_samples, sample_count).

    If sample rate != 44100, we'd need resampling. For now, we just
    note the rate difference and let the OCT/FNS handle pitch adjustment.
    """
    sample_count = end - start
    if sample_count <= 0:
        return b'', 0, 0, 0

    # Extract and byte-swap (LE → BE)
    pcm = bytearray()
    for i in range(start, min(end, len(raw_16le) // 2)):
        sample = struct.unpack('<h', raw_16le[i*2:i*2+2])[0]
        pcm += struct.pack('>h', sample)

    # Loop points relative to sample start
    lsa = max(0, loop_start - start)
    lea = max(0, min(loop_end - start, sample_count))

    return bytes(pcm), lsa, lea, sample_count


def sf2_to_ton(sf2_path: str, base_addr: int = 0x30000) -> Tuple[bytes, List[Tuple[str, int]]]:
    """Convert SF2 to TON. Returns (ton_data, [(preset_name, program_num), ...])."""
    with open(sf2_path, 'rb') as f:
        sf2_data = f.read()

    chunks = read_sf2_chunks(sf2_data)
    samples = parse_sf2_samples(chunks['shdr'])
    instruments = parse_sf2_instruments(chunks, samples)
    presets = parse_sf2_presets(chunks)
    raw_pcm = chunks['smpl']  # 16-bit LE samples

    print(f"[sf2] {len(samples)} samples, {len(instruments)} instruments, {len(presets)} presets")

    # Convert samples and track their offsets in the output
    sample_cache = {}  # sample_id → (pcm_offset, lsa, lea, count)
    pcm_chunks = []
    pcm_offset = 0  # will be adjusted after we know the voice data size

    for i, s in enumerate(samples):
        if s.sample_type not in (0, 1):  # skip linked/stereo
            continue
        pcm_data, lsa, lea, count = convert_sample(
            raw_pcm, s.start, s.end,
            s.loop_start, s.loop_end,
            s.sample_rate)
        if len(pcm_data) > 0:
            sample_cache[i] = (pcm_offset, lsa, lea, count, s)
            pcm_chunks.append(pcm_data)
            pcm_offset += len(pcm_data)

    all_pcm = b''.join(pcm_chunks)
    print(f"[sf2] {len(sample_cache)} usable samples, {len(all_pcm)} bytes PCM")

    # Build voices from presets (one voice per preset, ordered by program number)
    voices = []
    preset_info = []

    # Sort presets by program number
    sorted_presets = sorted(presets, key=lambda p: (p[2], p[1]))  # bank, program

    for name, prog, bank, inst_idx in sorted_presets:
        if bank != 0:
            continue  # only bank 0 for now
        if inst_idx < 0 or inst_idx >= len(instruments):
            continue
        zones = instruments[inst_idx]
        if not zones:
            continue

        voice = TonVoice(bend_range=2)
        for z in zones:
            if z.sample_id < 0 or z.sample_id not in sample_cache:
                continue

            pcm_off, lsa, lea, count, smp = sample_cache[z.sample_id]
            root = z.root_key if z.root_key >= 0 else smp.original_key

            # Convert envelope
            attack_ms = timecents_to_ms(z.vol_attack)
            decay_ms = timecents_to_ms(z.vol_decay)
            release_ms = timecents_to_ms(z.vol_release)

            layer = TonLayer(
                start_note=z.key_lo,
                end_note=z.key_hi,
                base_note=root & 0x7F,
                fine_tune=max(-128, min(127, z.fine_tune + z.coarse_tune * 100 + smp.pitch_correction)),
                sa=pcm_off,  # adjusted later
                lsa=lsa,
                lea=lea if lea > 0 else count,
                pcm8b=0,
                lpctl=1 if z.sample_modes in (1, 3) else 0,
                ar=ms_to_ar(attack_ms),
                d1r=ms_to_dr(decay_ms),
                d2r=0,
                dl=sustain_cb_to_dl(z.vol_sustain),
                rr=ms_to_dr(release_ms),
                tl=cb_to_tl(z.attenuation),
                disdl=7,
                dipan=sf2_pan_to_dipan(z.pan),
            )
            voice.layers.append(layer)

        if voice.layers:
            voices.append(voice)
            preset_info.append((name, prog))
            print(f"  Voice {len(voices)-1}: '{name}' (prog {prog}) — {len(voice.layers)} layers")

    if not voices:
        raise ValueError("No usable instruments found in SF2")

    # Now we know the voice data size, adjust SA offsets
    # SA = (offset within TON file where PCM lives) = voice_data_end + pcm_chunk_offset
    # We need to compute voice_data_end first
    header_size = 8 + len(voices) * 2
    tables_size = 0x12 + 0x0A + 0x0A + 0x04  # mixer + vl + peg + plfo
    voice_data_size = sum(v.pack().__len__() for v in voices)
    pcm_start_in_file = header_size + tables_size + voice_data_size

    # Rebuild sample_cache offsets relative to file start
    for voice in voices:
        for layer in voice.layers:
            layer.sa = pcm_start_in_file + layer.sa

    ton_data = build_ton(voices, all_pcm)
    print(f"[ton] {len(ton_data)} bytes ({len(voices)} voices)")
    return ton_data, preset_info


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Convert SoundFont (.sf2) to Saturn .TON')
    parser.add_argument('input', help='Input .sf2 file')
    parser.add_argument('-o', '--output', help='Output .ton file')
    parser.add_argument('--map', help='Output .map file')
    parser.add_argument('--seq', help='SEQ file (to compute MAP addresses)')
    parser.add_argument('--base-addr', type=lambda x: int(x, 0), default=0x02CFDC,
                        help='Base address for bank 1 data in sound RAM (default: 0x02CFDC, after SGL bank 0)')
    args = parser.parse_args()

    if not args.output:
        args.output = os.path.splitext(args.input)[0] + '.ton'

    ton_data, preset_info = sf2_to_ton(args.input, args.base_addr)

    with open(args.output, 'wb') as f:
        f.write(ton_data)
    print(f"[out] {args.output} ({len(ton_data)} bytes)")

    # Compute SEQ size if provided
    seq_size = 0
    if args.seq:
        seq_size = os.path.getsize(args.seq)
        print(f"[seq] {args.seq}: {seq_size} bytes")

    # Layout: SEQ at base_addr, TON immediately after
    seq_addr = args.base_addr
    ton_addr = seq_addr + seq_size
    # Align TON to 2-byte boundary
    if ton_addr & 1:
        ton_addr += 1

    map_output = args.map if args.map else os.path.splitext(args.output)[0] + '.map'
    map_data = build_map(ton_addr, len(ton_data), seq_addr, seq_size, bank=1)
    with open(map_output, 'wb') as f:
        f.write(map_data)
    print(f"[out] {map_output} ({len(map_data)} bytes)")

    total = ton_addr + len(ton_data) - 0xB000
    ram_pct = total / (512 * 1024) * 100
    print(f"\n[ram] Sound RAM usage: 0xB000..0x{ton_addr + len(ton_data):05X} "
          f"({total} bytes, {ram_pct:.1f}% of 512KB)")

    # Print voice mapping for reference
    print("\nVoice mapping (MIDI program → TON voice):")
    for i, (name, prog) in enumerate(preset_info):
        print(f"  Program {prog:3d} → Voice {i}: {name}")


if __name__ == '__main__':
    main()
