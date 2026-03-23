# mid2seq

Tools for creating music for Sega Saturn homebrew games. Convert standard MIDI files into the Saturn's native SEQ/TON formats, with support for both PCM waveform and FM synthesis instruments, playable through the SGL sound driver.

## Quick Start

```bash
# 1. Generate the Saturn Sound Kit (once)
python3 tools/saturn_kit.py -o kit/saturn_kit            # FM kit (default)
python3 tools/saturn_kit.py --mode pcm -o kit/saturn_kit  # PCM-only kit

# 2. Load kit/saturn_kit.sf2 into your DAW, compose music, export Format 0 MIDI

# 3. Convert to Saturn format
cc -O2 -o mid2seq tools/mid2seq.c    # compile (once)
./mid2seq my_song.mid my_song.seq

# 4. Ship kit/saturn_kit.ton + my_song.seq with your game
```

See **[MUSICIAN_GUIDE.md](MUSICIAN_GUIDE.md)** for the full composing and export workflow.

## Two Kit Modes

### FM Kit (`--mode fm`, default)
Uses the SCSP's built-in **FM synthesis** for melodic instruments. Each FM voice has a modulator and carrier layer sharing a single sine wave sample — DX7-style phase modulation creates rich timbres like electric piano, brass, organ, and bells at near-zero RAM cost. Drums remain PCM one-shot samples.

### PCM Kit (`--mode pcm`)
Uses **single-cycle waveforms** (sine, sawtooth, square, etc.) for all instruments. Simpler, chiptune-like character. Each instrument is one looped waveform.

Both kits use the same program numbers (0-15) so MIDI files work with either.

## Tools

| Tool | Description |
|------|-------------|
| `tools/mid2seq.c` | MIDI → SEQ converter (C, compile with any C compiler) |
| `tools/sf2ton.py` | SoundFont (.sf2) → TON converter |
| `tools/saturn_kit.py` | Saturn Sound Kit generator (TON + SF2 with PCM or FM instruments) |
| `tools/tonview.py` | TON file viewer — generates interactive HTML with waveform display and playback |
| `tools/fm_sim.py` | FM synthesis simulator — renders FM patches to WAV for auditioning |
| `tools/exc2exb.py` | DSP assembler .exc → SGL driver .exb converter |
| `tools/gen_kit_demo.py` | Generates a demo MIDI using all kit instruments |

## Pre-built Kit

The `kit/` directory contains a ready-to-use instrument set:

| File | Description |
|------|-------------|
| `kit/saturn_kit.ton` | 16 instruments with FM synthesis (~39KB) — ship this with your game |
| `kit/saturn_kit.sf2` | Matching SoundFont — load in your DAW for composing |
| `kit/default_kit.json` | Instrument definitions — edit to customize the kit |

## FM Synthesis

The Saturn's SCSP (YMF292) supports DX7-style **phase modulation** between any of its 32 sound slots. The FM kit exploits this:

- **Modulator + carrier layers** in the same voice — the modulator's output offsets the carrier's sample read position, creating FM sidebands
- **All FM voices share one sine wave sample** — near-zero RAM overhead
- **Modulator envelopes shape the timbre** — a decaying modulator gives bright attack/mellow sustain (electric piano, bells)
- **Self-feedback** supported for richer harmonics (organ, brass)
- **2-32 operators** with fully free wiring — more flexible than the DX7's fixed algorithms

Preview FM patches before committing to hardware:

```bash
python3 tools/fm_sim.py --list                    # List preset patches
python3 tools/fm_sim.py --patch epiano            # Render electric piano to WAV
python3 tools/fm_sim.py --all                     # Render all presets
python3 tools/fm_sim.py --patch bell --note 72    # Render bell at C5
```

## Documentation

- **[MUSICIAN_GUIDE.md](MUSICIAN_GUIDE.md)** — How to compose, export, and integrate music into your game
- **[SEQUENCES.md](SEQUENCES.md)** — Technical reference for SEQ, TON, and MAP file formats

## Examples

- `examples/kit_demo.mid` — Demo MIDI using all 16 kit instruments
- For a working integration example, see [Frogbull's SaturnRingLib Sound SEQ sample](https://github.com/Frogbull/SaturnRingLib/tree/main/Samples/Sound%20-%20SEQ)

## How It Works

```
Your DAW                    Saturn Hardware
────────                    ──────────────
saturn_kit.sf2              saturn_kit.ton ──→ SCSP Sound RAM
     │                           │
  Compose MIDI              SGL Sound Driver
     │                           │
  my_song.mid ──→ mid2seq ──→ my_song.seq ──→ SEQ Playback
                                 │
                            FM: modulator slots modulate
                                carrier slots via phase offset
                            PCM: single-cycle waveforms loop
```

The SF2 is a preview — it approximates how the Saturn will sound.
The TON + SEQ files are what actually run on the hardware.

FM voices sound richer on the Saturn than the SF2 preview (the SF2 can't simulate phase modulation — it just plays the raw sine sample).

## Credits

- [Frogbull's SaturnRingLib fork](https://github.com/Frogbull/SaturnRingLib) — adds SGL sound driver and SEQ/TON support to [SaturnRingLib](https://github.com/SaturnRingLib/SaturnRingLib). The Sound SEQ sample demonstrates the integration pattern used by these tools.
- SEQ format documentation from [seq2mid](https://github.com/mistydemeo/seq2mid)
- TON format reverse-engineered from [VGMToolbox](https://github.com/Hengle/VGMToolbox-1) (kingshriek) and [VGMTrans](https://github.com/vgmtrans/vgmtrans)
- ADSR timing tables from MAME's SCSP implementation
- FM synthesis behavior verified against [mednafen](https://mednafen.github.io/) SCSP emulation source

## License

BSD 3-Clause. See [LICENSE](LICENSE).
