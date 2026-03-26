#!/usr/bin/env python3
"""
saturn_tracker.py — Saturn SCSP FM Tracker.

Browser-based classic vertical tracker for composing music using the
hardware-accurate SCSP (YMF292-F) emulator. Exports SEQ + TON files
directly for use on Sega Saturn.

Usage:
  python3 saturn_tracker.py                     # Open tracker in browser
  python3 saturn_tracker.py -o tracker.html     # Save to specific file
  python3 saturn_tracker.py --no-open           # Generate without opening

Architecture: generates a self-contained HTML file with embedded WASM,
same pattern as fm_editor.py. No server required.
"""

import base64
import os
import sys
import tempfile
import webbrowser


def generate_html():
    # Load SCSP WASM binary and JS glue
    wasm_dir = os.path.join(os.path.dirname(__file__), 'scsp_wasm')
    wasm_path = os.path.join(wasm_dir, 'scsp.wasm')
    glue_path = os.path.join(wasm_dir, 'scsp.js')

    if os.path.exists(wasm_path) and os.path.exists(glue_path):
        with open(wasm_path, 'rb') as f:
            wasm_b64 = base64.b64encode(f.read()).decode('ascii')
        with open(glue_path, 'r') as f:
            glue_js = f.read()
    else:
        print("[tracker] WARNING: SCSP WASM not found. Run 'make' in tools/scsp_wasm/")
        wasm_b64 = ""
        glue_js = "var SCSPModule = () => Promise.resolve(null);"

    # Load ton_io.js
    ton_io_path = os.path.join(os.path.dirname(__file__), 'ton_io.js')
    if os.path.exists(ton_io_path):
        with open(ton_io_path, 'r') as f:
            ton_io_js = f.read()
    else:
        ton_io_js = "var TonIO = null;"

    html = _HTML_TEMPLATE.replace('__SCSP_WASM_B64__', wasm_b64)
    html = html.replace('__SCSP_GLUE_JS__', glue_js)
    html = html.replace('__TON_IO_JS__', ton_io_js)
    return html


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Saturn SCSP Tracker</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'SF Mono', Consolas, Monaco, monospace; background: #0a0a1a; color: #ccc;
       display: flex; flex-direction: column; height: 100vh; overflow: hidden; user-select: none; }

/* Transport bar */
#transport { display: flex; align-items: center; gap: 10px; padding: 8px 12px;
             background: #12122a; border-bottom: 1px solid #333; flex-shrink: 0; }
#transport h1 { color: #00d4ff; font-size: 13px; margin-right: 8px; }
#transport button { background: #2a2a4e; color: #ccc; border: 1px solid #444; padding: 4px 12px;
                     cursor: pointer; border-radius: 3px; font-family: inherit; font-size: 11px; }
#transport button:hover { background: #3a3a5e; }
#transport button.active { background: #0a4a2a; color: #4f4; border-color: #4f4; }
#transport label { font-size: 10px; color: #888; }
#transport input, #transport select { background: #222; color: #ccc; border: 1px solid #444;
                                       padding: 2px 4px; font-family: inherit; font-size: 11px;
                                       border-radius: 2px; width: 50px; text-align: center; }
#transport select { width: auto; }
.transport-group { display: flex; align-items: center; gap: 4px; }
.transport-sep { color: #333; }

/* Channel headers */
#ch-headers { display: flex; padding: 0 12px 0 42px; background: #14142e; border-bottom: 1px solid #333; flex-shrink: 0; }
.ch-hdr { flex: 1; min-width: 120px; padding: 4px 6px; font-size: 10px; color: #888;
           display: flex; align-items: center; gap: 4px; border-right: 1px solid #222; }
.ch-hdr select { background: #1a1a2e; color: #aaa; border: 1px solid #333; padding: 1px 2px;
                  font-family: inherit; font-size: 9px; border-radius: 2px; flex: 1; }
.ch-hdr span { color: #00d4ff; font-weight: bold; }

/* Pattern grid */
#grid-container { flex: 1; overflow-y: auto; overflow-x: auto; }
#grid { display: table; width: 100%; border-collapse: collapse; }
.row { display: flex; border-bottom: 1px solid #111; }
.row.beat { border-top: 2px solid #2a2a4e; }
.row.playing { background: #1a2a1a; }
.row-num { width: 30px; min-width: 30px; padding: 2px 4px; font-size: 10px; color: #555;
           text-align: right; border-right: 1px solid #222; flex-shrink: 0; background: #0d0d20; }
.row.beat .row-num { color: #888; }
.cell { flex: 1; min-width: 120px; padding: 2px 6px; font-size: 11px; color: #666;
        border-right: 1px solid #111; cursor: pointer; white-space: nowrap; }
.cell:hover { background: #1a1a3a; }
.cell.cursor { background: #1a1a4a; outline: 1px solid #00d4ff; }
.cell .note { color: #4cf; }
.cell .note.off { color: #f66; }
.cell .inst { color: #8a8; margin-left: 4px; }
.cell .vol { color: #aa8; margin-left: 4px; }
.cell.has-note { color: #ccc; }

/* Status bar */
/* Song bar */
#song-bar { display: flex; align-items: center; gap: 6px; padding: 4px 12px;
            background: #10102a; border-bottom: 1px solid #333; flex-shrink: 0; font-size: 10px; }
#song-bar label { color: #888; white-space: nowrap; }
#song-slots { display: flex; flex-wrap: wrap; gap: 3px; flex: 1; }
#song-bar .song-slot { padding: 3px 8px; background: #1a1a3a; border: 1px solid #333; border-radius: 3px;
                        cursor: pointer; color: #888; font-family: inherit; font-size: 10px; min-width: 28px; text-align: center; }
#song-bar .song-slot.active { background: #2a2a5a; color: #00d4ff; border-color: #00d4ff; }
#song-bar .song-slot.playing { background: #1a3a1a; border-color: #4f4; color: #4f4; }
#song-bar button { background: #2a2a4e; color: #ccc; border: 1px solid #444; padding: 2px 8px;
                    cursor: pointer; border-radius: 3px; font-family: inherit; font-size: 10px; }
#song-bar button:hover { background: #3a3a5e; }

/* Main area: grid + instrument panel */
#main-area { flex: 1; display: flex; overflow: hidden; }
#grid-wrapper { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

/* Instrument panel */
#inst-panel { width: 260px; background: #12122a; border-left: 1px solid #333; display: flex;
              flex-direction: column; overflow: hidden; flex-shrink: 0; }
#inst-panel.collapsed { width: 30px; }
#inst-panel.collapsed #inst-content { display: none; }
#inst-toggle { background: #1a1a3a; border: none; color: #888; cursor: pointer; padding: 4px;
               font-family: inherit; font-size: 10px; border-bottom: 1px solid #333; text-align: center; }
#inst-toggle:hover { background: #2a2a4e; color: #ccc; }
#inst-content { flex: 1; overflow-y: auto; padding: 8px; }
#inst-list { margin-bottom: 8px; }
.inst-item { padding: 3px 6px; cursor: pointer; border-radius: 3px; font-size: 10px; color: #888;
             display: flex; justify-content: space-between; align-items: center; }
.inst-item:hover { background: #1a1a3a; }
.inst-item.sel { background: #1a1a4a; color: #00d4ff; }
.inst-item .inst-num { color: #555; margin-right: 4px; }
#inst-buttons { display: flex; gap: 4px; margin-bottom: 8px; }
#inst-buttons button { background: #2a2a4e; color: #ccc; border: 1px solid #444; padding: 2px 6px;
                        cursor: pointer; border-radius: 3px; font-family: inherit; font-size: 9px; flex: 1; }
#inst-buttons button:hover { background: #3a3a5e; }
#inst-editor h3 { color: #00d4ff; font-size: 11px; margin: 8px 0 4px; }
.op-param { display: flex; align-items: center; gap: 4px; margin-bottom: 3px; font-size: 10px; }
.op-param label { color: #888; width: 40px; text-align: right; flex-shrink: 0; }
.op-param input[type="range"] { flex: 1; accent-color: #00d4ff; }
.op-param .val { color: #00d4ff; width: 35px; text-align: right; font-size: 9px; }
.op-param select { background: #222; color: #ccc; border: 1px solid #444; font-family: inherit;
                    font-size: 9px; border-radius: 2px; flex: 1; }
.op-tab { display: inline-block; padding: 2px 8px; background: #1a1a3a; border: 1px solid #333;
          border-bottom: none; border-radius: 4px 4px 0 0; cursor: pointer; font-size: 10px; color: #888; }
.op-tab:hover { background: #2a2a4e; }
.op-tab.sel { background: #222244; color: #00d4ff; }
.op-tab.carrier { color: #4a4; }

#status { padding: 4px 12px; background: #12122a; border-top: 1px solid #333; font-size: 10px;
          color: #666; flex-shrink: 0; display: flex; gap: 20px; }
#status .info { color: #888; }
</style>
</head>
<body>

<!-- Transport -->
<div id="transport">
  <h1>Saturn Tracker</h1>
  <button id="btn-play" onclick="togglePlay()">&#9654; Play</button>
  <button id="btn-stop" onclick="stopPlayback()">&#9632; Stop</button>
  <span class="transport-sep">|</span>
  <div class="transport-group">
    <label>BPM</label>
    <input id="bpm" type="number" value="120" min="30" max="300" onchange="updateTempo()">
  </div>
  <div class="transport-group">
    <label>Steps/Beat</label>
    <select id="steps-per-beat" onchange="updateTempo()">
      <option value="2">2</option>
      <option value="4" selected>4</option>
      <option value="8">8</option>
    </select>
  </div>
  <div class="transport-group">
    <label>Rows</label>
    <select id="pattern-length" onchange="setPatternLength()">
      <option value="16">16</option>
      <option value="32" selected>32</option>
      <option value="64">64</option>
    </select>
  </div>
  <div class="transport-group">
    <label>Oct</label>
    <input id="octave" type="number" value="4" min="1" max="7" style="width:35px;">
  </div>
  <span class="transport-sep">|</span>
  <button onclick="exportTON()">Export TON</button>
  <button onclick="exportSEQ()">Export SEQ</button>
  <span class="transport-sep">|</span>
  <button onclick="importMIDI()">Import MIDI</button>
  <button onclick="importTonForTracker()">Load Instruments (TON)</button>
</div>

<!-- Song arrangement -->
<div id="song-bar">
  <label>Song:</label>
  <div id="song-slots"></div>
  <button onclick="addSongSlot()">+</button>
  <button onclick="removeSongSlot()">-</button>
  <button onclick="dupPattern()">Dup Pat</button>
  <button onclick="newPattern()">New Pat</button>
  <label style="margin-left:8px;" id="pat-info">Pat 0</label>
</div>

<!-- Main area -->
<div id="main-area">
  <!-- Grid wrapper -->
  <div id="grid-wrapper">
    <div id="ch-headers"></div>
    <div id="grid-container">
      <div id="grid"></div>
    </div>
  </div>

  <!-- Instrument panel -->
  <div id="inst-panel">
    <button id="inst-toggle" onclick="toggleInstPanel()">Instruments &laquo;</button>
    <div id="inst-content">
      <div id="inst-list"></div>
      <div id="inst-buttons">
        <button onclick="addInstrument()">+New</button>
        <button onclick="dupInstrument()">Dup</button>
        <button onclick="delInstrument()">Del</button>
        <button onclick="importTonInst()">Load TON</button>
      </div>
      <div id="inst-editor"></div>
    </div>
  </div>
</div>

<!-- Status -->
<div id="status">
  <span class="info" id="status-pos">Row: 00</span>
  <span class="info" id="status-inst">Inst: 00</span>
  <span class="info" id="status-msg"></span>
</div>

<!-- TON I/O -->
<script>
__TON_IO_JS__
</script>

<script>
// ═══════════════════════════════════════════════════════════════
// SCSP ENGINE (shared with fm_editor.py)
// ═══════════════════════════════════════════════════════════════

const SCSP_WASM_B64 = '__SCSP_WASM_B64__';
__SCSP_GLUE_JS__

const SAMPLE_RATE = 44100;
const WAVE_LEN = 1024;
const WAVE_BYTES = WAVE_LEN * 2;
const SINE_BASE_FREQ = SAMPLE_RATE / WAVE_LEN;
const SINE_BASE_NOTE = 69 + 12 * Math.log2(SINE_BASE_FREQ / 440);
const WAVE_NAMES = ['Sine','Sawtooth','Square','Triangle','Organ','Brass','Strings','Piano','Flute','Bass'];
const MAX_SLOTS = 32;
const NUM_CHANNELS = 8;

let scsp = null, scspReady = false;
let actx = null, fmNode = null, fmGain = null;

// ── Waveform generators ──
function genAdditive(n, harmonics) {
    const out = new Float32Array(n);
    for (const [h, a] of harmonics) {
        for (let i = 0; i < n; i++) out[i] += a * Math.sin(2 * Math.PI * h * i / n);
    }
    let peak = 0;
    for (let i = 0; i < n; i++) if (Math.abs(out[i]) > peak) peak = Math.abs(out[i]);
    if (peak > 0) for (let i = 0; i < n; i++) out[i] /= peak;
    return out;
}

function generateWaveform(type, n) {
    switch (type) {
    case 0: return genAdditive(n, [[1, 1.0]]);
    case 1: return genAdditive(n, Array.from({length:15}, (_, i) => [i+1, (((i+1)%2===0)?-1:1)/(i+1)]));
    case 2: return genAdditive(n, Array.from({length:8}, (_, i) => [2*i+1, 1.0/(2*i+1)]));
    case 3: return genAdditive(n, Array.from({length:8}, (_, i) => [2*i+1, ((i%2===0)?1:-1)/((2*i+1)*(2*i+1))]));
    case 4: return genAdditive(n, [[1,1],[2,0.8],[3,0.6],[4,0.3],[6,0.2],[8,0.15],[10,0.1]]);
    case 5: return genAdditive(n, [[1,1],[2,0.3],[3,0.7],[4,0.15],[5,0.5],[6,0.1],[7,0.3],[9,0.15]]);
    case 6: return genAdditive(n, Array.from({length:20}, (_, i) => [i+1, 1.0/Math.pow(i+1, 1.2)]));
    case 7: return genAdditive(n, [[1,1],[2,0.7],[3,0.4],[4,0.25],[5,0.15],[6,0.1],[7,0.08],[8,0.05]]);
    case 8: return genAdditive(n, [[1,1],[2,0.15],[3,0.05]]);
    case 9: return genAdditive(n, [[1,1],[2,0.5],[3,0.2],[4,0.1]]);
    default: return new Float32Array(n);
    }
}

// ── Waveform store ──
const waveStore = { waves: [], nextOffset: 0 };

function waveStoreAdd(ramPtr, floatSamples, loopStart, loopEnd, loopMode) {
    const offset = waveStore.nextOffset;
    const len = floatSamples.length;
    for (let i = 0; i < len; i++) {
        const val = Math.round(floatSamples[i] * 32767);
        scsp.HEAPU8[ramPtr + offset + i * 2]     = val & 0xFF;
        scsp.HEAPU8[ramPtr + offset + i * 2 + 1] = (val >> 8) & 0xFF;
    }
    const id = waveStore.waves.length;
    waveStore.waves.push({ offset, length: len, loopStart, loopEnd, loopMode });
    waveStore.nextOffset = offset + len * 2;
    return id;
}

async function initSCSP() {
    if (scspReady) return;
    if (!SCSP_WASM_B64) { showStatus('No SCSP WASM'); return; }
    const wasmBytes = Uint8Array.from(atob(SCSP_WASM_B64), c => c.charCodeAt(0));
    scsp = await SCSPModule({ wasmBinary: wasmBytes.buffer });
    resetSCSP();
    scspReady = true;
}

/* Reset SCSP state and reload built-in waveforms.
 * Call before loading a new TON to avoid RAM overflow. */
function resetSCSP() {
    scsp._scsp_init();
    voiceAlloc.releaseAll();
    waveStore.waves = [];
    waveStore.nextOffset = 0;
    const ramPtr = scsp._scsp_get_ram_ptr();
    for (let t = 0; t < WAVE_NAMES.length; t++) {
        const samples = generateWaveform(t, WAVE_LEN);
        waveStoreAdd(ramPtr, samples, 0, WAVE_LEN, 1);
    }
    // Built-in waveforms are IDs 0-9. TON imports get IDs 10+.
}

// ── SCSP slot programming (from fm_editor.py, with variable waveform length support) ──
function programSlot(slot, op, midiNote, allOps) {
    const wid = op.waveform || 0;
    let wav = waveStore.waves[wid] || waveStore.waves[0];

    let lsa = op.loop_start >= 0 ? op.loop_start : wav.loopStart;
    let lea = op.loop_end > 0 ? op.loop_end : wav.loopEnd;
    let lpctl = op.loop_mode >= 0 ? op.loop_mode : wav.loopMode;
    let sa = wav.offset;

    // FM constraint: modulators and FM-modulated ops must use 1024-sample forward loop.
    // If the current waveform isn't 1024 samples, fall back to sine (waveStore[0]).
    const usesFM = (op.mod_source >= 0 && op.mdl >= 5) || op.feedback > 0;
    const isMod = !op.is_carrier;
    if (usesFM || isMod) {
        if (wav.length !== WAVE_LEN) {
            wav = waveStore.waves[0]; // sine, 1024 samples
            sa = wav.offset;
        }
        lsa = 0; lea = WAVE_LEN; lpctl = 1;
    }

    // Compute pitch from the FINAL waveform length (after any FM swap).
    // At OCT=0 FNS=0, the SCSP steps 1 sample per output sample,
    // so base freq = SAMPLE_RATE / waveform_length.
    const wavLen = wav.length || WAVE_LEN;
    const wavBaseFreq = SAMPLE_RATE / wavLen;
    const wavBaseNote = 69 + 12 * Math.log2(wavBaseFreq / 440);

    let opBaseNote;
    if (op.freq_fixed > 0) {
        opBaseNote = wavBaseNote + 12 * Math.log2(op.freq_fixed / wavBaseFreq);
    } else {
        opBaseNote = wavBaseNote - 12 * Math.log2(op.freq_ratio || 1);
    }
    const semi = midiNote - opBaseNote;
    const octave = Math.max(-8, Math.min(7, Math.floor(semi / 12)));
    const frac = semi - octave * 12;
    const fns = Math.max(0, Math.min(1023, Math.round(1024 * (Math.pow(2, frac / 12) - 1))));
    const octBits = ((octave & 0xF) << 11) | (fns & 0x3FF);

    const d0 = (lpctl << 5) | ((sa >> 16) & 0xF);
    const d4 = ((op.d2r & 0x1F) << 11) | ((op.d1r & 0x1F) << 6) | (op.ar & 0x1F);
    const d5 = ((op.dl & 0x1F) << 5) | (op.rr & 0x1F);

    let tl;
    if (op.is_carrier) {
        tl = Math.max(0, Math.min(255, Math.round((1.0 - op.level) * 255)));
    } else {
        tl = Math.round(24 + (1.0 - op.level) * 56);
    }
    const d6 = tl & 0xFF;

    let mdl = 0, mdxsl = 0, mdysl = 0;
    if (op.mod_source >= 0 && op.mdl >= 5) {
        const modOp = allOps[op.mod_source];
        const modTL = Math.round(24 + (1.0 - modOp.level) * 56);
        let segaDB = 0;
        if(modTL&1) segaDB-=0.4; if(modTL&2) segaDB-=0.8; if(modTL&4) segaDB-=1.5;
        if(modTL&8) segaDB-=3; if(modTL&16) segaDB-=6; if(modTL&32) segaDB-=12;
        if(modTL&64) segaDB-=24; if(modTL&128) segaDB-=48;
        const tlLin = Math.pow(10, segaDB / 20);
        const ringPeak = 32767 * 4 * tlLin / 2;
        const targetBeta = Math.min(modOp.level * Math.PI, 2.5);
        const needed = targetBeta * 1024 / (ringPeak * 2 * Math.PI);
        mdl = Math.max(0, Math.min(15, Math.round(16 + Math.log2(Math.max(needed, 1e-10)))));
        const maxSafe = 1024 / (ringPeak * 2);
        const maxMDL = Math.floor(15 + Math.log2(Math.max(maxSafe, 1e-10)));
        mdl = Math.min(mdl, maxMDL);
        const dist = (op.mod_source - slot) & 63;
        mdxsl = dist; mdysl = dist;
    }
    if (op.feedback > 0) {
        const fbDist = (-32) & 63;
        const myTL = tl;
        let segaDB = 0;
        if(myTL&1) segaDB-=0.4; if(myTL&2) segaDB-=0.8; if(myTL&4) segaDB-=1.5;
        if(myTL&8) segaDB-=3; if(myTL&16) segaDB-=6; if(myTL&32) segaDB-=12;
        if(myTL&64) segaDB-=24; if(myTL&128) segaDB-=48;
        const tlLin = Math.pow(10, segaDB / 20);
        const ringPeak = 32767 * 4 * tlLin / 2;
        const targetBeta = op.feedback * Math.PI;
        const needed = targetBeta * 1024 / (ringPeak * 2 * Math.PI);
        const fbMdl = Math.max(0, Math.min(15, Math.round(16 + Math.log2(Math.max(needed, 1e-10)))));
        if (mdl > 0) { mdysl = fbDist; mdl = Math.max(mdl, fbMdl); }
        else { mdl = fbMdl; mdxsl = fbDist; mdysl = fbDist; }
    }
    const d7 = ((mdl & 0xF) << 12) | ((mdxsl & 0x3F) << 6) | (mdysl & 0x3F);

    const disdl = op.is_carrier ? 7 : 0;
    const dipan = 16;
    const dB = ((disdl & 0x7) << 13) | ((dipan & 0x1F) << 8);

    scsp._scsp_write_slot(slot, 0x0, d0);
    scsp._scsp_write_slot(slot, 0x1, sa & 0xFFFF);
    scsp._scsp_write_slot(slot, 0x2, lsa);
    scsp._scsp_write_slot(slot, 0x3, lea);
    scsp._scsp_write_slot(slot, 0x4, d4);
    scsp._scsp_write_slot(slot, 0x5, d5);
    scsp._scsp_write_slot(slot, 0x6, d6);
    scsp._scsp_write_slot(slot, 0x7, d7);
    scsp._scsp_write_slot(slot, 0x8, octBits);
    scsp._scsp_write_slot(slot, 0x9, 0);
    scsp._scsp_write_slot(slot, 0xA, 0);
    scsp._scsp_write_slot(slot, 0xB, dB);
}

/*
 * Program SCSP slot directly from raw TON layer register data.
 * This bypasses all the programSlot recomputation and matches
 * exactly what the Saturn sound driver does: copy register values
 * and adjust only SA (sample address) and OCT/FNS (pitch).
 */
/*
 * Program SCSP slot directly from raw TON layer register data.
 * slot: SCSP slot number
 * rawRegs: raw register data from TON import
 * midiNote: MIDI note to play
 * sa: sample address in SCSP RAM (byte offset)
 * slotBase: first slot number of this instrument (for FM ring buffer offset fixup)
 * opIndex: index of this operator within the instrument
 */
function programSlotRaw(slot, rawRegs, midiNote, sa, slotBase, opIndex) {
    // Compute pitch from base_note — the MIDI note where this layer
    // plays at its natural pitch at OCT=0, FNS=0.
    // base_note accounts for both waveform length and freq_ratio.
    const semi = midiNote - rawRegs.baseNote;
    const octave = Math.max(-8, Math.min(7, Math.floor(semi / 12)));
    const frac = semi - octave * 12;
    const fns = Math.max(0, Math.min(1023, Math.round(1024 * (Math.pow(2, frac / 12) - 1))));
    const octBits = ((octave & 0xF) << 11) | (fns & 0x3FF);

    // SA: use the provided waveform address with original LPCTL
    const d0 = (rawRegs.d0 & 0xE0) | ((sa >> 16) & 0xF);

    // Fix up MDXSL/MDYSL for the actual slot layout.
    // The TON stores ring buffer offsets relative to the original layer indices.
    // In the tracker, operators are placed at consecutive slots starting at slotBase.
    // The SCSP ring buffer offset formula: MDXSL = (source_slot - this_slot) & 63
    let d7 = rawRegs.d7;
    const mdl = (d7 >> 12) & 0xF;
    if (mdl > 0) {
        const origMdxsl = (d7 >> 6) & 0x3F;
        const origMdysl = d7 & 0x3F;
        // Only remap if not self-feedback (self-fb uses offset 32)
        let newMdxsl = origMdxsl;
        let newMdysl = origMdysl;
        if (origMdxsl !== 32) {
            // Original: source was at layer index = (opIndex + origMdxsl) & 63
            // In tracker: source is at slot (slotBase + (opIndex + origMdxsl) & 63)
            // New offset: (source_slot - slot) & 63
            // Since layers map 1:1 to consecutive slots, the relative offset is the same
            // as long as ops are in the same order. No fixup needed for consecutive allocation.
        }
        d7 = ((mdl & 0xF) << 12) | ((newMdxsl & 0x3F) << 6) | (newMdysl & 0x3F);
    }

    scsp._scsp_write_slot(slot, 0x0, d0);
    scsp._scsp_write_slot(slot, 0x1, sa & 0xFFFF);
    scsp._scsp_write_slot(slot, 0x2, rawRegs.lsa);
    scsp._scsp_write_slot(slot, 0x3, rawRegs.lea);
    scsp._scsp_write_slot(slot, 0x4, rawRegs.d4);      // D2R|D1R|AR
    scsp._scsp_write_slot(slot, 0x5, rawRegs.d5);      // KRS|DL|RR
    scsp._scsp_write_slot(slot, 0x6, rawRegs.tl);      // TL — exact value, no recomputation
    scsp._scsp_write_slot(slot, 0x7, d7);               // MDL|MDXSL|MDYSL
    scsp._scsp_write_slot(slot, 0x8, octBits);          // OCT|FNS
    scsp._scsp_write_slot(slot, 0x9, 0);
    scsp._scsp_write_slot(slot, 0xA, 0);
    scsp._scsp_write_slot(slot, 0xB, rawRegs.dB >> 8);  // DISDL|DIPAN
}

function ensureAudio() {
    if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 44100 });
    if (actx.state === 'suspended') actx.resume();
    if (!fmNode && scspReady) {
        fmNode = actx.createScriptProcessor(2048, 0, 2);
        fmGain = actx.createGain();
        fmGain.gain.value = 0.35; // headroom for multiple simultaneous instruments
        // DAC reconstruction filter — simulates the Saturn's analog output stage.
        // The real hardware has a low-pass filter after the DAC that removes
        // aliasing artifacts from short waveforms played at high pitch.
        const lpf = actx.createBiquadFilter();
        lpf.type = 'lowpass';
        lpf.frequency.value = 16000; // ~16 kHz cutoff (Saturn DAC rolloff)
        lpf.Q.value = 0.707;         // Butterworth (flat passband)

        // Soft limiter to prevent harsh digital clipping
        const compressor = actx.createDynamicsCompressor();
        compressor.threshold.value = -6;
        compressor.knee.value = 12;
        compressor.ratio.value = 8;
        compressor.attack.value = 0.002;
        compressor.release.value = 0.05;

        fmNode.connect(fmGain);
        fmGain.connect(lpf);
        lpf.connect(compressor);
        compressor.connect(actx.destination);
        fmNode.onaudioprocess = function(e) {
            const outL = e.outputBuffer.getChannelData(0);
            const outR = e.outputBuffer.numberOfChannels > 1 ? e.outputBuffer.getChannelData(1) : outL;
            const n = outL.length;
            if (!scspReady) { for (let i = 0; i < n; i++) { outL[i] = 0; outR[i] = 0; } return; }

            // Process playback engine before rendering
            if (playback.playing) playback.processBlock(n);

            const bufPtr = scsp._scsp_render(n);
            const heap16 = new Int16Array(scsp.HEAP16.buffer, bufPtr, n * 2);
            for (let i = 0; i < n; i++) {
                outL[i] = heap16[i * 2]     / 32768.0;
                outR[i] = heap16[i * 2 + 1] / 32768.0;
            }
        };
    }
}

// ═══════════════════════════════════════════════════════════════
// PRESET INSTRUMENTS
// ═══════════════════════════════════════════════════════════════

const PRESET_INSTRUMENTS = [
    { name: 'Electric Piano', operators: [
        { freq_ratio:2.0, freq_fixed:0, level:0.9, ar:31, d1r:12, dl:8, d2r:0, rr:14, mdl:0, mod_source:-1, feedback:0, is_carrier:false, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
        { freq_ratio:1.0, freq_fixed:0, level:0.8, ar:31, d1r:6, dl:2, d2r:0, rr:14, mdl:9, mod_source:0, feedback:0, is_carrier:true, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
    ]},
    { name: 'Bell', operators: [
        { freq_ratio:3.5, freq_fixed:0, level:0.9, ar:31, d1r:4, dl:2, d2r:0, rr:8, mdl:0, mod_source:-1, feedback:0, is_carrier:false, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
        { freq_ratio:1.0, freq_fixed:0, level:0.7, ar:31, d1r:2, dl:0, d2r:0, rr:6, mdl:11, mod_source:0, feedback:0, is_carrier:true, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
    ]},
    { name: 'Brass', operators: [
        { freq_ratio:1.0, freq_fixed:0, level:0.8, ar:24, d1r:4, dl:2, d2r:0, rr:14, mdl:0, mod_source:-1, feedback:0.3, is_carrier:false, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
        { freq_ratio:1.0, freq_fixed:0, level:0.8, ar:22, d1r:2, dl:0, d2r:0, rr:14, mdl:9, mod_source:0, feedback:0, is_carrier:true, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
    ]},
    { name: 'Organ', operators: [
        { freq_ratio:1.0, freq_fixed:0, level:0.7, ar:31, d1r:0, dl:0, d2r:0, rr:20, mdl:0, mod_source:-1, feedback:0.6, is_carrier:false, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
        { freq_ratio:1.0, freq_fixed:0, level:0.8, ar:31, d1r:0, dl:0, d2r:0, rr:20, mdl:8, mod_source:0, feedback:0, is_carrier:true, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
    ]},
    { name: 'FM Bass', operators: [
        { freq_ratio:1.0, freq_fixed:0, level:0.9, ar:31, d1r:14, dl:10, d2r:0, rr:14, mdl:0, mod_source:-1, feedback:0.2, is_carrier:false, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
        { freq_ratio:1.0, freq_fixed:0, level:0.9, ar:31, d1r:6, dl:4, d2r:0, rr:14, mdl:10, mod_source:0, feedback:0, is_carrier:true, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
    ]},
    { name: 'Strings', operators: [
        { freq_ratio:1.002, freq_fixed:0, level:0.5, ar:20, d1r:0, dl:0, d2r:0, rr:16, mdl:0, mod_source:-1, feedback:0, is_carrier:false, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
        { freq_ratio:1.0, freq_fixed:0, level:0.7, ar:18, d1r:0, dl:0, d2r:0, rr:14, mdl:7, mod_source:0, feedback:0, is_carrier:true, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
    ]},
    { name: 'Clavinet', operators: [
        { freq_ratio:3.0, freq_fixed:0, level:0.9, ar:31, d1r:16, dl:14, d2r:0, rr:18, mdl:0, mod_source:-1, feedback:0, is_carrier:false, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
        { freq_ratio:1.0, freq_fixed:0, level:0.8, ar:31, d1r:10, dl:6, d2r:0, rr:16, mdl:10, mod_source:0, feedback:0, is_carrier:true, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
    ]},
    { name: 'Marimba', operators: [
        { freq_ratio:4.0, freq_fixed:0, level:0.8, ar:31, d1r:18, dl:16, d2r:0, rr:20, mdl:0, mod_source:-1, feedback:0, is_carrier:false, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
        { freq_ratio:1.0, freq_fixed:0, level:0.8, ar:31, d1r:8, dl:4, d2r:0, rr:12, mdl:9, mod_source:0, feedback:0, is_carrier:true, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
    ]},
];

// ═══════════════════════════════════════════════════════════════
// TRACKER STATE
// ═══════════════════════════════════════════════════════════════

const state = {
    bpm: 120,
    stepsPerBeat: 4,
    patternLength: 32,
    instruments: JSON.parse(JSON.stringify(PRESET_INSTRUMENTS)),
    patterns: [],
    song: [0],
    cursor: { row: 0, ch: 0, col: 0 }, // col: 0=note, 1=inst, 2=vol
};

function createEmptyPattern(len) {
    const channels = [];
    for (let c = 0; c < NUM_CHANNELS; c++) {
        const rows = [];
        for (let r = 0; r < len; r++) rows.push({ note: null, inst: null, vol: null });
        channels.push({ defaultInst: Math.min(c, state.instruments.length - 1), rows });
    }
    return { length: len, channels };
}

// Initialize with one empty pattern
state.patterns.push(createEmptyPattern(state.patternLength));

// ═══════════════════════════════════════════════════════════════
// VOICE ALLOCATOR
// ═══════════════════════════════════════════════════════════════

const voiceAlloc = {
    // Each active voice: { ch, note, slots: [slot0, slot1, ...], time }
    voices: [],
    time: 0,

    allocate(ch, note, numOps) {
        // Release any existing note on this channel
        this.release(ch);

        // Find numOps consecutive free slots
        const used = new Set();
        for (const v of this.voices) for (const s of v.slots) used.add(s);

        let startSlot = -1;
        for (let s = 0; s <= MAX_SLOTS - numOps; s++) {
            let ok = true;
            for (let j = 0; j < numOps; j++) {
                if (used.has(s + j)) { ok = false; break; }
            }
            if (ok) { startSlot = s; break; }
        }

        // If no space, steal oldest voice
        if (startSlot < 0) {
            if (this.voices.length > 0) {
                this.voices.sort((a, b) => a.time - b.time);
                const stolen = this.voices.shift();
                for (const s of stolen.slots) scsp._scsp_key_off(s);
                startSlot = stolen.slots[0];
            } else {
                startSlot = 0;
            }
        }

        const slots = [];
        for (let j = 0; j < numOps; j++) slots.push(startSlot + j);
        this.voices.push({ ch, note, slots, time: this.time++ });
        return slots;
    },

    release(ch, note) {
        const idx = note !== undefined
            ? this.voices.findIndex(v => v.ch === ch && v.note === note)
            : this.voices.findIndex(v => v.ch === ch);
        if (idx >= 0) {
            const v = this.voices[idx];
            for (const s of v.slots) scsp._scsp_key_off(s);
            this.voices.splice(idx, 1);
        }
    },

    releaseAll() {
        for (const v of this.voices) for (const s of v.slots) scsp._scsp_key_off(s);
        this.voices = [];
    }
};

// ═══════════════════════════════════════════════════════════════
// PLAYBACK ENGINE
// ═══════════════════════════════════════════════════════════════

const playback = {
    playing: false,
    currentRow: 0,
    currentSongSlot: 0,
    samplePos: 0,
    samplesPerStep: 0,

    start() {
        this.playing = true;
        this.currentRow = state.cursor.row;
        this.currentSongSlot = currentSongSlot;
        this.samplePos = 0;
        this.updateTempo();
        document.getElementById('btn-play').classList.add('active');
    },

    stop() {
        this.playing = false;
        voiceAlloc.releaseAll();
        document.getElementById('btn-play').classList.remove('active');
        renderGrid();
        renderSongBar();
    },

    updateTempo() {
        const bpm = state.bpm;
        const spb = state.stepsPerBeat;
        this.samplesPerStep = Math.round(SAMPLE_RATE * 60 / bpm / spb);
    },

    processBlock(numSamples) {
        let remaining = numSamples;
        while (remaining > 0) {
            const untilNext = this.samplesPerStep - this.samplePos;
            if (untilNext <= 0) {
                const pat = state.patterns[state.song[this.currentSongSlot]];
                this.triggerRow(this.currentRow, pat);
                this.currentRow++;
                if (this.currentRow >= pat.length) {
                    this.currentRow = 0;
                    this.currentSongSlot++;
                    if (this.currentSongSlot >= state.song.length) {
                        this.currentSongSlot = 0; // loop song
                    }
                }
                this.samplePos = 0;
                updatePlaybackCursor();
                continue;
            }
            const advance = Math.min(remaining, untilNext);
            this.samplePos += advance;
            remaining -= advance;
        }
    },

    triggerRow(row, pat) {
        for (let ch = 0; ch < NUM_CHANNELS; ch++) {
            const cell = pat.channels[ch].rows[row];
            if (cell.note === -1) {
                voiceAlloc.release(ch);
            } else if (cell.note !== null) {
                const instIdx = cell.inst !== null ? cell.inst : pat.channels[ch].defaultInst;
                triggerNote(ch, cell.note, instIdx);
            }
        }
    }
};

// ═══════════════════════════════════════════════════════════════
// NOTE TRIGGERING (shared by playback + keyboard preview)
// ═══════════════════════════════════════════════════════════════

function triggerNote(ch, midiNote, instIdx) {
    const inst = state.instruments[instIdx];
    if (!inst) return;
    const ops = inst.operators;
    const slots = voiceAlloc.allocate(ch, midiNote, ops.length);
    const slotBase = slots[0];
    for (let i = 0; i < ops.length; i++) {
        const op = ops[i];
        if (op.rawRegs) {
            // Imported from TON — use raw registers for exact Saturn playback
            const wav = waveStore.waves[op.waveform || 0] || waveStore.waves[0];
            programSlotRaw(slots[i], op.rawRegs, midiNote, wav.offset, slotBase, i);
        } else {
            // Built-in preset — use computed programSlot
            programSlot(slots[i], op, midiNote, ops);
        }
    }
    for (const s of slots) scsp._scsp_key_on(s);
}

// ═══════════════════════════════════════════════════════════════
// NOTE NAMES & KEYBOARD MAPPING
// ═══════════════════════════════════════════════════════════════

const NOTE_NAMES = ['C-','C#','D-','D#','E-','F-','F#','G-','G#','A-','A#','B-'];

function noteName(midi) {
    if (midi < 0 || midi > 127) return '???';
    return NOTE_NAMES[midi % 12] + Math.floor(midi / 12);
}

// ProTracker-style keyboard → note offset mapping
const KEY_NOTE_MAP = {
    'z':0, 's':1, 'x':2, 'd':3, 'c':4, 'v':5, 'g':6, 'b':7, 'h':8, 'n':9, 'j':10, 'm':11,
    'q':12,'2':13,'w':14,'3':15,'e':16, 'r':17,'5':18,'t':19,'6':20,'y':21,'7':22,'u':23,
    'i':24,'9':25,'o':26,'0':27,'p':28,
};

function getOctave() { return parseInt(document.getElementById('octave').value) || 4; }

// ═══════════════════════════════════════════════════════════════
// UI: GRID RENDERING
// ═══════════════════════════════════════════════════════════════

function renderChannelHeaders() {
    const el = document.getElementById('ch-headers');
    el.innerHTML = '';
    const pat = getCurrentPattern();
    for (let ch = 0; ch < NUM_CHANNELS; ch++) {
        const div = document.createElement('div');
        div.className = 'ch-hdr';
        div.innerHTML = '<span>CH' + (ch + 1) + '</span>';
        const sel = document.createElement('select');
        state.instruments.forEach((inst, i) => {
            const opt = document.createElement('option');
            opt.value = i; opt.textContent = i.toString(16).toUpperCase().padStart(2, '0') + ':' + inst.name;
            if (i === pat.channels[ch].defaultInst) opt.selected = true;
            sel.appendChild(opt);
        });
        sel.onchange = () => { pat.channels[ch].defaultInst = parseInt(sel.value); };
        div.appendChild(sel);
        el.appendChild(div);
    }
}

function renderGrid() {
    const grid = document.getElementById('grid');
    grid.innerHTML = '';
    const pat = getCurrentPattern();
    const spb = state.stepsPerBeat;

    for (let r = 0; r < pat.length; r++) {
        const row = document.createElement('div');
        row.className = 'row';
        if (r % spb === 0) row.classList.add('beat');
        if (playback.playing && playback.currentRow === r) row.classList.add('playing');
        row.id = 'row-' + r;

        const numDiv = document.createElement('div');
        numDiv.className = 'row-num';
        numDiv.textContent = r.toString(16).toUpperCase().padStart(2, '0');
        numDiv.onclick = ((row) => () => { state.cursor.row = row; state.cursor.ch = 0; renderGrid(); })(r);
        row.appendChild(numDiv);

        for (let ch = 0; ch < NUM_CHANNELS; ch++) {
            const cell = pat.channels[ch].rows[r];
            const cellDiv = document.createElement('div');
            cellDiv.className = 'cell';
            if (state.cursor.row === r && state.cursor.ch === ch) cellDiv.classList.add('cursor');
            if (cell.note !== null) cellDiv.classList.add('has-note');
            cellDiv.dataset.row = r;
            cellDiv.dataset.ch = ch;

            let noteStr = '---';
            let noteClass = 'note';
            if (cell.note === -1) { noteStr = 'OFF'; noteClass = 'note off'; }
            else if (cell.note !== null) { noteStr = noteName(cell.note); }

            const instStr = cell.inst !== null ? cell.inst.toString(16).toUpperCase().padStart(2, '0') : '..';
            const volStr = cell.vol !== null ? cell.vol.toString(16).toUpperCase().padStart(2, '0') : '..';

            cellDiv.innerHTML = '<span class="' + noteClass + '">' + noteStr + '</span>' +
                                '<span class="inst">' + instStr + '</span>' +
                                '<span class="vol">' + volStr + '</span>';

            cellDiv.onclick = () => {
                state.cursor.row = r;
                state.cursor.ch = ch;
                renderGrid();
            };

            row.appendChild(cellDiv);
        }
        grid.appendChild(row);
    }
    updateStatusBar();
}

function updatePlaybackCursor() {
    // Follow playback: switch to the currently-playing song slot
    if (playback.currentSongSlot !== currentSongSlot) {
        currentSongSlot = playback.currentSongSlot;
        renderSongBar();
        renderChannelHeaders();
        renderGrid();
    }

    // Update row highlight
    const rows = document.querySelectorAll('.row.playing');
    rows.forEach(r => r.classList.remove('playing'));
    const cur = document.getElementById('row-' + playback.currentRow);
    if (cur) {
        cur.classList.add('playing');
        cur.scrollIntoView({ block: 'nearest' });
    }

    // Update song slot highlight
    const slots = document.querySelectorAll('.song-slot.playing');
    slots.forEach(s => s.classList.remove('playing'));
    const songSlots = document.getElementById('song-slots').children;
    if (songSlots[playback.currentSongSlot]) {
        songSlots[playback.currentSongSlot].classList.add('playing');
    }
}

function updateStatusBar() {
    document.getElementById('status-pos').textContent = 'Row: ' + state.cursor.row.toString(16).toUpperCase().padStart(2, '0');
    const pat = getCurrentPattern();
    const instIdx = pat.channels[state.cursor.ch].defaultInst;
    document.getElementById('status-inst').textContent = 'Inst: ' + instIdx.toString(16).toUpperCase().padStart(2, '0') + ' ' + (state.instruments[instIdx] || {}).name;
}

function showStatus(msg) {
    document.getElementById('status-msg').textContent = msg;
    setTimeout(() => { document.getElementById('status-msg').textContent = ''; }, 3000);
}

// ═══════════════════════════════════════════════════════════════
// KEYBOARD INPUT
// ═══════════════════════════════════════════════════════════════

document.addEventListener('keydown', async (e) => {
    // Don't handle keys when focused on inputs
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

    const pat = getCurrentPattern();
    const cur = state.cursor;

    // Space = toggle play
    if (e.code === 'Space') {
        e.preventDefault();
        togglePlay();
        return;
    }

    // Navigation
    if (e.key === 'ArrowDown') { e.preventDefault(); cur.row = Math.min(cur.row + 1, pat.length - 1); renderGrid(); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); cur.row = Math.max(cur.row - 1, 0); renderGrid(); return; }
    if (e.key === 'ArrowRight') { e.preventDefault(); cur.ch = Math.min(cur.ch + 1, NUM_CHANNELS - 1); renderGrid(); return; }
    if (e.key === 'ArrowLeft') { e.preventDefault(); cur.ch = Math.max(cur.ch - 1, 0); renderGrid(); return; }
    if (e.key === 'Tab') { e.preventDefault(); cur.ch = (cur.ch + (e.shiftKey ? -1 : 1) + NUM_CHANNELS) % NUM_CHANNELS; renderGrid(); return; }

    // Delete = clear cell
    if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        pat.channels[cur.ch].rows[cur.row] = { note: null, inst: null, vol: null };
        if (e.key === 'Backspace' && cur.row > 0) cur.row--;
        renderGrid();
        return;
    }

    // Note off (period key or backtick)
    if (e.key === '.' || e.key === '`') {
        e.preventDefault();
        pat.channels[cur.ch].rows[cur.row].note = -1;
        pat.channels[cur.ch].rows[cur.row].inst = null;
        cur.row = Math.min(cur.row + 1, pat.length - 1);
        renderGrid();
        return;
    }

    // Note entry
    const noteOffset = KEY_NOTE_MAP[e.key.toLowerCase()];
    if (noteOffset !== undefined) {
        e.preventDefault();
        const midi = getOctave() * 12 + noteOffset;
        if (midi < 0 || midi > 127) return;

        const cell = pat.channels[cur.ch].rows[cur.row];
        cell.note = midi;
        if (cell.inst === null) cell.inst = pat.channels[cur.ch].defaultInst;

        // Preview the note
        await initSCSP();
        ensureAudio();
        if (cell.inst < state.instruments.length) {
            triggerNote(cur.ch, midi, cell.inst);
            setTimeout(() => voiceAlloc.release(cur.ch), 300);
        }

        cur.row = Math.min(cur.row + 1, pat.length - 1);
        renderGrid();
        return;
    }
});

// ═══════════════════════════════════════════════════════════════
// TRANSPORT CONTROLS
// ═══════════════════════════════════════════════════════════════

async function togglePlay() {
    await initSCSP();
    ensureAudio();
    if (playback.playing) {
        playback.stop();
    } else {
        playback.start();
    }
}

function stopPlayback() {
    playback.stop();
}

function updateTempo() {
    state.bpm = parseInt(document.getElementById('bpm').value) || 120;
    state.stepsPerBeat = parseInt(document.getElementById('steps-per-beat').value) || 4;
    playback.updateTempo();
}

function setPatternLength() {
    const newLen = parseInt(document.getElementById('pattern-length').value);
    state.patternLength = newLen;
    const pat = getCurrentPattern();
    // Resize pattern
    while (pat.length < newLen) {
        for (let ch = 0; ch < NUM_CHANNELS; ch++) {
            pat.channels[ch].rows.push({ note: null, inst: null, vol: null });
        }
        pat.length++;
    }
    pat.length = newLen;
    for (let ch = 0; ch < NUM_CHANNELS; ch++) {
        pat.channels[ch].rows.length = newLen;
    }
    if (state.cursor.row >= newLen) state.cursor.row = newLen - 1;
    renderGrid();
}

// ═══════════════════════════════════════════════════════════════
// EXPORT
// ═══════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════
// SONG ARRANGEMENT
// ═══════════════════════════════════════════════════════════════

let currentSongSlot = 0; // which song slot is selected for editing

function getCurrentPatternIndex() { return state.song[currentSongSlot] || 0; }
function getCurrentPattern() { return state.patterns[getCurrentPatternIndex()]; }

function renderSongBar() {
    const el = document.getElementById('song-slots');
    el.innerHTML = '';
    state.song.forEach((patIdx, i) => {
        const slot = document.createElement('div');
        slot.className = 'song-slot' + (i === currentSongSlot ? ' active' : '');
        if (playback.playing && playback.currentSongSlot === i) slot.classList.add('playing');
        slot.textContent = patIdx.toString(16).toUpperCase().padStart(2, '0');
        slot.onclick = () => { currentSongSlot = i; renderAll(); };
        el.appendChild(slot);
    });
    const usedPats = new Set(state.song);
    document.getElementById('pat-info').textContent =
        'Editing pat ' + getCurrentPatternIndex().toString(16).toUpperCase().padStart(2,'0') +
        ' | ' + usedPats.size + ' unique / ' + state.song.length + ' slots';
}

function addSongSlot() {
    state.song.push(getCurrentPatternIndex());
    renderSongBar();
}

function removeSongSlot() {
    if (state.song.length <= 1) return;
    state.song.splice(currentSongSlot, 1);
    if (currentSongSlot >= state.song.length) currentSongSlot = state.song.length - 1;
    renderAll();
}

function newPattern() {
    const idx = state.patterns.length;
    state.patterns.push(createEmptyPattern(state.patternLength));
    // Insert a new song slot after current, pointing to the new pattern
    state.song.splice(currentSongSlot + 1, 0, idx);
    currentSongSlot = currentSongSlot + 1;
    renderAll();
}

function dupPattern() {
    // Duplicate the current song slot (same pattern index, played again)
    const patIdx = getCurrentPatternIndex();
    state.song.splice(currentSongSlot + 1, 0, patIdx);
    currentSongSlot = currentSongSlot + 1;
    renderAll();
}

function renderAll() {
    renderSongBar();
    renderChannelHeaders();
    renderGrid();
    renderInstList();
}

// ═══════════════════════════════════════════════════════════════
// INSTRUMENT PANEL
// ═══════════════════════════════════════════════════════════════

let selectedInst = 0;
let selectedOp = 0;

function toggleInstPanel() {
    const panel = document.getElementById('inst-panel');
    panel.classList.toggle('collapsed');
    const btn = document.getElementById('inst-toggle');
    btn.textContent = panel.classList.contains('collapsed') ? '>>' : 'Instruments \u00ab';
}

function renderInstList() {
    const el = document.getElementById('inst-list');
    el.innerHTML = '';
    state.instruments.forEach((inst, i) => {
        const div = document.createElement('div');
        div.className = 'inst-item' + (i === selectedInst ? ' sel' : '');
        div.innerHTML = '<span><span class="inst-num">' + i.toString(16).toUpperCase().padStart(2, '0') + '</span>' + inst.name + '</span>' +
                        '<span style="color:#555;">' + inst.operators.length + 'op</span>';
        div.onclick = () => { selectedInst = i; selectedOp = 0; renderInstList(); renderInstEditor(); };
        div.ondblclick = () => {
            const name = prompt('Rename instrument:', inst.name);
            if (name) { inst.name = name; renderInstList(); renderChannelHeaders(); }
        };
        el.appendChild(div);
    });
    renderInstEditor();
}

function addInstrument() {
    state.instruments.push({
        name: 'New ' + state.instruments.length,
        operators: [
            { freq_ratio:1.0, freq_fixed:0, level:0.8, ar:31, d1r:0, dl:0, d2r:0, rr:14, mdl:0, mod_source:-1, feedback:0, is_carrier:true, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 },
        ]
    });
    selectedInst = state.instruments.length - 1;
    renderInstList(); renderChannelHeaders();
}

function dupInstrument() {
    const dup = JSON.parse(JSON.stringify(state.instruments[selectedInst]));
    dup.name += ' copy';
    state.instruments.push(dup);
    selectedInst = state.instruments.length - 1;
    renderInstList(); renderChannelHeaders();
}

function delInstrument() {
    if (state.instruments.length <= 1) return;
    state.instruments.splice(selectedInst, 1);
    if (selectedInst >= state.instruments.length) selectedInst = state.instruments.length - 1;
    renderInstList(); renderChannelHeaders();
}

async function importTonInst() {
    if (!TonIO) { showStatus('TonIO not available'); return; }
    await initSCSP();
    const input = document.createElement('input');
    input.type = 'file'; input.accept = '.ton,.TON';
    input.style.display = 'none';
    document.body.appendChild(input);
    input.onchange = (e) => {
        const file = e.target.files[0];
        document.body.removeChild(input);
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
            try {
                resetSCSP(); // Clear old waveforms before adding new ones
                const result = TonIO.importTon(ev.target.result);
                const ramPtr = scsp._scsp_get_ram_ptr();
                for (const p of result.patches) {
                    state.instruments.push({
                        name: p.name || 'TON ' + state.instruments.length,
                        operators: p.operators.map(o => {
                            let waveId = 0;
                            if (o.pcm && o.pcm.length > 0) {
                                waveId = waveStoreAdd(ramPtr, o.pcm, 0, o.pcm.length, o.loop_mode || 1);
                            }
                            return {
                                freq_ratio: o.freq_ratio || 1, freq_fixed: 0,
                                level: o.level !== undefined ? o.level : 0.8,
                                ar: o.ar !== undefined ? o.ar : 31, d1r: o.d1r || 0, dl: o.dl || 0,
                                d2r: o.d2r || 0, rr: o.rr !== undefined ? o.rr : 14,
                                mdl: o.mdl || 0, mod_source: o.mod_source !== undefined ? o.mod_source : -1,
                                feedback: o.feedback || 0, is_carrier: o.is_carrier !== undefined ? o.is_carrier : true,
                                waveform: waveId, loop_mode: o.loop_mode !== undefined ? o.loop_mode : 1,
                                loop_start: o.loop_start || 0, loop_end: o.pcm ? o.pcm.length : (o.loop_end || 1024),
                            };
                        })
                    });
                }
                showStatus('Imported ' + result.patches.length + ' instruments from TON');
                renderInstList(); renderChannelHeaders();
            } catch (err) { showStatus('TON error: ' + err.message); }
        };
        reader.readAsArrayBuffer(file);
    };
    input.click();
}

function renderInstEditor() {
    const el = document.getElementById('inst-editor');
    el.innerHTML = '';
    const inst = state.instruments[selectedInst];
    if (!inst) return;

    // Operator tabs
    const tabBar = document.createElement('div');
    tabBar.style.marginBottom = '4px';
    for (let i = 0; i < inst.operators.length; i++) {
        const tab = document.createElement('span');
        tab.className = 'op-tab' + (i === selectedOp ? ' sel' : '') + (inst.operators[i].is_carrier ? ' carrier' : '');
        tab.textContent = 'Op' + (i + 1);
        tab.onclick = () => { selectedOp = i; renderInstEditor(); };
        tabBar.appendChild(tab);
    }
    // Add/remove op buttons
    const addOp = document.createElement('span');
    addOp.className = 'op-tab'; addOp.textContent = '+';
    addOp.onclick = () => {
        if (inst.operators.length >= 6) return;
        inst.operators.push({ freq_ratio:1.0, freq_fixed:0, level:0.8, ar:31, d1r:0, dl:0, d2r:0, rr:14, mdl:0, mod_source:-1, feedback:0, is_carrier:true, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 });
        selectedOp = inst.operators.length - 1;
        renderInstEditor();
    };
    tabBar.appendChild(addOp);
    if (inst.operators.length > 1) {
        const rmOp = document.createElement('span');
        rmOp.className = 'op-tab'; rmOp.textContent = '-';
        rmOp.onclick = () => {
            inst.operators.splice(selectedOp, 1);
            if (selectedOp >= inst.operators.length) selectedOp = inst.operators.length - 1;
            renderInstEditor();
        };
        tabBar.appendChild(rmOp);
    }
    el.appendChild(tabBar);

    const op = inst.operators[selectedOp];
    if (!op) return;

    // Parameter controls
    const params = [
        { key:'freq_ratio', label:'Ratio', min:0.5, max:16, step:0.001, fmt: v => v.toFixed(3) },
        { key:'level', label:'Level', min:0, max:1, step:0.01, fmt: v => v.toFixed(2) },
        { key:'ar', label:'AR', min:0, max:31, step:1, fmt: v => Math.round(v) },
        { key:'d1r', label:'D1R', min:0, max:31, step:1, fmt: v => Math.round(v) },
        { key:'dl', label:'DL', min:0, max:31, step:1, fmt: v => Math.round(v) },
        { key:'d2r', label:'D2R', min:0, max:31, step:1, fmt: v => Math.round(v) },
        { key:'rr', label:'RR', min:0, max:31, step:1, fmt: v => Math.round(v) },
        { key:'feedback', label:'FB', min:0, max:0.5, step:0.01, fmt: v => v.toFixed(2) },
        { key:'mdl', label:'MDL', min:0, max:15, step:1, fmt: v => Math.round(v) },
    ];

    for (const p of params) {
        const row = document.createElement('div'); row.className = 'op-param';
        const lbl = document.createElement('label'); lbl.textContent = p.label;
        const inp = document.createElement('input'); inp.type = 'range';
        inp.min = p.min; inp.max = p.max; inp.step = p.step; inp.value = op[p.key] || 0;
        const val = document.createElement('span'); val.className = 'val'; val.textContent = p.fmt(op[p.key] || 0);
        inp.oninput = () => { op[p.key] = parseFloat(inp.value); val.textContent = p.fmt(op[p.key]); };
        row.appendChild(lbl); row.appendChild(inp); row.appendChild(val);
        el.appendChild(row);
    }

    // Mod source dropdown
    const msRow = document.createElement('div'); msRow.className = 'op-param';
    const msLbl = document.createElement('label'); msLbl.textContent = 'Mod';
    const msSel = document.createElement('select');
    const msNone = document.createElement('option'); msNone.value = -1; msNone.textContent = 'None'; msSel.appendChild(msNone);
    for (let i = 0; i < inst.operators.length; i++) {
        if (i === selectedOp) continue;
        const o = document.createElement('option'); o.value = i; o.textContent = 'Op' + (i + 1); msSel.appendChild(o);
    }
    msSel.value = op.mod_source;
    msSel.onchange = () => { op.mod_source = parseInt(msSel.value); };
    msRow.appendChild(msLbl); msRow.appendChild(msSel); el.appendChild(msRow);

    // Waveform dropdown
    const wvRow = document.createElement('div'); wvRow.className = 'op-param';
    const wvLbl = document.createElement('label'); wvLbl.textContent = 'Wave';
    const wvSel = document.createElement('select');
    WAVE_NAMES.forEach((name, i) => {
        const o = document.createElement('option'); o.value = i; o.textContent = name; wvSel.appendChild(o);
    });
    wvSel.value = op.waveform || 0;
    wvSel.onchange = () => { op.waveform = parseInt(wvSel.value); };
    wvRow.appendChild(wvLbl); wvRow.appendChild(wvSel); el.appendChild(wvRow);

    // Carrier toggle
    const cRow = document.createElement('div'); cRow.className = 'op-param';
    const cLbl = document.createElement('label'); cLbl.textContent = 'Carrier';
    const cChk = document.createElement('input'); cChk.type = 'checkbox'; cChk.checked = op.is_carrier;
    cChk.onchange = () => { op.is_carrier = cChk.checked; renderInstEditor(); };
    cRow.appendChild(cLbl); cRow.appendChild(cChk); el.appendChild(cRow);

    // Test button
    const testRow = document.createElement('div'); testRow.style.marginTop = '8px';
    const testBtn = document.createElement('button');
    testBtn.textContent = 'Test (C-4)';
    testBtn.style.cssText = 'background:#2a4a2e;color:#8c8;border:1px solid #4a4;padding:4px 12px;cursor:pointer;border-radius:3px;font-family:inherit;font-size:10px;';
    testBtn.onclick = async () => {
        await initSCSP(); ensureAudio();
        triggerNote(99, 60, selectedInst); // channel 99 = preview
        setTimeout(() => voiceAlloc.release(99), 500);
    };
    testRow.appendChild(testBtn);
    el.appendChild(testRow);
}

// ═══════════════════════════════════════════════════════════════
// MIDI IMPORT
// ═══════════════════════════════════════════════════════════════

function parseMIDI(buf) {
    const d = new DataView(buf);
    const u8 = new Uint8Array(buf);
    let pos = 0;

    function read32() { const v = d.getUint32(pos); pos += 4; return v; }
    function read16() { const v = d.getUint16(pos); pos += 2; return v; }
    function read8() { return u8[pos++]; }
    function readVarLen() {
        let v = 0;
        for (let i = 0; i < 4; i++) {
            const b = read8();
            v = (v << 7) | (b & 0x7F);
            if (!(b & 0x80)) break;
        }
        return v;
    }
    function readStr(n) { let s = ''; for (let i = 0; i < n; i++) s += String.fromCharCode(read8()); return s; }

    // MThd
    const hdId = readStr(4);
    if (hdId !== 'MThd') throw new Error('Not a MIDI file');
    const hdLen = read32();
    const format = read16();
    const nTracks = read16();
    const division = read16();

    // Parse all tracks
    const allEvents = []; // { absTime, ch, type, note, vel }

    for (let t = 0; t < nTracks; t++) {
        const trkId = readStr(4);
        const trkLen = read32();
        if (trkId !== 'MTrk') { pos += trkLen; continue; }

        const trkEnd = pos + trkLen;
        let absTime = 0;
        let runningStatus = 0;

        while (pos < trkEnd) {
            const delta = readVarLen();
            absTime += delta;

            let status = u8[pos];
            if (status & 0x80) {
                pos++;
                if (status < 0xF0) runningStatus = status;
            } else {
                status = runningStatus;
            }

            const type = status & 0xF0;
            const ch = status & 0x0F;

            if (type === 0x90) { // note on
                const note = read8();
                const vel = read8();
                allEvents.push({ absTime, ch, type: vel > 0 ? 'on' : 'off', note, vel });
            } else if (type === 0x80) { // note off
                const note = read8();
                read8(); // vel
                allEvents.push({ absTime, ch, type: 'off', note, vel: 0 });
            } else if (type === 0xC0) { // program change
                const prog = read8();
                allEvents.push({ absTime, ch, type: 'pc', prog });
            } else if (type === 0xB0) { // CC
                read8(); read8(); // controller, value
            } else if (type === 0xE0) { // pitch bend
                read8(); read8();
            } else if (type === 0xD0) { // channel pressure
                read8();
            } else if (type === 0xA0) { // poly pressure
                read8(); read8();
            } else if (status === 0xFF) { // meta event
                const metaType = read8();
                const metaLen = readVarLen();
                if (metaType === 0x51 && metaLen === 3) { // tempo
                    const uspb = (read8() << 16) | (read8() << 8) | read8();
                    allEvents.push({ absTime, type: 'tempo', bpm: Math.round(60000000 / uspb) });
                } else {
                    pos += metaLen;
                }
            } else if (status === 0xF0 || status === 0xF7) { // sysex
                const sxLen = readVarLen();
                pos += sxLen;
            }
        }
        pos = trkEnd;
    }

    return { format, division, events: allEvents };
}

function importMIDI() {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = '.mid,.midi,.MID,.MIDI';
    input.style.display = 'none';
    document.body.appendChild(input);
    input.onchange = (e) => {
        const file = e.target.files[0];
        document.body.removeChild(input);
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
            try {
                const midi = parseMIDI(ev.target.result);
                midiToPatterns(midi);
                showStatus('Imported MIDI: ' + file.name);
            } catch (err) {
                showStatus('MIDI error: ' + err.message);
            }
        };
        reader.readAsArrayBuffer(file);
    };
    input.click();
}

async function importTonForTracker() {
    if (!TonIO) { showStatus('TonIO not available'); return; }
    await initSCSP();
    const input = document.createElement('input');
    input.type = 'file'; input.accept = '.ton,.TON';
    input.style.display = 'none';
    document.body.appendChild(input);
    input.onchange = (e) => {
        const file = e.target.files[0];
        document.body.removeChild(input);
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
            try {
                resetSCSP(); // Clear all old waveforms and SCSP state
                const result = TonIO.importTon(ev.target.result);
                const ramPtr = scsp._scsp_get_ram_ptr();
                state.instruments = result.patches.map((p, i) => ({
                    name: p.name || ('Voice ' + i),
                    operators: p.operators.map(o => {
                        let waveId = 0;
                        if (o.pcm && o.pcm.length > 0) {
                            waveId = waveStoreAdd(ramPtr, o.pcm, 0, o.pcm.length, o.loop_mode || 1);
                        }
                        return {
                            freq_ratio: o.freq_ratio || 1, freq_fixed: 0,
                            level: o.level !== undefined ? o.level : 0.8,
                            ar: o.ar !== undefined ? o.ar : 31, d1r: o.d1r || 0, dl: o.dl || 0,
                            d2r: o.d2r || 0, rr: o.rr !== undefined ? o.rr : 14,
                            mdl: o.mdl || 0, mod_source: o.mod_source !== undefined ? o.mod_source : -1,
                            feedback: o.feedback || 0, is_carrier: o.is_carrier !== undefined ? o.is_carrier : true,
                            waveform: waveId, loop_mode: o.loop_mode !== undefined ? o.loop_mode : 1,
                            loop_start: o.loop_start || 0, loop_end: o.pcm ? o.pcm.length : (o.loop_end || 1024),
                        };
                    })
                }));
                showStatus('Loaded ' + state.instruments.length + ' instruments from ' + file.name);
                renderAll();
            } catch (err) { showStatus('TON error: ' + err.message); }
        };
        reader.readAsArrayBuffer(file);
    };
    input.click();
}

function midiToPatterns(midi) {
    const division = midi.division; // ticks per beat
    const spb = state.stepsPerBeat;
    const ticksPerStep = division / spb;

    // Get tempo from first tempo event, or default 120
    const tempoEv = midi.events.find(e => e.type === 'tempo');
    if (tempoEv) {
        state.bpm = tempoEv.bpm;
        document.getElementById('bpm').value = state.bpm;
    }

    // Collect note-on events, sorted by time
    const noteOns = midi.events.filter(e => e.type === 'on').sort((a, b) => a.absTime - b.absTime);
    if (noteOns.length === 0) { showStatus('No notes in MIDI'); return; }

    // Find total length in steps
    const lastTime = Math.max(...noteOns.map(e => e.absTime));
    const totalSteps = Math.ceil(lastTime / ticksPerStep) + 1;

    // Split into patterns of patternLength
    const patLen = state.patternLength;
    const numPatterns = Math.max(1, Math.ceil(totalSteps / patLen));

    // Find which MIDI channels are used, map to tracker channels (max NUM_CHANNELS)
    const usedChannels = [...new Set(noteOns.map(e => e.ch))].sort((a, b) => a - b);
    const chMap = {}; // MIDI channel → tracker channel
    usedChannels.forEach((midiCh, i) => {
        if (i < NUM_CHANNELS) chMap[midiCh] = i;
    });

    // Create patterns
    state.patterns = [];
    state.song = [];
    for (let p = 0; p < numPatterns; p++) {
        state.patterns.push(createEmptyPattern(patLen));
        state.song.push(p);
    }

    // Place notes
    for (const ev of noteOns) {
        const trackerCh = chMap[ev.ch];
        if (trackerCh === undefined) continue;

        const globalStep = Math.round(ev.absTime / ticksPerStep);
        const patIdx = Math.floor(globalStep / patLen);
        const row = globalStep % patLen;

        if (patIdx >= state.patterns.length) continue;
        const cell = state.patterns[patIdx].channels[trackerCh].rows[row];
        cell.note = ev.note;
        cell.vol = ev.vel;
    }

    // Handle program changes — map to channel default instruments
    const pcEvents = midi.events.filter(e => e.type === 'pc');
    for (const ev of pcEvents) {
        const trackerCh = chMap[ev.ch];
        if (trackerCh === undefined) continue;
        // Set default instrument for this channel across all patterns
        for (const pat of state.patterns) {
            if (ev.prog < state.instruments.length) {
                pat.channels[trackerCh].defaultInst = ev.prog;
            }
        }
    }

    currentSongSlot = 0;
    state.cursor.row = 0;
    state.cursor.ch = 0;
    updateTempo();
    renderAll();
}

// ═══════════════════════════════════════════════════════════════
// EXPORT
// ═══════════════════════════════════════════════════════════════

function exportTON() {
    if (!TonIO) { showStatus('TonIO not available'); return; }
    const tonData = TonIO.exportTon(state.instruments, generateWaveform);
    const blob = new Blob([tonData], { type: 'application/octet-stream' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'tracker.ton';
    a.click();
    URL.revokeObjectURL(a.href);
    showStatus('Exported TON (' + state.instruments.length + ' instruments)');
}

function exportSEQ() {
    const seqData = buildSEQ();
    if (!seqData) return;
    const blob = new Blob([seqData], { type: 'application/octet-stream' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'tracker.seq';
    a.click();
    URL.revokeObjectURL(a.href);
    showStatus('Exported SEQ (' + seqData.length + ' bytes)');
}

function buildSEQ() {
    const resolution = 480; // ticks per quarter note (standard MIDI resolution)
    const ticksPerStep = resolution / state.stepsPerBeat;
    const mspb = Math.round(60000000 / state.bpm); // microseconds per beat

    // Flatten song → linear event list
    // Each event: { absTick, status, data1, data2, gateTicks }
    const events = [];
    let stepOffset = 0;

    // Collect program changes (one per channel, based on first pattern's defaultInst)
    const channelInst = {};
    for (const patIdx of state.song) {
        const pat = state.patterns[patIdx];
        for (let ch = 0; ch < NUM_CHANNELS; ch++) {
            if (!(ch in channelInst)) channelInst[ch] = pat.channels[ch].defaultInst;
        }
    }

    // Add program change events at time 0
    for (const [ch, inst] of Object.entries(channelInst)) {
        events.push({
            absTick: 0,
            status: 0xC0 | parseInt(ch),
            data1: inst,
            data2: 0,
            gateTicks: 0,
        });
    }

    // Add note events from all patterns in song order
    for (const patIdx of state.song) {
        const pat = state.patterns[patIdx];
        for (let row = 0; row < pat.length; row++) {
            for (let ch = 0; ch < NUM_CHANNELS; ch++) {
                const cell = pat.channels[ch].rows[row];
                if (cell.note !== null && cell.note >= 0) {
                    const absTick = Math.round((stepOffset + row) * ticksPerStep);

                    // Compute gate time: steps until next note on same channel, or pattern end
                    let gateSteps = pat.length - row; // default: rest of pattern
                    for (let r = row + 1; r < pat.length; r++) {
                        const next = pat.channels[ch].rows[r];
                        if (next.note !== null) { gateSteps = r - row; break; }
                    }
                    const gateTicks = Math.round(gateSteps * ticksPerStep);

                    events.push({
                        absTick: absTick,
                        status: 0x90 | ch,
                        data1: cell.note,
                        data2: cell.vol !== null ? cell.vol : 100,
                        gateTicks: gateTicks,
                    });
                }
            }
        }
        stepOffset += pat.length;
    }

    // Sort: by time, then note-offs before note-ons at same time
    events.sort((a, b) => {
        if (a.absTick !== b.absTick) return a.absTick - b.absTick;
        const aIsNoteOn = (a.status & 0xF0) === 0x90;
        const bIsNoteOn = (b.status & 0xF0) === 0x90;
        if (!aIsNoteOn && bIsNoteOn) return -1;
        if (aIsNoteOn && !bIsNoteOn) return 1;
        return 0;
    });

    // Find first musical event time and total time
    let firstMusicalTick = 0;
    for (const ev of events) {
        if ((ev.status & 0xF0) === 0x90) { firstMusicalTick = ev.absTick; break; }
    }
    const totalTicks = Math.round(stepOffset * ticksPerStep);

    // Build binary
    const buf = [];
    function w8(v) { buf.push(v & 0xFF); }
    function w16(v) { buf.push((v >> 8) & 0xFF, v & 0xFF); }
    function w32(v) { buf.push((v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF); }

    // Bank header
    w16(1);       // num_songs = 1
    w32(6);       // song pointer at offset 6

    // SEQ header
    const tempoCount = 2;
    const dataOffset = 8 + tempoCount * 8;
    w16(resolution);
    w16(tempoCount);
    w16(dataOffset);
    w16(8 + 8); // tempo loop offset → 2nd tempo event

    // Tempo events (2-event convention from mid2seq.c)
    w32(firstMusicalTick);                  // event 0: time until first note
    w32(mspb);
    w32(totalTicks - firstMusicalTick);     // event 1: rest of song
    w32(mspb);

    // Bank select CC#32 = 1 on all 16 channels
    for (let ch = 0; ch < 16; ch++) {
        w8(0xB0 | ch); w8(0x20); w8(1); w8(0x00);
    }

    // Event stream
    let lastTick = 0;
    for (const ev of events) {
        let delta = ev.absTick - lastTick;
        lastTick = ev.absTick;
        const evType = ev.status & 0xF0;

        // Write step extend events for large deltas
        while (delta >= 0x1000) { w8(0x8F); delta -= 0x1000; }
        while (delta >= 0x800)  { w8(0x8E); delta -= 0x800; }
        while (delta >= 0x200)  { w8(0x8D); delta -= 0x200; }

        if (evType === 0x90) {
            // Note-on: gate extend + control byte + note + vel + gate + delta
            let gate = ev.gateTicks;
            while (gate >= 0x2000) { w8(0x8B); gate -= 0x2000; }
            while (gate >= 0x1000) { w8(0x8A); gate -= 0x1000; }
            while (gate >= 0x800)  { w8(0x89); gate -= 0x800; }
            while (gate >= 0x200)  { w8(0x88); gate -= 0x200; }

            let ctl = ev.status & 0x0F;
            if (delta >= 256) { ctl |= 0x20; delta -= 256; }
            if (gate >= 256)  { ctl |= 0x40; gate -= 256; }

            w8(ctl);
            w8(ev.data1);       // note
            w8(ev.data2);       // velocity
            w8(gate & 0xFF);    // gate low byte
            w8(delta & 0xFF);   // delta low byte
        } else {
            // Non-note events: 0x8C extend + status + data + delta
            while (delta >= 256) { w8(0x8C); delta -= 256; }
            w8(ev.status);
            if (evType === 0xB0 || evType === 0xA0) {
                w8(ev.data1); w8(ev.data2);
            } else if (evType === 0xE0) {
                w8(ev.data2); // pitch bend MSB
            } else {
                w8(ev.data1); // program change, channel pressure
            }
            w8(delta & 0xFF);
        }
    }

    w8(0x83); // end of track
    return new Uint8Array(buf);
}

// ═══════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════

renderAll();
updateTempo();

</script>
</body>
</html>"""


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Saturn SCSP Tracker')
    parser.add_argument('-o', '--output', help='Output HTML file')
    parser.add_argument('--no-open', action='store_true', help='Do not open in browser')
    args = parser.parse_args()

    html = generate_html()

    if args.output:
        out_path = args.output
    else:
        fd, out_path = tempfile.mkstemp(suffix='.html', prefix='saturn_tracker_')
        os.close(fd)

    with open(out_path, 'w') as f:
        f.write(html)

    print(f"[tracker] Generated: {out_path}")

    if not args.no_open:
        url = 'file://' + os.path.abspath(out_path)
        print(f"  Opening: {url}")
        webbrowser.open(url)


if __name__ == '__main__':
    main()
