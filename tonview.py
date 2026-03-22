#!/usr/bin/env python3
"""
tonview.py — Saturn TON file viewer and sample player.

Parses a .TON file and generates a self-contained HTML page with
interactive waveform display and Web Audio API playback.

Usage:
  python3 tonview.py file.ton [-o output.html]
"""

import struct
import sys
import os
import base64
import json

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def note_name(n):
    if n < 0 or n > 127:
        return '?'
    return f"{NOTE_NAMES[n % 12]}{n // 12 - 1}"


def parse_ton(data):
    offmix = struct.unpack('>H', data[0:2])[0]
    nvoices = (offmix - 8) // 2

    voices = []
    for vi in range(nvoices):
        voff = struct.unpack('>H', data[8 + vi * 2:10 + vi * 2])[0]
        bend_range = data[voff] & 0xF
        portamento = data[voff + 1]
        nlayers = struct.unpack('b', bytes([data[voff + 2]]))[0] + 1
        vol_bias = struct.unpack('b', bytes([data[voff + 3]]))[0]

        layers = []
        for li in range(nlayers):
            loff = voff + 4 + li * 0x20
            layer = data[loff:loff + 0x20]

            start_note = layer[0x00]
            end_note = layer[0x01]
            lpctl = (layer[0x03] >> 5) & 3
            pcm8b = (layer[0x03] >> 4) & 1
            sa_addr = ((layer[0x03] & 0xF) << 16) | struct.unpack('>H', layer[0x04:0x06])[0]
            lsa = struct.unpack('>H', layer[0x06:0x08])[0]
            lea = struct.unpack('>H', layer[0x08:0x0A])[0]
            d2r = layer[0x0A] >> 3
            d1r = ((layer[0x0A] & 0x7) << 2) | (layer[0x0B] >> 6)
            ar = layer[0x0B] & 0x1F
            krs = (layer[0x0C] >> 3) & 0x7
            dl = ((layer[0x0C] & 0x3) << 3) | (layer[0x0D] >> 5)
            rr = layer[0x0D] & 0x1F
            tl = layer[0x0F]
            disdl = layer[0x18] >> 5
            dipan = layer[0x18] & 0x1F
            base_note = layer[0x19]
            fine_tune = struct.unpack('b', bytes([layer[0x1A]]))[0]

            # Extract PCM as raw LE int16 bytes, then base64 encode
            sample_size = 1 if pcm8b else 2
            num_samples = lea if lea > 0 else 0
            raw_le = bytearray()
            for si in range(num_samples):
                addr = sa_addr + si * sample_size
                if addr + sample_size > len(data):
                    break
                if pcm8b:
                    val = struct.unpack('b', data[addr:addr + 1])[0] * 256
                else:
                    val = struct.unpack('>h', data[addr:addr + 2])[0]
                raw_le += struct.pack('<h', max(-32768, min(32767, val)))

            b64 = base64.b64encode(raw_le).decode('ascii')

            layers.append({
                'sn': start_note, 'en': end_note,
                'bn': base_note, 'ft': fine_tune,
                'snn': note_name(start_note), 'enn': note_name(end_note),
                'bnn': note_name(base_note),
                'p8': pcm8b, 'lp': lpctl,
                'sa': sa_addr, 'lsa': lsa, 'lea': lea,
                'ar': ar, 'd1r': d1r, 'dl': dl, 'd2r': d2r, 'rr': rr,
                'tl': tl, 'disdl': disdl, 'dipan': dipan, 'krs': krs,
                'ns': num_samples, 'b64': b64,
            })

        voices.append({
            'i': vi, 'br': bend_range,
            'po': portamento, 'vb': vol_bias,
            'nl': nlayers, 'layers': layers,
        })

    return voices


def generate_html(voices, filename, file_size):
    basename = os.path.basename(filename)
    ton_json = json.dumps(voices)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>TON Viewer - {basename}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'SF Mono', Consolas, Monaco, monospace; background: #0f0f23; color: #ccc; display: flex; height: 100vh; }}
#sidebar {{ width: 280px; background: #1a1a2e; overflow-y: auto; border-right: 1px solid #333; padding: 8px; flex-shrink: 0; }}
#main {{ flex: 1; display: flex; flex-direction: column; padding: 16px; overflow-y: auto; }}
h2 {{ color: #00d4ff; font-size: 14px; margin-bottom: 8px; }}
.voice-hdr {{ padding: 4px 8px; cursor: pointer; border-radius: 4px; font-size: 12px; color: #aaa; }}
.voice-hdr:hover {{ background: #2a2a4e; }}
.layer-item {{ padding: 3px 8px 3px 20px; cursor: pointer; border-radius: 4px; font-size: 11px; color: #888; }}
.layer-item:hover {{ background: #2a2a4e; }}
.layer-item.sel {{ background: #2a3a5e; color: #fff; }}
#info {{ font-size: 12px; line-height: 1.6; margin-bottom: 12px; white-space: pre; }}
#wv-box {{ background: #1a1a2e; border-radius: 8px; border: 1px solid #333; margin-bottom: 12px; }}
canvas {{ width: 100%; height: 200px; display: block; border-radius: 8px; }}
#kb {{ display: flex; margin-top: 8px; position: relative; height: 90px; }}
.wk {{ background: #ddd; color: #333; width: 38px; height: 80px; border: 1px solid #999; cursor: pointer;
       display: flex; align-items: flex-end; justify-content: center; padding-bottom: 4px;
       font-size: 10px; border-radius: 0 0 4px 4px; user-select: none; z-index: 1; }}
.wk:hover,.wk.act {{ background: #00d4ff; color: #000; }}
.bk {{ background: #222; color: #999; width: 26px; height: 52px; border: 1px solid #555; cursor: pointer;
       display: flex; align-items: flex-end; justify-content: center; padding-bottom: 2px;
       font-size: 9px; border-radius: 0 0 3px 3px; user-select: none; z-index: 2;
       margin-left: -14px; margin-right: -14px; }}
.bk:hover,.bk.act {{ background: #0088aa; color: #fff; }}
#oct-ctl {{ margin-top: 8px; font-size: 12px; color: #888; }}
#oct-ctl button {{ background: #2a2a4e; color: #ccc; border: 1px solid #555; padding: 4px 12px;
                   cursor: pointer; border-radius: 4px; margin: 0 4px; }}
</style>
</head>
<body>
<div id="sidebar">
  <h2>{basename}</h2>
  <div style="font-size:11px;color:#666;margin-bottom:8px;">{file_size} bytes, {len(voices)} voices</div>
  <div id="vlist"></div>
</div>
<div id="main">
  <div id="info">Select a layer to view its waveform and parameters.</div>
  <div id="wv-box"><canvas id="wv"></canvas></div>
  <div>
    <h2>Play (click keys or use A-K on keyboard, Z/X = octave)</h2>
    <div id="kb"></div>
    <div id="oct-ctl">
      Octave: <button id="oct-dn">&laquo;</button>
      <span id="oct-val">4</span>
      <button id="oct-up">&raquo;</button>
    </div>
  </div>
</div>
<script>
// Data is parsed inline to avoid string replacement issues
var V = {ton_json};

// Decode base64 to Float32Array
function dec(b64) {{
  var bin = atob(b64);
  var n = bin.length / 2;
  var out = new Float32Array(n);
  for (var i = 0; i < n; i++) {{
    var lo = bin.charCodeAt(i * 2);
    var hi = bin.charCodeAt(i * 2 + 1);
    var val = lo | (hi << 8);
    if (val >= 0x8000) val -= 0x10000;
    out[i] = val / 32768.0;
  }}
  return out;
}}

// Decode all samples
for (var vi = 0; vi < V.length; vi++) {{
  for (var li = 0; li < V[vi].layers.length; li++) {{
    var l = V[vi].layers[li];
    l.pcm = dec(l.b64);
    delete l.b64;
  }}
}}

var curL = null;
var oct = 4;
var actx = null;
var curSrc = null;
var curGain = null;
var NN = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];

function ensureAudio() {{
  if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)();
  if (actx.state === 'suspended') actx.resume();
  return actx;
}}

// Build sidebar
var vlist = document.getElementById('vlist');
for (var vi = 0; vi < V.length; vi++) {{
  (function(vi) {{
    var v = V[vi];
    var hdr = document.createElement('div');
    hdr.className = 'voice-hdr';
    hdr.textContent = 'Voice ' + v.i + '  (' + v.nl + ' layer' + (v.nl > 1 ? 's' : '') + ', bend=' + v.br + ')';
    vlist.appendChild(hdr);
    for (var li = 0; li < v.layers.length; li++) {{
      (function(li) {{
        var l = v.layers[li];
        var item = document.createElement('div');
        item.className = 'layer-item';
        var fmt = l.p8 ? '8bit' : '16bit';
        var lp = l.lp ? 'loop' : '-';
        item.textContent = 'L' + li + ' ' + l.snn + '-' + l.enn + '  base=' + l.bnn + '  ' + fmt + ' ' + lp + '  ' + l.ns + 'smp';
        item.onclick = function() {{ selLayer(vi, li, item); }};
        vlist.appendChild(item);
      }})(li);
    }}
  }})(vi);
}}

function stopSound() {{
  if (curSrc) {{
    try {{
      // Quick fade out to avoid click
      if (curGain && actx) {{
        curGain.gain.setValueAtTime(curGain.gain.value, actx.currentTime);
        curGain.gain.linearRampToValueAtTime(0, actx.currentTime + 0.05);
        var s = curSrc;
        setTimeout(function() {{ try {{ s.stop(); }} catch(e) {{}} }}, 60);
      }} else {{
        curSrc.stop();
      }}
    }} catch(e) {{}}
    curSrc = null;
    curGain = null;
  }}
}}

function selLayer(vi, li, el) {{
  stopSound();
  var all = document.querySelectorAll('.layer-item');
  for (var i = 0; i < all.length; i++) all[i].classList.remove('sel');
  if (el) el.classList.add('sel');
  var l = V[vi].layers[li];
  curL = l;
  var loopN = ['off','forward','reverse','alternating'];
  document.getElementById('info').textContent =
    'Voice ' + vi + ' Layer ' + li + '\\n' +
    '  Keys: ' + l.snn + ' - ' + l.enn + '\\n' +
    '  Base note: ' + l.bnn + ' (MIDI ' + l.bn + ')\\n' +
    '  Fine tune: ' + l.ft + ' cents\\n' +
    '  Format: ' + (l.p8 ? '8-bit' : '16-bit') + ' PCM\\n' +
    '  Samples: ' + l.ns + ' (' + (l.ns / 44100).toFixed(3) + 's @ 44.1kHz)\\n' +
    '  Loop: ' + loopN[l.lp] + ' (LSA=' + l.lsa + ' LEA=' + l.lea + ')\\n' +
    '  SA: 0x' + l.sa.toString(16).padStart(5, '0') + '\\n' +
    '  Envelope: AR=' + l.ar + ' D1R=' + l.d1r + ' DL=' + l.dl + ' D2R=' + l.d2r + ' RR=' + l.rr + '\\n' +
    '  TL: ' + l.tl + ' (' + (l.tl * 0.375).toFixed(1) + ' dB atten)\\n' +
    '  Output: DISDL=' + l.disdl + ' DIPAN=' + l.dipan;
  drawWave(l);
}}

function drawWave(l) {{
  var canvas = document.getElementById('wv');
  var rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * (window.devicePixelRatio || 1);
  canvas.height = 200 * (window.devicePixelRatio || 1);
  canvas.style.height = '200px';
  var ctx = canvas.getContext('2d');
  ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);
  var w = rect.width, h = 200;
  ctx.fillStyle = '#1a1a2e';
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = '#333355';
  ctx.setLineDash([2, 4]);
  ctx.beginPath(); ctx.moveTo(0, h/2); ctx.lineTo(w, h/2); ctx.stroke();
  ctx.setLineDash([]);
  var smp = l.pcm;
  if (!smp || !smp.length) return;
  var n = smp.length;
  if (l.lp && l.lsa < n && l.lea <= n) {{
    var lx = l.lsa / n * w, ex = l.lea / n * w;
    ctx.fillStyle = '#1a2a1a';
    ctx.fillRect(lx, 0, ex - lx, h);
    ctx.strokeStyle = '#44aa44'; ctx.setLineDash([3,3]);
    ctx.beginPath(); ctx.moveTo(lx, 0); ctx.lineTo(lx, h); ctx.stroke();
    ctx.strokeStyle = '#aa4444';
    ctx.beginPath(); ctx.moveTo(ex, 0); ctx.lineTo(ex, h); ctx.stroke();
    ctx.setLineDash([]);
  }}
  var peak = 0;
  for (var i = 0; i < n; i++) if (Math.abs(smp[i]) > peak) peak = Math.abs(smp[i]);
  if (peak === 0) peak = 1;
  var sy = (h / 2 - 10) / peak;
  ctx.strokeStyle = '#00d4ff'; ctx.lineWidth = 1;
  ctx.beginPath();
  var step = Math.max(1, Math.floor(n / w));
  for (var i = 0; i < n; i += step) {{
    var x = i / n * w, y = h / 2 - smp[i] * sy;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }}
  ctx.stroke();
}}

function playNote(midi) {{
  if (!curL || !curL.pcm || !curL.pcm.length) return;
  var c = ensureAudio();
  var l = curL;
  var semi = midi - l.bn - l.ft / 100;
  var rate = Math.pow(2, semi / 12);
  var smp = l.pcm;
  var bufLen, bufData, loopStart, loopEnd, isLoop;

  if (l.lp && l.lsa < smp.length && l.lsa < l.lea) {{
    // Looped: build buffer with attack + enough loops to sustain (~10 seconds)
    var pre = Array.prototype.slice.call(smp, 0, l.lsa);
    var body = Array.prototype.slice.call(smp, l.lsa);
    isLoop = body.length > 0;
    if (isLoop) {{
      loopStart = pre.length;
      var target = 44100 * 10; // 10 seconds max sustain
      while (pre.length < target) {{
        for (var j = 0; j < body.length && pre.length < target; j++) pre.push(body[j]);
      }}
      loopEnd = pre.length;
    }}
    bufLen = pre.length;
    bufData = pre;
  }} else {{
    bufLen = smp.length;
    bufData = smp;
    isLoop = false;
  }}

  var buf = c.createBuffer(1, bufLen, 44100);
  var ch = buf.getChannelData(0);
  for (var i = 0; i < bufLen; i++) ch[i] = bufData[i];

  stopSound();

  // Use a gain node for release fade
  var gain = c.createGain();
  gain.gain.value = 1.0;
  gain.connect(c.destination);

  var src = c.createBufferSource();
  src.buffer = buf;
  src.playbackRate.value = rate;
  if (isLoop) {{
    src.loop = true;
    src.loopStart = loopStart / 44100;
    src.loopEnd = loopEnd / 44100;
  }}
  src.connect(gain);
  src.start();
  curSrc = src;
  curGain = gain;
  src.onended = function() {{ if (curSrc === src) curSrc = null; }};
}}

// Build piano keyboard
var kbEl = document.getElementById('kb');
var whites = [0,2,4,5,7,9,11];
var blacks = {{0:1, 2:3, 5:6, 7:8, 9:10}};

function buildKB() {{
  kbEl.innerHTML = '';
  for (var wi = 0; wi < whites.length; wi++) {{
    (function(noteOff) {{
      var midi = oct * 12 + noteOff;
      var k = document.createElement('div');
      k.className = 'wk';
      k.textContent = NN[noteOff] + oct;
      k.onmousedown = function() {{ k.classList.add('act'); ensureAudio(); playNote(midi); }};
      k.onmouseup = function() {{ k.classList.remove('act'); stopSound(); }};
      k.onmouseleave = function() {{ k.classList.remove('act'); stopSound(); }};
      kbEl.appendChild(k);
      if (noteOff in blacks) {{
        var bmidi = oct * 12 + blacks[noteOff];
        var bk = document.createElement('div');
        bk.className = 'bk';
        bk.textContent = NN[blacks[noteOff]];
        bk.onmousedown = function(e) {{ e.stopPropagation(); bk.classList.add('act'); ensureAudio(); playNote(bmidi); }};
        bk.onmouseup = function() {{ bk.classList.remove('act'); stopSound(); }};
        bk.onmouseleave = function() {{ bk.classList.remove('act'); stopSound(); }};
        kbEl.appendChild(bk);
      }}
    }})(whites[wi]);
  }}
  // C of next octave
  var midi = (oct + 1) * 12;
  var k = document.createElement('div');
  k.className = 'wk';
  k.textContent = 'C' + (oct + 1);
  k.onmousedown = function() {{ k.classList.add('act'); ensureAudio(); playNote(midi); }};
  k.onmouseup = function() {{ k.classList.remove('act'); stopSound(); }};
  k.onmouseleave = function() {{ k.classList.remove('act'); stopSound(); }};
  kbEl.appendChild(k);
}}

document.getElementById('oct-dn').onclick = function() {{ oct = Math.max(0, oct - 1); document.getElementById('oct-val').textContent = oct; buildKB(); }};
document.getElementById('oct-up').onclick = function() {{ oct = Math.min(8, oct + 1); document.getElementById('oct-val').textContent = oct; buildKB(); }};

var KM = {{a:0, w:1, s:2, e:3, d:4, f:5, t:6, g:7, y:8, h:9, u:10, j:11, k:12}};
document.addEventListener('keydown', function(ev) {{
  if (ev.repeat) return;
  var key = ev.key.toLowerCase();
  if (key === 'z') {{ oct = Math.max(0, oct - 1); document.getElementById('oct-val').textContent = oct; buildKB(); return; }}
  if (key === 'x') {{ oct = Math.min(8, oct + 1); document.getElementById('oct-val').textContent = oct; buildKB(); return; }}
  if (key in KM) {{ ensureAudio(); playNote(oct * 12 + KM[key] + (ev.shiftKey ? 12 : 0)); }}
}});
document.addEventListener('keyup', function(ev) {{
  var key = ev.key.toLowerCase();
  if (key in KM) stopSound();
}});

window.addEventListener('resize', function() {{ if (curL) drawWave(curL); }});

buildKB();
</script>
</body>
</html>"""


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tonview.py <file.ton> [-o output.html]")
        sys.exit(1)

    ton_path = sys.argv[1]
    out_path = None
    if '-o' in sys.argv:
        out_path = sys.argv[sys.argv.index('-o') + 1]
    else:
        out_path = os.path.splitext(ton_path)[0] + '.html'

    with open(ton_path, 'rb') as f:
        data = f.read()

    voices = parse_ton(data)
    html = generate_html(voices, ton_path, len(data))

    with open(out_path, 'w') as f:
        f.write(html)

    print(f"[tonview] {out_path} ({os.path.getsize(out_path) // 1024}KB, {len(voices)} voices)")
    print(f"  Open in browser: file://{os.path.abspath(out_path)}")


if __name__ == '__main__':
    main()
