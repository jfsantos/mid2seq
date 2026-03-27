#!/usr/bin/env python3
"""
scan_saturn_audio.py — Scan Saturn game files for embedded TON and SEQ data.

Many Saturn games bundle TON (instrument/sample) and SEQ (sequence) data inside
larger binaries (sound drivers, data archives) rather than shipping them as
standalone files.  This tool scans arbitrary binary files for valid TON and SEQ
structures, reports what it finds, and optionally extracts them.

Usage:
  python3 scan_saturn_audio.py /path/to/disc              # scan & report
  python3 scan_saturn_audio.py /path/to/disc -x outdir    # scan & extract
  python3 scan_saturn_audio.py file.bin                    # scan a single file
  python3 scan_saturn_audio.py disc.bin --cue disc.cue     # scan a BIN/CUE image

The scanner uses structural validation (not magic bytes — TON/SEQ have none) so
it may produce false positives on non-Saturn data.  Candidates are ranked by a
confidence score; those below --min-confidence are hidden.
"""

import argparse
import os
import struct
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# TON / SEQ structural constants
# ---------------------------------------------------------------------------

TON_MIXER_SIZE = 0x12               # 18 bytes of EFSDL/EFPAN
TON_VL_ENTRY_SIZE = 0x0A            # velocity-level table entry
TON_PEG_ENTRY_SIZE = 0x0A           # pitch envelope entry
TON_PLFO_ENTRY_SIZE = 0x04          # pitch LFO entry
TON_LAYER_SIZE = 0x20               # 32 bytes per SCSP layer
TON_VOICE_HEADER = 4                # bend_range, portamento, nlayers-1, vol_bias
TON_UNIT_SIZES = [TON_MIXER_SIZE, TON_VL_ENTRY_SIZE, TON_PEG_ENTRY_SIZE,
                  TON_PLFO_ENTRY_SIZE]  # for offset delta validation

SA_MASK = 0x0007FFFF                # 19-bit SA address within 512KB SCSP RAM

SEQ_COMMON_RESOLUTIONS = {24, 48, 96, 120, 192, 240, 320, 384, 480, 960}
SEQ_END_OF_TRACK = 0x83

# SEQ command length table (from kingshriek's seqext.py).
# Index = command byte, value = total command length in bytes.
# 0x00-0x7F: NOTE events (5 bytes: note, velocity, gate, step — plus extended forms)
# 0x80: NOP (1), 0x81: REFERENCE (4), 0x82: LOOP (2), 0x83: END (1)
# 0x84-0x9F: extended gate/step prefixes (1 byte each)
# 0xA0-0xBF: CONTROL_CHANGE (4), 0xC0-0xEF: PC/CP/PB (3), 0xF0-0xFF: system (1)
SEQ_CMD_LEN = ([5] * 0x80 + [1, 4, 2, 1] + [1] * 0x1C +
               [4] * 0x20 + [3] * 0x30 + [1] * 0x10)


# ---------------------------------------------------------------------------
# Data classes for results
# ---------------------------------------------------------------------------

@dataclass
class TonCandidate:
    file: str
    offset: int
    nvoices: int
    mixer_off: int
    vl_off: int
    peg_off: int
    plfo_off: int
    voice_offsets: list
    confidence: float = 0.0
    pcm_region: Optional[tuple] = None   # (start, end) absolute in file
    size_estimate: int = 0
    notes: list = field(default_factory=list)


@dataclass
class SeqSong:
    index: int
    resolution: int
    num_tempo: int
    data_offset: int
    tempo_loop_offset: int
    bpm: float = 0.0


@dataclass
class SeqCandidate:
    file: str
    offset: int
    num_songs: int
    songs: list
    confidence: float = 0.0
    size_estimate: int = 0
    notes: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# TON scanning
# ---------------------------------------------------------------------------

def _validate_ton_at(data: bytes, off: int, filesize: int) -> Optional[TonCandidate]:
    """Try to parse a TON header at *off* inside *data*.  Return a
    TonCandidate if plausible, else None."""

    if off + 8 > len(data):
        return None

    mixer_off = struct.unpack('>H', data[off:off + 2])[0]
    vl_off    = struct.unpack('>H', data[off + 2:off + 4])[0]
    peg_off   = struct.unpack('>H', data[off + 4:off + 6])[0]
    plfo_off  = struct.unpack('>H', data[off + 6:off + 8])[0]

    # Basic sanity: offsets must be ascending and mixer_off large enough for
    # at least one voice pointer (8 header bytes + 2 per voice).
    # Kingshriek uses 0x000A–0x0108 for mixer_off (1–128 voices).
    if not (0x000A <= mixer_off <= 0x0108):
        return None
    if not (mixer_off < vl_off < peg_off < plfo_off):
        return None

    nvoices = (mixer_off - 8) // 2
    if not (1 <= nvoices <= 128):
        return None

    # Make sure we can read all voice pointers.
    if off + 8 + nvoices * 2 > len(data):
        return None

    voice_offsets = []
    for vi in range(nvoices):
        v = struct.unpack('>H', data[off + 8 + vi * 2:off + 10 + vi * 2])[0]
        voice_offsets.append(v)

    # Build the full offset list: mixer, vl, peg, plfo, voice0, voice1, ...
    offset_list = [mixer_off, vl_off, peg_off, plfo_off] + list(voice_offsets)

    # All offsets must be strictly monotonically increasing.
    offset_diffs = [offset_list[i + 1] - offset_list[i] for i in range(len(offset_list) - 1)]
    if any(d <= 0 for d in offset_diffs):
        return None

    # ---- Offset delta consistency check (from kingshriek's tonext.py) ----
    # The first 4 deltas (mixer→vl, vl→peg, peg→plfo, plfo→voice0) must be
    # exact multiples of the known unit data sizes.  Voice-to-voice deltas
    # must leave a remainder of exactly 4 (the voice header) when divided by
    # the layer size — i.e., delta % 0x20 == 0x04.
    score = 50.0
    notes = []

    unit_deltas = offset_diffs[:4]    # mixer→vl, vl→peg, peg→plfo, plfo→voice0
    voice_deltas = offset_diffs[4:]   # voice0→voice1, voice1→voice2, ...

    deltas_ok = True
    for d, unit_sz in zip(unit_deltas[:3], TON_UNIT_SIZES[:3]):
        if d % unit_sz != 0:
            deltas_ok = False
            break
    # plfo→voice0: remainder must be the voice header (4 bytes mod layersize).
    if deltas_ok and len(unit_deltas) >= 4:
        if unit_deltas[3] % TON_PLFO_ENTRY_SIZE != 0:
            # Not a strict multiple of PLFO entry size — tolerate if it's
            # at least larger than PLFO_ENTRY_SIZE.
            if unit_deltas[3] < TON_PLFO_ENTRY_SIZE:
                deltas_ok = False

    if not deltas_ok:
        return None  # hard fail — offset deltas are inconsistent

    # Voice deltas: each must be header(4) + nlayers * 0x20.
    voice_deltas_consistent = all(d % TON_LAYER_SIZE == TON_VOICE_HEADER
                                  for d in voice_deltas)
    if voice_deltas_consistent:
        score += 15  # strong structural signal

    # ---- Per-voice / per-layer validation ----
    total_layers = 0
    # Collect (sa, pcm8b, lea) for precise size calculation.
    sa_info: list[tuple[int, int, int]] = []  # (sa_addr, pcm8b, lea)

    for vi, voff_rel in enumerate(voice_offsets):
        abs_voff = off + voff_rel
        if abs_voff + TON_VOICE_HEADER > len(data):
            return None

        raw_nlayers = struct.unpack('b', bytes([data[abs_voff + 2]]))[0]
        nlayers = raw_nlayers + 1
        if not (1 <= nlayers <= 8):
            return None

        total_layers += nlayers

        # Verify we can read all layers.
        voice_end = abs_voff + TON_VOICE_HEADER + nlayers * TON_LAYER_SIZE
        if voice_end > len(data):
            return None

        for li in range(nlayers):
            loff = abs_voff + TON_VOICE_HEADER + li * TON_LAYER_SIZE
            layer = data[loff:loff + TON_LAYER_SIZE]

            start_note = layer[0x00]
            end_note = layer[0x01]
            pcm8b = (layer[0x03] >> 4) & 1
            # 19-bit SA address (kingshriek masks with 0x0007FFFF).
            sa_raw = struct.unpack('>I', data[loff + 2:loff + 6])[0]
            sa = sa_raw & SA_MASK
            lea = struct.unpack('>H', layer[0x08:0x0A])[0]  # loop end = num samples
            base_note = layer[0x19]

            sa_info.append((sa, pcm8b, lea))

            if start_note > 127 or end_note > 127:
                score -= 5
            if base_note > 127:
                score -= 3
            if start_note > end_note:
                score -= 5

    # ---- Precise TON size calculation (from kingshriek's tonext.py) ----
    # Find the layer with the highest SA, then size = sa + sample_bytes.
    last_voice_abs = off + voice_offsets[-1]
    raw_nl_last = struct.unpack('b', bytes([data[last_voice_abs + 2]]))[0] + 1
    voice_data_end_rel = voice_offsets[-1] + TON_VOICE_HEADER + raw_nl_last * TON_LAYER_SIZE

    pcm_region = None
    size_estimate = voice_data_end_rel  # fallback: header + voices only

    nonzero_sa = [(sa, pcm8b, lea) for sa, pcm8b, lea in sa_info if sa > 0]
    if nonzero_sa:
        # Find the layer whose SA + sample_bytes is the furthest into the file.
        max_sa_end = 0
        for sa, pcm8b, lea in nonzero_sa:
            sample_bytes = (1 if pcm8b else 2) * lea
            sa_end = sa + sample_bytes
            if sa_end > max_sa_end:
                max_sa_end = sa_end

        min_sa = min(s[0] for s in nonzero_sa)

        if min_sa >= voice_data_end_rel and off + max_sa_end <= len(data):
            # SA addresses are relative to TON start and PCM is embedded.
            pcm_region = (off + min_sa, off + max_sa_end)
            size_estimate = max_sa_end
            notes.append(f"PCM embedded (SA 0x{min_sa:05X}–0x{max_sa_end:05X}, "
                         f"{size_estimate:,} bytes total)")
            score += 15
        elif min_sa < voice_data_end_rel and min_sa > 0:
            # SA values overlap voice data — likely absolute addresses in a
            # larger file (embedded TON with separate PCM region).
            notes.append(f"SA values (0x{min_sa:05X}–0x{max_sa_end:05X}) "
                         f"appear to be absolute — PCM in separate region")
        elif off + min_sa >= len(data):
            notes.append(f"SA values (0x{min_sa:05X}+) exceed file — "
                         f"PCM may be in a separate region")
        else:
            # SA points beyond voice data, within file, absolute addressing.
            pcm_region = (min_sa, max_sa_end)  # absolute offsets in file
            size_estimate = max_sa_end  # relative to TON start (after relocation)
            notes.append(f"PCM at absolute offset 0x{min_sa:05X}–0x{max_sa_end:05X} "
                         f"(needs SA relocation)")
            score += 10

    # Voice count bonus.
    if nvoices >= 4:
        score += 5
    if nvoices >= 10:
        score += 5

    # SA plausibility bonus.
    if nonzero_sa:
        max_sa_addr = max(s[0] for s in nonzero_sa)
        if max_sa_addr < 0x80000:  # within 512KB SCSP RAM
            score += 10

    c = TonCandidate(
        file="", offset=off, nvoices=nvoices,
        mixer_off=mixer_off, vl_off=vl_off, peg_off=peg_off, plfo_off=plfo_off,
        voice_offsets=voice_offsets, confidence=max(0, min(100, score)),
        pcm_region=pcm_region, size_estimate=size_estimate, notes=notes,
    )
    return c


def scan_ton(data: bytes, filename: str, min_confidence: float = 40) -> list[TonCandidate]:
    """Scan *data* for all plausible TON headers."""
    results = []
    skip_until = 0

    for off in range(0, len(data) - 20, 2):
        if off < skip_until:
            continue

        c = _validate_ton_at(data, off, len(data))
        if c is None:
            continue
        if c.confidence < min_confidence:
            continue

        c.file = filename
        results.append(c)

        # Skip past this candidate's voice data to avoid overlapping hits.
        skip_until = off + c.size_estimate

    return results


# ---------------------------------------------------------------------------
# SEQ scanning
# ---------------------------------------------------------------------------

def _walk_seq_track(data: bytes, pos: int, end: int) -> int:
    """Walk SEQ commands from *pos* using the command length table until
    END_OF_TRACK (0x83) or *end* is reached.  Returns the offset just past
    the final command byte (i.e., past the 0x83).  This is the technique
    from kingshriek's seqext.py — much more accurate than scanning for 0x83
    because it actually parses the command stream."""
    while pos < end:
        cmd = data[pos]
        pos += SEQ_CMD_LEN[cmd]
        if cmd == SEQ_END_OF_TRACK:
            return pos
    return pos  # ran off end without finding 0x83


def _find_seq_end(data: bytes, start: int) -> int:
    """Find the exact end of a SEQ bank at *start* by walking the command
    stream of every track.  Returns the offset of the byte after the last
    track's END_OF_TRACK (0x83)."""

    nsongs = struct.unpack('>H', data[start:start + 2])[0]
    furthest = start + 2 + nsongs * 4  # minimum: bank header

    for si in range(nsongs):
        ptr_off = start + 2 + si * 4
        if ptr_off + 4 > len(data):
            break
        song_ptr = struct.unpack('>I', data[ptr_off:ptr_off + 4])[0]
        song_abs = start + song_ptr
        if song_abs + 8 > len(data):
            continue

        doff = struct.unpack('>H', data[song_abs + 4:song_abs + 6])[0]
        data_abs = song_abs + doff
        if data_abs >= len(data):
            continue

        track_end = _walk_seq_track(data, data_abs, len(data))
        furthest = max(furthest, track_end)

    return furthest


def _validate_seq_at(data: bytes, off: int) -> Optional[SeqCandidate]:
    """Try to parse a SEQ bank header at *off*.  Return a SeqCandidate if plausible."""

    if off + 6 > len(data):
        return None

    nsongs = struct.unpack('>H', data[off:off + 2])[0]
    if not (1 <= nsongs <= 256):
        return None

    # Read the first song pointer.
    first_ptr = struct.unpack('>I', data[off + 2:off + 6])[0]
    expected_first = 2 + nsongs * 4  # uint16 + nsongs × uint32
    if first_ptr != expected_first:
        return None

    # Verify all song pointers are within bounds and ascending.
    song_ptrs = []
    for si in range(nsongs):
        ptr_off = off + 2 + si * 4
        if ptr_off + 4 > len(data):
            return None
        sp = struct.unpack('>I', data[ptr_off:ptr_off + 4])[0]
        song_ptrs.append(sp)

    # Song pointers should be ascending.
    for i in range(len(song_ptrs) - 1):
        if song_ptrs[i + 1] < song_ptrs[i]:
            return None

    # ---- Validate individual songs ----
    score = 50.0
    notes = []
    songs = []
    valid_songs = 0
    has_bank_select = 0

    for si, sp in enumerate(song_ptrs):
        song_abs = off + sp
        if song_abs + 8 > len(data):
            continue

        res = struct.unpack('>H', data[song_abs:song_abs + 2])[0]
        nt = struct.unpack('>H', data[song_abs + 2:song_abs + 4])[0]
        doff = struct.unpack('>H', data[song_abs + 4:song_abs + 6])[0]
        tloop = struct.unpack('>H', data[song_abs + 6:song_abs + 8])[0]

        if not (1 <= res <= 960):
            return None
        if not (1 <= nt <= 100):
            return None

        # Tempo offset consistency check (from kingshriek's seqext.py):
        # data_offset must equal 8 (song header) + 8 * num_tempo_events.
        expected_doff = 8 * nt + 0x08
        if doff != expected_doff:
            return None

        # Read first tempo event.
        tempo_abs = song_abs + 8
        bpm = 0.0
        if tempo_abs + 8 <= len(data):
            usec = struct.unpack('>I', data[tempo_abs + 4:tempo_abs + 8])[0]
            if 50000 <= usec <= 3000000:
                bpm = 60_000_000.0 / usec
            else:
                score -= 10

        # Check first data bytes for MIDI status byte.
        data_abs = song_abs + doff
        if data_abs + 4 <= len(data):
            fb = data[data_abs]
            if 0x80 <= fb <= 0xEF:
                valid_songs += 1
            # Check for CC#32 bank select (B0 20).
            if data_abs + 3 <= len(data):
                if data[data_abs] & 0xF0 == 0xB0 and data[data_abs + 1] == 0x20:
                    has_bank_select += 1

        songs.append(SeqSong(
            index=si, resolution=res, num_tempo=nt,
            data_offset=doff, tempo_loop_offset=tloop, bpm=bpm,
        ))

    if valid_songs == 0:
        return None

    # Scoring.
    score += (valid_songs / nsongs) * 20
    if has_bank_select > 0:
        score += 15
        if has_bank_select == nsongs:
            score += 5
    if nsongs >= 4:
        score += 5
    if nsongs >= 10:
        score += 5

    # Bonus for common resolutions.
    resolutions = set(s.resolution for s in songs)
    if resolutions <= SEQ_COMMON_RESOLUTIONS:
        score += 5

    # Determine approximate size.
    end_off = _find_seq_end(data, off)
    size_estimate = end_off - off

    if has_bank_select > 0:
        notes.append(f"CC#32 Bank Select found in {has_bank_select}/{nsongs} songs")

    resolutions = set(s.resolution for s in songs)
    notes.append(f"Resolutions used: {sorted(resolutions)}")

    bpms = set(round(s.bpm) for s in songs if s.bpm > 0)
    if bpms:
        notes.append(f"Tempos: {sorted(bpms)} BPM")

    return SeqCandidate(
        file="", offset=off, num_songs=nsongs, songs=songs,
        confidence=max(0, min(100, score)),
        size_estimate=size_estimate, notes=notes,
    )


def scan_seq(data: bytes, filename: str, min_confidence: float = 40) -> list[SeqCandidate]:
    """Scan *data* for all plausible SEQ bank headers."""
    results = []
    skip_until = 0

    for off in range(0, len(data) - 10, 2):
        if off < skip_until:
            continue

        c = _validate_seq_at(data, off)
        if c is None:
            continue
        if c.confidence < min_confidence:
            continue

        c.file = filename
        results.append(c)
        skip_until = off + c.size_estimate

    return results


# ---------------------------------------------------------------------------
# BIN/CUE extraction
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ISO 9660 parser (pure Python, no external dependencies)
# ---------------------------------------------------------------------------

ISO_SECTOR_SIZE = 2048


def _parse_cue_sector_size(cue_path: str) -> int:
    """Parse a CUE sheet and return the raw sector size of the data track."""
    with open(cue_path, 'r') as f:
        for line in f:
            line = line.strip()
            if 'MODE1/2352' in line or 'MODE2/2352' in line:
                return 2352
            if 'MODE1/2048' in line or 'MODE2/2048' in line:
                return 2048
    return 2352  # default assumption


def _read_iso_sector(fobj, sector_num: int, raw_sector_size: int) -> bytes:
    """Read one 2048-byte logical sector from *fobj*, handling raw-mode
    sector wrappers (MODE1/2352 has 16-byte header + 2048 data + 288 ECC)."""
    fobj.seek(sector_num * raw_sector_size)
    raw = fobj.read(raw_sector_size)
    if len(raw) < raw_sector_size:
        return b''
    if raw_sector_size == 2048:
        return raw
    return raw[16:16 + 2048]  # strip sync/header and ECC/EDC


def _read_iso_bytes(fobj, offset: int, length: int, raw_sector_size: int) -> bytes:
    """Read *length* bytes starting at logical byte *offset* in an ISO image."""
    result = bytearray()
    remaining = length
    while remaining > 0:
        sector_num = offset // ISO_SECTOR_SIZE
        sector_off = offset % ISO_SECTOR_SIZE
        sector = _read_iso_sector(fobj, sector_num, raw_sector_size)
        if not sector:
            break
        chunk = sector[sector_off:sector_off + remaining]
        result.extend(chunk)
        offset += len(chunk)
        remaining -= len(chunk)
    return bytes(result)


def _parse_iso_directory(fobj, extent_lba: int, data_len: int,
                         raw_sector_size: int) -> list[dict]:
    """Parse an ISO 9660 directory extent and return a list of entries."""
    dir_data = _read_iso_bytes(fobj, extent_lba * ISO_SECTOR_SIZE,
                               data_len, raw_sector_size)
    entries = []
    pos = 0
    while pos < len(dir_data):
        rec_len = dir_data[pos]
        if rec_len == 0:
            # Padding to next sector boundary.
            next_sector = ((pos // ISO_SECTOR_SIZE) + 1) * ISO_SECTOR_SIZE
            if next_sector >= len(dir_data):
                break
            pos = next_sector
            continue

        if pos + rec_len > len(dir_data):
            break

        rec = dir_data[pos:pos + rec_len]
        extent = struct.unpack_from('<I', rec, 2)[0]     # LBA (LE half of both-endian)
        size = struct.unpack_from('<I', rec, 10)[0]       # data length (LE half)
        flags = rec[25]
        name_len = rec[32]
        name_raw = rec[33:33 + name_len]

        # Decode filename (strip version ";1").
        try:
            name = name_raw.decode('ascii')
        except UnicodeDecodeError:
            name = name_raw.decode('latin-1')
        if ';' in name:
            name = name[:name.index(';')]
        # Trim trailing dot that ISO 9660 sometimes includes for directories.
        name = name.rstrip('.')

        is_dir = bool(flags & 0x02)
        entries.append({
            'name': name, 'extent': extent, 'size': size, 'is_dir': is_dir,
        })
        pos += rec_len

    return entries


def _extract_iso_files(fobj, extent_lba: int, data_len: int,
                       raw_sector_size: int, dest_dir: str,
                       rel_path: str = "") -> list[str]:
    """Recursively extract files from an ISO 9660 directory to *dest_dir*.
    Returns a list of extracted file paths."""
    entries = _parse_iso_directory(fobj, extent_lba, data_len, raw_sector_size)
    extracted = []

    for ent in entries:
        # Skip '.' and '..' entries.
        if ent['name'] in ('', '\x00', '\x01'):
            continue

        entry_path = os.path.join(rel_path, ent['name'])
        full_path = os.path.join(dest_dir, entry_path)

        if ent['is_dir']:
            os.makedirs(full_path, exist_ok=True)
            sub = _extract_iso_files(fobj, ent['extent'], ent['size'],
                                     raw_sector_size, dest_dir, entry_path)
            extracted.extend(sub)
        else:
            if ent['size'] < 32 or ent['size'] > 100_000_000:
                continue
            file_data = _read_iso_bytes(fobj, ent['extent'] * ISO_SECTOR_SIZE,
                                        ent['size'], raw_sector_size)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'wb') as out:
                out.write(file_data)
            extracted.append(full_path)

    return extracted


def extract_files_from_bin_cue(bin_path: str, cue_path: str) -> list[str]:
    """Extract all files from a BIN/CUE disc image using pure Python ISO 9660
    parsing.  Returns a list of extracted file paths in a temp directory."""
    raw_sector_size = _parse_cue_sector_size(cue_path)
    dest_dir = tempfile.mkdtemp(prefix='saturn_scan_')

    with open(bin_path, 'rb') as fobj:
        # Read the Primary Volume Descriptor at sector 16.
        pvd = _read_iso_sector(fobj, 16, raw_sector_size)
        if len(pvd) < ISO_SECTOR_SIZE or pvd[0] != 1 or pvd[1:6] != b'CD001':
            print("  Warning: no valid ISO 9660 PVD found, scanning raw BIN instead.")
            return [bin_path]

        # Root directory record is at PVD offset 156, length 34.
        root_rec = pvd[156:156 + 34]
        root_extent = struct.unpack_from('<I', root_rec, 2)[0]
        root_size = struct.unpack_from('<I', root_rec, 10)[0]

        volume_id = pvd[40:72].decode('ascii', errors='replace').strip()
        print(f"  Volume: {volume_id}")
        print(f"  Extracting files to {dest_dir}")

        files = _extract_iso_files(fobj, root_extent, root_size,
                                   raw_sector_size, dest_dir)

    print(f"  Extracted {len(files)} file(s)")
    return sorted(files)


# ---------------------------------------------------------------------------
# File collector
# ---------------------------------------------------------------------------

def collect_files(path: str, cue_path: Optional[str] = None) -> list[str]:
    """Given a path (directory, file, or BIN/CUE), return a list of files to scan.
    If a BIN/CUE image is given, extract files and return those paths."""

    p = Path(path)

    if p.is_file():
        # Check if it's a BIN with a CUE alongside.
        if cue_path or (p.suffix.lower() in ('.bin', '.img') and (p.with_suffix('.cue').exists())):
            cue = cue_path or str(p.with_suffix('.cue'))
            print(f"BIN/CUE image detected: {p.name}")
            return extract_files_from_bin_cue(str(p), cue)

        # Also handle plain .iso files.
        if p.suffix.lower() == '.iso':
            print(f"ISO image detected: {p.name}")
            # Treat as BIN with 2048-byte sectors.
            dest_dir = tempfile.mkdtemp(prefix='saturn_scan_')
            with open(str(p), 'rb') as fobj:
                pvd = _read_iso_sector(fobj, 16, 2048)
                if len(pvd) >= ISO_SECTOR_SIZE and pvd[0] == 1 and pvd[1:6] == b'CD001':
                    root_rec = pvd[156:156 + 34]
                    root_extent = struct.unpack_from('<I', root_rec, 2)[0]
                    root_size = struct.unpack_from('<I', root_rec, 10)[0]
                    volume_id = pvd[40:72].decode('ascii', errors='replace').strip()
                    print(f"  Volume: {volume_id}")
                    print(f"  Extracting files to {dest_dir}")
                    files = _extract_iso_files(fobj, root_extent, root_size,
                                               2048, dest_dir)
                    print(f"  Extracted {len(files)} file(s)")
                    return sorted(files)
            print("  Not a valid ISO 9660 image, scanning as raw file.")
            return [str(p)]

        return [str(p)]

    if p.is_dir():
        files = []
        for root, _dirs, fnames in os.walk(str(p)):
            for fn in fnames:
                fp = os.path.join(root, fn)
                try:
                    sz = os.path.getsize(fp)
                except OSError:
                    continue
                if sz < 32 or sz > 100_000_000:
                    continue
                files.append(fp)
        return sorted(files)

    print(f"Error: {path} is not a file or directory.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# TON extraction with SA relocation
# ---------------------------------------------------------------------------

def extract_ton(data: bytes, candidate: TonCandidate, dest: str):
    """Extract a TON from *data* at *candidate.offset* and write to *dest*.

    If the TON's SA pointers reference a PCM region that is outside the
    contiguous TON header+voice area, we relocate the PCM data and adjust
    SA fields so the output is a self-contained .ton file.
    """
    off = candidate.offset
    mixer_off = candidate.mixer_off
    nvoices = candidate.nvoices
    voice_offsets = candidate.voice_offsets

    # Find the end of voice data.
    last_voff_abs = off + voice_offsets[-1]
    raw_nl = struct.unpack('b', bytes([data[last_voff_abs + 2]]))[0] + 1
    voice_data_end = voice_offsets[-1] + TON_VOICE_HEADER + raw_nl * TON_LAYER_SIZE

    # Collect all SA values with PCM size info for precise extraction.
    # Each entry: (voice_idx, layer_idx, sa_addr, pcm8b, lea, layer_rel_offset)
    sa_info = []
    for vi, voff_rel in enumerate(voice_offsets):
        abs_voff = off + voff_rel
        nlayers = struct.unpack('b', bytes([data[abs_voff + 2]]))[0] + 1
        for li in range(nlayers):
            loff = abs_voff + TON_VOICE_HEADER + li * TON_LAYER_SIZE
            layer = data[loff:loff + TON_LAYER_SIZE]
            sa_raw = struct.unpack('>I', data[loff + 2:loff + 6])[0]
            sa = sa_raw & SA_MASK
            pcm8b = (layer[0x03] >> 4) & 1
            lea = struct.unpack('>H', layer[0x08:0x0A])[0]
            sa_info.append((vi, li, sa, pcm8b, lea, loff - off))

    if not sa_info:
        with open(dest, 'wb') as f:
            f.write(data[off:off + voice_data_end])
        return

    nonzero = [(sa, pcm8b, lea) for _, _, sa, pcm8b, lea, _ in sa_info if sa > 0]
    if not nonzero:
        with open(dest, 'wb') as f:
            f.write(data[off:off + voice_data_end])
        return

    # Compute the precise PCM end: max(sa + sample_bytes) across all layers
    # (same technique as kingshriek's tonext.py).
    def _pcm_end(sa, pcm8b, lea):
        return sa + (1 if pcm8b else 2) * lea

    max_sa_end = max(_pcm_end(sa, p, l) for sa, p, l in nonzero)
    min_sa = min(sa for sa, _, _ in nonzero)

    # Case 1: SA relative to TON start (self-contained / standalone TON).
    if min_sa >= voice_data_end and off + max_sa_end <= len(data):
        with open(dest, 'wb') as f:
            f.write(data[off:off + max_sa_end])
        return

    # Case 2: SA is an absolute address in the containing file (embedded TON).
    if min_sa > voice_data_end and max_sa_end <= len(data):
        pcm_base = min_sa
        pcm_chunk = data[pcm_base:max_sa_end]

        header_chunk = bytearray(data[off:off + voice_data_end])
        new_pcm_start = voice_data_end

        # Relocate SA fields: new_sa = (old_sa - pcm_base) + new_pcm_start.
        for _vi, _li, sa, _pcm8b, _lea, layer_rel in sa_info:
            if sa == 0:
                continue
            new_sa = (sa - pcm_base) + new_pcm_start
            byte3_off = layer_rel + 0x03
            sa_hi_off = layer_rel + 0x04
            old_byte3 = header_chunk[byte3_off]
            header_chunk[byte3_off] = (old_byte3 & 0xF0) | ((new_sa >> 16) & 0x0F)
            struct.pack_into('>H', header_chunk, sa_hi_off, new_sa & 0xFFFF)

        with open(dest, 'wb') as f:
            f.write(header_chunk)
            f.write(pcm_chunk)
        return

    # Fallback: SA values point outside the file — save header+voices only.
    with open(dest, 'wb') as f:
        f.write(data[off:off + voice_data_end])


def extract_seq(data: bytes, candidate: SeqCandidate, dest: str):
    """Extract a SEQ bank from *data* and write to *dest*."""
    off = candidate.offset
    end = off + candidate.size_estimate
    with open(dest, 'wb') as f:
        f.write(data[off:end])


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_ton(c: TonCandidate, idx: int):
    conf = f"{c.confidence:.0f}%"
    print(f"  TON #{idx}  offset=0x{c.offset:06X}  voices={c.nvoices}  "
          f"size≈{c.size_estimate}  confidence={conf}")
    print(f"          mixer=0x{c.mixer_off:04X}  vl=0x{c.vl_off:04X}  "
          f"peg=0x{c.peg_off:04X}  plfo=0x{c.plfo_off:04X}")
    for n in c.notes:
        print(f"          {n}")


def print_seq(c: SeqCandidate, idx: int):
    conf = f"{c.confidence:.0f}%"
    print(f"  SEQ #{idx}  offset=0x{c.offset:06X}  songs={c.num_songs}  "
          f"size≈{c.size_estimate}  confidence={conf}")
    for n in c.notes:
        print(f"          {n}")

    # Brief per-song summary.
    if len(c.songs) <= 12:
        for s in c.songs:
            bpm_s = f"{s.bpm:.0f}" if s.bpm else "?"
            print(f"          Song {s.index:3d}: res={s.resolution:4d}  "
                  f"{bpm_s:>4s} BPM  tempos={s.num_tempo}")
    else:
        for s in c.songs[:6]:
            bpm_s = f"{s.bpm:.0f}" if s.bpm else "?"
            print(f"          Song {s.index:3d}: res={s.resolution:4d}  "
                  f"{bpm_s:>4s} BPM  tempos={s.num_tempo}")
        print(f"          ... ({len(c.songs) - 12} more) ...")
        for s in c.songs[-6:]:
            bpm_s = f"{s.bpm:.0f}" if s.bpm else "?"
            print(f"          Song {s.index:3d}: res={s.resolution:4d}  "
                  f"{bpm_s:>4s} BPM  tempos={s.num_tempo}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scan Saturn game files for embedded TON and SEQ data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("path", help="Directory, file, or BIN image to scan")
    parser.add_argument("--cue", help="CUE sheet (if scanning a raw BIN image)")
    parser.add_argument("-x", "--extract", metavar="DIR",
                        help="Extract found TON/SEQ to this directory")
    parser.add_argument("--min-confidence", type=float, default=40,
                        help="Hide results below this confidence (default: 40)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show low-confidence candidates too")
    args = parser.parse_args()

    if args.verbose:
        args.min_confidence = 0

    files = collect_files(args.path, args.cue)
    if not files:
        print("No files to scan.")
        sys.exit(1)

    print(f"Scanning {len(files)} file(s)...\n")

    all_tons: list[TonCandidate] = []
    all_seqs: list[SeqCandidate] = []

    for fpath in files:
        try:
            with open(fpath, 'rb') as f:
                data = f.read()
        except (OSError, IOError) as e:
            if args.verbose:
                print(f"  [skip] {fpath}: {e}")
            continue

        if len(data) < 32:
            continue

        # Quick check: skip files that are clearly AIFF/WAV/etc.
        if data[:4] in (b'FORM', b'RIFF', b'OggS', b'fLaC', b'ID3\x03'):
            if args.verbose:
                print(f"  [skip] {fpath}: audio file")
            continue

        tons = scan_ton(data, fpath, args.min_confidence)
        seqs = scan_seq(data, fpath, args.min_confidence)

        if tons or seqs:
            short = fpath
            print(f"{short} ({len(data)} bytes)")
            for i, t in enumerate(tons):
                print_ton(t, i)
            for i, s in enumerate(seqs):
                print_seq(s, i)
            print()

        all_tons.extend(tons)
        all_seqs.extend(seqs)

    # Summary.
    print(f"Found {len(all_tons)} TON candidate(s) and {len(all_seqs)} SEQ candidate(s).")

    # Extraction.
    if args.extract and (all_tons or all_seqs):
        out = Path(args.extract)
        out.mkdir(parents=True, exist_ok=True)
        print(f"\nExtracting to {out}/")

        # Group by file for per-file numbering.
        from collections import Counter
        ton_counts: Counter = Counter()
        seq_counts: Counter = Counter()

        for c in all_tons:
            basename = Path(c.file).stem.lower()
            idx = ton_counts[basename]
            ton_counts[basename] += 1
            suffix = f"_{idx}" if ton_counts[basename] > 1 or idx > 0 else ""
            label = f"{c.nvoices}v" if c.nvoices > 1 else "1v"
            dest = out / f"{basename}{suffix}.ton"
            try:
                with open(c.file, 'rb') as f:
                    fdata = f.read()
                extract_ton(fdata, c, str(dest))
                sz = os.path.getsize(dest)
                print(f"  {dest.name}  ({sz:,} bytes, {label}, {c.confidence:.0f}%)")
            except Exception as e:
                print(f"  {dest.name}  FAILED: {e}")

        for c in all_seqs:
            basename = Path(c.file).stem.lower()
            idx = seq_counts[basename]
            seq_counts[basename] += 1
            suffix = f"_{idx}" if seq_counts[basename] > 1 or idx > 0 else ""
            dest = out / f"{basename}{suffix}.seq"
            try:
                with open(c.file, 'rb') as f:
                    fdata = f.read()
                extract_seq(fdata, c, str(dest))
                sz = os.path.getsize(dest)
                print(f"  {dest.name}  ({sz:,} bytes, {c.num_songs} songs, {c.confidence:.0f}%)")
            except Exception as e:
                print(f"  {dest.name}  FAILED: {e}")


if __name__ == '__main__':
    main()
