# Making Music for Sega Saturn Homebrew

This guide walks you through composing and exporting music for Saturn homebrew games using standard MIDI tools. No retro hardware knowledge required — if you can write MIDI, you can make Saturn music.

## What You Need

- **Any DAW** (Reaper, Logic, FL Studio, Ableton, Ardour, etc.)
- **Python 3** (for the conversion tools)
- **Emscripten** (optional, only if building the SCSP WASM engine — `brew install emscripten`)

## Two Ways to Compose

### Option A: SCSP FM Synth VST (Recommended)

Compose directly with hardware-accurate Saturn FM synthesis in your DAW. What you hear is what plays on real hardware.

```bash
# 1. Build the VST plugin (once)
cd tools/scsp_vst && make
cp -R bin/scsp-fm-synth.vst3 ~/Library/Audio/Plug-Ins/VST3/  # macOS
# Or copy to your platform's VST3 directory

# 2. In your DAW: load "SCSP FM Synth" on each MIDI track
#    Choose a preset (Electric Piano, Brass, Organ, etc.)
#    Set the Program Number for each instance (0-15)
#    Compose your music, export as Format 0 MIDI

# 3. Export patches: click "Copy JSON" on each VST instance, save to files
#    Merge into one config:
python3 tools/merge_patches.py piano.json bass.json brass.json -o my_kit.json

# 4. Build the Saturn sound kit
python3 tools/saturn_kit.py --config my_kit.json -o my_kit

# 5. Convert MIDI to SEQ
./mid2seq my_song.mid my_song.seq

# 6. Ship my_kit.ton + my_song.seq + CUSTOM.MAP with your game
```

### Option B: SoundFont Preview (Simpler Setup)

Use a pre-built SoundFont for composing. Faster to set up, but FM instruments won't sound as rich as on the real Saturn (the SF2 can't simulate FM synthesis).

```bash
# 1. Generate the Saturn Sound Kit (once)
python3 tools/saturn_kit.py

# 2. Load saturn_kit.sf2 into your DAW
#    Compose your music, export as Format 0 MIDI

# 3. Convert to Saturn format
./mid2seq my_song.mid my_song.seq

# 4. Ship saturn_kit.ton + my_song.seq + CUSTOM.MAP with your game
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

### Using the SCSP FM Synth VST (Recommended)

The SCSP FM Synth runs the actual Saturn sound chip emulator natively in your DAW. Every note you play goes through the real SCSP engine — envelopes, FM modulation, ring buffer behavior, everything is hardware-accurate.

#### Installation

```bash
cd tools/scsp_vst && make
# macOS:
cp -R bin/scsp-fm-synth.vst3 ~/Library/Audio/Plug-Ins/VST3/
cp -R bin/scsp-fm-synth.clap ~/Library/Audio/Plug-Ins/CLAP/
# Linux:
cp -R bin/scsp-fm-synth.vst3 ~/.vst3/
cp -R bin/scsp-fm-synth.lv2 ~/.lv2/
```

Rescan plugins in your DAW. "SCSP FM Synth" should appear under the synthesizer category.

#### Channel Setup

Load one instance of SCSP FM Synth per instrument channel:

```
Track 1: SCSP FM Synth → Preset: Electric Piano, Program: 0
Track 2: SCSP FM Synth → Preset: Strings, Program: 3
Track 3: SCSP FM Synth → Preset: FM Bass, Program: 8
Track 4: SCSP FM Synth → Preset: Brass, Program: 4
...
```

Set a different **Program Number** on each instance (0-15). This determines the instrument's program number in the exported TON file — it must match the program changes in your MIDI.

#### Designing Custom Sounds

Each VST instance has a full FM editor in its WebView UI:

- **Operator tabs** (1-6 operators) — click tabs to switch, each has its own ratio, level, envelope, and modulation settings
- **Carrier/Modulator toggle** — carriers produce audio, modulators shape the timbre
- **Mod Source dropdown** — wire any operator as a modulator for any other
- **Per-operator waveform** — each operator can use a different waveform: Sine, Sawtooth, Square, Triangle, Organ, Brass, Strings, Piano, Flute, Bass, or a custom WAV file
- **Loop controls** — per-operator loop mode (Off, Forward, Reverse, Ping-pong) with adjustable loop start/end points
- **Waveform preview** — visualizes the selected waveform with highlighted loop region
- **Custom WAV upload** — load any WAV file as an operator waveform (auto-resampled to 1024 samples for FM operators)
- **Envelope visualization** — real-time ADSR curve with SCSP hardware rate tables
- **12 built-in presets** — Electric Piano, Bell, Brass, Organ, FM Bass, Strings, Clavinet, Marimba, Electric Piano 2 (3-op), Metallic (3-op), 4-Op E.Piano, Sine

All parameters are automatable — you can automate FM depth, envelope rates, operator ratios, or even waveform selection over time in your DAW.

**Important:** FM operators (modulators and FM-modulated carriers) must use 1024-sample waveforms — the SCSP's FM math is hardcoded for this length. The plugin handles this automatically: custom WAV files loaded on FM operators are resampled to 1024 samples. Pure PCM carriers (no FM modulation) can use any waveform length with full loop control.

#### Exporting Patches for Saturn

When your song is ready, export each VST instance's patch for the Saturn:

1. On each VST instance, click **Copy JSON**
2. Paste into a file (e.g., `piano.json`, `bass.json`, `brass.json`)
3. Merge all patches:
   ```bash
   python3 tools/merge_patches.py piano.json bass.json brass.json -o my_kit.json
   ```
4. Build the TON:
   ```bash
   python3 tools/saturn_kit.py --config my_kit.json -o my_kit
   ```

The exported JSON is in `saturn_kit.py --config` format. Each file includes the Program Number you set in the VST, so the merge tool preserves the correct instrument assignments.

You can also **Paste JSON** into the VST to import patches from the FM Patch Editor or from other sources.

#### Polyphony Budget

The Saturn SCSP has 32 slots total. FM instruments use 2-4 slots per note (one per operator). When you build the TON, `saturn_kit.py` reports the polyphony budget:

```
[polyphony] SCSP slot budget: 32 slots total
  Piano       : 2 slots → max 16 notes if playing alone
  E.Piano     : 3 slots → max 10 notes if playing alone
  Bass        : 2 slots → max 16 notes if playing alone
  With 1 note per instrument: 6-7 slots used, 25-26 remaining for polyphony
```

Keep this in mind when arranging — dense chords on a 4-op instrument eat slots quickly.

### Using the SoundFont (Alternative)

If you prefer a simpler setup or your DAW doesn't support VST3/CLAP:

1. Run `python3 tools/saturn_kit.py` to generate `saturn_kit.sf2`
2. Load `saturn_kit.sf2` as a virtual instrument (via sforzando, sfizz, juicysfplugin, or native SF2 support)
3. The SoundFont contains all 16 instruments at the program numbers listed above

Note: The SoundFont can't simulate FM synthesis — it plays the raw sine wave for FM instruments. The actual Saturn will sound richer. Use the SCSP FM Synth VST for accurate FM preview.

### Channel Setup (Both Methods)

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

Note: The SCSP FM Synth VST currently handles melodic FM instruments only. For drums, use the SoundFont or PCM samples in `saturn_kit.py`.

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

If you have the full dev environment set up (see the [scsp-fx](https://codeberg.org/magnavespa/scsp-fx) repo):

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

| | VST + FM Kit | SF2 + FM Kit | SF2 + PCM Kit |
|---|---|---|---|
| Preview accuracy | Exact (SCSP emulator) | Low (no FM in SF2) | High |
| Sound quality | Rich FM synthesis | Rich on Saturn, flat in DAW | Simple, retro |
| Custom sound design | Full FM editor in DAW | Edit JSON or use fm_editor.py | Edit JSON |
| Setup complexity | Build VST once | Generate SF2 | Generate SF2 |
| Slots per voice | 2-4 (configurable) | 2-3 (fixed per kit) | 1 |
| Max simultaneous notes | Depends on ops/voice | ~12-16 | ~28-32 |
| Best for | Serious FM composition | Quick prototyping | Chiptune style |

All approaches produce the same TON + SEQ files for the Saturn. The VST gives the most accurate preview of what the Saturn will actually sound like.

### FM Patch Editor (Interactive, Hardware-Accurate)

The FM Patch Editor lets you design, audition, and export FM patches in your browser with **real-time SCSP emulation** — the same chip emulator used by Saturn game music players, compiled to WebAssembly:

```bash
python3 tools/fm_editor.py                        # Launch the editor
python3 tools/fm_editor.py --load my_patches.json # Load existing patches
```

The editor provides:
- **Visual operator graph** — drag operators, wire modulation routing, toggle carrier/modulator
- **Full SCSP parameter control** — AR, D1R, DL, D2R, RR, TL, MDL, feedback, and more
- **Envelope visualization** — real-time display with SCSP rate tables
- **Piano keyboard** — click or use computer keyboard (A-K keys) to play notes live
- **Preset library** — Electric Piano, Brass, Organ, Bell, Strings, Bass, and more
- **Algorithm presets** — common FM topologies (2-op, 3-op serial, Y-shape, parallel, 4-op)
- **Export to JSON** — compatible with `saturn_kit.py --config`
- **Export to WAV** — offline render of any patch

**What makes it special:** The audio engine is the actual [aosdk](https://github.com/nmlgc/aosdk) SCSP emulator (by ElSemi, R. Belmont, kingshriek) compiled to WebAssembly. Envelopes, FM modulation depth, ring buffer behavior, and key rate scaling are all hardware-accurate. What you hear in the editor is what you'll hear on real Saturn hardware.

The editor generates a single self-contained HTML file (~120KB) with the WASM binary embedded — no server or installation required, just open in any modern browser.

#### Designing a custom FM instrument

1. Open the editor: `python3 tools/fm_editor.py`
2. Click **Algorithms** and choose a topology (e.g., "1→2" for a simple 2-op FM)
3. Click the modulator box, adjust its **frequency ratio** (2.0 for classic e-piano brightness) and **level**
4. Click the carrier box, adjust **MDL** (modulation depth — higher = brighter)
5. Tweak the **envelope** (AR/D1R/DL/D2R/RR) to shape the attack and decay
6. Play notes on the piano keyboard to audition
7. Click **Export JSON** to save your patches
8. Use them with saturn_kit: `python3 tools/saturn_kit.py --config my_patches.json -o my_kit`

#### DX7 Patch Import (Experimental)

Convert DX7 SysEx banks to Saturn-compatible FM patches:

```bash
python3 tools/dx7_to_saturn.py my_dx7_bank.syx --export patches.json
python3 tools/fm_editor.py --load patches.json   # Audition in the editor
```

**Most DX7 patches will not sound correct on Saturn.** The DX7 has 6 operators with 32 fixed algorithms, while the Saturn's SCSP has fundamentally different FM behavior: phase modulation via a shared ring buffer (not direct operator wiring), 16-bit ring buffer resolution (causes quantization noise in feedback), and no native multi-operator algorithm support. The converter reduces 6 operators to 2-4, simplifies envelopes from DX7's 4-stage to SCSP's format, and approximates feedback — but complex DX7 patches (especially those relying on 4+ operators, specific algorithms, or subtle level balancing) will sound different. Use imported patches as a starting point and tweak them in the editor.

### FM Simulator (Command-Line)

For quick offline rendering without the visual editor:

```bash
python3 tools/fm_sim.py --list                    # List available patches
python3 tools/fm_sim.py --patch epiano            # Render electric piano
python3 tools/fm_sim.py --patch bell --note 72    # Render bell at C5
python3 tools/fm_sim.py --all                     # Render all presets to fm_renders/
```

Note: `fm_sim.py` uses a simplified JS-style FM model. The FM Patch Editor's WASM engine is more accurate to the actual hardware.

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

### Per-Operator Waveforms (FM Instruments)

When using `fm_ops` in your JSON config (from the VST or FM editor), each operator can specify its own waveform and loop settings:

```json
{
  "instruments": [{
    "name": "Saw Mod Piano",
    "program": 0,
    "fm_ops": [
      {
        "freq_ratio": 2.0, "level": 0.9, "is_carrier": false,
        "waveform": "sawtooth",
        "loop_mode": 1, "loop_start": 0, "loop_end": 100,
        "ar": 31, "d1r": 12, "dl": 8, "rr": 14,
        "mdl": 0, "mod_source": -1, "feedback": 0.0
      },
      {
        "freq_ratio": 1.0, "level": 0.8, "is_carrier": true,
        "waveform": "sine",
        "loop_mode": 1, "loop_start": 0, "loop_end": 100,
        "ar": 31, "d1r": 6, "dl": 2, "rr": 14,
        "mdl": 9, "mod_source": 0, "feedback": 0.0
      }
    ]
  }]
}
```

Available waveform names: `sine`, `sawtooth`, `square`, `triangle`, `organ`, `brass`, `strings`, `piano`, `flute`, `bass`. Operators sharing the same waveform name reuse the same PCM data in the TON file (no duplicate storage).

Loop modes: `0` = off (one-shot), `1` = forward, `2` = reverse, `3` = ping-pong.

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
