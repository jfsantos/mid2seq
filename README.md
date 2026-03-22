# mid2seq

Tools for creating music for Sega Saturn homebrew games. Convert standard MIDI files and SoundFont instruments into the Saturn's native SEQ/TON formats, playable through the SGL sound driver.

## Quick Start

```bash
# 1. Generate the Saturn Sound Kit (once)
python3 tools/saturn_kit.py -o kit/saturn_kit

# 2. Load kit/saturn_kit.sf2 into your DAW, compose music, export Format 0 MIDI

# 3. Convert to Saturn format
cc -O2 -o mid2seq tools/mid2seq.c    # compile (once)
./mid2seq my_song.mid my_song.seq

# 4. Ship kit/saturn_kit.ton + my_song.seq with your game
```

See **[MUSICIAN_GUIDE.md](MUSICIAN_GUIDE.md)** for the full composing and export workflow.

## Tools

| Tool | Description |
|------|-------------|
| `tools/mid2seq.c` | MIDI → SEQ converter (C, compile with any C compiler) |
| `tools/sf2ton.py` | SoundFont (.sf2) → TON converter |
| `tools/saturn_kit.py` | Saturn Sound Kit generator (TON + SF2 from waveform definitions) |
| `tools/tonview.py` | TON file viewer — generates interactive HTML with waveform display and playback |
| `tools/gen_kit_demo.py` | Generates a demo MIDI using all kit instruments |

## Pre-built Kit

The `kit/` directory contains a ready-to-use instrument set:

| File | Description |
|------|-------------|
| `kit/saturn_kit.ton` | 16 instruments (38KB) — ship this with your game |
| `kit/saturn_kit.sf2` | Matching SoundFont — load in your DAW for composing |
| `kit/default_kit.json` | Instrument definitions — edit to customize the kit |

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
```

The SF2 is a preview — it approximates how the Saturn will sound.
The TON + SEQ files are what actually run on the hardware.

## Credits

- [Frogbull's SaturnRingLib fork](https://github.com/Frogbull/SaturnRingLib) — adds SGL sound driver and SEQ/TON support to [SaturnRingLib](https://github.com/SaturnRingLib/SaturnRingLib). The Sound SEQ sample demonstrates the integration pattern used by these tools.
- SEQ format documentation from [seq2mid](https://github.com/mistydemeo/seq2mid)
- TON format reverse-engineered from [VGMToolbox](https://github.com/Hengle/VGMToolbox-1) (kingshriek) and [VGMTrans](https://github.com/vgmtrans/vgmtrans)
- ADSR timing tables from MAME's SCSP implementation

## License

BSD 3-Clause. See [LICENSE](LICENSE).
