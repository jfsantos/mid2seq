#!/usr/bin/env python3
"""
fm_editor.py — Saturn SCSP FM Patch Editor.

Generates a self-contained HTML file with an interactive FM patch editor,
real-time synthesis via Web Audio AudioWorklet, and full SCSP envelope
emulation with hardware-accurate rate tables.

Usage:
  python3 fm_editor.py                    → opens editor in browser
  python3 fm_editor.py --load bank.json   → opens with existing patches
  python3 fm_editor.py -o editor.html     → save HTML without opening
"""

import json
import os
import sys
import webbrowser
import tempfile
import base64


def generate_html(presets_json="null"):
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
        print("[fm_editor] WARNING: SCSP WASM not found. Run 'make' in tools/scsp_wasm/")
        print("            Falling back to no audio.")
        wasm_b64 = ""
        glue_js = "var SCSPModule = () => Promise.resolve(null);"

    # Load ton_io.js for TON import/export
    ton_io_path = os.path.join(os.path.dirname(__file__), 'ton_io.js')
    if os.path.exists(ton_io_path):
        with open(ton_io_path, 'r') as f:
            ton_io_js = f.read()
    else:
        print("[fm_editor] WARNING: ton_io.js not found. TON import/export disabled.")
        ton_io_js = "var TonIO = null;"

    # Inject WASM data into the HTML template via placeholder replacement
    html = _HTML_TEMPLATE.replace('__SCSP_WASM_B64__', wasm_b64)
    html = html.replace('__SCSP_GLUE_JS__', glue_js)
    html = html.replace('__TON_IO_JS__', ton_io_js)
    return html


_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Saturn SCSP FM Patch Editor</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'SF Mono', Consolas, Monaco, monospace; background: #0f0f23; color: #ccc; display: flex; height: 100vh; overflow: hidden; }

/* ── Sidebar ── */
#sidebar { width: 200px; background: #1a1a2e; border-right: 1px solid #333; display: flex; flex-direction: column; flex-shrink: 0; }
#sidebar h2 { color: #00d4ff; font-size: 13px; padding: 10px 10px 6px; }
#patch-list { flex: 1; overflow-y: auto; padding: 0 6px; }
.patch-item { padding: 5px 8px; cursor: pointer; border-radius: 4px; font-size: 12px; color: #aaa; display: flex; justify-content: space-between; align-items: center; }
.patch-item:hover { background: #2a2a4e; }
.patch-item.sel { background: #2a3a5e; color: #fff; }
.patch-item .del-btn { color: #666; font-size: 14px; padding: 0 4px; cursor: pointer; display: none; }
.patch-item:hover .del-btn { display: inline; }
.patch-item .del-btn:hover { color: #f44; }
#patch-btns { padding: 6px; display: flex; gap: 4px; }
#patch-btns button { flex: 1; background: #2a2a4e; color: #ccc; border: 1px solid #444; padding: 4px; cursor: pointer; border-radius: 4px; font-size: 11px; font-family: inherit; }
#patch-btns button:hover { background: #3a3a5e; }

/* ── Main area ── */
#main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

/* ── Toolbar ── */
#toolbar { display: flex; align-items: center; padding: 6px 12px; gap: 8px; border-bottom: 1px solid #333; background: #161628; }
#toolbar h1 { font-size: 14px; color: #00d4ff; flex: 1; }
#toolbar button { background: #2a2a4e; color: #ccc; border: 1px solid #444; padding: 4px 12px; cursor: pointer; border-radius: 4px; font-size: 11px; font-family: inherit; }
#toolbar button:hover { background: #3a3a5e; }

/* ── Content scroll area ── */
#content { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 12px; }

/* ── Operator graph ── */
#op-graph { background: #1a1a2e; border: 1px solid #333; border-radius: 8px; padding: 12px; min-height: 120px; position: relative; }
#op-graph h3 { font-size: 12px; color: #888; margin-bottom: 8px; }
#op-boxes { display: flex; gap: 12px; align-items: flex-start; flex-wrap: wrap; }
.op-box { background: #222244; border: 2px solid #444; border-radius: 6px; padding: 8px 12px; cursor: pointer; min-width: 100px; text-align: center; font-size: 11px; user-select: none; transition: border-color 0.15s; }
.op-box:hover { border-color: #666; }
.op-box.sel { border-color: #00d4ff; }
.op-box.carrier { border-color: #4a4; }
.op-box.carrier.sel { border-color: #0f0; }
.op-box .op-name { font-weight: bold; color: #ddd; font-size: 12px; }
.op-box .op-role { font-size: 10px; margin-top: 2px; }
.op-box .op-role.car { color: #4a4; }
.op-box .op-role.mod { color: #a84; }
.op-box .op-detail { color: #888; font-size: 10px; margin-top: 3px; }
#op-btns { margin-top: 8px; display: flex; gap: 4px; }
#op-btns button { background: #2a2a4e; color: #ccc; border: 1px solid #444; padding: 3px 10px; cursor: pointer; border-radius: 4px; font-size: 11px; font-family: inherit; }
#op-btns button:hover { background: #3a3a5e; }

/* ── Operator params ── */
#op-params { background: #1a1a2e; border: 1px solid #333; border-radius: 8px; padding: 12px; }
#op-params h3 { font-size: 12px; color: #888; margin-bottom: 8px; }
#op-params .row { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-bottom: 8px; }
#op-params .param { display: flex; flex-direction: column; gap: 2px; }
#op-params label { font-size: 10px; color: #888; }
#op-params input[type="range"] { width: 120px; accent-color: #00d4ff; }
#op-params input[type="number"] { width: 60px; background: #222; color: #ccc; border: 1px solid #444; padding: 2px 4px; font-size: 11px; font-family: inherit; border-radius: 3px; }
#op-params select { background: #222; color: #ccc; border: 1px solid #444; padding: 2px 4px; font-size: 11px; font-family: inherit; border-radius: 3px; }
#op-params .val { font-size: 10px; color: #00d4ff; min-width: 30px; text-align: right; }
.param-group { border-left: 2px solid #333; padding-left: 10px; }
.param-group-title { font-size: 10px; color: #666; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }
.carrier-toggle { display: flex; align-items: center; gap: 6px; }
.carrier-toggle input { accent-color: #4a4; }

/* ── Envelope viz ── */
#env-section { background: #1a1a2e; border: 1px solid #333; border-radius: 8px; padding: 12px; }
#env-section h3 { font-size: 12px; color: #888; margin-bottom: 8px; }
#env-canvas { width: 100%; height: 120px; display: block; border-radius: 4px; background: #12122a; }

/* ── Keyboard ── */
#kb-section { background: #1a1a2e; border: 1px solid #333; border-radius: 8px; padding: 12px; }
#kb-section h3 { font-size: 12px; color: #888; margin-bottom: 8px; }
#kb { display: flex; position: relative; height: 80px; }
.wk { background: #ddd; color: #333; width: 34px; height: 72px; border: 1px solid #999; cursor: pointer;
       display: flex; align-items: flex-end; justify-content: center; padding-bottom: 3px;
       font-size: 9px; border-radius: 0 0 3px 3px; user-select: none; z-index: 1; }
.wk:hover,.wk.act { background: #00d4ff; color: #000; }
.bk { background: #222; color: #999; width: 22px; height: 46px; border: 1px solid #555; cursor: pointer;
       display: flex; align-items: flex-end; justify-content: center; padding-bottom: 2px;
       font-size: 8px; border-radius: 0 0 3px 3px; user-select: none; z-index: 2;
       margin-left: -12px; margin-right: -12px; }
.bk:hover,.bk.act { background: #0088aa; color: #fff; }
#oct-ctl { margin-top: 6px; font-size: 11px; color: #888; display: flex; align-items: center; gap: 6px; }
#oct-ctl button { background: #2a2a4e; color: #ccc; border: 1px solid #555; padding: 3px 10px;
                   cursor: pointer; border-radius: 4px; font-family: inherit; font-size: 11px; }
#no-op-msg { color: #666; font-style: italic; padding: 20px; text-align: center; }
</style>
</head>
<body>

<div id="sidebar">
  <h2>Patches</h2>
  <div id="patch-list"></div>
  <div id="patch-btns">
    <button onclick="addPatch()">+ New</button>
    <button onclick="dupPatch()">Dup</button>
  </div>
</div>

<div id="main">
  <div id="toolbar">
    <h1>Saturn SCSP FM Patch Editor</h1>
    <button onclick="loadFile()">Load</button>
    <button onclick="exportFile()">Export JSON</button>
    <button onclick="exportTonFile()">Export TON</button>
    <button onclick="loadTonFile()">Load TON</button>
    <button onclick="mergeToKitFile()">Merge to Kit</button>
    <button onclick="exportWav()">Export WAV</button>
  </div>

  <div id="content">
    <!-- Operator Graph -->
    <div id="op-graph">
      <h3>Operators <span id="alg-label" style="color:#666; font-weight:normal;"></span></h3>
      <svg id="op-svg" style="position:absolute; top:0; left:0; width:100%; height:100%; pointer-events:none; z-index:0;"></svg>
      <div id="op-boxes"></div>
      <div id="op-btns">
        <button onclick="addOp()">+ Add Op</button>
        <button onclick="removeOp()">- Remove Op</button>
        <button onclick="showAlgMenu(event)">Algorithms</button>
      </div>
    </div>

    <!-- Operator Parameters -->
    <div id="op-params">
      <h3>Operator Parameters</h3>
      <div id="op-params-body"><div id="no-op-msg">Select an operator above to edit its parameters.</div></div>
    </div>

    <!-- Envelope Visualization -->
    <div id="env-section">
      <h3>Envelope <span id="env-time-label" style="color:#555; font-weight:normal; font-size:10px;"></span></h3>
      <canvas id="env-canvas"></canvas>
    </div>

    <!-- Piano Keyboard -->
    <div id="kb-section">
      <h3>Play (click keys or use A-K, Z/X = octave)</h3>
      <div id="kb"></div>
      <div id="oct-ctl">
        Octave: <button id="oct-dn">&laquo;</button>
        <span id="oct-val">4</span>
        <button id="oct-up">&raquo;</button>
      </div>
    </div>
  </div>
</div>

<!-- Algorithm context menu -->
<div id="alg-menu" style="display:none; position:fixed; background:#222; border:1px solid #555; border-radius:4px; padding:4px; z-index:100; max-height:300px; overflow-y:auto;">
</div>

<script>
// ═══════════════════════════════════════════════════════════════
// TON I/O MODULE (embedded from ton_io.js)
// ═══════════════════════════════════════════════════════════════
__TON_IO_JS__
</script>
<script>
// ═══════════════════════════════════════════════════════════════
// SCSP RATE TABLES (from MAME YMF292 documentation)
// ═══════════════════════════════════════════════════════════════

const AR_TIMES = [
  100000, 100000, 8100, 6900, 6000, 4800, 4000, 3400,
  3000, 2400, 2000, 1700, 1500, 1200, 1000, 860,
  760, 600, 500, 430, 380, 300, 250, 220,
  190, 150, 130, 110, 95, 76, 63, 55
];

const DR_TIMES = [
  100000, 100000, 118200, 101300, 88600, 70900, 59100, 50700,
  44300, 35500, 29600, 25300, 22200, 17700, 14800, 12700,
  11100, 8900, 7400, 6300, 5500, 4400, 3700, 3200,
  2800, 2200, 1800, 1600, 1400, 1100, 920, 790
];

const SAMPLE_RATE = 44100;
const TABLE_SIZE = 1024;

// ═══════════════════════════════════════════════════════════════
// PRESET PATCHES (from fm_sim.py)
// ═══════════════════════════════════════════════════════════════

const PRESETS = {
  'Electric Piano': {
    operators: [
      { freq_ratio: 2.0, freq_fixed: 0, level: 0.9, ar: 31, d1r: 12, dl: 8, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 6, dl: 2, d2r: 0, rr: 14, mdl: 9, mod_source: 0, feedback: 0.0, is_carrier: true },
    ]
  },
  'Electric Piano 2': {
    operators: [
      { freq_ratio: 14.0, freq_fixed: 0, level: 0.4, ar: 31, d1r: 14, dl: 12, d2r: 0, rr: 16, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.7, ar: 31, d1r: 10, dl: 6, d2r: 0, rr: 14, mdl: 8, mod_source: 0, feedback: 0.0, is_carrier: false },
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 4, dl: 2, d2r: 0, rr: 12, mdl: 9, mod_source: 1, feedback: 0.0, is_carrier: true },
    ]
  },
  'Bell': {
    operators: [
      { freq_ratio: 3.5, freq_fixed: 0, level: 0.9, ar: 31, d1r: 4, dl: 2, d2r: 0, rr: 8, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.7, ar: 31, d1r: 2, dl: 0, d2r: 0, rr: 6, mdl: 11, mod_source: 0, feedback: 0.0, is_carrier: true },
    ]
  },
  'Brass': {
    operators: [
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 24, d1r: 4, dl: 2, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.3, is_carrier: false },
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 22, d1r: 2, dl: 0, d2r: 0, rr: 14, mdl: 9, mod_source: 0, feedback: 0.0, is_carrier: true },
    ]
  },
  'Organ': {
    operators: [
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.7, ar: 31, d1r: 0, dl: 0, d2r: 0, rr: 20, mdl: 0, mod_source: -1, feedback: 0.6, is_carrier: false },
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 0, dl: 0, d2r: 0, rr: 20, mdl: 8, mod_source: 0, feedback: 0.0, is_carrier: true },
    ]
  },
  'FM Bass': {
    operators: [
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.9, ar: 31, d1r: 14, dl: 10, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.2, is_carrier: false },
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.9, ar: 31, d1r: 6, dl: 4, d2r: 0, rr: 14, mdl: 10, mod_source: 0, feedback: 0.0, is_carrier: true },
    ]
  },
  'Strings': {
    operators: [
      { freq_ratio: 1.002, freq_fixed: 0, level: 0.5, ar: 20, d1r: 0, dl: 0, d2r: 0, rr: 16, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.7, ar: 18, d1r: 0, dl: 0, d2r: 0, rr: 14, mdl: 7, mod_source: 0, feedback: 0.0, is_carrier: true },
    ]
  },
  'Clavinet': {
    operators: [
      { freq_ratio: 3.0, freq_fixed: 0, level: 0.9, ar: 31, d1r: 16, dl: 14, d2r: 0, rr: 18, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 10, dl: 6, d2r: 0, rr: 16, mdl: 10, mod_source: 0, feedback: 0.0, is_carrier: true },
    ]
  },
  'Marimba': {
    operators: [
      { freq_ratio: 4.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 18, dl: 16, d2r: 0, rr: 20, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 8, dl: 4, d2r: 0, rr: 12, mdl: 9, mod_source: 0, feedback: 0.0, is_carrier: true },
    ]
  },
  'Metallic': {
    operators: [
      { freq_ratio: 1.414, freq_fixed: 0, level: 0.6, ar: 31, d1r: 6, dl: 3, d2r: 0, rr: 10, mdl: 0, mod_source: -1, feedback: 0.4, is_carrier: false },
      { freq_ratio: 3.82, freq_fixed: 0, level: 0.5, ar: 31, d1r: 8, dl: 4, d2r: 0, rr: 12, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.7, ar: 31, d1r: 4, dl: 2, d2r: 0, rr: 10, mdl: 10, mod_source: 0, feedback: 0.0, is_carrier: true },
    ]
  },
  '4-Op E.Piano': {
    operators: [
      { freq_ratio: 5.0, freq_fixed: 0, level: 0.3, ar: 31, d1r: 16, dl: 14, d2r: 0, rr: 16, mdl: 0, mod_source: -1, feedback: 0.2, is_carrier: false },
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.5, ar: 31, d1r: 12, dl: 8, d2r: 0, rr: 14, mdl: 7, mod_source: 0, feedback: 0.0, is_carrier: false },
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.7, ar: 31, d1r: 8, dl: 4, d2r: 0, rr: 12, mdl: 8, mod_source: 1, feedback: 0.0, is_carrier: false },
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 4, dl: 2, d2r: 0, rr: 12, mdl: 9, mod_source: 2, feedback: 0.0, is_carrier: true },
    ]
  },
  'Sine': {
    operators: [
      { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 0, dl: 0, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: true },
    ]
  },
};

// ═══════════════════════════════════════════════════════════════
// ALGORITHM PRESETS
// ═══════════════════════════════════════════════════════════════

const ALGORITHMS = [
  { name: '1→2 (2-op)', ops: [
    { freq_ratio: 2.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 10, dl: 6, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
    { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 4, dl: 2, d2r: 0, rr: 14, mdl: 9, mod_source: 0, feedback: 0.0, is_carrier: true },
  ]},
  { name: '1→2→3 (3-op serial)', ops: [
    { freq_ratio: 3.0, freq_fixed: 0, level: 0.5, ar: 31, d1r: 12, dl: 8, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
    { freq_ratio: 1.0, freq_fixed: 0, level: 0.7, ar: 31, d1r: 8, dl: 4, d2r: 0, rr: 14, mdl: 8, mod_source: 0, feedback: 0.0, is_carrier: false },
    { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 4, dl: 2, d2r: 0, rr: 12, mdl: 9, mod_source: 1, feedback: 0.0, is_carrier: true },
  ]},
  { name: '1+2→3 (Y-shape)', ops: [
    { freq_ratio: 3.0, freq_fixed: 0, level: 0.6, ar: 31, d1r: 10, dl: 6, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
    { freq_ratio: 1.5, freq_fixed: 0, level: 0.5, ar: 31, d1r: 8, dl: 5, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
    { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 4, dl: 2, d2r: 0, rr: 12, mdl: 9, mod_source: 0, feedback: 0.0, is_carrier: true },
  ]},
  { name: '1→2→3→4 (4-op serial)', ops: [
    { freq_ratio: 5.0, freq_fixed: 0, level: 0.3, ar: 31, d1r: 16, dl: 14, d2r: 0, rr: 16, mdl: 0, mod_source: -1, feedback: 0.2, is_carrier: false },
    { freq_ratio: 1.0, freq_fixed: 0, level: 0.5, ar: 31, d1r: 12, dl: 8, d2r: 0, rr: 14, mdl: 7, mod_source: 0, feedback: 0.0, is_carrier: false },
    { freq_ratio: 1.0, freq_fixed: 0, level: 0.7, ar: 31, d1r: 8, dl: 4, d2r: 0, rr: 12, mdl: 8, mod_source: 1, feedback: 0.0, is_carrier: false },
    { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 4, dl: 2, d2r: 0, rr: 12, mdl: 9, mod_source: 2, feedback: 0.0, is_carrier: true },
  ]},
  { name: '1→3, 2→3 (parallel mod)', ops: [
    { freq_ratio: 2.0, freq_fixed: 0, level: 0.7, ar: 31, d1r: 10, dl: 6, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
    { freq_ratio: 3.0, freq_fixed: 0, level: 0.5, ar: 31, d1r: 12, dl: 8, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
    { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 4, dl: 2, d2r: 0, rr: 12, mdl: 9, mod_source: 0, feedback: 0.0, is_carrier: true },
  ]},
  { name: '1→2, 3→4 (dual 2-op)', ops: [
    { freq_ratio: 2.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 10, dl: 6, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
    { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 4, dl: 2, d2r: 0, rr: 14, mdl: 9, mod_source: 0, feedback: 0.0, is_carrier: true },
    { freq_ratio: 3.0, freq_fixed: 0, level: 0.6, ar: 31, d1r: 12, dl: 8, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: false },
    { freq_ratio: 1.0, freq_fixed: 0, level: 0.7, ar: 31, d1r: 4, dl: 2, d2r: 0, rr: 14, mdl: 8, mod_source: 2, feedback: 0.0, is_carrier: true },
  ]},
  { name: 'All carriers (additive)', ops: [
    { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 4, dl: 2, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: true },
    { freq_ratio: 2.0, freq_fixed: 0, level: 0.5, ar: 31, d1r: 6, dl: 3, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: true },
    { freq_ratio: 3.0, freq_fixed: 0, level: 0.3, ar: 31, d1r: 8, dl: 4, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: true },
    { freq_ratio: 4.0, freq_fixed: 0, level: 0.2, ar: 31, d1r: 10, dl: 5, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: true },
  ]},
];

// ═══════════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════════

let patches = [];    // array of { name, operators[] }
let curPatch = 0;    // selected patch index
let selOp = 0;       // selected operator index
let oct = 4;
let actx = null;     // AudioContext
let fmNode = null;   // ScriptProcessorNode
let fmGain = null;   // master gain
let scsp = null;     // WASM SCSP module instance
let scspReady = false;
let activeNotes = {}; // midi note → { slots: [slot indices] }

// ═══════════════════════════════════════════════════════════════
// INIT: Load presets as patches
// ═══════════════════════════════════════════════════════════════

function initPatches() {
  for (const [name, preset] of Object.entries(PRESETS)) {
    patches.push({ name, operators: JSON.parse(JSON.stringify(preset.operators)) });
  }
}

function defaultOp() {
  return { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 0, dl: 0, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0.0, is_carrier: true, waveform: 0, loop_mode: 1, loop_start: 0, loop_end: 1024 };
}

// ═══════════════════════════════════════════════════════════════
// SCSP WASM ENGINE
// ═══════════════════════════════════════════════════════════════

// Embedded SCSP WASM binary and Emscripten glue
const SCSP_WASM_B64 = '__SCSP_WASM_B64__';
__SCSP_GLUE_JS__

// Sine wave sample loaded into SCSP sound RAM.
// All built-in waveforms are 1024 samples (required by SCSP FM math: smp <<= 0xA).
const WAVE_LEN = 1024;
const WAVE_BYTES = WAVE_LEN * 2;
const SINE_BASE_FREQ = 44100.0 / WAVE_LEN;
const SINE_BASE_NOTE = 69 + 12 * Math.log2(SINE_BASE_FREQ / 440);

const WAVE_NAMES = ['Sine','Sawtooth','Square','Triangle','Organ','Brass','Strings','Piano','Flute','Bass'];
const LOOP_NAMES = ['Off','Forward','Reverse','Ping-pong'];

// ── JS Waveform Generators (matching scsp_waveforms.c) ──
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

// ── Waveform Store: tracks waveforms loaded into SCSP RAM ──
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
  const wasmBytes = Uint8Array.from(atob(SCSP_WASM_B64), c => c.charCodeAt(0));
  scsp = await SCSPModule({ wasmBinary: wasmBytes.buffer });
  scsp._scsp_init();

  // Load all built-in waveforms into SCSP RAM
  const ramPtr = scsp._scsp_get_ram_ptr();
  waveStore.waves = [];
  waveStore.nextOffset = 0;
  for (let t = 0; t < WAVE_NAMES.length; t++) {
    const samples = generateWaveform(t, WAVE_LEN);
    waveStoreAdd(ramPtr, samples, 0, WAVE_LEN, 1);
  }
  scspReady = true;
}

/*
 * Program SCSP slot registers for one operator.
 * Maps editor patch params to the exact SCSP register layout.
 */
function programSlot(slot, op, midiNote, allOps) {
  const _wid = op.waveform || 0;
  let wav = waveStore.waves[_wid] || waveStore.waves[0];

  // Resolve loop points (per-op override or waveform default)
  let lsa   = op.loop_start >= 0 ? op.loop_start : wav.loopStart;
  let lea   = op.loop_end > 0    ? op.loop_end   : wav.loopEnd;
  let lpctl = op.loop_mode >= 0  ? op.loop_mode  : wav.loopMode;
  let sa    = wav.offset;

  // FM constraint: modulators and FM-modulated carriers must use 1024-sample forward loop
  const usesFM = (op.mod_source >= 0 && op.mdl >= 5) || op.feedback > 0;
  const isMod = !op.is_carrier;
  if (usesFM || isMod) {
    if (wav.length !== WAVE_LEN) { wav = waveStore.waves[0]; sa = wav.offset; }
    lsa = 0; lea = WAVE_LEN; lpctl = 1;
  }

  // Compute pitch from the FINAL waveform (after any FM swap).
  const _wavLen = wav.length || WAVE_LEN;
  const _wavBaseFreq = SAMPLE_RATE / _wavLen;
  const _wavBaseNote = 69 + 12 * Math.log2(_wavBaseFreq / 440);

  let opBaseNote;
  if (op.freq_fixed > 0) {
    opBaseNote = _wavBaseNote + 12 * Math.log2(op.freq_fixed / _wavBaseFreq);
  } else {
    opBaseNote = _wavBaseNote - 12 * Math.log2(op.freq_ratio);
  }
  const semi = midiNote - opBaseNote;
  const octave = Math.max(-8, Math.min(7, Math.floor(semi / 12)));
  const frac = semi - octave * 12;
  const fns = Math.max(0, Math.min(1023, Math.round(1024 * (Math.pow(2, frac / 12) - 1))));
  const octBits = ((octave & 0xF) << 11) | (fns & 0x3FF);

  const saHigh = (sa >> 16) & 0xF;
  const saLow = sa & 0xFFFF;

  // data[0]: LPCTL at bits [6:5], SA high at bits [3:0]
  const d0 = (lpctl << 5) | saHigh;

  // data[4]: D2R[15:11] | D1R[10:6] | EGHOLD[5] | AR[4:0]
  const d4 = ((op.d2r & 0x1F) << 11) | ((op.d1r & 0x1F) << 6) | (op.ar & 0x1F);

  // data[5]: LPSLNK[14] | KRS[13:10] | DL[9:5] | RR[4:0]
  const d5 = ((op.dl & 0x1F) << 5) | (op.rr & 0x1F);

  // TL from level.
  // For carriers: full 0-255 range maps level to output volume.
  // For modulators: TL also controls the ring buffer amplitude, which determines
  // FM modulation strength. The SCSP's TL-to-dB curve is very steep (each bit
  // adds 0.4 to 48 dB of attenuation), so moderate levels can kill FM entirely.
  // Solution: modulators use a compressed TL range (24-80) to keep the ring
  // buffer strong, and the carrier's MDL controls the actual FM depth.
  let tl;
  if (op.is_carrier) {
    tl = Math.max(0, Math.min(255, Math.round((1.0 - op.level) * 255)));
  } else {
    // Modulator: TL=24 at level=1.0 (prevents int16 ring buffer overflow),
    // TL=80 at level=0.0 (still audible in ring buffer for FM).
    tl = Math.round(24 + (1.0 - op.level) * 56);
  }
  // data[6]: STWINH[9] | SDIR[8] | TL[7:0]
  const d6 = tl & 0xFF;

  // FM modulation: MDL and MDXSL
  // SCSP FM uses a 64-entry ring buffer. Before processing slot S, BUFPTR
  // points to where slot S will write. After slot S, BUFPTR increments.
  // So slot S writes at RINGBUF[BUFPTR_S], and BUFPTR_S+1 = BUFPTR_S + 1.
  // When slot M reads modulation, BUFPTR is at M's position.
  // To read slot N's output (where N < M): MDXSL = (N - M) & 63
  // Example: slot 1 reading slot 0: MDXSL = (0 - 1) & 63 = 63
  // FM modulation via SCSP ring buffer.
  // The SCSP always reads BOTH MDXSL and MDYSL and averages them:
  //   smp = (RINGBUF[BUFPTR+MDXSL] + RINGBUF[BUFPTR+MDYSL]) / 2
  // Both must point to valid sources.
  //
  // MDL computation: we need to match fm_sim.py's modulation index.
  // In fm_sim.py: beta ≈ mod_level * pi (at carrier's MDL point).
  // On SCSP: beta = ringPeak * 2^(MDL-16) * 2pi / 1024.
  // ringPeak depends on modulator's TL. We compute MDL to achieve the
  // target beta for the given modulator TL and original level.
  let mdl = 0, mdxsl = 0, mdysl = 0;
  if (op.mod_source >= 0 && op.mdl >= 5) {
    // Find the modulator's TL to compute effective ring buffer peak
    const modOp = allOps[op.mod_source];
    const modTL = Math.round(24 + (1.0 - modOp.level) * 56);
    // Compute ring buffer peak for this TL
    let segaDB = 0;
    if(modTL&1) segaDB-=0.4; if(modTL&2) segaDB-=0.8; if(modTL&4) segaDB-=1.5;
    if(modTL&8) segaDB-=3; if(modTL&16) segaDB-=6; if(modTL&32) segaDB-=12;
    if(modTL&64) segaDB-=24; if(modTL&128) segaDB-=48;
    const tlLin = Math.pow(10, segaDB / 20);
    const ringPeak = 32767 * 4 * tlLin / 2; // LPANTABLE has 4x gain, >>SHIFT+1 divides by 2
    // Target beta from fm_sim.py: modulator_level * pi.
    // Cap at ~2.5 to keep FM offset within the 1024-sample waveform bounds
    // (beta=pi would swing ±512 samples = full half-waveform).
    const targetBeta = Math.min(modOp.level * Math.PI, 2.5);
    // beta = ringPeak * 2^(MDL-16) * 2pi / 1024
    // Solve for MDL: 2^(MDL-16) = targetBeta * 1024 / (ringPeak * 2pi)
    const needed = targetBeta * 1024 / (ringPeak * 2 * Math.PI);
    mdl = Math.max(0, Math.min(15, Math.round(16 + Math.log2(Math.max(needed, 1e-10)))));
    // Safety: cap MDL so max FM offset stays within ±512 samples (1024 bytes)
    const maxSafe = 1024 / (ringPeak * 2); // 2^(MDL-15) <= maxSafe
    const maxMDL = Math.floor(15 + Math.log2(Math.max(maxSafe, 1e-10)));
    mdl = Math.min(mdl, maxMDL);
    const dist = (op.mod_source - slot) & 63;
    mdxsl = dist;
    mdysl = dist;
  }
  // Self-feedback via ring buffer
  if (op.feedback > 0) {
    const fbDist = (-32) & 63;
    // Target beta for self-feedback: feedback * pi
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
    if (mdl > 0) {
      // Both cross-modulation and self-feedback: average via MDXSL/MDYSL
      mdysl = fbDist;
      mdl = Math.max(mdl, fbMdl);
    } else {
      mdl = fbMdl;
      mdxsl = fbDist;
      mdysl = fbDist;
    }
  }
  // data[7]: MDL[15:12] | MDXSL[11:6] | MDYSL[5:0]
  const d7 = ((mdl & 0xF) << 12) | ((mdxsl & 0x3F) << 6) | (mdysl & 0x3F);

  // data[0xB]: DISDL[15:13] | DIPAN[12:8] | EFSDL[7:5] | EFPAN[4:0]
  const disdl = op.is_carrier ? 7 : 0; // carriers are audible
  const dipan = 16; // center
  const dB = ((disdl & 0x7) << 13) | ((dipan & 0x1F) << 8);

  // Write all slot registers
  scsp._scsp_write_slot(slot, 0x0, d0);
  scsp._scsp_write_slot(slot, 0x1, saLow);
  scsp._scsp_write_slot(slot, 0x2, lsa);
  scsp._scsp_write_slot(slot, 0x3, lea);
  scsp._scsp_write_slot(slot, 0x4, d4);
  scsp._scsp_write_slot(slot, 0x5, d5);
  scsp._scsp_write_slot(slot, 0x6, d6);
  scsp._scsp_write_slot(slot, 0x7, d7);
  scsp._scsp_write_slot(slot, 0x8, octBits);
  scsp._scsp_write_slot(slot, 0x9, 0);           // LFO off
  scsp._scsp_write_slot(slot, 0xA, 0);           // ISEL/IMXL
  scsp._scsp_write_slot(slot, 0xB, dB);
}

function ensureAudio() {
  if (!actx) {
    actx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 44100 });
  }
  if (actx.state === 'suspended') actx.resume();
  if (!fmNode && scspReady) {
    fmNode = actx.createScriptProcessor(2048, 0, 2); // stereo output
    fmGain = actx.createGain();
    fmGain.gain.value = 0.7;
    fmNode.connect(fmGain);
    fmGain.connect(actx.destination);
    fmNode.onaudioprocess = function(e) {
      const outL = e.outputBuffer.getChannelData(0);
      const outR = e.outputBuffer.numberOfChannels > 1 ? e.outputBuffer.getChannelData(1) : outL;
      const n = outL.length;
      if (!scspReady) { for (let i = 0; i < n; i++) { outL[i] = 0; outR[i] = 0; } return; }
      // Render n samples from SCSP
      const bufPtr = scsp._scsp_render(n);
      const heap16 = new Int16Array(scsp.HEAP16.buffer, bufPtr, n * 2);
      for (let i = 0; i < n; i++) {
        outL[i] = heap16[i * 2]     / 32768.0;
        outR[i] = heap16[i * 2 + 1] / 32768.0;
      }
    };
  }
}

async function playNote(midi) {
  await initSCSP();
  ensureAudio();
  stopNote(midi);

  const patch = patches[curPatch];
  const ops = patch.operators;
  const slots = [];

  // Program each operator into a SCSP slot (use slots 0..N-1)
  for (let i = 0; i < ops.length; i++) {
    programSlot(i, ops[i], midi, ops);
    slots.push(i);
  }

  // Key-on all slots
  for (const s of slots) {
    scsp._scsp_key_on(s);
  }

  activeNotes[midi] = { slots };
}

function stopNote(midi) {
  const an = activeNotes[midi];
  if (an && scspReady) {
    for (const s of an.slots) {
      scsp._scsp_key_off(s);
    }
    delete activeNotes[midi];
  }
}

// ═══════════════════════════════════════════════════════════════
// UI: Patch List
// ═══════════════════════════════════════════════════════════════

function renderPatchList() {
  const el = document.getElementById('patch-list');
  el.innerHTML = '';
  patches.forEach((p, i) => {
    const div = document.createElement('div');
    div.className = 'patch-item' + (i === curPatch ? ' sel' : '');
    const nameSpan = document.createElement('span');
    nameSpan.textContent = p.name;
    nameSpan.ondblclick = (e) => {
      e.stopPropagation();
      const newName = prompt('Rename patch:', p.name);
      if (newName) { p.name = newName; renderPatchList(); }
    };
    div.appendChild(nameSpan);
    if (patches.length > 1) {
      const del = document.createElement('span');
      del.className = 'del-btn';
      del.textContent = '\u00d7';
      del.onclick = (e) => { e.stopPropagation(); deletePatch(i); };
      div.appendChild(del);
    }
    div.onclick = () => { curPatch = i; selOp = 0; renderAll(); };
    el.appendChild(div);
  });
}

function addPatch() {
  patches.push({ name: 'New Patch', operators: [defaultOp()] });
  curPatch = patches.length - 1;
  selOp = 0;
  renderAll();
}

function dupPatch() {
  const src = patches[curPatch];
  patches.push({ name: src.name + ' (copy)', operators: JSON.parse(JSON.stringify(src.operators)) });
  curPatch = patches.length - 1;
  renderAll();
}

function deletePatch(i) {
  if (patches.length <= 1) return;
  patches.splice(i, 1);
  if (curPatch >= patches.length) curPatch = patches.length - 1;
  selOp = 0;
  renderAll();
}

// ═══════════════════════════════════════════════════════════════
// UI: Operator Graph
// ═══════════════════════════════════════════════════════════════

function renderOpGraph() {
  const patch = patches[curPatch];
  const ops = patch.operators;
  const container = document.getElementById('op-boxes');
  container.innerHTML = '';

  ops.forEach((op, i) => {
    const box = document.createElement('div');
    box.className = 'op-box' + (op.is_carrier ? ' carrier' : '') + (i === selOp ? ' sel' : '');
    const nameDiv = document.createElement('div');
    nameDiv.className = 'op-name';
    nameDiv.textContent = 'Op ' + (i + 1);
    box.appendChild(nameDiv);

    const roleDiv = document.createElement('div');
    roleDiv.className = 'op-role ' + (op.is_carrier ? 'car' : 'mod');
    roleDiv.textContent = op.is_carrier ? 'CARRIER' : 'MODULATOR';
    box.appendChild(roleDiv);

    const detDiv = document.createElement('div');
    detDiv.className = 'op-detail';
    let ratioStr = op.freq_fixed > 0 ? op.freq_fixed + 'Hz' : 'x' + op.freq_ratio;
    let modStr = op.mod_source >= 0 ? ' \u2190Op' + (op.mod_source + 1) : '';
    let mdlStr = op.mdl >= 5 ? ' MDL=' + op.mdl : '';
    let fbStr = op.feedback > 0 ? ' fb=' + op.feedback.toFixed(1) : '';
    detDiv.textContent = ratioStr + ' lv=' + op.level.toFixed(1) + modStr + mdlStr + fbStr;
    box.appendChild(detDiv);

    box.onclick = () => { selOp = i; renderAll(); };
    box.oncontextmenu = (e) => {
      e.preventDefault();
      op.is_carrier = !op.is_carrier;
      renderAll();
    };
    container.appendChild(box);
  });

  // Draw modulation arrows via SVG
  // We'll do this after layout settles
  requestAnimationFrame(drawModArrows);
}

function drawModArrows() {
  const svg = document.getElementById('op-svg');
  svg.innerHTML = '';
  const patch = patches[curPatch];
  const boxes = document.querySelectorAll('.op-box');
  if (!boxes.length) return;

  const graphRect = document.getElementById('op-graph').getBoundingClientRect();

  patch.operators.forEach((op, i) => {
    if (op.mod_source >= 0 && op.mod_source < boxes.length && i < boxes.length) {
      const srcBox = boxes[op.mod_source];
      const dstBox = boxes[i];
      const sr = srcBox.getBoundingClientRect();
      const dr = dstBox.getBoundingClientRect();

      const x1 = sr.left + sr.width / 2 - graphRect.left;
      const y1 = sr.top + sr.height / 2 - graphRect.top;
      const x2 = dr.left + dr.width / 2 - graphRect.left;
      const y2 = dr.top + dr.height / 2 - graphRect.top;

      // Arrow line
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', x1); line.setAttribute('y1', y1);
      line.setAttribute('x2', x2); line.setAttribute('y2', y2);
      line.setAttribute('stroke', '#a84');
      line.setAttribute('stroke-width', '2');
      line.setAttribute('stroke-dasharray', '4,3');
      svg.appendChild(line);

      // Arrowhead
      const angle = Math.atan2(y2 - y1, x2 - x1);
      const headLen = 8;
      const cx = (x1 + x2) / 2;
      const cy = (y1 + y2) / 2;
      const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
      const p1x = cx + headLen * Math.cos(angle);
      const p1y = cy + headLen * Math.sin(angle);
      const p2x = cx - headLen * Math.cos(angle - 0.5);
      const p2y = cy - headLen * Math.sin(angle - 0.5);
      const p3x = cx - headLen * Math.cos(angle + 0.5);
      const p3y = cy - headLen * Math.sin(angle + 0.5);
      poly.setAttribute('points', `${p1x},${p1y} ${p2x},${p2y} ${p3x},${p3y}`);
      poly.setAttribute('fill', '#a84');
      svg.appendChild(poly);
    }

    // Self-feedback arc
    if (op.feedback > 0 && i < boxes.length) {
      const box = boxes[i];
      const br = box.getBoundingClientRect();
      const cx = br.left + br.width / 2 - graphRect.left;
      const cy = br.top - graphRect.top;
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', `M ${cx-10},${cy} C ${cx-15},${cy-20} ${cx+15},${cy-20} ${cx+10},${cy}`);
      path.setAttribute('stroke', '#866');
      path.setAttribute('stroke-width', '1.5');
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke-dasharray', '3,2');
      svg.appendChild(path);
    }
  });
}

function addOp() {
  const patch = patches[curPatch];
  if (patch.operators.length >= 6) return;
  patch.operators.push(defaultOp());
  selOp = patch.operators.length - 1;
  renderAll();
}

function removeOp() {
  const patch = patches[curPatch];
  if (patch.operators.length <= 1) return;
  patch.operators.splice(selOp, 1);
  // Fix mod_source references
  for (const op of patch.operators) {
    if (op.mod_source === selOp) op.mod_source = -1;
    else if (op.mod_source > selOp) op.mod_source--;
  }
  if (selOp >= patch.operators.length) selOp = patch.operators.length - 1;
  renderAll();
}

function showAlgMenu(e) {
  const menu = document.getElementById('alg-menu');
  menu.style.display = 'block';
  menu.style.left = e.clientX + 'px';
  menu.style.top = e.clientY + 'px';
  menu.innerHTML = '';
  ALGORITHMS.forEach((alg) => {
    const item = document.createElement('div');
    item.style.cssText = 'padding:4px 10px; cursor:pointer; font-size:12px; color:#ccc; white-space:nowrap;';
    item.textContent = alg.name;
    item.onmouseenter = () => item.style.background = '#3a3a5e';
    item.onmouseleave = () => item.style.background = 'none';
    item.onclick = () => {
      patches[curPatch].operators = JSON.parse(JSON.stringify(alg.ops));
      selOp = 0;
      menu.style.display = 'none';
      renderAll();
    };
    menu.appendChild(item);
  });
  // Add preset patches section
  const sep = document.createElement('div');
  sep.style.cssText = 'border-top:1px solid #444; margin:4px 0;';
  menu.appendChild(sep);
  const hdr = document.createElement('div');
  hdr.style.cssText = 'padding:2px 10px; font-size:10px; color:#666; text-transform:uppercase;';
  hdr.textContent = 'Presets';
  menu.appendChild(hdr);
  for (const [name, preset] of Object.entries(PRESETS)) {
    const item = document.createElement('div');
    item.style.cssText = 'padding:4px 10px; cursor:pointer; font-size:12px; color:#ccc; white-space:nowrap;';
    item.textContent = name;
    item.onmouseenter = () => item.style.background = '#3a3a5e';
    item.onmouseleave = () => item.style.background = 'none';
    item.onclick = () => {
      patches[curPatch].operators = JSON.parse(JSON.stringify(preset.operators));
      patches[curPatch].name = name;
      selOp = 0;
      menu.style.display = 'none';
      renderAll();
    };
    menu.appendChild(item);
  }
}
document.addEventListener('click', (e) => {
  const menu = document.getElementById('alg-menu');
  if (!menu.contains(e.target)) menu.style.display = 'none';
});

// ═══════════════════════════════════════════════════════════════
// UI: Operator Parameters
// ═══════════════════════════════════════════════════════════════

function renderOpParams() {
  const body = document.getElementById('op-params-body');
  const patch = patches[curPatch];
  if (!patch.operators.length) {
    body.innerHTML = '<div id="no-op-msg">No operators. Click "+ Add Op" to add one.</div>';
    return;
  }
  const op = patch.operators[selOp];
  if (!op) { selOp = 0; return renderOpParams(); }

  body.innerHTML = '';

  // Helper to create a param control
  function mkSlider(label, key, min, max, step, displayFn) {
    const div = document.createElement('div');
    div.className = 'param';
    const lbl = document.createElement('label');
    lbl.textContent = label;
    div.appendChild(lbl);
    const row = document.createElement('div');
    row.style.display = 'flex'; row.style.alignItems = 'center'; row.style.gap = '6px';
    const inp = document.createElement('input');
    inp.type = 'range'; inp.min = min; inp.max = max; inp.step = step;
    inp.value = op[key];
    const val = document.createElement('span');
    val.className = 'val';
    val.textContent = displayFn ? displayFn(op[key]) : op[key];
    inp.oninput = () => {
      op[key] = parseFloat(inp.value);
      val.textContent = displayFn ? displayFn(op[key]) : op[key];
      renderOpGraph();
      drawEnvelope();
    };
    row.appendChild(inp); row.appendChild(val);
    div.appendChild(row);
    return div;
  }

  function mkNumber(label, key, min, max, step) {
    const div = document.createElement('div');
    div.className = 'param';
    const lbl = document.createElement('label');
    lbl.textContent = label;
    div.appendChild(lbl);
    const inp = document.createElement('input');
    inp.type = 'number'; inp.min = min; inp.max = max; inp.step = step;
    inp.value = op[key];
    inp.onchange = () => {
      op[key] = parseFloat(inp.value);
      renderOpGraph();
      drawEnvelope();
    };
    div.appendChild(inp);
    return div;
  }

  function mkSelect(label, key, options) {
    const div = document.createElement('div');
    div.className = 'param';
    const lbl = document.createElement('label');
    lbl.textContent = label;
    div.appendChild(lbl);
    const sel = document.createElement('select');
    options.forEach(o => {
      const opt = document.createElement('option');
      opt.value = o.value; opt.textContent = o.label;
      if (op[key] == o.value) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.onchange = () => {
      op[key] = parseFloat(sel.value);
      renderOpGraph();
      drawEnvelope();
    };
    div.appendChild(sel);
    return div;
  }

  // ── Pitch group ──
  const pitchGrp = document.createElement('div');
  pitchGrp.className = 'param-group';
  const pitchTitle = document.createElement('div');
  pitchTitle.className = 'param-group-title';
  pitchTitle.textContent = 'Pitch';
  pitchGrp.appendChild(pitchTitle);
  const pitchRow = document.createElement('div');
  pitchRow.className = 'row';
  pitchRow.appendChild(mkNumber('Freq Ratio', 'freq_ratio', 0.5, 32, 0.001));
  pitchRow.appendChild(mkNumber('Fixed Hz', 'freq_fixed', 0, 10000, 1));
  pitchGrp.appendChild(pitchRow);
  body.appendChild(pitchGrp);

  // ── Amplitude group ──
  const ampGrp = document.createElement('div');
  ampGrp.className = 'param-group';
  const ampTitle = document.createElement('div');
  ampTitle.className = 'param-group-title';
  ampTitle.textContent = 'Amplitude';
  ampGrp.appendChild(ampTitle);
  const ampRow = document.createElement('div');
  ampRow.className = 'row';
  ampRow.appendChild(mkSlider('Level', 'level', 0, 1, 0.01, v => v.toFixed(2)));

  // Computed TL display
  const tlDiv = document.createElement('div');
  tlDiv.className = 'param';
  const tlLbl = document.createElement('label');
  tlLbl.textContent = 'TL (computed)';
  tlDiv.appendChild(tlLbl);
  const tlVal = document.createElement('span');
  tlVal.className = 'val';
  tlVal.style.fontSize = '12px';
  const tl = Math.max(0, Math.min(255, Math.round((1.0 - op.level) * 128)));
  tlVal.textContent = tl + ' (' + (tl * 0.375).toFixed(1) + ' dB)';
  tlDiv.appendChild(tlVal);
  ampRow.appendChild(tlDiv);

  ampGrp.appendChild(ampRow);
  body.appendChild(ampGrp);

  // ── Envelope group ──
  const envGrp = document.createElement('div');
  envGrp.className = 'param-group';
  const envTitle = document.createElement('div');
  envTitle.className = 'param-group-title';
  envTitle.textContent = 'Envelope';
  envGrp.appendChild(envTitle);
  const envRow = document.createElement('div');
  envRow.className = 'row';
  envRow.appendChild(mkSlider('AR', 'ar', 0, 31, 1, v => {
    const ms = AR_TIMES[Math.min(v, 31)];
    return v + (ms < 10000 ? ' (' + ms + 'ms)' : '');
  }));
  envRow.appendChild(mkSlider('D1R', 'd1r', 0, 31, 1, v => {
    const ms = v > 0 ? DR_TIMES[Math.min(v, 31)] : 'inf';
    return v + (typeof ms === 'number' && ms < 10000 ? ' (' + ms + 'ms)' : '');
  }));
  envRow.appendChild(mkSlider('DL', 'dl', 0, 31, 1, v => {
    const sus = v < 31 ? (1 - v/31).toFixed(2) : '0';
    return v + ' (sus=' + sus + ')';
  }));
  envRow.appendChild(mkSlider('D2R', 'd2r', 0, 31, 1, v => {
    const ms = v > 0 ? DR_TIMES[Math.min(v, 31)] : 'inf';
    return v + (typeof ms === 'number' && ms < 10000 ? ' (' + ms + 'ms)' : '');
  }));
  envRow.appendChild(mkSlider('RR', 'rr', 0, 31, 1, v => {
    const ms = DR_TIMES[Math.min(v, 31)];
    return v + (ms < 10000 ? ' (' + ms + 'ms)' : '');
  }));
  envGrp.appendChild(envRow);
  body.appendChild(envGrp);

  // ── Modulation group ──
  const modGrp = document.createElement('div');
  modGrp.className = 'param-group';
  const modTitle = document.createElement('div');
  modTitle.className = 'param-group-title';
  modTitle.textContent = 'Modulation';
  modGrp.appendChild(modTitle);
  const modRow = document.createElement('div');
  modRow.className = 'row';

  // Mod source selector
  const srcOpts = [{ value: -1, label: 'None' }];
  patch.operators.forEach((_, i) => {
    if (i !== selOp) srcOpts.push({ value: i, label: 'Op ' + (i + 1) });
  });
  modRow.appendChild(mkSelect('Mod Source', 'mod_source', srcOpts));
  modRow.appendChild(mkSlider('MDL', 'mdl', 0, 15, 1, v => v + (v < 5 ? ' (off)' : '')));
  modRow.appendChild(mkSlider('Feedback', 'feedback', 0, 0.5, 0.01, v => v.toFixed(2)));

  // Carrier toggle
  const carrDiv = document.createElement('div');
  carrDiv.className = 'param carrier-toggle';
  const carrLbl = document.createElement('label');
  carrLbl.textContent = 'Carrier (audible)';
  const carrChk = document.createElement('input');
  carrChk.type = 'checkbox';
  carrChk.checked = op.is_carrier;
  carrChk.onchange = () => {
    op.is_carrier = carrChk.checked;
    renderOpGraph();
  };
  carrDiv.appendChild(carrChk); carrDiv.appendChild(carrLbl);
  modRow.appendChild(carrDiv);

  modGrp.appendChild(modRow);
  body.appendChild(modGrp);

  // ── Waveform group ──
  const waveGrp = document.createElement('div');
  waveGrp.className = 'param-group';
  const waveTitle = document.createElement('div');
  waveTitle.className = 'param-group-title';
  waveTitle.textContent = 'Waveform';
  waveGrp.appendChild(waveTitle);
  const waveRow = document.createElement('div');
  waveRow.className = 'row';

  // Waveform selector dropdown
  const waveDiv = document.createElement('div');
  waveDiv.className = 'param';
  const waveLbl = document.createElement('label');
  waveLbl.textContent = 'Waveform';
  waveDiv.appendChild(waveLbl);
  const waveSel = document.createElement('select');
  WAVE_NAMES.forEach((name, wi) => {
    const o = document.createElement('option');
    o.value = wi; o.textContent = name;
    if (wi === (op.waveform || 0)) o.selected = true;
    waveSel.appendChild(o);
  });
  waveSel.onchange = () => {
    op.waveform = parseInt(waveSel.value);
    drawWaveformPreview();
    renderOpGraph();
  };
  waveDiv.appendChild(waveSel);
  waveRow.appendChild(waveDiv);

  // Loop mode dropdown
  const loopDiv = document.createElement('div');
  loopDiv.className = 'param';
  const loopLbl = document.createElement('label');
  loopLbl.textContent = 'Loop Mode';
  loopDiv.appendChild(loopLbl);
  const loopSel = document.createElement('select');
  LOOP_NAMES.forEach((name, li) => {
    const o = document.createElement('option');
    o.value = li; o.textContent = name;
    if (li === (op.loop_mode !== undefined ? op.loop_mode : 1)) o.selected = true;
    loopSel.appendChild(o);
  });
  loopSel.onchange = () => {
    op.loop_mode = parseInt(loopSel.value);
    drawWaveformPreview();
  };
  loopDiv.appendChild(loopSel);
  waveRow.appendChild(loopDiv);

  // Loop start slider
  const waveLen = (waveStore.waves[op.waveform || 0] || {}).length || WAVE_LEN;
  const lsDiv = document.createElement('div');
  lsDiv.className = 'param';
  const lsLbl = document.createElement('label');
  lsLbl.textContent = 'Loop Start';
  lsDiv.appendChild(lsLbl);
  const lsInp = document.createElement('input');
  lsInp.type = 'range'; lsInp.min = 0; lsInp.max = waveLen; lsInp.step = 1;
  lsInp.value = op.loop_start || 0;
  const lsVal = document.createElement('span');
  lsVal.className = 'val'; lsVal.textContent = op.loop_start || 0;
  lsInp.oninput = () => { op.loop_start = parseInt(lsInp.value); lsVal.textContent = op.loop_start; drawWaveformPreview(); };
  lsDiv.appendChild(lsInp); lsDiv.appendChild(lsVal);
  waveRow.appendChild(lsDiv);

  // Loop end slider
  const leDiv = document.createElement('div');
  leDiv.className = 'param';
  const leLbl = document.createElement('label');
  leLbl.textContent = 'Loop End';
  leDiv.appendChild(leLbl);
  const leInp = document.createElement('input');
  leInp.type = 'range'; leInp.min = 0; leInp.max = waveLen; leInp.step = 1;
  leInp.value = op.loop_end || waveLen;
  const leVal = document.createElement('span');
  leVal.className = 'val'; leVal.textContent = op.loop_end || waveLen;
  leInp.oninput = () => { op.loop_end = parseInt(leInp.value); leVal.textContent = op.loop_end; drawWaveformPreview(); };
  leDiv.appendChild(leInp); leDiv.appendChild(leVal);
  waveRow.appendChild(leDiv);

  // Load WAV button
  const loadBtn = document.createElement('button');
  loadBtn.style.cssText = 'background:#2a3a2e;color:#8c8;border:1px solid #4a4;padding:3px 8px;cursor:pointer;border-radius:3px;font-family:inherit;font-size:10px;align-self:flex-end;';
  loadBtn.textContent = 'Load WAV';
  loadBtn.onclick = () => loadWavForOp(selOp);
  waveRow.appendChild(loadBtn);

  waveGrp.appendChild(waveRow);

  // Waveform preview canvas
  const wvCanvas = document.createElement('canvas');
  wvCanvas.id = 'op-wave-preview';
  wvCanvas.style.cssText = 'width:100%;height:60px;display:block;border-radius:4px;background:#12122a;margin-top:6px;';
  waveGrp.appendChild(wvCanvas);
  body.appendChild(waveGrp);

  requestAnimationFrame(drawWaveformPreview);
}

// Custom waveform storage per operator
const customWaves = {};

function loadWavForOp(opIdx) {
  const input = document.createElement('input');
  input.type = 'file'; input.accept = '.wav,audio/wav';
  input.onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const result = parseWav(ev.target.result);
        applyCustomWaveform(opIdx, result.samples, file.name);
      } catch (err) { alert('WAV error: ' + err.message); }
    };
    reader.readAsArrayBuffer(file);
  };
  input.click();
}

function parseWav(buf) {
  const v = new DataView(buf);
  const tag = (o) => String.fromCharCode(v.getUint8(o),v.getUint8(o+1),v.getUint8(o+2),v.getUint8(o+3));
  if (tag(0) !== 'RIFF' || tag(8) !== 'WAVE') throw new Error('Not a WAV file');
  let fmt = null, dOff = 0, dSize = 0, pos = 12;
  while (pos < v.byteLength - 8) {
    const id = tag(pos), sz = v.getUint32(pos+4, true);
    if (id === 'fmt ') fmt = { ch: v.getUint16(pos+10,true), sr: v.getUint32(pos+12,true), bits: v.getUint16(pos+22,true) };
    else if (id === 'data') { dOff = pos+8; dSize = sz; }
    pos += 8 + sz; if (pos%2) pos++;
  }
  if (!fmt || !dOff) throw new Error('Invalid WAV');
  const bps = fmt.bits/8, nf = Math.floor(dSize/(bps*fmt.ch));
  const out = new Float32Array(nf);
  for (let i = 0; i < nf; i++) {
    const o = dOff + i*bps*fmt.ch;
    out[i] = fmt.bits===16 ? v.getInt16(o,true)/32768 : fmt.bits===8 ? (v.getUint8(o)-128)/128 : 0;
  }
  return { samples: out };
}

function resampleTo(input, targetLen) {
  const out = new Float32Array(targetLen);
  const ratio = input.length / targetLen;
  for (let i = 0; i < targetLen; i++) {
    const si = i * ratio, idx = Math.floor(si), fr = si - idx;
    out[i] = input[Math.min(idx,input.length-1)] * (1-fr) + input[Math.min(idx+1,input.length-1)] * fr;
  }
  return out;
}

function applyCustomWaveform(opIdx, floatSamples, filename) {
  const patch = patches[curPatch];
  const op = patch.operators[opIdx];
  const usesFM = (op.mod_source >= 0 && op.mdl >= 5) || op.feedback > 0 || !op.is_carrier;

  let samples = floatSamples;
  if (usesFM && samples.length !== WAVE_LEN) {
    samples = resampleTo(floatSamples, WAVE_LEN);
  }

  // Add to wave store in SCSP RAM
  const ramPtr = scsp._scsp_get_ram_ptr();
  const wid = waveStoreAdd(ramPtr, samples, 0, samples.length, 1);
  op.waveform = wid;
  op.loop_start = 0;
  op.loop_end = samples.length;
  op.loop_mode = 1;

  customWaves[opIdx] = samples;
  renderOpParams();
  drawWaveformPreview();
}

function drawWaveformPreview() {
  const canvas = document.getElementById('op-wave-preview');
  if (!canvas) return;
  const patch = patches[curPatch];
  if (!patch.operators.length) return;
  const op = patch.operators[selOp];
  if (!op) return;

  const rect = canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = 60 * dpr;
  canvas.style.height = '60px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const w = rect.width, h = 60;
  ctx.fillStyle = '#12122a'; ctx.fillRect(0, 0, w, h);

  // Get waveform samples
  let samples;
  if (customWaves[selOp]) {
    samples = customWaves[selOp];
  } else {
    samples = generateWaveform(op.waveform || 0, WAVE_LEN);
  }
  const n = samples.length;
  const lsa = op.loop_start || 0;
  const lea = op.loop_end || n;
  const lm = op.loop_mode !== undefined ? op.loop_mode : 1;

  // Loop region
  if (lm > 0 && lea > lsa) {
    const lx = lsa / n * w, ex = lea / n * w;
    ctx.fillStyle = '#1a2a1a'; ctx.fillRect(lx, 0, ex - lx, h);
    ctx.strokeStyle = '#44aa44'; ctx.setLineDash([2,3]); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(lx, 0); ctx.lineTo(lx, h); ctx.stroke();
    ctx.strokeStyle = '#aa4444';
    ctx.beginPath(); ctx.moveTo(ex, 0); ctx.lineTo(ex, h); ctx.stroke();
    ctx.setLineDash([]);
  }

  // Waveform
  ctx.strokeStyle = '#00d4ff'; ctx.lineWidth = 1; ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const x = i / n * w, y = h/2 - samples[i] * (h/2 - 4);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Center line
  ctx.strokeStyle = '#333'; ctx.setLineDash([2,4]); ctx.lineWidth = 0.5;
  ctx.beginPath(); ctx.moveTo(0, h/2); ctx.lineTo(w, h/2); ctx.stroke();
  ctx.setLineDash([]);

  // Labels
  ctx.fillStyle = '#555'; ctx.font = '9px monospace';
  const isCustom = !!customWaves[selOp];
  ctx.fillText(isCustom ? 'Custom ('+n+' smp)' : (WAVE_NAMES[op.waveform || 0] || '?'), 4, 12);
  ctx.fillText(lm > 0 ? LOOP_NAMES[lm]+' '+lsa+'-'+lea : 'No loop', 4, h - 4);
}

// ═══════════════════════════════════════════════════════════════
// UI: Envelope Visualization
// ═══════════════════════════════════════════════════════════════

function drawEnvelope() {
  const canvas = document.getElementById('env-canvas');
  const rect = canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = 120 * dpr;
  canvas.style.height = '120px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const w = rect.width, h = 120;

  ctx.fillStyle = '#12122a';
  ctx.fillRect(0, 0, w, h);

  // Grid
  ctx.strokeStyle = '#1a1a3a';
  ctx.lineWidth = 0.5;
  for (let y = 0; y <= h; y += h/4) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }

  const patch = patches[curPatch];
  if (!patch.operators.length) return;

  const margin = 10;
  const drawW = w - margin * 2;
  const drawH = h - margin * 2;

  // Draw all operator envelopes (selected op on top, in brighter color)
  patch.operators.forEach((op, oi) => {
    const isSelected = oi === selOp;
    if (isSelected) return; // draw last
    drawOneEnvelope(ctx, op, oi, margin, drawW, drawH, h, false);
  });
  drawOneEnvelope(ctx, patch.operators[selOp], selOp, margin, drawW, drawH, h, true);
}

// Slope for envelope visualization (approximate — real SCSP EG is in the WASM engine)
const EG_SLOPE = 12.0;

function drawOneEnvelope(ctx, op, oi, margin, drawW, drawH, h, isSelected) {
  // Compute time segments using actual SCSP rate tables + exponential model
  const arMs = AR_TIMES[Math.min(op.ar, 31)];
  const d1rMs = op.d1r > 0 ? DR_TIMES[Math.min(op.d1r, 31)] : 100000;
  const sustainLevel = op.dl < 31 ? 1.0 - op.dl / 31.0 : 0.0;
  const d2rMs = op.d2r > 0 ? DR_TIMES[Math.min(op.d2r, 31)] : 100000;
  const rrMs = DR_TIMES[Math.min(op.rr, 31)];

  // With EG_SLOPE=20, level reaches -60dB at T/3. Show visual segments
  // up to ~-40dB which happens at about T * (40/(20*8.686)) ≈ T * 0.23.
  const VIS_FRAC = 0.23;
  const d1VisMs = d1rMs * VIS_FRAC;
  const holdWindow = 500;  // ms of held note to display
  const rrVisMs = rrMs * VIS_FRAC;

  // Compute level at note-off after D2 decay during hold window
  // Exponential: level = sustain * exp(-EG_SLOPE * holdWindow / d2rMs)
  const d2decay = Math.exp(-EG_SLOPE * holdWindow / (d2rMs));
  const levelAtNoteOff = sustainLevel * d2decay;

  const totalMs = arMs + d1VisMs + holdWindow + rrVisMs;
  const scale = drawW / Math.max(totalMs, 100);
  const bottom = h - margin;
  const nSteps = 60; // curve resolution

  ctx.beginPath();
  let cx = margin;

  // Attack: linear ramp 0 → 1.0
  ctx.moveTo(cx, bottom);
  cx += arMs * scale;
  ctx.lineTo(cx, bottom - drawH);
  const d1StartX = cx;

  // D1: exponential approach from 1.0 to sustain
  for (let i = 1; i <= nSteps; i++) {
    const t = i / nSteps;
    const tMs = t * d1VisMs;
    // level = sustain + (1 - sustain) * exp(-EG_SLOPE * tMs / d1rMs)
    const lv = sustainLevel + (1.0 - sustainLevel) * Math.exp(-EG_SLOPE * tMs / d1rMs);
    ctx.lineTo(d1StartX + tMs * scale, bottom - drawH * lv);
  }
  cx = d1StartX + d1VisMs * scale;

  // D2 during hold window: exponential decay from sustain toward 0
  const d2StartX = cx;
  for (let i = 1; i <= nSteps; i++) {
    const t = i / nSteps;
    const tMs = t * holdWindow;
    const lv = sustainLevel * Math.exp(-EG_SLOPE * tMs / d2rMs);
    ctx.lineTo(d2StartX + tMs * scale, bottom - drawH * lv);
  }
  const noteOffX = d2StartX + holdWindow * scale;
  cx = noteOffX;

  // Release: exponential decay from levelAtNoteOff toward 0
  const relStartX = cx;
  for (let i = 1; i <= nSteps; i++) {
    const t = i / nSteps;
    const tMs = t * rrVisMs;
    const lv = levelAtNoteOff * Math.exp(-EG_SLOPE * tMs / rrMs);
    ctx.lineTo(relStartX + tMs * scale, bottom - drawH * lv);
  }

  if (isSelected) {
    ctx.strokeStyle = op.is_carrier ? '#00d4ff' : '#ffaa44';
    ctx.lineWidth = 2;
  } else {
    ctx.strokeStyle = op.is_carrier ? 'rgba(0,212,255,0.25)' : 'rgba(255,170,68,0.25)';
    ctx.lineWidth = 1;
  }
  ctx.stroke();

  if (isSelected) {
    // Fill under curve
    ctx.lineTo(relStartX + rrVisMs * scale, bottom);
    ctx.lineTo(margin, bottom);
    ctx.closePath();
    ctx.fillStyle = op.is_carrier ? 'rgba(0,212,255,0.08)' : 'rgba(255,170,68,0.08)';
    ctx.fill();

    // Note-off marker
    ctx.save();
    ctx.strokeStyle = '#666';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(noteOffX, margin);
    ctx.lineTo(noteOffX, bottom);
    ctx.stroke();
    ctx.restore();
    ctx.fillStyle = '#555';
    ctx.font = '8px monospace';
    ctx.fillText('note off', noteOffX + 3, margin + 10);

    // Segment labels
    ctx.fillStyle = '#555';
    ctx.font = '9px monospace';
    const segX = [margin, d1StartX, d2StartX, noteOffX, relStartX + rrVisMs * scale];
    const labels = ['AR', 'D1R', 'D2R', 'RR'];
    for (let i = 0; i < 4; i++) {
      const mx = (segX[i] + segX[i+1]) / 2;
      ctx.fillText(labels[i], mx - 8, h - 1);
    }

    // Time label
    document.getElementById('env-time-label').textContent =
      '(AR=' + Math.round(arMs) + 'ms D1=' + Math.round(d1rMs) +
      'ms D2=' + (op.d2r > 0 ? Math.round(d2rMs) + 'ms' : 'off') +
      ' RR=' + Math.round(rrMs) + 'ms)';
  }
}

// ═══════════════════════════════════════════════════════════════
// UI: Piano Keyboard
// ═══════════════════════════════════════════════════════════════

const NN = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
const whites = [0,2,4,5,7,9,11];
const blacks = {0:1, 2:3, 5:6, 7:8, 9:10};

function buildKB() {
  const kbEl = document.getElementById('kb');
  kbEl.innerHTML = '';
  for (let wi = 0; wi < whites.length; wi++) {
    (function(noteOff) {
      const midi = oct * 12 + noteOff;
      const k = document.createElement('div');
      k.className = 'wk';
      k.textContent = NN[noteOff] + oct;
      k.onmousedown = function() { k.classList.add('act'); playNote(midi); };
      k.onmouseup = function() { k.classList.remove('act'); stopNote(midi); };
      k.onmouseleave = function() { k.classList.remove('act'); stopNote(midi); };
      kbEl.appendChild(k);
      if (noteOff in blacks) {
        const bmidi = oct * 12 + blacks[noteOff];
        const bk = document.createElement('div');
        bk.className = 'bk';
        bk.textContent = NN[blacks[noteOff]];
        bk.onmousedown = function(e) { e.stopPropagation(); bk.classList.add('act'); playNote(bmidi); };
        bk.onmouseup = function() { bk.classList.remove('act'); stopNote(bmidi); };
        bk.onmouseleave = function() { bk.classList.remove('act'); stopNote(bmidi); };
        kbEl.appendChild(bk);
      }
    })(whites[wi]);
  }
  // C of next octave
  const midi = (oct + 1) * 12;
  const k = document.createElement('div');
  k.className = 'wk';
  k.textContent = 'C' + (oct + 1);
  k.onmousedown = function() { k.classList.add('act'); playNote(midi); };
  k.onmouseup = function() { k.classList.remove('act'); stopNote(midi); };
  k.onmouseleave = function() { k.classList.remove('act'); stopNote(midi); };
  kbEl.appendChild(k);
}

document.getElementById('oct-dn').onclick = () => { oct = Math.max(0, oct - 1); document.getElementById('oct-val').textContent = oct; buildKB(); };
document.getElementById('oct-up').onclick = () => { oct = Math.min(8, oct + 1); document.getElementById('oct-val').textContent = oct; buildKB(); };

const KM = {a:0, w:1, s:2, e:3, d:4, f:5, t:6, g:7, y:8, h:9, u:10, j:11, k:12};
const heldKeys = {};
document.addEventListener('keydown', function(ev) {
  if (ev.repeat) return;
  if (ev.target.tagName === 'INPUT' || ev.target.tagName === 'SELECT') return;
  const key = ev.key.toLowerCase();
  if (key === 'z') { oct = Math.max(0, oct - 1); document.getElementById('oct-val').textContent = oct; buildKB(); return; }
  if (key === 'x') { oct = Math.min(8, oct + 1); document.getElementById('oct-val').textContent = oct; buildKB(); return; }
  if (key in KM) {
    const midi = oct * 12 + KM[key] + (ev.shiftKey ? 12 : 0);
    if (!heldKeys[key]) {
      heldKeys[key] = midi;
      playNote(midi);
    }
  }
});
document.addEventListener('keyup', function(ev) {
  const key = ev.key.toLowerCase();
  if (key in KM && heldKeys[key] !== undefined) {
    stopNote(heldKeys[key]);
    delete heldKeys[key];
  }
});

// ═══════════════════════════════════════════════════════════════
// IMPORT / EXPORT
// ═══════════════════════════════════════════════════════════════

function exportFile() {
  // Export in saturn_kit.py compatible format
  const instruments = patches.map((p, i) => ({
    name: p.name,
    program: i,
    waveform: 'sine',
    base_note: 69,
    loop: true,
    fm_ops: p.operators.map(op => ({
      freq_ratio: op.freq_ratio,
      freq_fixed: op.freq_fixed || undefined,
      level: op.level,
      ar: op.ar,
      d1r: op.d1r,
      dl: op.dl,
      d2r: op.d2r,
      rr: op.rr,
      mdl: op.mdl,
      mod_source: op.mod_source,
      feedback: op.feedback,
      is_carrier: op.is_carrier,
      waveform: WAVE_NAMES[op.waveform || 0] || 'sine',
      loop_mode: op.loop_mode !== undefined ? op.loop_mode : 1,
      loop_start: op.loop_start || 0,
      loop_end: op.loop_end || WAVE_LEN,
    }))
  }));

  const config = { instruments };
  const json = JSON.stringify(config, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'fm_patches.json'; a.click();
  URL.revokeObjectURL(url);
}

function loadFile() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.json';
  input.onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const data = JSON.parse(ev.target.result);
        if (data.instruments) {
          // saturn_kit.py format
          patches = data.instruments.map(inst => ({
            name: inst.name,
            operators: (inst.fm_ops || []).map(op => ({
              freq_ratio: op.freq_ratio || 1.0,
              freq_fixed: op.freq_fixed || 0,
              level: op.level || 0.8,
              ar: op.ar !== undefined ? op.ar : 31,
              d1r: op.d1r || 0,
              dl: op.dl || 0,
              d2r: op.d2r || 0,
              rr: op.rr !== undefined ? op.rr : 14,
              mdl: op.mdl || 0,
              mod_source: op.mod_source !== undefined ? op.mod_source : -1,
              feedback: op.feedback || 0,
              is_carrier: op.is_carrier !== undefined ? op.is_carrier : true,
              waveform: typeof op.waveform === 'string' ? WAVE_NAMES.indexOf(op.waveform.charAt(0).toUpperCase() + op.waveform.slice(1)) : (op.waveform || 0),
              loop_mode: op.loop_mode !== undefined ? op.loop_mode : 1,
              loop_start: op.loop_start || 0,
              loop_end: op.loop_end || WAVE_LEN,
            }))
          })).filter(p => p.operators.length > 0);
        } else if (data.operators) {
          // Single patch (fm_sim.py format)
          patches = [{ name: data.name || 'Imported', operators: data.operators.map(op => ({
            freq_ratio: op.freq_ratio || 1.0,
            freq_fixed: op.freq_fixed || 0,
            level: op.level || 0.8,
            ar: op.ar !== undefined ? op.ar : 31,
            d1r: op.d1r || 0,
            dl: op.dl || 0,
            d2r: op.d2r || 0,
            rr: op.rr !== undefined ? op.rr : 14,
            mdl: op.mdl || 0,
            mod_source: op.mod_source !== undefined ? op.mod_source : -1,
            feedback: op.feedback || 0,
            is_carrier: op.is_carrier !== undefined ? op.is_carrier : true,
            waveform: typeof op.waveform === 'string' ? WAVE_NAMES.indexOf(op.waveform.charAt(0).toUpperCase() + op.waveform.slice(1)) : (op.waveform || 0),
            loop_mode: op.loop_mode !== undefined ? op.loop_mode : 1,
            loop_start: op.loop_start || 0,
            loop_end: op.loop_end || WAVE_LEN,
          }))}];
        }
        if (patches.length === 0) {
          alert('No FM patches found in file.');
          return;
        }
        curPatch = 0; selOp = 0;
        renderAll();
      } catch(err) {
        alert('Error loading file: ' + err.message);
      }
    };
    reader.readAsText(file);
  };
  input.click();
}

function exportTonFile() {
  if (!TonIO) { alert('TON I/O not available'); return; }
  // Build custom waves map: "patchIdx:opIdx" → Float32Array
  const cw = {};
  // customWaves only stores waves for current patch's operators;
  // for a full export we regenerate built-in waveforms via generateWaveform.
  // Custom waves in customWaves dict are keyed by op index for current patch only,
  // so we skip them here (they'll be generated from the waveform type).

  const tonData = TonIO.exportTon(patches, generateWaveform, cw);
  const blob = new Blob([tonData], { type: 'application/octet-stream' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'fm_patches.ton'; a.click();
  URL.revokeObjectURL(url);
}

function loadTonFile() {
  if (!TonIO) { alert('TON I/O not available'); return; }
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.ton,.TON';
  input.onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const result = TonIO.importTon(ev.target.result);
        if (!result.patches || result.patches.length === 0) {
          alert('No voices found in TON file.');
          return;
        }
        // Convert imported patches to editor format
        patches = result.patches.map(p => ({
          name: p.name,
          operators: p.operators.map((op, oi) => ({
            freq_ratio: op.freq_ratio,
            freq_fixed: 0,
            level: op.level,
            ar: op.ar,
            d1r: op.d1r,
            dl: op.dl,
            d2r: op.d2r,
            rr: op.rr,
            mdl: op.mdl,
            mod_source: op.mod_source,
            feedback: op.feedback,
            is_carrier: op.is_carrier,
            // Imported waveforms are custom PCM — use waveform index 0 as placeholder
            waveform: 0,
            loop_mode: op.loop_mode,
            loop_start: op.loop_start,
            loop_end: op.loop_end,
          }))
        }));
        // Store imported PCM as custom waveforms so they render correctly
        for (let pi = 0; pi < result.patches.length; pi++) {
          for (let oi = 0; oi < result.patches[pi].operators.length; oi++) {
            const pcm = result.patches[pi].operators[oi].pcm;
            if (pcm && pcm.length > 0) {
              // customWaves is per-selected-patch; we'll store for current patch
              // and reload when switching patches
              if (pi === 0) customWaves[oi] = pcm;
            }
          }
        }
        // Stash all imported PCM on the patch objects for later access
        for (let pi = 0; pi < result.patches.length; pi++) {
          for (let oi = 0; oi < result.patches[pi].operators.length; oi++) {
            if (!patches[pi]._importedPcm) patches[pi]._importedPcm = {};
            patches[pi]._importedPcm[oi] = result.patches[pi].operators[oi].pcm;
          }
        }
        curPatch = 0; selOp = 0;
        renderAll();
      } catch (err) {
        alert('Error loading TON: ' + err.message);
      }
    };
    reader.readAsArrayBuffer(file);
  };
  input.click();
}

function mergeToKitFile() {
  if (!TonIO) { alert('TON I/O not available'); return; }
  // Step 1: Pick existing .ton file
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.ton,.TON';
  input.onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const existingBuffer = ev.target.result;
        // Step 2: Ask which program slot
        const slot = parseInt(prompt('Program slot number (0-15) for patch "' + patches[curPatch].name + '":', curPatch));
        if (isNaN(slot) || slot < 0 || slot > 15) { alert('Invalid slot number.'); return; }
        // Step 3: Merge current patch into that slot
        const patch = {
          name: patches[curPatch].name,
          operators: patches[curPatch].operators.map(op => ({
            freq_ratio: op.freq_ratio,
            level: op.level, ar: op.ar, d1r: op.d1r, dl: op.dl, d2r: op.d2r, rr: op.rr,
            mdl: op.mdl, mod_source: op.mod_source, feedback: op.feedback, is_carrier: op.is_carrier,
            waveform: op.waveform, loop_mode: op.loop_mode !== undefined ? op.loop_mode : 1,
            loop_start: op.loop_start || 0, loop_end: op.loop_end || WAVE_LEN,
          })),
        };
        const merged = TonIO.mergeTon(existingBuffer, slot, patch, generateWaveform);
        // Step 4: Download the merged file
        const blob = new Blob([merged], { type: 'application/octet-stream' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = file.name; a.click();
        URL.revokeObjectURL(url);
      } catch (err) {
        alert('Merge error: ' + err.message);
      }
    };
    reader.readAsArrayBuffer(file);
  };
  input.click();
}

async function exportWav() {
  await initSCSP();
  const patch = patches[curPatch];
  const note = oct * 12 + 0; // C of current octave
  const sr = 44100;
  const duration = 1.0;
  const release = 0.5;
  const totalSamples = Math.floor((duration + release) * sr);
  const noteOnSamples = Math.floor(duration * sr);

  // Re-init SCSP for clean render
  scsp._scsp_init();
  const ramPtr = scsp._scsp_get_ram_ptr();
  for (let i = 0; i < SINE_CYCLE_LEN; i++) {
    const val = Math.round(Math.sin(2 * Math.PI * i / SINE_CYCLE_LEN) * 32767);
    scsp.HEAPU8[ramPtr + i * 2]     = val & 0xFF;
    scsp.HEAPU8[ramPtr + i * 2 + 1] = (val >> 8) & 0xFF;
  }

  // Program slots
  for (let i = 0; i < patch.operators.length; i++) {
    programSlot(i, patch.operators[i], note, patch.operators);
  }
  for (let i = 0; i < patch.operators.length; i++) scsp._scsp_key_on(i);

  // Render note-on portion
  const bufPtr1 = scsp._scsp_render(noteOnSamples);
  const onData = new Int16Array(noteOnSamples * 2);
  onData.set(new Int16Array(scsp.HEAP16.buffer, bufPtr1, noteOnSamples * 2));

  // Key off, render release
  for (let i = 0; i < patch.operators.length; i++) scsp._scsp_key_off(i);
  const relSamples = totalSamples - noteOnSamples;
  const bufPtr2 = scsp._scsp_render(relSamples);
  const offData = new Int16Array(relSamples * 2);
  offData.set(new Int16Array(scsp.HEAP16.buffer, bufPtr2, relSamples * 2));

  // Combine to mono (mix L+R)
  const output = new Float32Array(totalSamples);
  for (let i = 0; i < noteOnSamples; i++) {
    output[i] = (onData[i*2] + onData[i*2+1]) / 65536.0;
  }
  for (let i = 0; i < relSamples; i++) {
    output[noteOnSamples + i] = (offData[i*2] + offData[i*2+1]) / 65536.0;
  }

  // Normalize
  let peak = 0;
  for (let i = 0; i < output.length; i++) if (Math.abs(output[i]) > peak) peak = Math.abs(output[i]);
  if (peak > 0.001) for (let i = 0; i < output.length; i++) output[i] = output[i] / peak * 0.9;

  // Re-init SCSP for live playback (export clobbers state)
  scsp._scsp_init();
  for (let i = 0; i < SINE_CYCLE_LEN; i++) {
    const val = Math.round(Math.sin(2 * Math.PI * i / SINE_CYCLE_LEN) * 32767);
    scsp.HEAPU8[ramPtr + i * 2]     = val & 0xFF;
    scsp.HEAPU8[ramPtr + i * 2 + 1] = (val >> 8) & 0xFF;
  }

  // Encode WAV
  const wavBuf = new ArrayBuffer(44 + totalSamples * 2);
  const view = new DataView(wavBuf);
  function writeStr(off, str) { for (let i = 0; i < str.length; i++) view.setUint8(off+i, str.charCodeAt(i)); }
  writeStr(0, 'RIFF');
  view.setUint32(4, 36 + totalSamples * 2, true);
  writeStr(8, 'WAVE');
  writeStr(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sr, true);
  view.setUint32(28, sr * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, 'data');
  view.setUint32(40, totalSamples * 2, true);
  for (let i = 0; i < totalSamples; i++) {
    view.setInt16(44 + i * 2, Math.max(-32768, Math.min(32767, Math.round(output[i] * 32000))), true);
  }

  const blob = new Blob([wavBuf], { type: 'audio/wav' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = patch.name.replace(/[^a-zA-Z0-9]/g, '_') + '.wav';
  a.click();
  URL.revokeObjectURL(url);
}

// ═══════════════════════════════════════════════════════════════
// RENDER ALL
// ═══════════════════════════════════════════════════════════════

function renderAll() {
  // Restore imported PCM waveforms when switching patches
  const p = patches[curPatch];
  if (p && p._importedPcm) {
    for (const [oi, pcm] of Object.entries(p._importedPcm)) {
      customWaves[parseInt(oi)] = pcm;
    }
  }
  renderPatchList();
  renderOpGraph();
  renderOpParams();
  drawEnvelope();
}

// ═══════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════

initPatches();
renderAll();
buildKB();
window.addEventListener('resize', () => { drawEnvelope(); drawModArrows(); });
</script>
</body>
</html>"""


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Saturn SCSP FM Patch Editor')
    parser.add_argument('--load', help='Load patches from JSON file')
    parser.add_argument('-o', '--output', help='Output HTML file (default: temp file)')
    parser.add_argument('--no-open', action='store_true', help='Do not open in browser')
    args = parser.parse_args()

    presets_json = "null"
    if args.load:
        with open(args.load) as f:
            presets_json = f.read()

    html = generate_html(presets_json)

    if args.output:
        out_path = args.output
    else:
        fd, out_path = tempfile.mkstemp(suffix='.html', prefix='fm_editor_')
        os.close(fd)

    with open(out_path, 'w') as f:
        f.write(html)

    print(f"[fm_editor] Generated: {out_path}")

    if not args.no_open:
        url = 'file://' + os.path.abspath(out_path)
        print(f"  Opening: {url}")
        webbrowser.open(url)


if __name__ == '__main__':
    main()
