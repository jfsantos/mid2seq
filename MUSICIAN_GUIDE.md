# Making Music for Sega Saturn Homebrew

This guide walks you through composing and exporting music for Saturn homebrew games using standard MIDI tools. No retro hardware knowledge required — if you can write MIDI, you can make Saturn music.

## What You Need

- **Any DAW or MIDI editor** (Reaper, Logic, FL Studio, LMMS, MuseScore, even GarageBand)
- **Python 3** (for the conversion tools)
- **fluidsynth** (optional, for previewing audio — `brew install fluid-synth` or `apt install fluidsynth`)

## Quick Start

```bash
# 1. Generate the Saturn Sound Kit (do this once)
python3 tools/saturn_kit.py

# 2. Load saturn_kit.sf2 into your DAW
#    Compose your music using the instruments below
#    Export as Format 0 MIDI

# 3. Preview how it will sound (optional)
fluidsynth -ni -F preview.wav -r 44100 saturn_kit.sf2 my_song.mid

# 4. Convert to Saturn format
./mid2seq my_song.mid my_song.seq

# 5. Done! Ship saturn_kit.ton + my_song.seq + CUSTOM.MAP with your game
```

## Available Instruments

The Saturn Sound Kit provides 16 instruments. Use these **program numbers** in your MIDI:

| Program | Name | Type | Best for |
|---------|------|------|----------|
| 0 | Piano | Decay | Melodies, arpeggios |
| 1 | E.Piano | Soft decay | Ballads, chords |
| 2 | Organ | Sustained | Chords, pads |
| 3 | Strings | Slow attack | Sustained harmony, pads |
| 4 | Brass | Medium attack | Fanfares, counter-melodies |
| 5 | Flute | Soft | Gentle melodies, ornaments |
| 6 | Saw Lead | Instant | Lead lines, solos |
| 7 | Square Lead | Instant | Chiptune-style leads |
| 8 | Bass | Punchy decay | Bass lines |
| 9 | Syn Bass | Buzzy decay | Aggressive bass |
| 10 | Pad | Very slow attack | Ambient backgrounds |
| 11 | Triangle | Clean | Subtle melodies, sub-bass |
| 12 | Kick | One-shot | Drum pattern |
| 13 | Snare | One-shot | Drum pattern |
| 14 | Hi-Hat | One-shot | Drum pattern |
| 15 | Crash | One-shot | Accents |

## Setting Up Your DAW

### Loading the SoundFont

1. Run `python3 tools/saturn_kit.py` to generate `saturn_kit.sf2`
2. In your DAW, load `saturn_kit.sf2` as a virtual instrument (most DAWs support SF2 natively or via a plugin like sforzando, sfizz, or juicysfplugin)
3. The SoundFont contains all 16 instruments at the program numbers listed above

### Channel Setup

Assign each instrument to its own MIDI channel with a Program Change at the start:

```
Channel 0: Program 0 (Piano) — melody
Channel 1: Program 3 (Strings) — harmony
Channel 2: Program 8 (Bass) — bass line
Channel 3: Program 2 (Organ) — rhythm
...etc
```

### Drums

Unlike General MIDI, drums are **not** on a special channel. Each drum sound is a separate program on its own channel:

```
Channel 9:  Program 12 (Kick)
Channel 10: Program 13 (Snare)
Channel 11: Program 14 (Hi-Hat)
Channel 12: Program 15 (Crash)
```

Each drum channel plays the drum at whatever MIDI note you send. The pitch will shift relative to the drum's base note, so middle C area works best.

## Composing Tips

### Saturn Limitations

- **32 voices maximum** — the Saturn can play up to 32 simultaneous notes across all channels. If you exceed this, notes will be cut off.
- **Single-cycle waveforms** — the instruments are made from short looped waveforms, not multi-sampled recordings. They have a distinctive synth-like character. Embrace it.
- **No velocity layers** — every note uses the same waveform regardless of velocity. Velocity still controls volume.

### What Sounds Good

- **Simple arrangements work best.** 4-6 channels with clear roles (melody, harmony, bass, rhythm) sound great.
- **Use sustained instruments (Strings, Organ, Pad) for chords.** They fill space without using many notes.
- **Bass sounds strong.** The Saturn's sound chip handles low frequencies well.
- **Drums are punchy.** Short single-hit samples with tight envelopes cut through the mix.
- **Arpeggios and sequences shine.** The consistent timbre of single-cycle waveforms makes rapid note patterns sound clean.

### What to Avoid

- **Dense chords with many notes.** You'll eat through the 32-voice limit quickly.
- **Very high notes.** Pitching single-cycle waveforms far above their base note creates interpolation artifacts.
- **Expecting realism.** This is a synthesizer, not a sample library. Write for the sound, not against it.
- **MIDI channel 10 for drums.** Unlike GM, the Saturn driver doesn't treat channel 10 specially. Use separate channels with explicit program changes.

## Exporting MIDI

### Format Requirements

- **Format 0 MIDI** (single track). Most DAWs can export this. If your DAW only exports Format 1 (multi-track), use a converter.
- **Program changes** must be at the start of the file, before any notes.
- **Supported events:** Note On/Off, Program Change, Control Change, Pitch Bend.
- **Tempo changes** are supported.

### Export Steps

1. In your DAW, select **File → Export → MIDI** (or similar)
2. Choose **Format 0** if available
3. Save as `.mid`

If your DAW only exports Format 1, you can convert:
```bash
# Using Python mido library
python3 -c "
import mido
mid = mido.MidiFile('my_song.mid')
mid.type = 0
merged = mido.merge_tracks(mid.tracks)
mid.tracks = [merged]
mid.save('my_song_format0.mid')
"
```

## Converting to Saturn Format

```bash
# Convert MIDI to Saturn SEQ
./mid2seq my_song.mid my_song.seq
```

The converter:
- Reads all MIDI events (notes, program changes, CCs, pitch bends)
- Calculates gate times (note durations) from Note On/Off pairs
- Adds Bank Select CC#32=1 to all channels (tells the Saturn which tone bank to use)
- Writes the compressed SEQ format

## Previewing

### Software Preview

```bash
# Render to WAV using the SoundFont
fluidsynth -ni -F preview.wav -r 44100 saturn_kit.sf2 my_song.mid
open preview.wav
```

This gives you an approximation. The actual Saturn will sound different due to hardware envelope generators, interpolation, and DAC characteristics — but the notes, timing, and instrument assignments will match.

### Hardware Preview (mednafen)

If you have the full dev environment set up (see the scsp-fx repo):

```bash
# Copy files to the SRL sample project's cd/data/ folder:
#   my_song.seq → BGM01.SEQ
#   saturn_kit.ton → BGM01.TON
#   (keep the existing CUSTOM.MAP)

# Build and run
./dspbuild srlbuild /path/to/SaturnRingLib/Samples/Sound\ -\ SEQ
mednafen -force_module ss -ss.region_default na -ss.region_autodetect 0 \
  /path/to/SaturnRingLib/Samples/Sound\ -\ SEQ/BuildDrop/Sound_SEQ.cue
```

Press START in the emulator to play.

### TON Viewer

Inspect the waveforms and play individual instruments in your browser:

```bash
python3 tools/tonview.py saturn_kit.ton
open saturn_kit.html    # Click a layer, then click the piano keys
```

## FM vs PCM Kits

The Saturn Sound Kit comes in two modes:

### FM Kit (default)
```bash
python3 tools/saturn_kit.py -o kit/saturn_kit              # or explicitly:
python3 tools/saturn_kit.py --mode fm -o kit/saturn_kit
```

Uses the SCSP's built-in **FM synthesis** for melodic instruments (programs 0-5, 8). Each FM voice has two or more layers — a silent modulator that shifts the carrier's waveform, creating rich, evolving timbres from a single shared sine wave. Drums (programs 12-15) remain PCM samples.

FM instruments sound noticeably richer on the Saturn than in the SF2 preview. The SF2 can't simulate FM — it just plays the raw sine wave. The Saturn's hardware does the phase modulation in real time.

### PCM Kit
```bash
python3 tools/saturn_kit.py --mode pcm -o kit/saturn_kit
```

Uses single-cycle waveforms (sine, sawtooth, square, etc.) for all instruments. Each voice is one looped sample. Simpler, chiptune-like character. What you hear in the SF2 preview closely matches the Saturn output.

### Which to choose?

| | FM Kit | PCM Kit |
|---|---|---|
| Sound quality | Richer, more expressive | Simple, retro |
| SF2 preview accuracy | Low (can't preview FM) | High |
| Slots per voice | 2-3 (mod+carrier) | 1 |
| Max simultaneous notes | ~12-16 | ~28-32 |
| Best for | More complex instruments | Chiptune style |

Both kits use the same program numbers, so the same MIDI works with either TON file.

### Previewing FM Patches

The FM simulator renders patches to WAV using the same math as the Saturn:

```bash
python3 tools/fm_sim.py --list                    # List available patches
python3 tools/fm_sim.py --patch epiano            # Render electric piano
python3 tools/fm_sim.py --patch bell --note 72    # Render bell at C5
python3 tools/fm_sim.py --all                     # Render all presets to fm_renders/
```

This gives a better preview of FM instruments than the SF2 can.

## Customizing the Instrument Kit

Don't like the default sounds? There are two ways to customize:

### Option A: Edit the JSON Config

The quickest way to tweak waveforms and envelopes without leaving the command line:

```bash
# Export the default config
python3 tools/saturn_kit.py --save-config my_kit.json

# Edit my_kit.json (change waveforms, envelopes, add instruments)

# See available waveforms
python3 tools/saturn_kit.py --list-waveforms

# Regenerate with your custom config
python3 tools/saturn_kit.py --config my_kit.json -o my_kit
```

### Option B: Create Your Own SoundFont

For full control over the sound design, create a custom SoundFont using [Polyphone](https://www.polyphone.io/) — a free, open-source SoundFont editor available for Windows, macOS, and Linux.

With Polyphone you can:
- Record or import your own samples (keep them short and mono for Saturn)
- Design instruments with custom loop points, key ranges, and velocity layers
- Set envelope and filter parameters visually
- Preview everything before exporting

Once you have your `.sf2` file, convert it to a Saturn TON:

```bash
python3 tools/sf2ton.py my_sounds.sf2 -o my_sounds.ton --seq my_song.seq
```

**Tips for Saturn-friendly SoundFonts:**
- Keep total sample data under ~200KB (mono, 22050 Hz, 16-bit)
- Use short looped samples — a single cycle (50-400 samples) is ideal
- One sample per instrument is fine; multi-sample key splits work but cost more RAM
- Set the root key correctly in Polyphone — it determines the playback pitch on Saturn

### Waveform Types

| Waveform | Character |
|----------|-----------|
| `sine` | Pure, clean tone |
| `triangle` | Soft, slightly bright |
| `square` | Hollow, classic chiptune |
| `sawtooth` | Buzzy, bright, aggressive |
| `pulse` | Nasal, variable duty cycle |
| `piano` | Sine + decaying harmonics |
| `organ` | Drawbar-style additive |
| `strings` | Sawtooth with rolled-off highs |
| `brass` | Strong odd harmonics |
| `flute` | Fundamental + weak overtones |
| `bass` | Strong fundamental + low harmonics |
| `kick` | Pitched sine sweep (drum) |
| `snare` | Tone + noise burst (drum) |
| `hihat` | Filtered noise (drum) |
| `crash` | Long noise decay (drum) |
| `tom` | Pitched sine sweep (drum) |

### Envelope Parameters

Each instrument has an ADSR envelope matching the Saturn's SCSP hardware:

| Parameter | Range | Effect |
|-----------|-------|--------|
| `ar` | 0-31 | Attack rate (31 = instant, lower = slower) |
| `d1r` | 0-31 | Decay rate after attack (0 = no decay = sustain) |
| `dl` | 0-31 | Decay level / sustain point (0 = max sustain) |
| `rr` | 0-31 | Release rate after note off (31 = instant, lower = longer tail) |

Tips:
- **Piano feel:** `ar=31, d1r=8, dl=4, rr=12` (instant attack, noticeable decay)
- **Organ/pad:** `ar=31, d1r=0, dl=0, rr=16` (instant attack, full sustain)
- **Strings:** `ar=20, d1r=0, dl=0, rr=16` (slow attack, full sustain)
- **Drums:** `ar=31, d1r=0, dl=0, rr=31` (instant on/off)

## Integration with Your Game

The recommended way to build Saturn homebrew is [SaturnRingLib](https://github.com/SaturnRingLib/SaturnRingLib). The SEQ/TON audio support used by these tools requires [Frogbull's fork](https://github.com/Frogbull/SaturnRingLib), which adds the SGL sound driver integration and the `LoadSEQandTON` sample code. The instructions below assume you're using Frogbull's fork with `SRL_USE_SGL_SOUND_DRIVER = 1` in your makefile.

### File Setup

Copy your music files into the SRL project's `cd/data/` directory:

| File | Source | Description |
|------|--------|-------------|
| `BGM01.TON` | Your `saturn_kit.ton` (or custom TON) | Instrument data |
| `BGM01.SEQ` | Your converted `.seq` | Music sequence |

The following files are managed by SRL automatically when `SRL_USE_SGL_SOUND_DRIVER = 1`:

| File | Description |
|------|-------------|
| `CUSTOM.MAP` | Memory layout — use the one from the SRL Sound SEQ sample |
| `SDDRVS.TSK` | Sound driver program (auto-copied from SGL) |
| `SDDRVS.DAT` | Sound driver data (auto-copied from SGL) |
| `BOOTSND.MAP` | Boot-time config (auto-copied from SGL) |

### SRL Project Setup

In your project's `makefile`, enable the SGL sound driver:

```makefile
SRL_USE_SGL_SOUND_DRIVER = 1
```

In your source, define SEQ support and load the music:

```cpp
#define SRL_ENABLE_AUDIO_SEQ_SUPPORT 1
#define SoundMem 0x25a0b000
#include <srl.hpp>

// Use the LoadSEQandTON function from the SRL Sound SEQ sample
// (see SaturnRingLib/Samples/Sound - SEQ/src/main.cxx for the full implementation)
LoadSEQandTON("BGM01.SEQ", "BGM01.TON");

// Play bank 1, song 0, at full volume
slBGMOn((1 << 8) + 0, 0, 127, 0);

// Stop
slBGMOff();

// Pause / Resume
slBGMPause();
slBGMCont();

// Volume (0-127) and Tempo (-32768 to 32767, 0 = normal)
slBGMFade(100, 0);
slBGMTempo(0);
```

### Working Example

The complete working example is in Frogbull's fork:
[Frogbull/SaturnRingLib/Samples/Sound - SEQ](https://github.com/Frogbull/SaturnRingLib/tree/main/Samples/Sound%20-%20SEQ)

This sample includes a `LoadSEQandTON()` function that reads `CUSTOM.MAP` to find the correct memory addresses, loads the SEQ and TON files from CD, and DMAs them into sound RAM. Copy this function into your project. Note that this functionality is specific to Frogbull's fork and may not be available in upstream SaturnRingLib.

### Important: CUSTOM.MAP

The `CUSTOM.MAP` file tells both the SRL code and the sound driver where to place data in the SCSP's 512KB sound RAM. Use the `CUSTOM.MAP` from the SRL Sound SEQ sample — it defines bank 0 (driver defaults) and bank 1 (your music) at addresses the sound driver expects.

If your TON file is larger than the allocation in the MAP (~247KB for bank 1 TON), you'll need to regenerate the MAP with larger sizes. See [SEQUENCES.md](SEQUENCES.md) for the MAP format.

## File Size Budget

The Saturn has 512KB of sound RAM, shared between the driver, instruments, and sequences:

| Component | Typical Size | Notes |
|-----------|-------------|-------|
| Sound driver | ~180KB | Fixed overhead |
| Bank 0 defaults | ~35KB | Fixed overhead |
| **Your TON** | **30-60KB** | Depends on number of instruments |
| **Your SEQ** | **1-10KB** | Depends on song length/complexity |
| **Available** | **~230KB** | For your music data |

The default Saturn Sound Kit uses ~40KB for 16 instruments, leaving plenty of room. You could add more instruments or use longer/higher-quality samples if needed.
