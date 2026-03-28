/**
 * @module scsp_panels
 * @description SCSP-specific panels: instrument detail (envelope, waveform, routing),
 * DSP effect editor, and MIDI input handling. Uses only the SCSPEngine public API —
 * not loaded for other sound engines.
 */
var SCSPPanels = (function() {
    'use strict';

    var state, engine, ui;

    // ═══════════════════════════════════════════════════════════════
    // INSTRUMENT DETAIL PANEL (envelope, waveform, routing)
    // ═══════════════════════════════════════════════════════════════

    function toggleInstDetail() {
        var panel = document.getElementById('inst-detail');
        panel.classList.toggle('open');
        if (panel.classList.contains('open')) {
            document.getElementById('dsp-panel').classList.remove('open');
            panel.addEventListener('transitionend', function onEnd() {
                panel.removeEventListener('transitionend', onEnd);
                refreshInstDetail();
            });
        }
    }

    function refreshInstDetail() {
        var panel = document.getElementById('inst-detail');
        if (!panel.classList.contains('open')) return;
        var inst = state.instruments[ui.getSelectedInst()];
        if (!inst) return;
        document.getElementById('inst-detail-title').textContent =
            inst.name + ' \u2014 Op' + (ui.getSelectedOp() + 1);
        var wps = document.getElementById('wave-preset');
        if (wps.options.length <= 1) {
            engine.WAVE_NAMES.forEach(function(name, i) {
                var o = document.createElement('option'); o.value = i; o.textContent = name;
                wps.appendChild(o);
            });
        }
        wps.selectedIndex = 0;
        drawEnvelope();
        drawWaveformPreview();
        drawRouting();
        renderWaveControls();
    }

    function applyWavePreset(val) {
        var wid = parseInt(val);
        if (isNaN(wid)) return;
        var inst = state.instruments[ui.getSelectedInst()];
        if (!inst) return;
        var op = inst.operators[ui.getSelectedOp()];
        if (!op) return;
        op.waveform = wid;
        op.useTonSA = false;
        op.loop_start = 0;
        op.loop_end = engine.WAVE_LEN;
        op.loop_mode = 1;
        delete engine.customWaves[ui.getSelectedInst() + '_' + ui.getSelectedOp()];
        engine.syncRawRegs(op);
        engine.liveUpdatePreview(state.instruments, ui.getSelectedInst(), ui.getSelectedOp());
        refreshInstDetail();
        document.getElementById('wave-preset').selectedIndex = 0;
    }

    // --- Envelope visualization ---

    var EG_SLOPE = 12.0;

    function drawEnvelope() {
        var canvas = document.getElementById('env-canvas');
        if (!canvas) return;
        var rect = canvas.parentElement.getBoundingClientRect();
        var dpr = window.devicePixelRatio || 1;
        canvas.width = rect.width * dpr;
        canvas.height = (rect.height - 20) * dpr;
        canvas.style.height = (rect.height - 20) + 'px';
        var ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        var w = rect.width, h = rect.height - 20;

        ctx.fillStyle = '#12122a';
        ctx.fillRect(0, 0, w, h);

        ctx.strokeStyle = '#1a1a3a'; ctx.lineWidth = 0.5;
        for (var y = 0; y <= h; y += h / 4) {
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
        }

        var inst = state.instruments[ui.getSelectedInst()];
        if (!inst || !inst.operators.length) return;

        var margin = 10;
        var drawW = w - margin * 2;
        var drawH = h - margin * 2;

        inst.operators.forEach(function(op, oi) {
            if (oi === ui.getSelectedOp()) return;
            drawOneEnvelope(ctx, op, oi, margin, drawW, drawH, h, false);
        });
        drawOneEnvelope(ctx, inst.operators[ui.getSelectedOp()], ui.getSelectedOp(), margin, drawW, drawH, h, true);
    }

    function drawOneEnvelope(ctx, op, oi, margin, drawW, drawH, h, isSelected) {
        var AR_TIMES = engine.AR_TIMES, DR_TIMES = engine.DR_TIMES;
        var arMs = AR_TIMES[Math.min(op.ar, 31)];
        var d1rMs = op.d1r > 0 ? DR_TIMES[Math.min(op.d1r, 31)] : 100000;
        var sustainLevel = op.dl < 31 ? 1.0 - op.dl / 31.0 : 0.0;
        var d2rMs = op.d2r > 0 ? DR_TIMES[Math.min(op.d2r, 31)] : 100000;
        var rrMs = DR_TIMES[Math.min(op.rr, 31)];

        var VIS_FRAC = 0.23;
        var d1VisMs = d1rMs * VIS_FRAC;
        var holdWindow = 500;
        var rrVisMs = rrMs * VIS_FRAC;

        var d2decay = Math.exp(-EG_SLOPE * holdWindow / d2rMs);
        var levelAtNoteOff = sustainLevel * d2decay;

        var totalMs = arMs + d1VisMs + holdWindow + rrVisMs;
        var scale = drawW / Math.max(totalMs, 100);
        var bottom = h - margin;
        var nSteps = 60;

        ctx.beginPath();
        var cx = margin;

        ctx.moveTo(cx, bottom);
        cx += arMs * scale;
        ctx.lineTo(cx, bottom - drawH);
        var d1StartX = cx;

        for (var i = 1; i <= nSteps; i++) {
            var t = i / nSteps;
            var tMs = t * d1VisMs;
            var lv = sustainLevel + (1.0 - sustainLevel) * Math.exp(-EG_SLOPE * tMs / d1rMs);
            ctx.lineTo(d1StartX + tMs * scale, bottom - drawH * lv);
        }
        cx = d1StartX + d1VisMs * scale;

        var d2StartX = cx;
        for (var i = 1; i <= nSteps; i++) {
            var t = i / nSteps;
            var tMs = t * holdWindow;
            var lv = sustainLevel * Math.exp(-EG_SLOPE * tMs / d2rMs);
            ctx.lineTo(d2StartX + tMs * scale, bottom - drawH * lv);
        }
        var noteOffX = d2StartX + holdWindow * scale;
        cx = noteOffX;

        var relStartX = cx;
        for (var i = 1; i <= nSteps; i++) {
            var t = i / nSteps;
            var tMs = t * rrVisMs;
            var lv = levelAtNoteOff * Math.exp(-EG_SLOPE * tMs / rrMs);
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
            ctx.lineTo(relStartX + rrVisMs * scale, bottom);
            ctx.lineTo(margin, bottom);
            ctx.closePath();
            ctx.fillStyle = op.is_carrier ? 'rgba(0,212,255,0.08)' : 'rgba(255,170,68,0.08)';
            ctx.fill();

            ctx.save();
            ctx.strokeStyle = '#666'; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
            ctx.beginPath(); ctx.moveTo(noteOffX, margin); ctx.lineTo(noteOffX, bottom); ctx.stroke();
            ctx.restore();
            ctx.fillStyle = '#555'; ctx.font = '8px monospace';
            ctx.fillText('note off', noteOffX + 3, margin + 10);

            ctx.fillStyle = '#555'; ctx.font = '9px monospace';
            var segX = [margin, d1StartX, d2StartX, noteOffX, relStartX + rrVisMs * scale];
            var labels = ['AR', 'D1R', 'D2R', 'RR'];
            for (var i = 0; i < 4; i++) {
                var mx = (segX[i] + segX[i + 1]) / 2;
                ctx.fillText(labels[i], mx - 8, h - 1);
            }

            document.getElementById('env-time-label').textContent =
                'AR=' + Math.round(arMs) + 'ms D1=' + Math.round(d1rMs) +
                'ms D2=' + (op.d2r > 0 ? Math.round(d2rMs) + 'ms' : 'off') +
                ' RR=' + Math.round(rrMs) + 'ms';
        }
    }

    // --- Waveform preview ---

    function drawWaveformPreview() {
        var canvas = document.getElementById('wave-canvas');
        if (!canvas) return;
        var selectedInst = ui.getSelectedInst(), selectedOp = ui.getSelectedOp();
        var inst = state.instruments[selectedInst];
        if (!inst || !inst.operators.length) return;
        var op = inst.operators[selectedOp];
        if (!op) return;

        var rect = canvas.parentElement.getBoundingClientRect();
        var dpr = window.devicePixelRatio || 1;
        canvas.width = rect.width * dpr;
        var ch = rect.height - 60;
        canvas.height = Math.max(ch, 40) * dpr;
        canvas.style.height = Math.max(ch, 40) + 'px';
        var ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        var w = rect.width, h = Math.max(ch, 40);
        ctx.fillStyle = '#12122a'; ctx.fillRect(0, 0, w, h);

        var WAVE_LEN = engine.WAVE_LEN;
        var samples;
        var customKey = selectedInst + '_' + selectedOp;
        if (engine.customWaves[customKey]) {
            samples = engine.customWaves[customKey];
        } else if (op.useTonSA && op.rawRegs) {
            var sa = ((op.rawRegs.d0 & 0x0F) << 16) | op.rawRegs.sa;
            var numSamples = Math.max(op.rawRegs.lea || op.loop_end || WAVE_LEN, 64);
            samples = engine.readRamPCM(sa, numSamples, op.pcm8b);
            if (!samples) samples = engine.generateWaveform(op.waveform || 0, WAVE_LEN);
        } else {
            samples = engine.generateWaveform(op.waveform || 0, WAVE_LEN);
        }
        var n = samples.length;
        var lsa = op.loop_start || 0;
        var lea = op.loop_end || n;
        var lm = op.loop_mode !== undefined ? op.loop_mode : 1;

        if (lm > 0 && lea > lsa) {
            var lx = lsa / n * w, ex = lea / n * w;
            ctx.fillStyle = '#1a2a1a'; ctx.fillRect(lx, 0, ex - lx, h);
            ctx.strokeStyle = '#44aa44'; ctx.setLineDash([2, 3]); ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(lx, 0); ctx.lineTo(lx, h); ctx.stroke();
            ctx.strokeStyle = '#aa4444';
            ctx.beginPath(); ctx.moveTo(ex, 0); ctx.lineTo(ex, h); ctx.stroke();
            ctx.setLineDash([]);
        }

        ctx.strokeStyle = '#00d4ff'; ctx.lineWidth = 1; ctx.beginPath();
        for (var i = 0; i < n; i++) {
            var x = i / n * w, y = h / 2 - samples[i] * (h / 2 - 4);
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();

        ctx.strokeStyle = '#333'; ctx.setLineDash([2, 4]); ctx.lineWidth = 0.5;
        ctx.beginPath(); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = '#555'; ctx.font = '9px monospace';
        var WAVE_NAMES = engine.WAVE_NAMES, LOOP_NAMES = engine.LOOP_NAMES;
        var isCustom = !!engine.customWaves[customKey];
        var isTonPCM = op.useTonSA && op.rawRegs;
        var waveLabel = isCustom ? 'Custom (' + n + ' smp)' : isTonPCM ? 'PCM ' + (op.pcm8b ? '8-bit' : '16-bit') + ' (' + n + ' smp)' : (WAVE_NAMES[op.waveform || 0] || '?');
        ctx.fillText(waveLabel, 4, 12);
        ctx.fillText(lm > 0 ? LOOP_NAMES[lm] + ' ' + lsa + '-' + lea : 'No loop', 4, h - 4);
    }

    function renderWaveControls() {
        var el = document.getElementById('wave-controls');
        el.innerHTML = '';
        var selectedInst = ui.getSelectedInst(), selectedOp = ui.getSelectedOp();
        var inst = state.instruments[selectedInst];
        if (!inst || !inst.operators.length) return;
        var op = inst.operators[selectedOp];
        if (!op) return;

        var LOOP_NAMES = engine.LOOP_NAMES, WAVE_LEN = engine.WAVE_LEN;

        var lmLbl = document.createElement('label'); lmLbl.textContent = 'Loop:';
        var lmSel = document.createElement('select');
        LOOP_NAMES.forEach(function(name, i) {
            var o = document.createElement('option'); o.value = i; o.textContent = name;
            if (i === (op.loop_mode !== undefined ? op.loop_mode : 1)) o.selected = true;
            lmSel.appendChild(o);
        });
        lmSel.onchange = function() {
            op.loop_mode = parseInt(lmSel.value);
            engine.syncRawRegs(op);
            engine.liveUpdatePreview(state.instruments, selectedInst, selectedOp);
            drawWaveformPreview();
        };
        el.appendChild(lmLbl); el.appendChild(lmSel);

        var customKey = selectedInst + '_' + selectedOp;
        var waveLen = WAVE_LEN;
        if (engine.customWaves[customKey]) {
            waveLen = engine.customWaves[customKey].length;
        } else if (op.useTonSA && op.rawRegs) {
            waveLen = op.rawRegs.lea || op.loop_end || WAVE_LEN;
        } else {
            waveLen = engine.getWaveLength(op.waveform || 0);
        }

        var lsLbl = document.createElement('label'); lsLbl.textContent = 'Start:';
        var lsInp = document.createElement('input'); lsInp.type = 'range'; lsInp.min = 0; lsInp.max = waveLen; lsInp.step = 1;
        lsInp.value = op.loop_start || 0;
        lsInp.oninput = function() {
            op.loop_start = parseInt(lsInp.value);
            engine.syncRawRegs(op);
            engine.liveUpdatePreview(state.instruments, selectedInst, selectedOp);
            drawWaveformPreview();
        };
        el.appendChild(lsLbl); el.appendChild(lsInp);

        var leLbl = document.createElement('label'); leLbl.textContent = 'End:';
        var leInp = document.createElement('input'); leInp.type = 'range'; leInp.min = 0; leInp.max = waveLen; leInp.step = 1;
        leInp.value = op.loop_end || waveLen;
        leInp.oninput = function() {
            op.loop_end = parseInt(leInp.value);
            engine.syncRawRegs(op);
            engine.liveUpdatePreview(state.instruments, selectedInst, selectedOp);
            drawWaveformPreview();
        };
        el.appendChild(leLbl); el.appendChild(leInp);
    }

    // --- Routing graph ---

    function drawRouting() {
        var container = document.getElementById('op-graph-mini');
        var svg = document.getElementById('routing-svg');
        container.innerHTML = ''; svg.innerHTML = '';

        var selectedInst = ui.getSelectedInst(), selectedOp = ui.getSelectedOp();
        var inst = state.instruments[selectedInst];
        if (!inst) return;

        inst.operators.forEach(function(op, i) {
            var box = document.createElement('div');
            box.className = 'op-box-mini' + (i === selectedOp ? ' sel' : '') + (op.is_carrier ? ' carrier' : '');
            box.innerHTML = '<div class="op-name">Op' + (i + 1) + '</div>' +
                '<div class="op-role ' + (op.is_carrier ? 'car' : 'mod') + '">' +
                (op.is_carrier ? 'C' : 'M') + '</div>';
            box.onclick = (function(idx) { return function() {
                ui.setSelectedOp(idx);
                ui.renderInstEditor();
                refreshInstDetail();
            }; })(i);
            container.appendChild(box);
        });

        requestAnimationFrame(function() {
            svg.innerHTML = '';
            var boxes = container.querySelectorAll('.op-box-mini');
            var secRect = document.getElementById('routing-section').getBoundingClientRect();

            inst.operators.forEach(function(op, i) {
                if (op.mod_source >= 0 && op.mod_source < boxes.length && i < boxes.length) {
                    var sr = boxes[op.mod_source].getBoundingClientRect();
                    var dr = boxes[i].getBoundingClientRect();
                    var x1 = sr.left + sr.width / 2 - secRect.left;
                    var y1 = sr.top + sr.height / 2 - secRect.top;
                    var x2 = dr.left + dr.width / 2 - secRect.left;
                    var y2 = dr.top + dr.height / 2 - secRect.top;

                    var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                    line.setAttribute('x1', x1); line.setAttribute('y1', y1);
                    line.setAttribute('x2', x2); line.setAttribute('y2', y2);
                    line.setAttribute('stroke', '#a84'); line.setAttribute('stroke-width', '2');
                    line.setAttribute('stroke-dasharray', '4,3');
                    svg.appendChild(line);

                    var angle = Math.atan2(y2 - y1, x2 - x1);
                    var headLen = 8;
                    var cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
                    var poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
                    var p1x = cx + headLen * Math.cos(angle);
                    var p1y = cy + headLen * Math.sin(angle);
                    var p2x = cx - headLen * Math.cos(angle - 0.5);
                    var p2y = cy - headLen * Math.sin(angle - 0.5);
                    var p3x = cx - headLen * Math.cos(angle + 0.5);
                    var p3y = cy - headLen * Math.sin(angle + 0.5);
                    poly.setAttribute('points', p1x + ',' + p1y + ' ' + p2x + ',' + p2y + ' ' + p3x + ',' + p3y);
                    poly.setAttribute('fill', '#a84');
                    svg.appendChild(poly);
                }

                if (op.feedback > 0 && i < boxes.length) {
                    var br = boxes[i].getBoundingClientRect();
                    var bx = br.left + br.width / 2 - secRect.left;
                    var by = br.top - secRect.top;
                    var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                    path.setAttribute('d', 'M ' + (bx - 10) + ',' + by + ' C ' + (bx - 15) + ',' + (by - 20) + ' ' + (bx + 15) + ',' + (by - 20) + ' ' + (bx + 10) + ',' + by);
                    path.setAttribute('stroke', '#866'); path.setAttribute('stroke-width', '1.5');
                    path.setAttribute('fill', 'none'); path.setAttribute('stroke-dasharray', '3,2');
                    svg.appendChild(path);
                }
            });
        });
    }

    // --- WAV import ---

    function parseWav(buf) {
        var v = new DataView(buf);
        var tag = function(o) { return String.fromCharCode(v.getUint8(o), v.getUint8(o+1), v.getUint8(o+2), v.getUint8(o+3)); };
        if (tag(0) !== 'RIFF' || tag(8) !== 'WAVE') throw new Error('Not a WAV file');
        var fmt = null, dOff = 0, dSize = 0, pos = 12;
        while (pos < v.byteLength - 8) {
            var id = tag(pos), sz = v.getUint32(pos + 4, true);
            if (id === 'fmt ') fmt = { ch: v.getUint16(pos+10, true), sr: v.getUint32(pos+12, true), bits: v.getUint16(pos+22, true) };
            else if (id === 'data') { dOff = pos + 8; dSize = sz; }
            pos += 8 + sz; if (pos % 2) pos++;
        }
        if (!fmt || !dOff) throw new Error('Invalid WAV');
        var bps = fmt.bits / 8, nf = Math.floor(dSize / (bps * fmt.ch));
        var out = new Float32Array(nf);
        for (var i = 0; i < nf; i++) {
            var o = dOff + i * bps * fmt.ch;
            out[i] = fmt.bits === 16 ? v.getInt16(o, true) / 32768 : fmt.bits === 8 ? (v.getUint8(o) - 128) / 128 : 0;
        }
        return { samples: out };
    }

    function resampleTo(input, targetLen) {
        var out = new Float32Array(targetLen);
        var ratio = input.length / targetLen;
        for (var i = 0; i < targetLen; i++) {
            var si = i * ratio, idx = Math.floor(si), fr = si - idx;
            out[i] = input[Math.min(idx, input.length - 1)] * (1 - fr) + input[Math.min(idx + 1, input.length - 1)] * fr;
        }
        return out;
    }

    function loadWavForOp() {
        var input = document.createElement('input');
        input.type = 'file'; input.accept = '.wav,audio/wav';
        input.onchange = function(e) {
            var file = e.target.files[0];
            if (!file) return;
            var reader = new FileReader();
            reader.onload = function(ev) {
                try {
                    engine.init().then(function() {
                        var result = parseWav(ev.target.result);
                        var selectedInst = ui.getSelectedInst(), selectedOp = ui.getSelectedOp();
                        var inst = state.instruments[selectedInst];
                        var op = inst.operators[selectedOp];

                        var samples = result.samples;
                        if (samples.length !== engine.WAVE_LEN) {
                            samples = resampleTo(samples, engine.WAVE_LEN);
                        }

                        var wid = engine.addWaveform(samples, 0, samples.length, 1);
                        op.waveform = wid;
                        op.loop_start = 0;
                        op.loop_end = samples.length;
                        op.loop_mode = 1;
                        engine.customWaves[selectedInst + '_' + selectedOp] = samples;
                        engine.syncRawRegs(op);
                        refreshInstDetail();
                        ui.renderInstEditor();
                    });
                } catch (err) { alert('WAV error: ' + err.message); }
            };
            reader.readAsArrayBuffer(file);
        };
        input.click();
    }

    // ═══════════════════════════════════════════════════════════════
    // DSP EFFECT EDITOR
    // ═══════════════════════════════════════════════════════════════

    var dspState = {
        enabled: false,
        compiled: false,
        sendLevel: 7,
        rbl: 1,
        coefNames: [],
        madrsNames: [],
    };

    function toggleDspPanel() {
        var panel = document.getElementById('dsp-panel');
        panel.classList.toggle('open');
        if (panel.classList.contains('open')) {
            document.getElementById('inst-detail').classList.remove('open');
        }
    }

    function dspCompile() {
        if (!engine.isReady()) { dspSetStatus('SCSP not ready', true); return; }
        var code = document.getElementById('dsp-code').value;
        var rbl = parseInt(document.getElementById('dsp-rbl').value) || 0;
        dspState.rbl = rbl;

        var result = scspdspAssemble(code, { rbl: rbl });
        if (result.errors.length) { dspSetStatus(result.errors[0], true); return; }
        if (result.steps === 0) { dspSetStatus('No program steps', true); return; }

        engine.dspLoadProgram(result.mpro, result.coef, result.madrs, rbl);

        dspState.compiled = true;
        var statusMsg = result.steps + ' steps loaded';
        if (result.warnings && result.warnings.length) {
            statusMsg += ' (' + result.warnings.length + ' NOP' +
                (result.warnings.length > 1 ? 's' : '') + ' inserted for alignment)';
        }
        dspSetStatus(statusMsg, false);

        dspExtractKnobs(code, result);

        if (!dspState.enabled) dspToggleEnable();
        dspApplySendToActiveSlots();
    }

    function dspExtractKnobs(code, result) {
        dspState.coefNames = [];
        dspState.madrsNames = [];

        var section = null;
        var coefIdx = 1;
        var adrsIdx = 0;
        var lines = code.split(String.fromCharCode(10));
        for (var li = 0; li < lines.length; li++) {
            var line = lines[li].split("'")[0].trim();
            if (!line) continue;
            var u = line.toUpperCase();
            if (u === '#COEF') { section = 'COEF'; continue; }
            if (u === '#ADRS') { section = 'ADRS'; continue; }
            if (u === '#PROG' || u === '#END' || u === '=END') { section = null; continue; }
            var m = line.match(/^\s*([A-Za-z][A-Za-z0-9]{0,14})\s*=\s*(.+?)\s*$/);
            if (!m) continue;
            if (section === 'COEF') {
                dspState.coefNames.push({ name: m[1], index: coefIdx, rawExpr: m[2].trim() });
                coefIdx++;
            } else if (section === 'ADRS') {
                dspState.madrsNames.push({ name: m[1], index: adrsIdx, rawExpr: m[2].trim() });
                adrsIdx++;
            }
        }
        dspRenderKnobs();
    }

    function dspRenderKnobs() {
        var el = document.getElementById('dsp-knobs');
        el.innerHTML = '';
        for (var ci = 0; ci < dspState.coefNames.length; ci++) {
            var c = dspState.coefNames[ci];
            var currentRaw = engine.dspGetCoef(c.index);
            var current13 = (currentRaw >> 3) & 0x1FFF;
            var pct = Math.round((current13 / 4095) * 100);

            var wrap = document.createElement('div'); wrap.className = 'dsp-knob';
            var lbl = document.createElement('label'); lbl.textContent = c.name;
            var inp = document.createElement('input');
            inp.type = 'range'; inp.min = 0; inp.max = 100; inp.step = 1; inp.value = pct;
            var val = document.createElement('span'); val.className = 'dsp-knob-val'; val.textContent = pct + '%';

            (function(c2, inp2, val2) {
                inp2.oninput = function() {
                    var p = parseInt(inp2.value);
                    val2.textContent = p + '%';
                    var v13 = Math.round(4095 * p / 100);
                    var shifted = (v13 << 3) & 0xFFFF;
                    engine.dspSetCoef(c2.index, shifted > 32767 ? shifted - 65536 : shifted);
                };
            })(c, inp, val);

            wrap.appendChild(lbl); wrap.appendChild(inp); wrap.appendChild(val);
            el.appendChild(wrap);
        }
        for (var ai = 0; ai < dspState.madrsNames.length; ai++) {
            var a = dspState.madrsNames[ai];
            var currentSamples = engine.dspGetMadrs(a.index);
            var currentMs = (currentSamples / 44100 * 1000);

            var wrap = document.createElement('div'); wrap.className = 'dsp-knob';
            var lbl = document.createElement('label'); lbl.textContent = a.name;
            var inp = document.createElement('input');
            inp.type = 'range'; inp.min = 0; inp.max = 500; inp.step = 1;
            inp.value = Math.round(currentMs);
            var val = document.createElement('span'); val.className = 'dsp-knob-val'; val.textContent = Math.round(currentMs) + 'ms';

            (function(a2, inp2, val2) {
                inp2.oninput = function() {
                    var ms = parseInt(inp2.value);
                    val2.textContent = ms + 'ms';
                    var samples = Math.round(44100 * ms / 1000) & 0xFFFF;
                    engine.dspSetMadrs(a2.index, samples);
                };
            })(a, inp, val);

            wrap.appendChild(lbl); wrap.appendChild(inp); wrap.appendChild(val);
            el.appendChild(wrap);
        }
    }

    function dspToggleEnable() {
        if (!engine.isReady()) return;
        dspState.enabled = !dspState.enabled;
        var btn = document.getElementById('dsp-enable-btn');
        if (dspState.enabled) {
            btn.classList.add('active');
            btn.textContent = 'Enabled';
            if (dspState.compiled) engine.dspStart();
            dspApplySendToActiveSlots();
            dspApplyEfsdl();
        } else {
            btn.classList.remove('active');
            btn.textContent = 'Enable';
            engine.dspStop();
            engine.dspClear();
            for (var s = 0; s < 32; s++) {
                engine.dspWriteSlotReg(s, 0xA, 0);
                engine.dspSetSlotOutput(s, 0, 0);
            }
        }
    }

    function dspApplyEfsdl() {
        if (!engine.isReady() || !dspState.enabled) return;
        engine.dspSetSlotOutput(0, 7, 0x1F);
        engine.dspSetSlotOutput(1, 7, 0x0F);
    }

    function dspUpdateSend(val) {
        dspState.sendLevel = parseInt(val) || 0;
        if (dspState.enabled) dspApplySendToActiveSlots();
    }

    function dspApplySendToActiveSlots() {
        if (!engine.isReady() || !dspState.enabled) return;
        for (var s = 0; s < 32; s++) {
            engine.dspSetSlotSend(s, dspState.sendLevel);
        }
    }

    function dspSetStatus(msg, isError) {
        var el = document.getElementById('dsp-status');
        el.textContent = msg;
        el.className = 'dsp-status' + (isError ? ' dsp-error' : '');
    }

    function dspLoadExb() {
        var input = document.createElement('input');
        input.type = 'file';
        input.accept = '.exb,.EXB';
        input.onchange = function(e) {
            var file = e.target.files[0];
            if (!file) return;
            file.arrayBuffer().then(function(buf) {
                if (buf.byteLength < 0x540) { dspSetStatus('File too small for EXB', true); return; }
                engine.init().then(function() {
                    var bytes = new Uint8Array(buf);
                    engine.dspLoadExb(bytes);
                    dspState.compiled = true;
                    var parsed = scspdspParseExb(bytes);
                    dspSetStatus('Loaded: ' + (parsed.name || file.name) + ' (' + parsed.steps + ' steps)', false);
                    dspState.coefNames = [];
                    dspState.madrsNames = [];
                    document.getElementById('dsp-knobs').innerHTML = '';
                    document.getElementById('dsp-rbl').value = parsed.rbl;
                    if (!dspState.enabled) dspToggleEnable();
                    dspApplySendToActiveSlots();
                });
            });
        };
        input.click();
    }

    // ═══════════════════════════════════════════════════════════════
    // INIT
    // ═══════════════════════════════════════════════════════════════

    function init(_state, _engine, _ui) {
        state = _state;
        engine = _engine;
        ui = _ui;

        // Expose functions referenced by HTML onclick attributes
        var w = typeof window !== 'undefined' ? window : {};
        w.toggleInstDetail = toggleInstDetail;
        w.toggleDspPanel = toggleDspPanel;
        w.dspCompile = dspCompile;
        w.dspToggleEnable = dspToggleEnable;
        w.dspUpdateSend = dspUpdateSend;
        w.dspLoadExb = dspLoadExb;
        w.applyWavePreset = applyWavePreset;
        w.loadWavForOp = loadWavForOp;

        // Wire Ctrl+Enter in DSP editor
        var ta = document.getElementById('dsp-code');
        if (ta) {
            ta.addEventListener('keydown', function(e) {
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                    e.preventDefault();
                    dspCompile();
                }
                if (e.key === 'Tab') {
                    e.preventDefault();
                    var s = ta.selectionStart;
                    ta.value = ta.value.substring(0, s) + '  ' + ta.value.substring(ta.selectionEnd);
                    ta.selectionStart = ta.selectionEnd = s + 2;
                }
            });
        }

        // DSP hook: after each slot is programmed, apply effect send if DSP is active
        // Also re-apply EFSDL on slots 0-1 (stereo wet return for EFREG0/1)
        engine.setSlotPostProgramHook(function(slot) {
            if (dspState.enabled && dspState.compiled) {
                engine.dspSetSlotSend(slot, dspState.sendLevel);
                if (slot === 0) engine.dspSetSlotOutput(0, 7, 0x1F);
                if (slot === 1) engine.dspSetSlotOutput(1, 7, 0x0F);
            }
        });

        // Refresh detail panel when instrument/operator selection changes
        ui.onSelectionChange(function() {
            refreshInstDetail();
        });
    }

    return {
        init: init,
        refreshInstDetail: refreshInstDetail,
    };
})();
