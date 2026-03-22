# Saturn Audio Pipeline: SEQ + TON

Status: **Working**. We can create SEQ and TON files from MIDI and SoundFont sources, and play them through the original SGL sound driver. Tested with [Frogbull's SaturnRingLib fork](https://github.com/Frogbull/SaturnRingLib), which adds SEQ/TON audio support to the upstream [SaturnRingLib](https://github.com/SaturnRingLib/SaturnRingLib) SDK.

## Tools

| Tool | Input | Output | Status |
|------|-------|--------|--------|
| `mid2seq` (C) | Format 0 MIDI | `.seq` | Working |
| `sf2ton.py` (Python) | SoundFont `.sf2` | `.ton` + `.map` | Working (basic) |
| `gen_test_sf2.py` | — | Test `.sf2` with 4 instruments | Working |
| `gen_demo_midi.py` | — | 4-instrument demo `.mid` | Working |

## File Formats

### SEQ (Sequence Data)

Saturn's MIDI-like sequence format. Structure documented in [seq2mid](https://github.com/mistydemeo/seq2mid).

**Header (variable size):**
- `uint16 num_songs` (big-endian)
- `uint32 song_pointer`
- Per-song: `uint16 resolution`, `uint16 num_tempo_events`, `uint16 data_offset`, `uint16 tempo_loop_offset`
- Tempo events: `uint32 step_time`, `uint32 microseconds_per_beat`

**Critical: Bank Select is required.** The SEQ must emit CC#32 (Bank Select LSB) = 1 on all 16 channels before any program changes. Without this, the sound driver defaults to bank 0 (driver internals with no user instruments). The working mechs.seq from the MECHS port does this; our mid2seq now does too.

### TON (Tone Data)

Instrument definitions + embedded PCM samples. All big-endian.

**File layout:**
```
Offset table (16-bit pointers):
  [0x00] mixer_offset
  [0x02] velocity_offset (VL)
  [0x04] pitch_envelope_offset (PEG)
  [0x06] pitch_lfo_offset (PLFO)
  [0x08..] voice_offsets[0..N-1]

Mixer data:      0x12 bytes (18 EFSDL/EFPAN entries)
VL table:        0x0A bytes/entry (velocity → TL attenuation curve)
PEG table:       0x0A bytes/entry (pitch envelope ADSR)
PLFO table:      0x04 bytes/entry (pitch LFO params)
Voice entries:   4-byte header + N × 32-byte layers
PCM sample data: 16-bit big-endian (or 8-bit) raw audio
```

**Voice header (4 bytes):**
- `[6:4]` play_mode, `[3:0]` bend_range
- `[7:0]` portamento_time
- `[7:0]` num_layers - 1 (signed, add 1)
- `[7:0]` volume_bias (signed)

**Layer entry (32 bytes):** Maps almost directly to SCSP slot registers. See `ASSEMBLER.md` in the scsp-fx repo for the SCSP slot register reference, or `ssfinfo.py` from VGMToolbox for the definitive bit-level layout.

Key fields: SA (sample address, 20-bit byte offset within TON file), LSA/LEA (loop points in samples), AR/D1R/DL/D2R/RR (ADSR envelope), TL (total level attenuation), OCT/FNS (pitch), DISDL/DIPAN (output level/pan), base_note, fine_tune, velocity_id, peg_id, plfo_id.

**Velocity Level (VL) table — critical for volume:**
The VL table maps MIDI velocity to TL attenuation via a piecewise-linear curve. Format per entry (10 bytes): `slope0, point0, level0, slope1, point1, level1, slope2, point2, level2, slope3`. The `level` values are TL attenuation (0 = loudest, 127 = silent). A bad VL table makes everything nearly inaudible. We use the curve from mechs.ton: `slopes=[25,9,19,43] points=[16,49,93] levels=[54,102,122]`.

### MAP (Area Map)

Tells the SGL sound driver where each data block lives in the SCSP's 512KB sound RAM. Loaded by `slInitSound` at boot.

**Format:** 8-byte entries, terminated by `0xFFFF`:
```
[0]     type (high nibble) | bank (low nibble)
[1-3]   24-bit address in sound RAM
[4]     bit 7 = transfer complete flag
[5-7]   24-bit data size
```

Types: 0=TONE, 1=SEQ, 2=DSP_PROG, 3=DSP_RAM.

**Bank layout:** Bank 0 holds driver defaults (DSP RAM, DSP program, default SEQ/TON). Bank 1+ holds user music. The standard bank 0 entries (from SGL's BOOTSND.MAP) must be present for the driver to function.

**SaturnRingLib integration:** When `SRL_ENABLE_AUDIO_SEQ_SUPPORT=1`, SRL loads `CUSTOM.MAP` (not `BOOTSND.MAP`) into the sound driver. The SRL code reads `CUSTOM.MAP` to compute DMA offsets for SEQ/TON uploads to sound RAM. The driver then uses these same addresses when playing back. Both must agree.

## Integration with SaturnRingLib (Frogbull's fork)

### File placement

Place files in the SRL project's `cd/data/` directory:
- `CUSTOM.MAP` — must define bank 0 defaults + bank 1 for user data
- `BGM01.SEQ` — sequence data
- `BGM01.TON` — tone bank with embedded PCM

### How playback works

1. `SRL::Core::Initialize` loads `SDDRVS.TSK` (sound driver) and `CUSTOM.MAP` via `slInitSound`
2. `LoadSEQandTON("BGM01.SEQ", "BGM01.TON")` reads `CUSTOM.MAP` for bank 1 offsets, DMAs SEQ+TON to sound RAM
3. `slBGMOn((1 << 8) + 0, 0, volume, 0)` plays bank 1, song 0

### Building SRL projects

Use the scsp-fx Docker container (has both yaul and Saturn-SDK-GCC-SH2 toolchains):

```bash
./dspbuild srlbuild /path/to/SaturnRingLib/Samples/Sound\ -\ SEQ
```

## Known Limitations / TODO

| Issue | Status | Notes |
|-------|--------|-------|
| Sample rate compensation | Not done | SF2 samples at rates ≠ 44100 Hz play at wrong pitch. Need to set OCT/FNS based on sample rate and base note |
| Multi-sample instruments | Not done | SF2 instruments with multiple key-split samples need proper layer generation |
| VL table from SF2 | Not done | Currently hardcoded from mechs.ton. Should derive from SF2 velocity curves |
| PEG/PLFO tables | Not done | Currently zeroed (no pitch envelope/LFO). Should map from SF2 modulators |
| ADSR accuracy | Basic | Conversion uses MAME's AR/DR time tables but mapping may need refinement |
| Memory budget | No check | Should warn when TON+SEQ exceeds MAP allocation or 512KB total |
| DSP effects + sequences | Not tested | Combining custom DSP programs with the SGL driver's DSP slot allocation |
| Real hardware testing | Not done | All testing on mednafen emulator only |
| Multiple banks | Not done | Only bank 1 supported. Multi-bank MAP generation not implemented |

## Key References

- [seq2mid](https://github.com/mistydemeo/seq2mid) — SEQ format documentation (reverse direction)
- [VGMToolbox ssfinfo.py](https://github.com/Hengle/VGMToolbox-1/blob/master/VGMToolbox/external/ssf/ssfinfo/ssfinfo.py) — definitive TON field-level parser
- [VGMToolbox tonext.py](https://github.com/Hengle/VGMToolbox-1/blob/master/VGMToolbox/external/ssf/tonext.py) — TON extractor with validation
- [VGMTrans SegSatInstrSet](https://github.com/vgmtrans/vgmtrans/tree/master/src/main/formats/SegSat) — TON→SF2 converter (we reverse this), ADSR timing tables
- [Saturn Sound Driver Manual (ST-241)](https://antime.kapsi.fi/sega/files/ST-241-042795.pdf) — official Sega documentation
- [SCSP User's Manual](https://www.infochunk.com/saturn/segahtml_en/hard/scsp/sakuin.htm) — SCSP register reference
