#!/usr/bin/env python3
"""
saturn_tracker.py — Bebhionn — Saturn SCSP FM Tracker.

Browser-based classic vertical tracker for composing music using the
hardware-accurate SCSP (YMF292-F) emulator. Exports SEQ + TON files
directly for use on Sega Saturn.

Usage:
  python3 saturn_tracker.py                     # Open tracker in browser
  python3 saturn_tracker.py -o tracker.html     # Save to specific file
  python3 saturn_tracker.py --no-open           # Generate without opening
  python3 saturn_tracker.py --dev -o tracker.html  # Dev mode: external JS files

Architecture: generates a self-contained HTML file with embedded WASM,
same pattern as fm_editor.py. No server required.

Dev mode (--dev): emits <script src="tools/..."> tags instead of inlining
JS, so you can edit the JS files and just reload the browser. WASM is
fetched at runtime. Must be served from the repo root (or use --dev with
-o to place the HTML there).
"""

import base64
import json
import os
import sys
import tempfile
import webbrowser


# JS modules loaded by the tracker, in dependency order.
# Each entry: (placeholder, filename, fallback)
_JS_MODULES = [
    ('ton_io.js',          "var TonIO = null;"),
    ('note_util.js',       "const NOTE_NAMES = []; function noteName() { return '???'; }"),
    ('midi_io.js',         "function parseMIDI() { throw new Error('midi_io.js not found'); } function buildMIDI() { throw new Error('midi_io.js not found'); }"),
    ('seq_io.js',          "function parseSEQ() { throw new Error('seq_io.js not found'); } function buildSEQ() { throw new Error('seq_io.js not found'); }"),
    ('tracker_state.js',   "var TrackerState = { NUM_CHANNELS: 8, create: function() { return {}; } };"),
    ('tracker_playback.js',"var TrackerPlayback = { create: function() { return {}; } };"),
    ('scsp_engine.js',     "var SCSPEngine = {};"),
    ('tracker_ui.js',      "var TrackerUI = { init: function() {} };"),
    ('scsp_panels.js',  "var SCSPPanels = { init: function() {} };"),
    ('scspdspasm.js',      "function scspdspAssemble(){return {errors:['assembler not found'],mpro:new Uint16Array(512),coef:new Int16Array(64),madrs:new Uint16Array(32),rbl:0,steps:0};}"),
]


def generate_html(bundled=True):
    """Generate the tracker HTML.

    Args:
        bundled: If True (default), produce a self-contained HTML with all JS/WASM
                 inlined.  If False, emit <script src="..."> tags referencing
                 external files (for development — edit JS and just reload).
    """
    tools_dir = os.path.dirname(__file__)

    def load_file(filename, mode='r'):
        p = os.path.join(tools_dir, filename)
        if os.path.exists(p):
            with open(p, mode) as f:
                return f.read()
        return None

    # ── Build the <script> block that replaces __SCRIPTS__ ──────────
    script_lines = []

    if bundled:
        # Inline every JS module
        for filename, fallback in _JS_MODULES:
            content = load_file(filename) or fallback
            script_lines.append(f'<script>\n{content}\n</script>')

        # Inline WASM binary + Emscripten glue
        wasm_bytes = load_file(os.path.join('scsp_wasm', 'scsp.wasm'), mode='rb')
        glue_js = load_file(os.path.join('scsp_wasm', 'scsp.js'))
        if wasm_bytes and glue_js:
            wasm_b64 = base64.b64encode(wasm_bytes).decode('ascii')
        else:
            print("[tracker] WARNING: SCSP WASM not found. Run 'make' in tools/scsp_wasm/")
            wasm_b64 = ""
            glue_js = "var SCSPModule = () => Promise.resolve(null);"

        # Embed demo MIDI + example TON files so the JS can reference them
        demo_midi_b64 = ""
        demo_path = os.path.join(tools_dir, '..', 'examples', 'kit_demo.mid')
        if os.path.exists(demo_path):
            with open(demo_path, 'rb') as f:
                demo_midi_b64 = base64.b64encode(f.read()).decode('ascii')

        example_tons = {}
        ton_dir = os.path.join(tools_dir, '..', 'test_ton')
        if os.path.isdir(ton_dir):
            for fn in sorted(os.listdir(ton_dir)):
                if fn.upper().endswith('.TON'):
                    with open(os.path.join(ton_dir, fn), 'rb') as f:
                        example_tons[fn] = base64.b64encode(f.read()).decode('ascii')

        # The inlined JS modules contain __DEMO_MIDI_B64__ / __EXAMPLE_TONS_JSON__
        # placeholders that were baked into tracker_ui.js — patch them now.
        patched = '\n'.join(script_lines)
        patched = patched.replace('__DEMO_MIDI_B64__', demo_midi_b64)
        patched = patched.replace('__EXAMPLE_TONS_JSON__', json.dumps(example_tons))
        script_lines = [patched]

        script_lines.append(
            '<script>\n'
            f"const SCSP_WASM_B64 = '{wasm_b64}';\n"
            f'{glue_js}\n\n'
            '// Bootstrap\n'
            'var state = TrackerState.create(SCSPEngine.getPresets());\n'
            'var playback = TrackerPlayback.create(state, SCSPEngine);\n'
            'TrackerUI.init(state, playback, SCSPEngine);\n'
            'SCSPPanels.init(state, SCSPEngine, TrackerUI);\n'
            '</script>'
        )

    else:
        # External script references — for development
        for filename, _fallback in _JS_MODULES:
            script_lines.append(f'<script src="tools/{filename}"></script>')

        # WASM + glue loaded at runtime via fetch; bootstrap is async
        script_lines.append(
            '<script src="tools/scsp_wasm/scsp.js"></script>\n'
            '<script>\n'
            '// Dev mode: fetch WASM binary and convert to base64 for the engine\n'
            '(async function() {\n'
            '  var resp = await fetch("tools/scsp_wasm/scsp.wasm");\n'
            '  if (resp.ok) {\n'
            '    var buf = await resp.arrayBuffer();\n'
            '    var bytes = new Uint8Array(buf);\n'
            '    var bin = "";\n'
            '    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);\n'
            '    window.SCSP_WASM_B64 = btoa(bin);\n'
            '  } else {\n'
            '    window.SCSP_WASM_B64 = "";\n'
            '    console.warn("SCSP WASM not found — run make in tools/scsp_wasm/");\n'
            '  }\n'
            '  // Bootstrap\n'
            '  var state = TrackerState.create(SCSPEngine.getPresets());\n'
            '  var playback = TrackerPlayback.create(state, SCSPEngine);\n'
            '  TrackerUI.init(state, playback, SCSPEngine);\n'
            '  SCSPPanels.init(state, SCSPEngine, TrackerUI);\n'
            '})();\n'
            '</script>'
        )

    html = _HTML_TEMPLATE.replace('__SCRIPTS__', '\n'.join(script_lines))
    return html


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Bebhionn</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'SF Mono', Consolas, Monaco, monospace; background: #0a0a1a; color: #ccc;
       display: flex; flex-direction: column; height: 100vh; overflow: hidden; user-select: none; }

/* Menu bar */
#menubar { display: flex; align-items: center; padding: 0 8px; background: #0e0e22;
           border-bottom: 1px solid #222; flex-shrink: 0; font-size: 11px; height: 24px; }
#menubar h1 { color: #00d4ff; font-size: 12px; margin-right: 12px; padding: 0 6px; }
.menu-item { position: relative; }
.menu-item > button { background: none; border: none; color: #999; cursor: pointer; padding: 3px 10px;
                      font-family: inherit; font-size: 11px; border-radius: 2px; }
.menu-item > button:hover, .menu-item.open > button { background: #1a1a3a; color: #ccc; }
.menu-dropdown { display: none; position: absolute; top: 100%; left: 0; min-width: 180px; z-index: 900;
                 background: #16162e; border: 1px solid #333; border-radius: 0 0 4px 4px;
                 box-shadow: 0 4px 12px #000a; padding: 4px 0; }
.menu-item.open .menu-dropdown { display: block; }
.menu-dropdown button { display: block; width: 100%; text-align: left; background: none; border: none;
                        color: #bbb; padding: 5px 14px; font-family: inherit; font-size: 11px;
                        cursor: pointer; white-space: nowrap; }
.menu-dropdown button:hover { background: #2a2a5a; color: #fff; }
.menu-dropdown .menu-sep { height: 1px; background: #333; margin: 4px 8px; }
.menu-dropdown .menu-section { padding: 4px 14px; display: flex; align-items: center; gap: 6px; }
.menu-dropdown .menu-section label { font-size: 10px; color: #888; white-space: nowrap; }
.menu-dropdown .menu-section select { background: #222; color: #ccc; border: 1px solid #444;
                                       font-family: inherit; font-size: 10px; border-radius: 2px;
                                       padding: 1px 3px; flex: 1; max-width: 140px; }
.menu-dropdown .menu-kbd { float: right; color: #555; font-size: 10px; margin-left: 20px; }

/* Transport bar */
#transport { display: flex; align-items: center; gap: 10px; padding: 6px 12px;
             background: #12122a; border-bottom: 1px solid #333; flex-shrink: 0; }
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
.ch-btn { padding: 1px 4px; border: 1px solid #444; border-radius: 2px; cursor: pointer;
          font-family: inherit; font-size: 8px; background: #1a1a2e; color: #666; }
.ch-btn:hover { background: #2a2a4e; }
.ch-btn.muted { background: #4a2a2a; color: #f88; border-color: #f44; }
.ch-btn.solo { background: #2a4a2a; color: #8f8; border-color: #4f4; }
.ch-hdr.muted { opacity: 0.4; }
.cell.ch-muted { opacity: 0.3; }

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
.cell .col-cursor { background: #00d4ff33; border-radius: 2px; padding: 0 1px; }
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
.op-param .val { color: #00d4ff; width: 42px; text-align: right; font-size: 9px;
  background: #1a1a2e; border: 1px solid #333; border-radius: 2px; padding: 0 2px;
  font-family: inherit; -moz-appearance: textfield; }
.op-param .val::-webkit-inner-spin-button,
.op-param .val::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
.op-param select { background: #222; color: #ccc; border: 1px solid #444; font-family: inherit;
                    font-size: 9px; border-radius: 2px; flex: 1; }
.op-tab { display: inline-block; padding: 2px 8px; background: #1a1a3a; border: 1px solid #333;
          border-bottom: none; border-radius: 4px 4px 0 0; cursor: pointer; font-size: 10px; color: #888; }
.op-tab:hover { background: #2a2a4e; }
.op-tab.sel { background: #222244; color: #00d4ff; }
.op-tab.carrier { color: #4a4; }

/* Instrument detail panel (expandable bottom) */
#inst-detail { height: 0; background: #12122a; border-top: 1px solid #333; flex-shrink: 0;
               overflow: hidden; transition: height 0.2s ease; display: flex; flex-direction: column; }
#inst-detail.open { height: 280px; }
#inst-detail-header { display: flex; align-items: center; padding: 4px 12px; gap: 8px;
                       background: #14142e; border-bottom: 1px solid #333; flex-shrink: 0; }
#inst-detail-header h3 { font-size: 11px; color: #00d4ff; flex: 1; }
#inst-detail-header button { background: #2a2a4e; color: #ccc; border: 1px solid #444; padding: 2px 8px;
                              cursor: pointer; border-radius: 3px; font-family: inherit; font-size: 10px; }
#inst-detail-header button:hover { background: #3a3a5e; }
#inst-detail-body { flex: 1; display: flex; gap: 12px; padding: 8px 12px; overflow-x: auto; min-height: 0; }
.detail-section { background: #1a1a2e; border: 1px solid #333; border-radius: 6px; padding: 8px;
                  display: flex; flex-direction: column; min-width: 0; }
.detail-section h4 { font-size: 10px; color: #888; margin-bottom: 4px; flex-shrink: 0; }
.detail-section canvas { width: 100%; flex: 1; display: block; border-radius: 4px; background: #12122a; min-height: 0; }
#env-section { flex: 2; }
#wave-section { flex: 1; }
#routing-section { flex: 1; min-width: 160px; position: relative; }
/* DSP panel — independent expandable bottom panel */
#dsp-panel { height: 0; background: #0d0d1a; border-top: 1px solid #333; flex-shrink: 0;
             overflow: hidden; transition: height 0.2s ease; display: flex; flex-direction: column; }
#dsp-panel.open { height: 300px; }
#dsp-panel-header { display: flex; align-items: center; padding: 4px 12px; gap: 6px;
                    background: #0f1a0f; border-bottom: 1px solid #333; flex-shrink: 0; }
#dsp-panel-header h3 { font-size: 11px; color: #4f8; margin: 0; }
#dsp-panel-header button { background: #2a3a4e; color: #ccc; border: 1px solid #444; padding: 2px 8px;
                            cursor: pointer; border-radius: 3px; font-family: inherit; font-size: 10px; }
#dsp-panel-header button:hover { background: #3a5a6e; }
#dsp-panel-header button.active { background: #1a5a3e; border-color: #4f8; color: #4f8; }
#dsp-panel-header .dsp-status { font-size: 9px; color: #666; }
#dsp-panel-header .dsp-error { color: #f66; }
#dsp-panel-body { flex: 1; display: flex; gap: 12px; padding: 8px 12px; min-height: 0; overflow: hidden; }
#dsp-code-col { flex: 3; display: flex; flex-direction: column; min-width: 0; }
#dsp-code-col textarea { flex: 1; width: 100%; background: #0a0a14; color: #8f8; border: 1px solid #333;
                          border-radius: 4px; font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 10px;
                          padding: 4px 6px; resize: none; tab-size: 2; line-height: 1.4; }
#dsp-code-col textarea:focus { outline: 1px solid #4f8; border-color: #4f8; }
#dsp-knobs-col { flex: 2; display: flex; flex-direction: column; min-width: 180px; overflow-y: auto; }
#dsp-knobs-col h4 { font-size: 10px; color: #888; margin: 0 0 6px 0; }
#dsp-knobs { display: flex; flex-direction: column; gap: 5px; }
.dsp-knob { display: flex; align-items: center; gap: 4px; }
.dsp-knob label { font-size: 9px; color: #aaa; min-width: 48px; text-align: right; }
.dsp-knob input[type=range] { flex: 1; height: 10px; min-width: 60px; }
.dsp-knob .dsp-knob-val { font-size: 9px; color: #8f8; min-width: 36px; text-align: right; font-family: monospace; }
#env-time-label { color: #555; font-weight: normal; font-size: 9px; }
#wave-controls { display: flex; gap: 6px; align-items: center; margin-top: 4px; flex-shrink: 0; font-size: 10px; }
#wave-controls select, #wave-controls input { background: #222; color: #ccc; border: 1px solid #444;
  font-family: inherit; font-size: 9px; border-radius: 2px; padding: 1px 3px; }
#wave-controls input[type="range"] { flex: 1; accent-color: #00d4ff; min-width: 50px; }
#wave-controls label { color: #888; white-space: nowrap; }
#wave-controls button { background: #2a3a2e; color: #8c8; border: 1px solid #4a4; padding: 2px 6px;
  cursor: pointer; border-radius: 3px; font-family: inherit; font-size: 9px; }
#wave-controls button:hover { background: #3a4a3e; }
#op-graph-mini { display: flex; gap: 6px; flex-wrap: wrap; align-items: flex-start; flex: 1; }
#op-graph-mini svg { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }
.op-box-mini { background: #222244; border: 2px solid #444; border-radius: 4px; padding: 4px 8px;
               cursor: pointer; text-align: center; font-size: 9px; user-select: none; z-index: 1; position: relative; }
.op-box-mini:hover { border-color: #666; }
.op-box-mini.sel { border-color: #00d4ff; }
.op-box-mini.carrier { border-color: #4a4; }
.op-box-mini.carrier.sel { border-color: #0f0; }
.op-box-mini .op-name { font-weight: bold; color: #ddd; font-size: 10px; }
.op-box-mini .op-role { font-size: 8px; }
.op-box-mini .op-role.car { color: #4a4; }
.op-box-mini .op-role.mod { color: #a84; }

#status { padding: 4px 12px; background: #12122a; border-top: 1px solid #333; font-size: 10px;
          color: #666; flex-shrink: 0; display: flex; gap: 20px; }
#status .info { color: #888; }

/* Keyboard overlay */
#kb-overlay { position: fixed; z-index: 1000; display: none; background: #12122aee;
              border: 1px solid #00d4ff44; border-radius: 6px; padding: 0; min-width: 340px;
              box-shadow: 0 4px 20px #000a; backdrop-filter: blur(4px); font-size: 10px; }
#kb-overlay.visible { display: block; }
#kb-overlay-header { display: flex; justify-content: space-between; align-items: center; padding: 5px 10px;
                     cursor: move; background: #1a1a3a; border-radius: 6px 6px 0 0; border-bottom: 1px solid #333;
                     user-select: none; }
#kb-overlay-header span { color: #00d4ff; font-weight: bold; font-size: 11px; }
#kb-overlay-close { background: none; border: none; color: #666; cursor: pointer; font-size: 14px;
                    font-family: inherit; padding: 0 4px; }
#kb-overlay-close:hover { color: #f66; }
#kb-overlay-body { padding: 8px 10px; }
.kb-section { margin-bottom: 8px; }
.kb-section-title { color: #00d4ff; font-size: 9px; text-transform: uppercase; letter-spacing: 1px;
                    margin-bottom: 4px; }
.kb-row { display: flex; gap: 2px; margin-bottom: 2px; }
.kb-key { display: inline-flex; align-items: center; justify-content: center; min-width: 22px; height: 22px;
          background: #1a1a3a; border: 1px solid #333; border-radius: 3px; color: #ccc; font-size: 9px;
          padding: 0 3px; }
.kb-key.black { background: #2a1a3a; border-color: #5a3a6a; color: #c8a; }
.kb-key.white { background: #1a2a3a; border-color: #3a5a6a; color: #8cf; }
.kb-key.nav { background: #1a2a1e; border-color: #3a5a3e; color: #8c8; }
.kb-key-label { font-size: 7px; color: #666; margin-left: 2px; }
.kb-shortcut-row { display: flex; gap: 8px; align-items: center; margin-bottom: 3px; color: #888; }
.kb-shortcut-row .kb-key { min-width: 18px; height: 18px; font-size: 8px; }
.kb-shortcut-label { font-size: 9px; }
</style>
</head>
<body>

<!-- Menu bar -->
<div id="menubar">
  <h1>Bebhionn</h1>
  <div class="menu-item" id="menu-file">
    <button onclick="menuToggle('menu-file')">File</button>
    <div class="menu-dropdown">
      <button onclick="importSEQ(); menuClose()">Import SEQ...</button>
      <button onclick="importTonForTracker(); menuClose()">Import TON...</button>
      <div class="menu-sep"></div>
      <button onclick="exportSEQ(); menuClose()">Export SEQ</button>
      <button onclick="exportTON(); menuClose()">Export TON</button>
      <div class="menu-sep"></div>
      <div class="menu-section">
        <label>Instruments:</label>
        <select id="ton-select" onchange="onTonSelect(this.value)">
          <option value="">-- Select TON --</option>
        </select>
      </div>
    </div>
  </div>
  <div class="menu-item" id="menu-view">
    <button onclick="menuToggle('menu-view')">View</button>
    <div class="menu-dropdown">
      <button onclick="toggleDspPanel(); menuClose()">DSP Effect Panel</button>
      <button onclick="toggleInstDetail(); menuClose()">Instrument Detail</button>
      <div class="menu-sep"></div>
      <button onclick="toggleKbOverlay(); menuClose()">Keyboard Map <span class="menu-kbd">F1</span></button>
    </div>
  </div>
  <div class="menu-item" id="menu-midi">
    <button onclick="menuToggle('menu-midi')">MIDI</button>
    <div class="menu-dropdown">
      <div class="menu-section">
        <label>Input:</label>
        <select id="midi-input" onchange="selectMidiInput(this.value)">
          <option value="">-- None --</option>
        </select>
      </div>
      <button id="btn-midi-live" onclick="toggleMidiLive(); menuClose()">Live Mode</button>
      <div class="menu-sep"></div>
      <button onclick="importMIDI(); menuClose()">Import MIDI...</button>
      <button onclick="exportMIDI(); menuClose()">Export MIDI</button>
    </div>
  </div>
  <div class="menu-item" id="menu-help">
    <button onclick="menuToggle('menu-help')">Help</button>
    <div class="menu-dropdown">
      <button onclick="toggleKbOverlay(); menuClose()">Keyboard Shortcuts <span class="menu-kbd">F1</span></button>
    </div>
  </div>
</div>

<!-- Transport -->
<div id="transport">
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
  <div class="transport-group">
    <label>Step</label>
    <input id="edit-step" type="number" value="1" min="0" max="16" style="width:35px;" title="Edit step — rows to advance after entering a note (0 = stay in place)">
  </div>
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
        <button onclick="toggleInstDetail()" style="background:#2a3a4e;color:#4cf;">Edit</button>
      </div>
      <div id="inst-editor"></div>
    </div>
  </div>
</div>

<!-- Instrument detail panel (expandable) -->
<div id="inst-detail">
  <div id="inst-detail-header">
    <h3 id="inst-detail-title">Instrument Editor</h3>
    <span id="env-time-label"></span>
    <select id="wave-preset" onchange="applyWavePreset(this.value)" style="background:#222;color:#ccc;border:1px solid #444;font-family:inherit;font-size:10px;border-radius:2px;padding:2px 4px;">
      <option value="" disabled selected>Wave preset...</option>
    </select>
    <button onclick="loadWavForOp()">Load WAV</button>
    <button onclick="toggleInstDetail()">Close</button>
  </div>
  <div id="inst-detail-body">
    <div class="detail-section" id="env-section">
      <h4>Envelope</h4>
      <canvas id="env-canvas"></canvas>
    </div>
    <div class="detail-section" id="wave-section">
      <h4>Waveform</h4>
      <canvas id="wave-canvas"></canvas>
      <div id="wave-controls"></div>
    </div>
    <div class="detail-section" id="routing-section">
      <h4>Routing</h4>
      <svg id="routing-svg"></svg>
      <div id="op-graph-mini"></div>
    </div>
  </div>
</div>

<!-- DSP Effect Panel (independent) -->
<div id="dsp-panel">
  <div id="dsp-panel-header">
    <h3>DSP Effect</h3>
    <button onclick="dspCompile()" title="Compile & load (Ctrl+Enter)">Compile</button>
    <button id="dsp-enable-btn" onclick="dspToggleEnable()">Enable</button>
    <label style="font-size:9px;color:#aaa;">Send:</label>
    <input type="range" id="dsp-send" min="0" max="7" value="7" step="1"
           style="width:48px;height:10px;" oninput="dspUpdateSend(this.value)">
    <label style="font-size:9px;color:#aaa;">RBL:</label>
    <select id="dsp-rbl" style="background:#222;color:#ccc;border:1px solid #444;font-size:9px;padding:1px;">
      <option value="0">8Kw</option><option value="1" selected>16Kw</option>
      <option value="2">32Kw</option><option value="3">64Kw</option>
    </select>
    <button onclick="dspLoadExb()" title="Load .EXB file">Load EXB</button>
    <span class="dsp-status" id="dsp-status"></span>
    <span style="flex:1"></span>
    <button onclick="toggleDspPanel()">Close</button>
  </div>
  <div id="dsp-panel-body">
    <div id="dsp-code-col">
      <textarea id="dsp-code" spellcheck="false">' Delay effect — edit and press Compile (Ctrl+Enter)
' Memory reads/writes are auto-aligned to odd DSP steps.
' (The assembler inserts NOPs if needed.)

#COEF
Send = %100
Fb = %40
Dry = %50
Wet = %75

#ADRS
wa = ms0.0
ra = ms200.0

#PROG
' Read delayed sample from ring buffer
NOP                                    ' step 0 (even) — align
MR MR[ra + DEC]                        ' step 1 (ODD) — memory read works
NOP                                    ' step 2 (even) — pipeline delay
IW MEMS00                              ' step 3 — store read value
' Write input + feedback to delay line
@ MIXS00 * Send + (MEMS00 * Fb +)     ' steps 4-5 — compute
NOP                                    ' step 6 (even) — align
> MW[wa + DEC]                         ' step 7 (ODD) — memory write works
' Output: dry + wet to left and right
@ MIXS00 * Dry + (MEMS00 * Wet +)     ' steps 8-9
> S1 EFREG00                           ' step 10 — left out
@ MIXS00 * Dry + (MEMS00 * Wet +)     ' steps 11-12
> S1 EFREG01                           ' step 13 — right out

=END</textarea>
    </div>
    <div id="dsp-knobs-col">
      <h4>Parameters</h4>
      <div id="dsp-knobs"></div>
    </div>
  </div>
</div>

<!-- Status -->
<div id="status">
  <span class="info" id="status-pos">Row: 00</span>
  <span class="info" id="status-inst">Inst: 00</span>
  <span class="info" id="status-msg"></span>
</div>

__SCRIPTS__

<!-- Keyboard mapping overlay -->
<div id="kb-overlay">
  <div id="kb-overlay-header">
    <span>Keyboard Map</span>
    <button id="kb-overlay-close" onclick="toggleKbOverlay()">&times;</button>
  </div>
  <div id="kb-overlay-body">
    <div class="kb-section">
      <div class="kb-section-title">Piano Keys (lower octave)</div>
      <div class="kb-row">
        <span class="kb-key black" style="margin-left:15px;">S<span class="kb-key-label">C#</span></span>
        <span class="kb-key black">D<span class="kb-key-label">D#</span></span>
        <span style="width:24px;"></span>
        <span class="kb-key black">G<span class="kb-key-label">F#</span></span>
        <span class="kb-key black">H<span class="kb-key-label">G#</span></span>
        <span class="kb-key black">J<span class="kb-key-label">A#</span></span>
      </div>
      <div class="kb-row">
        <span class="kb-key white">Z<span class="kb-key-label">C</span></span>
        <span class="kb-key white">X<span class="kb-key-label">D</span></span>
        <span class="kb-key white">C<span class="kb-key-label">E</span></span>
        <span class="kb-key white">V<span class="kb-key-label">F</span></span>
        <span class="kb-key white">B<span class="kb-key-label">G</span></span>
        <span class="kb-key white">N<span class="kb-key-label">A</span></span>
        <span class="kb-key white">M<span class="kb-key-label">B</span></span>
      </div>
    </div>
    <div class="kb-section">
      <div class="kb-section-title">Piano Keys (upper octave)</div>
      <div class="kb-row">
        <span class="kb-key black" style="margin-left:15px;">2<span class="kb-key-label">C#</span></span>
        <span class="kb-key black">3<span class="kb-key-label">D#</span></span>
        <span style="width:24px;"></span>
        <span class="kb-key black">5<span class="kb-key-label">F#</span></span>
        <span class="kb-key black">6<span class="kb-key-label">G#</span></span>
        <span class="kb-key black">7<span class="kb-key-label">A#</span></span>
      </div>
      <div class="kb-row">
        <span class="kb-key white">Q<span class="kb-key-label">C</span></span>
        <span class="kb-key white">W<span class="kb-key-label">D</span></span>
        <span class="kb-key white">E<span class="kb-key-label">E</span></span>
        <span class="kb-key white">R<span class="kb-key-label">F</span></span>
        <span class="kb-key white">T<span class="kb-key-label">G</span></span>
        <span class="kb-key white">Y<span class="kb-key-label">A</span></span>
        <span class="kb-key white">U<span class="kb-key-label">B</span></span>
        <span class="kb-key white">I<span class="kb-key-label">C+</span></span>
        <span class="kb-key white">O<span class="kb-key-label">D+</span></span>
        <span class="kb-key white">P<span class="kb-key-label">E+</span></span>
      </div>
    </div>
    <div class="kb-section">
      <div class="kb-section-title">Shortcuts</div>
      <div class="kb-shortcut-row"><span class="kb-key nav">Space</span> <span class="kb-shortcut-label">Play / Stop</span></div>
      <div class="kb-shortcut-row"><span class="kb-key nav">&uarr;</span><span class="kb-key nav">&darr;</span> <span class="kb-shortcut-label">Navigate rows</span></div>
      <div class="kb-shortcut-row"><span class="kb-key nav">&larr;</span><span class="kb-key nav">&rarr;</span> <span class="kb-shortcut-label">Note / Inst / Vol columns</span></div>
      <div class="kb-shortcut-row"><span class="kb-key nav">Tab</span> <span class="kb-shortcut-label">Next channel</span> &nbsp;<span class="kb-key nav">Shift</span>+<span class="kb-key nav">Tab</span> <span class="kb-shortcut-label">Prev</span></div>
      <div class="kb-shortcut-row"><span class="kb-key nav">.</span> or <span class="kb-key nav">`</span> <span class="kb-shortcut-label">Note off</span></div>
      <div class="kb-shortcut-row"><span class="kb-key nav">Del</span> <span class="kb-shortcut-label">Clear cell</span> &nbsp;<span class="kb-key nav">Bksp</span> <span class="kb-shortcut-label">Clear + move up</span></div>
      <div class="kb-shortcut-row"><span class="kb-key nav">0-F</span> <span class="kb-shortcut-label">Hex input (Inst/Vol columns)</span></div>
      <div class="kb-shortcut-row"><span class="kb-key nav">F1</span> <span class="kb-shortcut-label">Toggle this overlay</span></div>
    </div>
  </div>
</div>

<script>
// Menu bar: toggle dropdowns, close on outside click
function menuToggle(id) {
    var item = document.getElementById(id);
    var wasOpen = item.classList.contains('open');
    menuClose();
    if (!wasOpen) item.classList.add('open');
}
function menuClose() {
    var items = document.querySelectorAll('.menu-item.open');
    for (var i = 0; i < items.length; i++) items[i].classList.remove('open');
}
// Hovering over sibling menu items while one is open switches the dropdown
document.getElementById('menubar').addEventListener('mouseover', function(e) {
    if (!document.querySelector('.menu-item.open')) return;
    var item = e.target.closest('.menu-item');
    if (item && !item.classList.contains('open')) {
        menuClose();
        item.classList.add('open');
    }
});
// Click outside closes menus
document.addEventListener('mousedown', function(e) {
    if (!e.target.closest('#menubar')) menuClose();
});

// Keyboard overlay: toggle, drag, F1 shortcut
function toggleKbOverlay() {
    var el = document.getElementById('kb-overlay');
    el.classList.toggle('visible');
    if (el.classList.contains('visible') && !el.dataset.positioned) {
        el.style.right = '280px';
        el.style.top = '60px';
        el.dataset.positioned = '1';
    }
}

(function() {
    var overlay = document.getElementById('kb-overlay');
    var header = document.getElementById('kb-overlay-header');
    var dragging = false, ox = 0, oy = 0;

    header.addEventListener('mousedown', function(e) {
        dragging = true;
        ox = e.clientX - overlay.offsetLeft;
        oy = e.clientY - overlay.offsetTop;
        e.preventDefault();
    });
    document.addEventListener('mousemove', function(e) {
        if (!dragging) return;
        overlay.style.left = (e.clientX - ox) + 'px';
        overlay.style.top = (e.clientY - oy) + 'px';
        overlay.style.right = 'auto';
    });
    document.addEventListener('mouseup', function() { dragging = false; });

    // F1 toggles overlay
    document.addEventListener('keydown', function(e) {
        if (e.key === 'F1') { e.preventDefault(); toggleKbOverlay(); }
    });
})();
</script>
</body>
</html>"""


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Bebhionn — Saturn SCSP FM Tracker')
    parser.add_argument('-o', '--output', help='Output HTML file')
    parser.add_argument('--no-open', action='store_true', help='Do not open in browser')
    parser.add_argument('--dev', action='store_true',
                        help='Dev mode: emit <script src="..."> tags instead of '
                             'inlining JS. Edit JS files and reload the browser.')
    args = parser.parse_args()

    html = generate_html(bundled=not args.dev)

    if args.output:
        out_path = args.output
    else:
        fd, out_path = tempfile.mkstemp(suffix='.html', prefix='bebhionn_')
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
