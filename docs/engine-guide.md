# Building a Custom Sound Engine for Bebhionn

This guide explains how to create a new sound engine for the Bebhionn tracker.
The tracker architecture separates the pattern sequencer and UI from the audio
engine, so you can reuse the tracker with any synthesizer, sampler, or external
MIDI device.

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  tracker_ui.js                                      │
│  Grid, keyboard, transport, import/export           │
│                                                     │
│  Calls engine methods for sound, delegates          │
│  instrument editor to the engine                    │
└──────────┬──────────────────────────┬───────────────┘
           │                          │
     ┌─────▼─────┐            ┌──────▼──────┐
     │ tracker_   │            │ tracker_    │
     │ state.js   │            │ playback.js │
     │            │            │             │
     │ Patterns,  │            │ Step        │
     │ song,      │◄───────────│ sequencer,  │
     │ instruments│            │ note timing │
     └────────────┘            └──────┬──────┘
                                      │
                               ┌──────▼──────┐
                               │ YOUR ENGINE │
                               │             │
                               │ Implements  │
                               │ SoundEngine │
                               │ interface   │
                               └─────────────┘
```

The tracker never calls your engine directly except through 11 methods defined
by the **SoundEngine interface**. Implement those methods and you have a
working tracker.

## The SoundEngine Interface

Your engine must be a JavaScript object (typically an IIFE) with these methods:

### Required Methods

#### `init() → Promise<void>`

One-time async initialization. Called before first note playback. Load samples,
initialize Web Audio, compile WASM — whatever your engine needs. Called multiple
times (guard with a `ready` flag).

#### `startAudio(playback)`

Create the AudioContext and start the audio processing loop. Your audio callback
must call `playback.processBlock(numSamples)` when `playback.playing` is true —
this advances the sequencer and triggers notes via your `triggerNote` method.

The `playback` parameter is the TrackerPlayback instance. Store a reference to it.

**Why the engine owns the AudioContext:** Different engines have fundamentally
different audio architectures. A WASM emulator uses `ScriptProcessorNode`,
a Web Audio synth uses `OscillatorNode` graphs, a MIDI output engine doesn't
render audio at all. The engine decides how audio flows.

#### `triggerNote(ch, midiNote, instIdx, inst)`

Start playing a note.

| Param | Type | Description |
|-------|------|-------------|
| `ch` | number | Tracker channel (0–7) |
| `midiNote` | number | MIDI note number (0–127) |
| `instIdx` | number | Index into `state.instruments[]` |
| `inst` | object | The instrument object itself (your engine's format) |

The `inst` object is whatever your `getPresets()` or `createDefaultInstrument()`
returned — the tracker stores it opaquely. You define the fields.

#### `releaseChannel(ch)`

Stop the note playing on tracker channel `ch`. Called on note-off events, when a
new note replaces the previous one on the same channel, and when channels are muted.

#### `releaseAll()`

Stop all playing notes. Called when playback stops.

#### `getSampleRate() → number`

Return the sample rate your engine uses (e.g., 44100, 48000). Used by the
playback engine to calculate step timing.

#### `getPresets() → Object[]`

Return an array of default instruments for initial state. Deep-cloned by the
tracker, so return fresh objects. Each instrument must have at minimum a `name`
field. All other fields are engine-specific.

#### `createDefaultInstrument() → Object`

Return a single new default instrument. Used by the "Add Instrument" button.

#### `importBank(arrayBuffer, label) → { instruments, message }`

Import a bank file (your engine's native format). Return:
- `instruments`: array of instrument objects, or `null` on error
- `message`: status string shown to the user

If your engine doesn't support bank files, return `{ instruments: null, message: 'Not supported' }`.

#### `exportBank(instruments) → Uint8Array | null`

Export instruments to your engine's native bank format. Return `null` if not supported.

#### `renderInstEditor(container, inst, selectedOp, onChange)`

Build your engine-specific instrument editor into the provided DOM element.

| Param | Type | Description |
|-------|------|-------------|
| `container` | HTMLElement | Empty `<div>` to fill with your editor UI |
| `inst` | object | The instrument being edited |
| `selectedOp` | number | Currently selected operator/layer index |
| `onChange` | function | Call this when the user changes a parameter (re-renders the instrument list) |

This is where your engine's personality lives. The SCSP engine builds FM operator
sliders (AR, D1R, D2R, RR, MDL). A sample-based engine might show a waveform
editor. A MIDI output engine might show CC mappings. You have full control.

## Example: Web Audio Subtractive Synth Engine

Here's a complete, minimal engine using the Web Audio API. It implements a
simple subtractive synthesizer with oscillator type, filter cutoff, and
ADSR envelope.

```javascript
/**
 * Minimal subtractive synth engine for the Bebhionn tracker.
 * Demonstrates the SoundEngine interface with Web Audio API.
 */
var SubSynthEngine = (function () {
    'use strict';

    var SAMPLE_RATE = 44100;
    var actx = null;
    var playbackRef = null;
    var voices = {};  // ch → { osc, gain, filter }

    // ── Presets ────────────────────────────────────────────────

    var PRESETS = [
        { name: 'Saw Lead',  oscType: 'sawtooth', cutoff: 2000, resonance: 1,  attack: 0.01, decay: 0.2, sustain: 0.6, release: 0.3 },
        { name: 'Square Pad', oscType: 'square',   cutoff: 800,  resonance: 0.5, attack: 0.3,  decay: 0.1, sustain: 0.8, release: 0.5 },
        { name: 'Sine Bass',  oscType: 'sine',     cutoff: 500,  resonance: 2,  attack: 0.005,decay: 0.1, sustain: 0.4, release: 0.1 },
        { name: 'Triangle',   oscType: 'triangle', cutoff: 4000, resonance: 0,  attack: 0.02, decay: 0.3, sustain: 0.5, release: 0.4 },
    ];

    // ── Helpers ────────────────────────────────────────────────

    function midiToFreq(note) {
        return 440 * Math.pow(2, (note - 69) / 12);
    }

    // ── SoundEngine implementation ────────────────────────────

    var api = {
        init: function () {
            if (actx) return Promise.resolve();
            actx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: SAMPLE_RATE });
            return Promise.resolve();
        },

        startAudio: function (playback) {
            playbackRef = playback;
            if (actx && actx.state === 'suspended') actx.resume();

            // Use a silent ScriptProcessor to drive the sequencer.
            // A real engine might use AudioWorklet instead.
            if (!api._ticker && actx) {
                var ticker = actx.createScriptProcessor(2048, 0, 1);
                ticker.onaudioprocess = function (e) {
                    if (playbackRef && playbackRef.playing) {
                        playbackRef.processBlock(e.outputBuffer.length);
                    }
                    // Output silence — actual sound comes from oscillators
                    var out = e.outputBuffer.getChannelData(0);
                    for (var i = 0; i < out.length; i++) out[i] = 0;
                };
                ticker.connect(actx.destination);
                api._ticker = ticker;
            }
        },

        triggerNote: function (ch, midiNote, instIdx, inst) {
            if (!actx || !inst) return;
            // Release previous note on this channel
            api.releaseChannel(ch);

            var now = actx.currentTime;
            var freq = midiToFreq(midiNote);

            // Oscillator
            var osc = actx.createOscillator();
            osc.type = inst.oscType || 'sawtooth';
            osc.frequency.value = freq;

            // Filter
            var filter = actx.createBiquadFilter();
            filter.type = 'lowpass';
            filter.frequency.value = inst.cutoff || 2000;
            filter.Q.value = inst.resonance || 1;

            // Gain envelope (ADSR)
            var gain = actx.createGain();
            gain.gain.setValueAtTime(0, now);
            gain.gain.linearRampToValueAtTime(1.0, now + (inst.attack || 0.01));
            gain.gain.linearRampToValueAtTime(
                inst.sustain || 0.5,
                now + (inst.attack || 0.01) + (inst.decay || 0.1)
            );

            // Connect: osc → filter → gain → output
            osc.connect(filter);
            filter.connect(gain);
            gain.connect(actx.destination);
            osc.start(now);

            voices[ch] = { osc: osc, gain: gain, filter: filter, inst: inst };
        },

        releaseChannel: function (ch) {
            var v = voices[ch];
            if (!v) return;
            var now = actx.currentTime;
            var rel = v.inst.release || 0.3;
            v.gain.gain.cancelScheduledValues(now);
            v.gain.gain.setValueAtTime(v.gain.gain.value, now);
            v.gain.gain.linearRampToValueAtTime(0, now + rel);
            v.osc.stop(now + rel + 0.05);
            delete voices[ch];
        },

        releaseAll: function () {
            for (var ch in voices) api.releaseChannel(parseInt(ch));
        },

        getSampleRate: function () { return SAMPLE_RATE; },

        getPresets: function () {
            return JSON.parse(JSON.stringify(PRESETS));
        },

        createDefaultInstrument: function () {
            return {
                name: 'New Synth',
                oscType: 'sawtooth',
                cutoff: 2000,
                resonance: 1,
                attack: 0.01,
                decay: 0.2,
                sustain: 0.6,
                release: 0.3,
            };
        },

        importBank: function () {
            return { instruments: null, message: 'Bank import not supported' };
        },

        exportBank: function () { return null; },

        renderInstEditor: function (container, inst, selectedOp, onChange) {
            container.innerHTML = '';
            if (!inst) return;

            var params = [
                { key: 'cutoff',    label: 'Cutoff',    min: 100,   max: 8000, step: 10,    fmt: function(v) { return Math.round(v) + ' Hz'; } },
                { key: 'resonance', label: 'Resonance', min: 0,     max: 20,   step: 0.1,   fmt: function(v) { return v.toFixed(1); } },
                { key: 'attack',    label: 'Attack',    min: 0.001, max: 2,    step: 0.001, fmt: function(v) { return (v * 1000).toFixed(0) + ' ms'; } },
                { key: 'decay',     label: 'Decay',     min: 0.001, max: 2,    step: 0.001, fmt: function(v) { return (v * 1000).toFixed(0) + ' ms'; } },
                { key: 'sustain',   label: 'Sustain',   min: 0,     max: 1,    step: 0.01,  fmt: function(v) { return v.toFixed(2); } },
                { key: 'release',   label: 'Release',   min: 0.01,  max: 5,    step: 0.01,  fmt: function(v) { return (v * 1000).toFixed(0) + ' ms'; } },
            ];

            // Oscillator type dropdown
            var oscRow = document.createElement('div');
            oscRow.className = 'op-param';
            var oscLbl = document.createElement('label');
            oscLbl.textContent = 'Osc';
            var oscSel = document.createElement('select');
            ['sine', 'sawtooth', 'square', 'triangle'].forEach(function (t) {
                var o = document.createElement('option');
                o.value = t;
                o.textContent = t.charAt(0).toUpperCase() + t.slice(1);
                oscSel.appendChild(o);
            });
            oscSel.value = inst.oscType || 'sawtooth';
            oscSel.onchange = function () { inst.oscType = oscSel.value; };
            oscRow.appendChild(oscLbl);
            oscRow.appendChild(oscSel);
            container.appendChild(oscRow);

            // Parameter sliders
            for (var i = 0; i < params.length; i++) {
                (function (p) {
                    var row = document.createElement('div');
                    row.className = 'op-param';
                    var lbl = document.createElement('label');
                    lbl.textContent = p.label;
                    var inp = document.createElement('input');
                    inp.type = 'range';
                    inp.min = p.min; inp.max = p.max; inp.step = p.step;
                    inp.value = inst[p.key] || 0;
                    var val = document.createElement('span');
                    val.className = 'val';
                    val.textContent = p.fmt(inst[p.key] || 0);
                    inp.oninput = function () {
                        inst[p.key] = parseFloat(inp.value);
                        val.textContent = p.fmt(inst[p.key]);
                    };
                    row.appendChild(lbl);
                    row.appendChild(inp);
                    row.appendChild(val);
                    container.appendChild(row);
                })(params[i]);
            }

            // Test button
            var testRow = document.createElement('div');
            testRow.style.marginTop = '8px';
            var testBtn = document.createElement('button');
            testBtn.textContent = 'Test (C-4)';
            testBtn.style.cssText = 'background:#2a4a2e;color:#8c8;border:1px solid #4a4;' +
                'padding:4px 12px;cursor:pointer;border-radius:3px;font-family:inherit;font-size:10px;';
            testBtn.onclick = function () {
                api.init().then(function () {
                    api.triggerNote(99, 60, 0, inst);
                    setTimeout(function () { api.releaseChannel(99); }, 500);
                });
            };
            testRow.appendChild(testBtn);
            container.appendChild(testRow);
        },
    };

    return api;
})();
```

## Wiring It Up

Create an HTML file that loads the tracker modules and your engine:

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>My Tracker</title>
<!-- Copy the <style> block from the Bebhionn tracker.html -->
</head>
<body>
<!-- Copy the HTML structure (transport bar, grid, inst panel, etc.)
     from the Bebhionn tracker.html — it's engine-agnostic -->

<!-- Tracker core modules -->
<script src="tools/note_util.js"></script>
<script src="tools/midi_io.js"></script>
<script src="tools/seq_io.js"></script>
<script src="tools/tracker_state.js"></script>
<script src="tools/tracker_playback.js"></script>

<!-- Your engine (instead of scsp_engine.js) -->
<script src="my_subsynth_engine.js"></script>

<!-- Tracker UI -->
<script src="tools/tracker_ui.js"></script>

<!-- Bootstrap -->
<script>
var state = TrackerState.create(SubSynthEngine.getPresets());
var playback = TrackerPlayback.create(state, SubSynthEngine);
TrackerUI.init(state, playback, SubSynthEngine);
</script>
</body>
</html>
```

That's it. Three lines of bootstrap. The grid, keyboard input, playback engine,
MIDI/SEQ import/export, song arrangement — everything works automatically. Your
engine just handles sound and the instrument editor.

## Instrument Data Model

The tracker stores instruments as opaque objects in `state.instruments[]`. The
only field the tracker itself reads is `name` (for the instrument list display).
Everything else — oscillator type, filter params, sample data, register values —
is your engine's business.

```javascript
// The tracker sees:
{ name: 'Saw Lead', /* ...your fields here... */ }

// Your engine sees all its fields:
{ name: 'Saw Lead', oscType: 'sawtooth', cutoff: 2000, resonance: 1,
  attack: 0.01, decay: 0.2, sustain: 0.6, release: 0.3 }
```

When the user edits parameters in your `renderInstEditor`, you modify the
instrument object directly. The tracker doesn't care what you change — it just
stores the object and passes it back to you in `triggerNote`.

## The Audio Callback Pattern

Your `startAudio` method must ensure that `playback.processBlock(n)` is called
from within the audio processing loop. This is what drives the sequencer.

The pattern depends on your audio architecture:

### ScriptProcessorNode (simplest, used by the SCSP engine)

```javascript
var node = actx.createScriptProcessor(2048, 0, 2);
node.onaudioprocess = function (e) {
    var n = e.outputBuffer.getChannelData(0).length;
    if (playback.playing) playback.processBlock(n);
    // ... render your audio into the output buffer ...
};
node.connect(actx.destination);
```

### AudioWorklet (modern, better performance)

```javascript
// In your worklet processor:
process(inputs, outputs) {
    if (this.playback && this.playback.playing) {
        this.playback.processBlock(outputs[0][0].length);
    }
    // ... render audio ...
    return true;
}
```

### No audio rendering (e.g., external MIDI output)

If your engine sends MIDI to an external device instead of rendering audio,
you still need a timer to drive the sequencer:

```javascript
startAudio: function (playback) {
    playbackRef = playback;
    // Use a setInterval as a clock source
    if (!this._timer) {
        var samplesPerTick = 2048;
        var interval = (samplesPerTick / 44100) * 1000;
        this._timer = setInterval(function () {
            if (playbackRef.playing) playbackRef.processBlock(samplesPerTick);
        }, interval);
    }
},
```

## Bank Import/Export

`importBank` and `exportBank` handle your engine's native file format.

- **importBank** receives raw bytes and returns instrument objects. The tracker
  replaces `state.instruments` with whatever you return.
- **exportBank** receives the current instrument array and returns bytes for download.

If your engine uses SoundFont (.sf2), you'd parse the SF2 in `importBank` and
return instruments with sample references. If your engine uses no bank format,
just return `null`.

The tracker separately handles MIDI and SEQ import/export — those are
engine-agnostic (they only deal with note/timing data, not instrument
definitions).

## Testing Your Engine

You can test your engine in Node.js by mocking the browser APIs, similar to
how `scsp_engine.test.js` works:

```javascript
const vm = require('vm');
const fs = require('fs');

var sandbox = {
    console: console, Math: Math, JSON: JSON,
    Promise: Promise, Float32Array: Float32Array,
    window: { AudioContext: function() {} },
    document: { createElement: function() { return { style: {} }; } },
    setTimeout: setTimeout,
};

var src = fs.readFileSync('my_subsynth_engine.js', 'utf8');
vm.runInNewContext(src, sandbox);
var engine = sandbox.SubSynthEngine;

// Test getPresets
assert(engine.getPresets().length > 0);
assert(engine.getSampleRate() === 44100);
assert(engine.createDefaultInstrument().name);
```

## Checklist

When building a new engine, verify:

- [ ] `init()` returns a Promise (even if it resolves immediately)
- [ ] `startAudio()` calls `playback.processBlock(n)` from the audio loop
- [ ] `triggerNote()` handles the `inst` object from your own `getPresets()`
- [ ] `releaseChannel()` silences just one channel without affecting others
- [ ] `releaseAll()` silences everything (called on stop)
- [ ] `getPresets()` returns deep copies (not shared references)
- [ ] `createDefaultInstrument()` returns a fresh object each time
- [ ] `renderInstEditor()` clears `container.innerHTML` before building
- [ ] `renderInstEditor()` calls `onChange()` when parameters change
- [ ] `getSampleRate()` returns the correct rate for tempo calculation

## Files Reference

| File | Role | You need it? |
|------|------|-------------|
| `tracker_state.js` | Pattern/song/instrument data model | Yes |
| `tracker_playback.js` | Step sequencer | Yes |
| `tracker_ui.js` | Grid, keyboard, transport, import/export | Yes |
| `note_util.js` | `noteName()` for display | Yes |
| `midi_io.js` | MIDI file import/export | Yes (for MIDI support) |
| `seq_io.js` | Saturn SEQ import/export | Only if targeting Saturn |
| `ton_io.js` | Saturn TON bank format | Only if targeting Saturn |
| `scsp_engine.js` | SCSP FM synth engine | No — replace with yours |
