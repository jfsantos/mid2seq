/*
 * ui.js — SCSP FM Synth WebView UI
 * Tabbed operator editor with envelope visualization.
 */

const MAX_OPS = 6;
const PARAMS_PER_OP = 14;

/* Per-operator param definitions (matches C++ enum OpParam) */
const OP_PARAMS = [
    { key: 'ratio',    name: 'Ratio',    min: 0.5, max: 32,  step: 0.001, fmt: v => v.toFixed(3) },
    { key: 'level',    name: 'Level',    min: 0,   max: 1,   step: 0.01,  fmt: v => v.toFixed(2) },
    { key: 'ar',       name: 'AR',       min: 0,   max: 31,  step: 1,     fmt: v => Math.round(v) },
    { key: 'd1r',      name: 'D1R',      min: 0,   max: 31,  step: 1,     fmt: v => Math.round(v) },
    { key: 'dl',       name: 'DL',       min: 0,   max: 31,  step: 1,     fmt: v => Math.round(v) },
    { key: 'd2r',      name: 'D2R',      min: 0,   max: 31,  step: 1,     fmt: v => Math.round(v) },
    { key: 'rr',       name: 'RR',       min: 0,   max: 31,  step: 1,     fmt: v => Math.round(v) },
    { key: 'feedback',  name: 'Feedback', min: 0,   max: 0.5, step: 0.01,  fmt: v => v.toFixed(2) },
    { key: 'mdl',      name: 'MDL',      min: 0,   max: 15,  step: 1,     fmt: v => Math.round(v) },
    { key: 'modsrc',   name: 'Mod Source',min: 0,   max: 6,   step: 1,     fmt: v => Math.round(v) },
    { key: 'waveform', name: 'Waveform', min: 0,   max: 9,   step: 1,     fmt: v => WAVE_NAMES[Math.round(v)] || '?' },
    { key: 'loopmode', name: 'Loop Mode',min: 0,   max: 3,   step: 1,     fmt: v => LOOP_NAMES[Math.round(v)] || '?' },
    { key: 'loopstart',name: 'Loop Start',min: 0,  max: 65535,step: 1,     fmt: v => Math.round(v) },
    { key: 'loopend',  name: 'Loop End', min: 0,   max: 65535,step: 1,     fmt: v => Math.round(v) },
];

const WAVE_NAMES = ['Sine','Sawtooth','Square','Triangle','Organ','Brass','Strings','Piano','Flute','Bass'];
const LOOP_NAMES = ['Off','Forward','Reverse','Ping-pong'];

/* ── JS Waveform Generators (matching scsp_waveforms.c) ──────── */

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
    case 0: /* Sine */
        return genAdditive(n, [[1, 1.0]]);
    case 1: /* Sawtooth */
        return genAdditive(n, Array.from({length:15}, (_, i) => [i+1, (((i+1)%2===0)?-1:1)/(i+1)]));
    case 2: /* Square */
        return genAdditive(n, Array.from({length:8}, (_, i) => [2*i+1, 1.0/(2*i+1)]));
    case 3: /* Triangle */
        return genAdditive(n, Array.from({length:8}, (_, i) => [2*i+1, ((i%2===0)?1:-1)/((2*i+1)*(2*i+1))]));
    case 4: /* Organ */
        return genAdditive(n, [[1,1],[2,0.8],[3,0.6],[4,0.3],[6,0.2],[8,0.15],[10,0.1]]);
    case 5: /* Brass */
        return genAdditive(n, [[1,1],[2,0.3],[3,0.7],[4,0.15],[5,0.5],[6,0.1],[7,0.3],[9,0.15]]);
    case 6: /* Strings */
        return genAdditive(n, Array.from({length:20}, (_, i) => [i+1, 1.0/Math.pow(i+1, 1.2)]));
    case 7: /* Piano */
        return genAdditive(n, [[1,1],[2,0.7],[3,0.4],[4,0.25],[5,0.15],[6,0.1],[7,0.08],[8,0.05]]);
    case 8: /* Flute */
        return genAdditive(n, [[1,1],[2,0.15],[3,0.05]]);
    case 9: /* Bass */
        return genAdditive(n, [[1,1],[2,0.5],[3,0.2],[4,0.1]]);
    default:
        return new Float32Array(n);
    }
}

/* Global param indices (must match C++ enum) */
const IDX_NUM_OPS = MAX_OPS * PARAMS_PER_OP;  // 84
const IDX_CARRIER_BASE = IDX_NUM_OPS + 1;      // 85-90
const IDX_PROGRAM_NUM = IDX_CARRIER_BASE + 6;  // 91

/* SCSP rate tables for envelope visualization */
const AR_TIMES = [100000,100000,8100,6900,6000,4800,4000,3400,3000,2400,2000,1700,1500,1200,1000,860,760,600,500,430,380,300,250,220,190,150,130,110,95,76,63,55];
const DR_TIMES = [100000,100000,118200,101300,88600,70900,59100,50700,44300,35500,29600,25300,22200,17700,14800,12700,11100,8900,7400,6300,5500,4400,3700,3200,2800,2200,1800,1600,1400,1100,920,790];
const EG_SLOPE = 12.0;

/* ── Presets (must match kPresets[] in SCSPSynthPlugin.cpp) ──── */
const PRESET_DATA = [
    { name:'Electric Piano', n:2, ops:[
        {r:2.0,l:0.9,ar:31,d1r:12,dl:8,d2r:0,rr:14,fb:0,mdl:0,ms:-1,c:0},
        {r:1.0,l:0.8,ar:31,d1r:6,dl:2,d2r:0,rr:14,fb:0,mdl:9,ms:0,c:1}]},
    { name:'Bell', n:2, ops:[
        {r:3.5,l:0.9,ar:31,d1r:4,dl:2,d2r:0,rr:8,fb:0,mdl:0,ms:-1,c:0},
        {r:1.0,l:0.7,ar:31,d1r:2,dl:0,d2r:0,rr:6,fb:0,mdl:11,ms:0,c:1}]},
    { name:'Brass', n:2, ops:[
        {r:1.0,l:0.8,ar:24,d1r:4,dl:2,d2r:0,rr:14,fb:0.3,mdl:0,ms:-1,c:0},
        {r:1.0,l:0.8,ar:22,d1r:2,dl:0,d2r:0,rr:14,fb:0,mdl:9,ms:0,c:1}]},
    { name:'Organ', n:2, ops:[
        {r:1.0,l:0.7,ar:31,d1r:0,dl:0,d2r:0,rr:20,fb:0.6,mdl:0,ms:-1,c:0},
        {r:1.0,l:0.8,ar:31,d1r:0,dl:0,d2r:0,rr:20,fb:0,mdl:8,ms:0,c:1}]},
    { name:'FM Bass', n:2, ops:[
        {r:1.0,l:0.9,ar:31,d1r:14,dl:10,d2r:0,rr:14,fb:0.2,mdl:0,ms:-1,c:0},
        {r:1.0,l:0.9,ar:31,d1r:6,dl:4,d2r:0,rr:14,fb:0,mdl:10,ms:0,c:1}]},
    { name:'Strings', n:2, ops:[
        {r:1.002,l:0.5,ar:20,d1r:0,dl:0,d2r:0,rr:16,fb:0,mdl:0,ms:-1,c:0},
        {r:1.0,l:0.7,ar:18,d1r:0,dl:0,d2r:0,rr:14,fb:0,mdl:7,ms:0,c:1}]},
    { name:'Clavinet', n:2, ops:[
        {r:3.0,l:0.9,ar:31,d1r:16,dl:14,d2r:0,rr:18,fb:0,mdl:0,ms:-1,c:0},
        {r:1.0,l:0.8,ar:31,d1r:10,dl:6,d2r:0,rr:16,fb:0,mdl:10,ms:0,c:1}]},
    { name:'Marimba', n:2, ops:[
        {r:4.0,l:0.8,ar:31,d1r:18,dl:16,d2r:0,rr:20,fb:0,mdl:0,ms:-1,c:0},
        {r:1.0,l:0.8,ar:31,d1r:8,dl:4,d2r:0,rr:12,fb:0,mdl:9,ms:0,c:1}]},
    { name:'Electric Piano 2', n:3, ops:[
        {r:14.0,l:0.4,ar:31,d1r:14,dl:12,d2r:0,rr:16,fb:0,mdl:0,ms:-1,c:0},
        {r:1.0,l:0.7,ar:31,d1r:10,dl:6,d2r:0,rr:14,fb:0,mdl:8,ms:0,c:0},
        {r:1.0,l:0.8,ar:31,d1r:4,dl:2,d2r:0,rr:12,fb:0,mdl:9,ms:1,c:1}]},
    { name:'Metallic', n:3, ops:[
        {r:1.414,l:0.6,ar:31,d1r:6,dl:3,d2r:0,rr:10,fb:0.4,mdl:0,ms:-1,c:0},
        {r:3.82,l:0.5,ar:31,d1r:8,dl:4,d2r:0,rr:12,fb:0,mdl:0,ms:-1,c:0},
        {r:1.0,l:0.7,ar:31,d1r:4,dl:2,d2r:0,rr:10,fb:0,mdl:10,ms:0,c:1}]},
    { name:'4-Op E.Piano', n:4, ops:[
        {r:5.0,l:0.3,ar:31,d1r:16,dl:14,d2r:0,rr:16,fb:0.2,mdl:0,ms:-1,c:0},
        {r:1.0,l:0.5,ar:31,d1r:12,dl:8,d2r:0,rr:14,fb:0,mdl:7,ms:0,c:0},
        {r:1.0,l:0.7,ar:31,d1r:8,dl:4,d2r:0,rr:12,fb:0,mdl:8,ms:1,c:0},
        {r:1.0,l:0.8,ar:31,d1r:4,dl:2,d2r:0,rr:12,fb:0,mdl:9,ms:2,c:1}]},
    { name:'Sine', n:1, ops:[
        {r:1.0,l:0.8,ar:31,d1r:0,dl:0,d2r:0,rr:14,fb:0,mdl:0,ms:-1,c:1}]},
];

/* ── UI Class ─────────────────────────────────────────────────── */

class SCSPSynthUI extends DISTRHO.UI {
    constructor() {
        super();
        this.sliders = {};  // paramIndex → {input, val}
        this.numOps = 2;
        this.activeTab = 0;
        this.buildPresets();
        this.buildJsonButtons();
        this.buildNumOps();
        this.buildTabs();
        this.buildTabContent(0);
        this.drawEnvelope();
        window.addEventListener('resize', () => this.drawEnvelope());
    }

    /* ── Preset selector ── */
    buildPresets() {
        const sel = document.getElementById('preset-select');
        PRESET_DATA.forEach((p, i) => {
            const opt = document.createElement('option');
            opt.value = i; opt.textContent = p.name;
            sel.appendChild(opt);
        });
        sel.addEventListener('change', () => this.applyPreset(parseInt(sel.value)));
    }

    applyPreset(index) {
        const pr = PRESET_DATA[index];
        if (!pr) return;
        /* Set numOps */
        this.setParameterValue(IDX_NUM_OPS, pr.n);
        /* Set per-op params */
        for (let i = 0; i < MAX_OPS; i++) {
            const o = i < pr.n ? pr.ops[i] : {r:1,l:0.8,ar:31,d1r:0,dl:0,d2r:0,rr:14,fb:0,mdl:0,ms:-1,c:0};
            const b = i * PARAMS_PER_OP;
            this.setParameterValue(b + 0, o.r);
            this.setParameterValue(b + 1, o.l);
            this.setParameterValue(b + 2, o.ar);
            this.setParameterValue(b + 3, o.d1r);
            this.setParameterValue(b + 4, o.dl);
            this.setParameterValue(b + 5, o.d2r);
            this.setParameterValue(b + 6, o.rr);
            this.setParameterValue(b + 7, o.fb);
            this.setParameterValue(b + 8, o.mdl);
            this.setParameterValue(b + 9, o.ms + 1); /* -1→0, 0→1, ... */
            this.setParameterValue(b + 10, o.wv || 0);    /* waveform (default: sine) */
            this.setParameterValue(b + 11, o.lm !== undefined ? o.lm : 1); /* loop mode (default: forward) */
            this.setParameterValue(b + 12, o.ls || 0);     /* loop start */
            this.setParameterValue(b + 13, o.le || 1024);  /* loop end (default: 1024) */
            this.setParameterValue(IDX_CARRIER_BASE + i, o.c);
        }
    }

    /* ── JSON export/import ── */
    buildJsonButtons() {
        const bind = (id, fn) => { const el = document.getElementById(id); if (el) el.addEventListener('click', fn); };
        bind('btn-copy-json', () => this.copyJson());
        bind('btn-paste-json', () => this.pasteJson());
        bind('btn-export-ton', () => this.exportTon());
        bind('btn-load-ton', () => this.loadTon());
        bind('btn-set-kit', () => this.setKitPath());
        bind('btn-save-kit', () => this.saveToKit());
        bind('btn-load-kit', () => this.loadFromKit());
        const progSel = document.getElementById('program-num-select');
        progSel.addEventListener('change', () => {
            const prog = parseInt(progSel.value);
            this.setParameterValue(IDX_PROGRAM_NUM, prog);
            if (this.tonPatches && prog < this.tonPatches.length) {
                this._applyPatch(this.tonPatches[prog]);
            }
        });
    }

    /* Build one instrument entry from current parameters */
    buildInstrumentJson() {
        const ops = [];
        for (let i = 0; i < this.numOps; i++) {
            const b = i * PARAMS_PER_OP;
            const getV = (pi) => {
                const s = this.sliders[b + pi];
                return s ? parseFloat(s.input.value) : 0;
            };
            const modSrc = Math.round(getV(9));
            ops.push({
                freq_ratio: parseFloat(getV(0).toFixed(3)),
                level: parseFloat(getV(1).toFixed(2)),
                ar: Math.round(getV(2)),
                d1r: Math.round(getV(3)),
                dl: Math.round(getV(4)),
                d2r: Math.round(getV(5)),
                rr: Math.round(getV(6)),
                feedback: parseFloat(getV(7).toFixed(2)),
                mdl: Math.round(getV(8)),
                mod_source: modSrc > 0 ? modSrc - 1 : -1,
                is_carrier: this.getParamValue(IDX_CARRIER_BASE + i) > 0.5,
                waveform: WAVE_NAMES[Math.round(getV(10))] || 'sine',
                loop_mode: Math.round(getV(11)),
                loop_start: Math.round(getV(12)),
                loop_end: Math.round(getV(13)),
            });
        }

        const progNum = parseInt(document.getElementById('program-num-select').value);
        const presetName = document.getElementById('preset-select').selectedOptions[0]?.textContent || 'Custom';

        return {
            name: presetName,
            program: progNum,
            waveform: 'sine',
            base_note: 69,
            loop: true,
            fm_ops: ops,
        };
    }

    /* Export current patch as saturn_kit.py-compatible JSON → clipboard */
    copyJson() {
        const instrument = this.buildInstrumentJson();
        const config = { instruments: [instrument] };
        const json = JSON.stringify(config, null, 2);

        navigator.clipboard.writeText(json).then(() => {
            this.showStatus('Copied (program ' + instrument.program + ')');
        }).catch(() => {
            prompt('Copy this JSON:', json);
        });
    }

    /* Import patch from clipboard JSON */
    pasteJson() {
        navigator.clipboard.readText().then(text => {
            this.importJson(text);
        }).catch(() => {
            /* Fallback: prompt for paste */
            const text = prompt('Paste JSON:');
            if (text) this.importJson(text);
        });
    }

    importJson(text) {
        try {
            const data = JSON.parse(text);
            let ops;
            if (data.instruments && data.instruments[0] && data.instruments[0].fm_ops) {
                ops = data.instruments[0].fm_ops; /* saturn_kit.py format */
            } else if (data.operators) {
                ops = data.operators; /* fm_sim.py format */
            } else if (Array.isArray(data.fm_ops)) {
                ops = data.fm_ops;
            } else {
                this.showStatus('No FM operators found');
                return;
            }

            const n = Math.min(ops.length, MAX_OPS);
            this.setParameterValue(IDX_NUM_OPS, n);

            for (let i = 0; i < n; i++) {
                const o = ops[i];
                const b = i * PARAMS_PER_OP;
                this.setParameterValue(b + 0, o.freq_ratio || 1);
                this.setParameterValue(b + 1, o.level !== undefined ? o.level : 0.8);
                this.setParameterValue(b + 2, o.ar !== undefined ? o.ar : 31);
                this.setParameterValue(b + 3, o.d1r || 0);
                this.setParameterValue(b + 4, o.dl || 0);
                this.setParameterValue(b + 5, o.d2r || 0);
                this.setParameterValue(b + 6, o.rr !== undefined ? o.rr : 14);
                this.setParameterValue(b + 7, o.feedback || 0);
                this.setParameterValue(b + 8, o.mdl || 0);
                this.setParameterValue(b + 9, (o.mod_source !== undefined ? o.mod_source : -1) + 1);
                this.setParameterValue(IDX_CARRIER_BASE + i, o.is_carrier ? 1 : 0);
            }
            this.showStatus('Imported ' + n + ' operators');
        } catch (e) {
            this.showStatus('Invalid JSON: ' + e.message);
        }
    }

    showStatus(msg) {
        const el = document.getElementById('json-status');
        el.textContent = msg;
        setTimeout(() => { el.textContent = ''; }, 3000);
    }

    /* Export current patch as TON file → download */
    exportTon() {
        if (typeof TonIO === 'undefined' || !TonIO) {
            this.showStatus('TON I/O not available');
            return;
        }
        const instrument = this.buildInstrumentJson();
        // Convert to editor patch format for TonIO
        const patch = {
            name: instrument.name,
            operators: instrument.fm_ops.map(op => ({
                freq_ratio: op.freq_ratio,
                level: op.level,
                ar: op.ar, d1r: op.d1r, dl: op.dl, d2r: op.d2r, rr: op.rr,
                mdl: op.mdl,
                mod_source: op.mod_source,
                feedback: op.feedback,
                is_carrier: op.is_carrier,
                waveform: op.waveform, // string name
                loop_mode: op.loop_mode,
                loop_start: op.loop_start,
                loop_end: op.loop_end,
            })),
        };
        const tonData = TonIO.exportTon([patch], generateWaveform);
        const blob = new Blob([tonData], { type: 'application/octet-stream' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = (instrument.name || 'patch') + '.ton'; a.click();
        URL.revokeObjectURL(url);
        this.showStatus('Exported TON');
    }

    /* Apply a TonIO patch to the DSP via setState('load_patch', ...).
     * Sends all params + PCM in a single message to the C++ side,
     * which sets fParams directly and calls rebuildOps() once.
     * This bypasses the setParameterValue host round-trip entirely.
     *
     * Format: "numOps|ratio,level,ar,d1r,dl,d2r,rr,fb,mdl,ms,carrier,lm,ls,le,pcmLen,pcmB64|..." */
    _applyPatch(patch) {
        if (!patch || !patch.operators) return;
        const ops = patch.operators;
        const n = Math.min(ops.length, MAX_OPS);

        this.customWaves = {};
        let msg = '' + n;

        for (let i = 0; i < n; i++) {
            const o = ops[i];
            const ratio = o.freq_ratio || 1;
            const level = o.level !== undefined ? o.level : 0.8;
            const ar = o.ar !== undefined ? o.ar : 31;
            const d1r = o.d1r || 0;
            const dl = o.dl || 0;
            const d2r = o.d2r || 0;
            const rr = o.rr !== undefined ? o.rr : 14;
            const fb = o.feedback || 0;
            const mdl = o.mdl || 0;
            const ms = (o.mod_source !== undefined ? o.mod_source : -1) + 1;
            const carrier = o.is_carrier ? 1 : 0;
            const lm = o.loop_mode !== undefined ? o.loop_mode : 1;
            const ls = o.loop_start || 0;
            let le = o.loop_end || 1024;

            let pcmLen = 0;
            let pcmB64 = '';
            if (o.pcm && o.pcm.length > 0) {
                this.customWaves[i] = o.pcm;
                const int16 = new Int16Array(o.pcm.length);
                for (let s = 0; s < o.pcm.length; s++) {
                    int16[s] = Math.max(-32768, Math.min(32767, Math.round(o.pcm[s] * 32767)));
                }
                const bytes = new Uint8Array(int16.buffer);
                let raw = '';
                for (let s = 0; s < bytes.length; s++) raw += String.fromCharCode(bytes[s]);
                pcmB64 = btoa(raw);
                pcmLen = o.pcm.length;
                le = o.pcm.length;
            }

            msg += '|' + ratio + ',' + level + ',' + ar + ',' + d1r + ',' + dl + ','
                 + d2r + ',' + rr + ',' + fb + ',' + mdl + ',' + ms + ',' + carrier + ','
                 + lm + ',' + ls + ',' + le + ',' + pcmLen + ',' + pcmB64;
        }

        /* Send everything to C++ in one shot */
        this.setState('load_patch', msg);

        /* Update UI directly since parameterChanged won't fire from setState.
         * Pre-seed slider values so buildTabContent reads correct values. */
        for (let i = 0; i < MAX_OPS; i++) {
            const b = i * PARAMS_PER_OP;
            if (i < n) {
                const o = ops[i];
                this._setSlider(b + 0,  o.freq_ratio || 1);
                this._setSlider(b + 1,  o.level !== undefined ? o.level : 0.8);
                this._setSlider(b + 2,  o.ar !== undefined ? o.ar : 31);
                this._setSlider(b + 3,  o.d1r || 0);
                this._setSlider(b + 4,  o.dl || 0);
                this._setSlider(b + 5,  o.d2r || 0);
                this._setSlider(b + 6,  o.rr !== undefined ? o.rr : 14);
                this._setSlider(b + 7,  o.feedback || 0);
                this._setSlider(b + 8,  o.mdl || 0);
                this._setSlider(b + 9,  (o.mod_source !== undefined ? o.mod_source : -1) + 1);
                this._setSlider(b + 10, 0);
                this._setSlider(b + 11, o.loop_mode !== undefined ? o.loop_mode : 1);
                this._setSlider(b + 12, o.loop_start || 0);
                this._setSlider(b + 13, o.pcm ? o.pcm.length : (o.loop_end || 1024));
                this._setSlider(IDX_CARRIER_BASE + i, o.is_carrier ? 1 : 0);
            } else {
                this._setSlider(b + 0, 1); this._setSlider(b + 1, 0.8);
                this._setSlider(b + 2, 31); this._setSlider(b + 3, 0);
                this._setSlider(b + 4, 0); this._setSlider(b + 5, 0);
                this._setSlider(b + 6, 14); this._setSlider(b + 7, 0);
                this._setSlider(b + 8, 0); this._setSlider(b + 9, 0);
                this._setSlider(b + 10, 0); this._setSlider(b + 11, 1);
                this._setSlider(b + 12, 0); this._setSlider(b + 13, 1024);
                this._setSlider(IDX_CARRIER_BASE + i, 0);
            }
        }

        this.numOps = n;
        document.getElementById('num-ops-select').value = n;
        this.buildTabs();
        this.activeTab = 0;
        this.buildTabContent(0);
        this.drawEnvelope();
    }

    /* Set a slider value locally without calling setParameterValue */
    _setSlider(index, value) {
        const s = this.sliders[index];
        if (s) {
            if (s.input.tagName === 'SELECT') {
                s.input.value = Math.round(value);
            } else {
                s.input.value = value;
                if (s.val) {
                    const opParam = index % PARAMS_PER_OP;
                    if (opParam < OP_PARAMS.length) s.val.textContent = OP_PARAMS[opParam].fmt(value);
                }
            }
        } else {
            /* Slider doesn't exist yet — create a dummy so getParamValue/buildTabContent can read it */
            this.sliders[index] = { input: { value: value, tagName: 'INPUT' }, val: null };
        }
    }

    /* Load TON file → import all voices, show current program */
    loadTon() {
        this.showStatus('Load TON: picking file...');
        if (typeof TonIO === 'undefined' || !TonIO) {
            this.showStatus('TON I/O not available');
            return;
        }
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.ton,.TON';
        input.style.display = 'none';
        document.body.appendChild(input); /* Must be in DOM for WKWebView change events */
        input.onchange = (e) => {
            const file = e.target.files[0];
            document.body.removeChild(input); /* Clean up */
            if (!file) { this.showStatus('No file selected'); return; }
            this.showStatus('Reading ' + file.name + '...');
            const reader = new FileReader();
            reader.onload = (ev) => {
                this.showStatus('Parsing ' + ev.target.result.byteLength + ' bytes...');
                try {
                    const result = TonIO.importTon(ev.target.result);
                    if (!result.patches || result.patches.length === 0) {
                        this.showStatus('No voices in TON');
                        return;
                    }
                    this.tonPatches = result.patches;
                    const progNum = parseInt(document.getElementById('program-num-select').value);
                    const idx = Math.min(progNum, this.tonPatches.length - 1);
                    document.getElementById('program-num-select').value = idx;
                    this.setParameterValue(IDX_PROGRAM_NUM, idx);
                    this._applyPatch(this.tonPatches[idx]);
                    this.showStatus('Loaded ' + this.tonPatches.length + ' voices, prog ' + idx + ' (' + this.tonPatches[idx].operators.length + ' ops)');
                } catch (err) {
                    this.showStatus('TON error: ' + err.message);
                }
            };
            reader.onerror = () => { this.showStatus('File read error'); };
            reader.readAsArrayBuffer(file);
        };
        input.click();
    }

    /* ── Shared Kit workflow ── */

    setKitPath() {
        const current = this.kitPath || '';
        const path = prompt('Enter full path to shared .ton kit file:', current);
        if (path === null) return; // cancelled
        this.kitPath = path;
        this.setState('kit_path', path);
        document.getElementById('kit-path-label').textContent = path.split('/').pop() || path.split('\\').pop() || path;
        this.showStatus('Kit path set');
    }

    /* Build a TonIO-compatible patch from current params */
    _buildTonPatch() {
        const instrument = this.buildInstrumentJson();
        return {
            name: instrument.name,
            operators: instrument.fm_ops.map(op => ({
                freq_ratio: op.freq_ratio,
                level: op.level,
                ar: op.ar, d1r: op.d1r, dl: op.dl, d2r: op.d2r, rr: op.rr,
                mdl: op.mdl,
                mod_source: op.mod_source,
                feedback: op.feedback,
                is_carrier: op.is_carrier,
                waveform: op.waveform,
                loop_mode: op.loop_mode,
                loop_start: op.loop_start,
                loop_end: op.loop_end,
            })),
        };
    }

    async saveToKit() {
        if (typeof TonIO === 'undefined' || !TonIO) {
            this.showStatus('TON I/O not available');
            return;
        }
        if (!this.kitPath) {
            this.setKitPath();
            if (!this.kitPath) return;
        }

        const progNum = parseInt(document.getElementById('program-num-select').value);
        const patch = this._buildTonPatch();

        // Read existing kit file (may not exist yet)
        let existingBuffer = null;
        try {
            const b64 = await this.call('readBinaryFile', this.kitPath);
            if (b64 && b64.length > 0) {
                existingBuffer = _b64ToArrayBuffer(b64);
            }
        } catch (e) {
            // File doesn't exist yet — start fresh
        }

        let tonData;
        if (existingBuffer) {
            tonData = TonIO.mergeTon(existingBuffer, progNum, patch, generateWaveform);
        } else {
            // Create new kit with empty slots up to progNum
            const patches = [];
            for (let i = 0; i < progNum; i++) {
                patches.push({ name: 'Empty', operators: [{ freq_ratio: 1, level: 0, ar: 31, d1r: 0, dl: 0, d2r: 0, rr: 14, mdl: 0, mod_source: -1, feedback: 0, is_carrier: true, waveform: 0, loop_mode: 1, loop_start: 0, loop_end: 1024 }] });
            }
            patches.push(patch);
            tonData = TonIO.exportTon(patches, generateWaveform);
        }

        // Write back
        const b64out = _arrayBufferToB64(tonData);
        try {
            const ok = await this.call('writeBinaryFile', this.kitPath, b64out);
            this.showStatus(ok ? 'Saved prog ' + progNum + ' to kit' : 'Write failed');
        } catch (e) {
            this.showStatus('Write error: ' + e);
        }
    }

    async loadFromKit() {
        if (typeof TonIO === 'undefined' || !TonIO) {
            this.showStatus('TON I/O not available');
            return;
        }
        if (!this.kitPath) {
            this.setKitPath();
            if (!this.kitPath) return;
        }

        const progNum = parseInt(document.getElementById('program-num-select').value);

        let b64;
        try {
            b64 = await this.call('readBinaryFile', this.kitPath);
        } catch (e) {
            this.showStatus('Read error: ' + e);
            return;
        }
        if (!b64 || b64.length === 0) {
            this.showStatus('Kit file not found');
            return;
        }

        const buffer = _b64ToArrayBuffer(b64);
        const result = TonIO.importTon(buffer);
        if (!result.patches || result.patches.length === 0) {
            this.showStatus('No voices in kit');
            return;
        }
        this.tonPatches = result.patches;
        const idx = Math.min(progNum, this.tonPatches.length - 1);
        if (idx !== progNum) {
            document.getElementById('program-num-select').value = idx;
            this.setParameterValue(IDX_PROGRAM_NUM, idx);
        }
        this._applyPatch(this.tonPatches[idx]);
        this.showStatus('Loaded kit: ' + this.tonPatches.length + ' voices, showing prog ' + idx);
    }

    /* ── Num operators selector ── */
    buildNumOps() {
        const sel = document.getElementById('num-ops-select');
        sel.addEventListener('change', () => {
            this.numOps = parseInt(sel.value);
            this.setParameterValue(IDX_NUM_OPS, this.numOps);
            this.buildTabs();
            this.buildTabContent(Math.min(this.activeTab, this.numOps - 1));
            this.drawEnvelope();
        });
    }

    /* ── Operator tabs ── */
    buildTabs() {
        const container = document.getElementById('op-tabs');
        container.innerHTML = '';
        for (let i = 0; i < this.numOps; i++) {
            const tab = document.createElement('div');
            tab.className = 'tab' + (i === this.activeTab ? ' active' : '');
            const isCarrier = this.getParamValue(IDX_CARRIER_BASE + i) > 0.5;
            if (isCarrier) tab.classList.add('carrier');
            tab.textContent = 'Op ' + (i + 1) + (isCarrier ? ' (C)' : ' (M)');
            tab.onclick = () => { this.activeTab = i; this.buildTabs(); this.buildTabContent(i); this.drawEnvelope(); };
            container.appendChild(tab);
        }
    }

    getParamValue(index) {
        const s = this.sliders[index];
        return s ? parseFloat(s.input.value) : 0;
    }

    /* ── Tab content: operator parameters ── */
    buildTabContent(opIdx) {
        this.activeTab = opIdx;
        const container = document.getElementById('tab-content');
        container.innerHTML = '';

        const base = opIdx * PARAMS_PER_OP;

        /* Carrier toggle */
        const carrDiv = document.createElement('div');
        carrDiv.className = 'carrier-toggle';
        const carrChk = document.createElement('input');
        carrChk.type = 'checkbox';
        carrChk.checked = this.getParamValue(IDX_CARRIER_BASE + opIdx) > 0.5;
        carrChk.addEventListener('change', () => {
            this.setParameterValue(IDX_CARRIER_BASE + opIdx, carrChk.checked ? 1 : 0);
            this.buildTabs();
        });
        const carrLbl = document.createElement('label');
        carrLbl.textContent = 'Carrier (audible output)';
        carrDiv.appendChild(carrChk);
        carrDiv.appendChild(carrLbl);
        container.appendChild(carrDiv);

        /* Parameter sliders */
        const row1 = document.createElement('div'); row1.className = 'param-row';
        const row2 = document.createElement('div'); row2.className = 'param-row';
        const row3 = document.createElement('div'); row3.className = 'param-row';
        const row4 = document.createElement('div'); row4.className = 'param-row';

        for (let pi = 0; pi < PARAMS_PER_OP; pi++) {
            const pd = OP_PARAMS[pi];
            const paramIdx = base + pi;
            const row = pi < 2 ? row1 : pi < 8 ? row2 : pi < 10 ? row3 : row4;

            if (pd.key === 'waveform') {
                /* Waveform dropdown */
                const div = document.createElement('div'); div.className = 'param';
                const lbl = document.createElement('label'); lbl.textContent = pd.name;
                div.appendChild(lbl);
                const sel = document.createElement('select');
                WAVE_NAMES.forEach((name, wi) => {
                    const opt = document.createElement('option');
                    opt.value = wi; opt.textContent = name;
                    sel.appendChild(opt);
                });
                const curVal = this.sliders[paramIdx] ? parseFloat(this.sliders[paramIdx].input.value) : 0;
                sel.value = Math.round(curVal);
                sel.addEventListener('change', () => {
                    this.setParameterValue(paramIdx, parseInt(sel.value));
                    this.drawWaveformPreview(opIdx);
                });
                div.appendChild(sel);
                this.sliders[paramIdx] = { input: sel, val: null };
                row.appendChild(div);
            } else if (pd.key === 'loopmode') {
                /* Loop mode dropdown */
                const div = document.createElement('div'); div.className = 'param';
                const lbl = document.createElement('label'); lbl.textContent = pd.name;
                div.appendChild(lbl);
                const sel = document.createElement('select');
                LOOP_NAMES.forEach((name, li) => {
                    const opt = document.createElement('option');
                    opt.value = li; opt.textContent = name;
                    sel.appendChild(opt);
                });
                const curVal = this.sliders[paramIdx] ? parseFloat(this.sliders[paramIdx].input.value) : 1;
                sel.value = Math.round(curVal);
                sel.addEventListener('change', () => {
                    this.setParameterValue(paramIdx, parseInt(sel.value));
                    this.drawWaveformPreview(opIdx);
                });
                div.appendChild(sel);
                this.sliders[paramIdx] = { input: sel, val: null };
                row.appendChild(div);
            } else if (pd.key === 'modsrc') {
                /* Mod source dropdown */
                const div = document.createElement('div'); div.className = 'param';
                const lbl = document.createElement('label'); lbl.textContent = pd.name;
                div.appendChild(lbl);
                const sel = document.createElement('select');
                const opts = [{v:0, t:'None'}];
                for (let j = 0; j < this.numOps; j++) {
                    if (j !== opIdx) opts.push({v: j+1, t: 'Op ' + (j+1)});
                }
                opts.forEach(o => {
                    const opt = document.createElement('option');
                    opt.value = o.v; opt.textContent = o.t;
                    sel.appendChild(opt);
                });
                const curVal = this.sliders[paramIdx] ? parseFloat(this.sliders[paramIdx].input.value) : 0;
                sel.value = Math.round(curVal);
                sel.addEventListener('change', () => {
                    this.setParameterValue(paramIdx, parseInt(sel.value));
                    this.drawEnvelope();
                });
                div.appendChild(sel);
                this.sliders[paramIdx] = { input: sel, val: null };
                row.appendChild(div);
            } else {
                /* Slider */
                const div = document.createElement('div'); div.className = 'param';
                const lbl = document.createElement('label'); lbl.textContent = pd.name;
                div.appendChild(lbl);
                const inp = document.createElement('input');
                /* Cap loop start/end sliders to the waveform length */
                let sliderMax = pd.max;
                if (pd.key === 'loopstart' || pd.key === 'loopend') {
                    if (this.customWaves && this.customWaves[opIdx]) {
                        sliderMax = this.customWaves[opIdx].length;
                    } else {
                        sliderMax = 1024; /* built-ins are 1024 */
                    }
                }
                inp.type = 'range'; inp.min = pd.min; inp.max = sliderMax; inp.step = pd.step;
                const curVal = this.sliders[paramIdx] ? parseFloat(this.sliders[paramIdx].input.value) : pd.min;
                inp.value = curVal;
                div.appendChild(inp);
                const val = document.createElement('span'); val.className = 'val';
                val.textContent = pd.fmt(curVal);
                div.appendChild(val);
                inp.addEventListener('input', () => {
                    const v = parseFloat(inp.value);
                    val.textContent = pd.fmt(v);
                    this.setParameterValue(paramIdx, v);
                    this.drawEnvelope();
                    if (pd.key === 'loopstart' || pd.key === 'loopend')
                        this.drawWaveformPreview(opIdx);
                });
                this.sliders[paramIdx] = { input: inp, val };
                row.appendChild(div);
            }
        }

        const grp1 = document.createElement('div');
        const h1 = document.createElement('div'); h1.style.cssText = 'font-size:10px;color:#555;margin-bottom:4px;'; h1.textContent = 'PITCH / LEVEL';
        grp1.appendChild(h1); grp1.appendChild(row1);
        container.appendChild(grp1);

        const grp2 = document.createElement('div');
        const h2 = document.createElement('div'); h2.style.cssText = 'font-size:10px;color:#555;margin:8px 0 4px;'; h2.textContent = 'ENVELOPE';
        grp2.appendChild(h2); grp2.appendChild(row2);
        container.appendChild(grp2);

        const grp3 = document.createElement('div');
        const h3 = document.createElement('div'); h3.style.cssText = 'font-size:10px;color:#555;margin:8px 0 4px;'; h3.textContent = 'MODULATION';
        grp3.appendChild(h3); grp3.appendChild(row3);
        container.appendChild(grp3);

        const grp4 = document.createElement('div');
        const h4 = document.createElement('div'); h4.style.cssText = 'font-size:10px;color:#555;margin:8px 0 4px;'; h4.textContent = 'WAVEFORM';
        grp4.appendChild(h4); grp4.appendChild(row4);
        /* Load WAV button */
        const loadBtn = document.createElement('button');
        loadBtn.className = 'load-wav-btn';
        loadBtn.textContent = 'Load WAV';
        loadBtn.addEventListener('click', () => this.loadWavForOp(opIdx));
        row4.appendChild(loadBtn);

        /* Waveform preview canvas */
        const wvCanvas = document.createElement('canvas');
        wvCanvas.id = 'waveform-preview';
        wvCanvas.style.cssText = 'width:100%;height:60px;display:block;border-radius:4px;background:#12122a;margin-top:6px;';
        grp4.appendChild(wvCanvas);
        container.appendChild(grp4);

        /* Draw the waveform preview after layout settles */
        requestAnimationFrame(() => this.drawWaveformPreview(opIdx));
    }

    /* ── Envelope visualization ── */
    drawEnvelope() {
        const canvas = document.getElementById('env-canvas');
        if (!canvas) return;
        const rect = canvas.parentElement.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        canvas.width = rect.width * dpr;
        canvas.height = 100 * dpr;
        canvas.style.height = '100px';
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        const w = rect.width, h = 100;
        ctx.fillStyle = '#12122a';
        ctx.fillRect(0, 0, w, h);

        /* Grid lines */
        ctx.strokeStyle = '#1a1a3a'; ctx.lineWidth = 0.5;
        for (let y = 0; y <= h; y += h/4) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }

        const margin = 8, drawW = w - margin * 2, drawH = h - margin * 2;

        /* Draw all operators' envelopes */
        for (let i = 0; i < this.numOps; i++) {
            this.drawOneEnvelope(ctx, i, margin, drawW, drawH, h, i === this.activeTab);
        }
    }

    drawOneEnvelope(ctx, opIdx, margin, drawW, drawH, h, isSelected) {
        const base = opIdx * PARAMS_PER_OP;
        const getV = (pi) => {
            const s = this.sliders[base + pi];
            return s ? parseFloat(s.input.value) : 0;
        };

        const ar = getV(2), d1r = getV(3), dl = getV(4), d2r = getV(5), rr = getV(6);
        const isCarrier = this.getParamValue(IDX_CARRIER_BASE + opIdx) > 0.5;

        const arMs = AR_TIMES[Math.min(Math.round(ar), 31)];
        const d1rMs = d1r > 0 ? DR_TIMES[Math.min(Math.round(d1r), 31)] : 100000;
        const sustainLevel = dl < 31 ? 1.0 - dl / 31.0 : 0.0;
        const d2rMs = d2r > 0 ? DR_TIMES[Math.min(Math.round(d2r), 31)] : 100000;
        const rrMs = DR_TIMES[Math.min(Math.round(rr), 31)];

        const VIS_FRAC = 0.23;
        const d1VisMs = d1rMs * VIS_FRAC;
        const holdWindow = 500;
        const rrVisMs = rrMs * VIS_FRAC;
        const d2decay = Math.exp(-EG_SLOPE * holdWindow / d2rMs);
        const levelAtNoteOff = sustainLevel * d2decay;

        const totalMs = arMs + d1VisMs + holdWindow + rrVisMs;
        const scale = drawW / Math.max(totalMs, 100);
        const bottom = h - margin;
        const nSteps = 40;

        ctx.beginPath();
        let cx = margin;
        ctx.moveTo(cx, bottom);
        cx += arMs * scale;
        ctx.lineTo(cx, bottom - drawH);
        const d1Start = cx;

        for (let i = 1; i <= nSteps; i++) {
            const tMs = (i / nSteps) * d1VisMs;
            const lv = sustainLevel + (1 - sustainLevel) * Math.exp(-EG_SLOPE * tMs / d1rMs);
            ctx.lineTo(d1Start + tMs * scale, bottom - drawH * lv);
        }
        cx = d1Start + d1VisMs * scale;
        const d2Start = cx;
        for (let i = 1; i <= nSteps; i++) {
            const tMs = (i / nSteps) * holdWindow;
            const lv = sustainLevel * Math.exp(-EG_SLOPE * tMs / d2rMs);
            ctx.lineTo(d2Start + tMs * scale, bottom - drawH * lv);
        }
        const noteOffX = d2Start + holdWindow * scale;
        cx = noteOffX;
        const relStart = cx;
        for (let i = 1; i <= nSteps; i++) {
            const tMs = (i / nSteps) * rrVisMs;
            const lv = levelAtNoteOff * Math.exp(-EG_SLOPE * tMs / rrMs);
            ctx.lineTo(relStart + tMs * scale, bottom - drawH * lv);
        }

        if (isSelected) {
            ctx.strokeStyle = isCarrier ? '#00d4ff' : '#ffaa44';
            ctx.lineWidth = 2;
        } else {
            ctx.strokeStyle = isCarrier ? 'rgba(0,212,255,0.2)' : 'rgba(255,170,68,0.2)';
            ctx.lineWidth = 1;
        }
        ctx.stroke();

        if (isSelected) {
            /* Fill under curve */
            ctx.lineTo(relStart + rrVisMs * scale, bottom);
            ctx.lineTo(margin, bottom);
            ctx.closePath();
            ctx.fillStyle = isCarrier ? 'rgba(0,212,255,0.06)' : 'rgba(255,170,68,0.06)';
            ctx.fill();

            /* Note-off marker */
            ctx.save();
            ctx.strokeStyle = '#555'; ctx.lineWidth = 1; ctx.setLineDash([2, 3]);
            ctx.beginPath(); ctx.moveTo(noteOffX, margin); ctx.lineTo(noteOffX, bottom); ctx.stroke();
            ctx.restore();
            ctx.fillStyle = '#444'; ctx.font = '8px monospace';
            ctx.fillText('note off', noteOffX + 3, margin + 8);

            /* Segment labels */
            ctx.fillStyle = '#444'; ctx.font = '9px monospace';
            const segX = [margin, d1Start, d2Start, noteOffX, relStart + rrVisMs * scale];
            ['AR','D1R','D2R','RR'].forEach((lbl, i) => {
                ctx.fillText(lbl, (segX[i] + segX[i+1]) / 2 - 8, h - 2);
            });
        }
    }

    /* ── Custom WAV Loading ── */

    loadWavForOp(opIdx) {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.wav,audio/wav';
        input.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (ev) => {
                try {
                    const result = this.parseWav(ev.target.result);
                    this.applyCustomWaveform(opIdx, result.samples, result.sampleRate, file.name);
                } catch (err) {
                    this.showStatus('WAV error: ' + err.message);
                }
            };
            reader.readAsArrayBuffer(file);
        });
        input.click();
    }

    parseWav(arrayBuffer) {
        const view = new DataView(arrayBuffer);
        /* RIFF header */
        const riff = String.fromCharCode(view.getUint8(0), view.getUint8(1), view.getUint8(2), view.getUint8(3));
        if (riff !== 'RIFF') throw new Error('Not a WAV file');
        const wave = String.fromCharCode(view.getUint8(8), view.getUint8(9), view.getUint8(10), view.getUint8(11));
        if (wave !== 'WAVE') throw new Error('Not a WAVE file');

        /* Find fmt and data chunks */
        let fmt = null, dataOffset = 0, dataSize = 0;
        let pos = 12;
        while (pos < view.byteLength - 8) {
            const id = String.fromCharCode(view.getUint8(pos), view.getUint8(pos+1), view.getUint8(pos+2), view.getUint8(pos+3));
            const size = view.getUint32(pos + 4, true);
            if (id === 'fmt ') {
                fmt = {
                    format: view.getUint16(pos + 8, true),
                    channels: view.getUint16(pos + 10, true),
                    sampleRate: view.getUint32(pos + 12, true),
                    bitsPerSample: view.getUint16(pos + 22, true),
                };
            } else if (id === 'data') {
                dataOffset = pos + 8;
                dataSize = size;
            }
            pos += 8 + size;
            if (pos % 2) pos++; /* pad byte */
        }
        if (!fmt) throw new Error('No fmt chunk');
        if (!dataOffset) throw new Error('No data chunk');
        if (fmt.format !== 1) throw new Error('Not PCM (format=' + fmt.format + ')');

        /* Extract samples as float */
        const bytesPerSample = fmt.bitsPerSample / 8;
        const numFrames = Math.floor(dataSize / (bytesPerSample * fmt.channels));
        const samples = new Float32Array(numFrames);

        for (let i = 0; i < numFrames; i++) {
            const offset = dataOffset + i * bytesPerSample * fmt.channels;
            let val;
            if (fmt.bitsPerSample === 16) {
                val = view.getInt16(offset, true) / 32768.0;
            } else if (fmt.bitsPerSample === 8) {
                val = (view.getUint8(offset) - 128) / 128.0;
            } else if (fmt.bitsPerSample === 24) {
                val = ((view.getUint8(offset) | (view.getUint8(offset+1)<<8) | (view.getInt8(offset+2)<<16))) / 8388608.0;
            } else if (fmt.bitsPerSample === 32 && fmt.format === 1) {
                val = view.getInt32(offset, true) / 2147483648.0;
            } else {
                val = 0;
            }
            samples[i] = val;
        }

        return { samples, sampleRate: fmt.sampleRate, channels: fmt.channels };
    }

    applyCustomWaveform(opIdx, floatSamples, sampleRate, filename) {
        /* Check if this op uses FM — if so, resample to 1024 */
        const base = opIdx * PARAMS_PER_OP;
        const mdl = this.getParamValue(base + 8);
        const modSrc = this.getParamValue(base + 9);
        const isCarrier = this.getParamValue(IDX_CARRIER_BASE + opIdx) > 0.5;
        const usesFM = (modSrc > 0 && mdl >= 5) || !isCarrier;

        let samples = floatSamples;
        if (usesFM && samples.length !== 1024) {
            /* Resample to 1024 for FM compatibility */
            samples = this.resampleTo(floatSamples, 1024);
            this.showStatus('Resampled to 1024 for FM (' + filename + ')');
        } else {
            this.showStatus('Loaded ' + filename + ' (' + samples.length + ' samples)');
        }

        /* Convert to int16 LE and base64-encode */
        const int16 = new Int16Array(samples.length);
        for (let i = 0; i < samples.length; i++) {
            int16[i] = Math.max(-32768, Math.min(32767, Math.round(samples[i] * 32767)));
        }
        const bytes = new Uint8Array(int16.buffer);
        let b64 = '';
        for (let i = 0; i < bytes.length; i++) b64 += String.fromCharCode(bytes[i]);
        b64 = btoa(b64);

        /* Send to DSP via setState */
        this.setState('wave_' + opIdx, b64);

        /* Update loop end to match sample length */
        this.setParameterValue(base + 13, samples.length); /* kOpLoopEnd */
        this.setParameterValue(base + 12, 0);              /* kOpLoopStart */

        /* Store locally for preview drawing */
        this.customWaves = this.customWaves || {};
        this.customWaves[opIdx] = samples;

        /* Update loop slider max and redraw */
        this.buildTabContent(opIdx);
        this.drawWaveformPreview(opIdx);
    }

    resampleTo(input, targetLen) {
        const out = new Float32Array(targetLen);
        const ratio = input.length / targetLen;
        for (let i = 0; i < targetLen; i++) {
            const srcIdx = i * ratio;
            const idx = Math.floor(srcIdx);
            const frac = srcIdx - idx;
            const s0 = input[Math.min(idx, input.length - 1)];
            const s1 = input[Math.min(idx + 1, input.length - 1)];
            out[i] = s0 + (s1 - s0) * frac;
        }
        return out;
    }

    /* ── Waveform Preview ── */

    drawWaveformPreview(opIdx) {
        const canvas = document.getElementById('waveform-preview');
        if (!canvas) return;
        const rect = canvas.parentElement.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        canvas.width = rect.width * dpr;
        canvas.height = 60 * dpr;
        canvas.style.height = '60px';
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        const w = rect.width, h = 60;
        ctx.fillStyle = '#12122a';
        ctx.fillRect(0, 0, w, h);

        /* Get waveform type for this operator */
        const base = opIdx * PARAMS_PER_OP;
        const waveType = Math.round(this.getParamValue(base + 10)); /* kOpWaveform */
        const loopStart = Math.round(this.getParamValue(base + 12)); /* kOpLoopStart */
        const loopEnd = Math.round(this.getParamValue(base + 13));   /* kOpLoopEnd */
        const loopMode = Math.round(this.getParamValue(base + 11));  /* kOpLoopMode */

        /* Generate or use custom waveform samples */
        let samples;
        let n;
        if (this.customWaves && this.customWaves[opIdx]) {
            samples = this.customWaves[opIdx];
            n = samples.length;
        } else {
            n = 1024;
            samples = generateWaveform(waveType, n);
        }

        /* Draw loop region */
        if (loopMode > 0 && loopEnd > loopStart) {
            const lx = loopStart / n * w;
            const ex = loopEnd / n * w;
            ctx.fillStyle = '#1a2a1a';
            ctx.fillRect(lx, 0, ex - lx, h);
            ctx.strokeStyle = '#44aa44'; ctx.setLineDash([2, 3]); ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(lx, 0); ctx.lineTo(lx, h); ctx.stroke();
            ctx.strokeStyle = '#aa4444';
            ctx.beginPath(); ctx.moveTo(ex, 0); ctx.lineTo(ex, h); ctx.stroke();
            ctx.setLineDash([]);
        }

        /* Draw waveform */
        ctx.strokeStyle = '#00d4ff'; ctx.lineWidth = 1;
        ctx.beginPath();
        for (let i = 0; i < n; i++) {
            const x = i / n * w;
            const y = h / 2 - samples[i] * (h / 2 - 4);
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();

        /* Center line */
        ctx.strokeStyle = '#333'; ctx.setLineDash([2, 4]); ctx.lineWidth = 0.5;
        ctx.beginPath(); ctx.moveTo(0, h/2); ctx.lineTo(w, h/2); ctx.stroke();
        ctx.setLineDash([]);

        /* Label */
        ctx.fillStyle = '#555'; ctx.font = '9px monospace';
        const isCustom = this.customWaves && this.customWaves[opIdx];
        ctx.fillText(isCustom ? 'Custom (' + n + ' smp)' : (WAVE_NAMES[waveType] || '?'), 4, 12);
        if (loopMode > 0) {
            ctx.fillText(LOOP_NAMES[loopMode] + ' ' + loopStart + '-' + loopEnd, 4, h - 4);
        } else {
            ctx.fillText('No loop (one-shot)', 4, h - 4);
        }
    }

    /* ── DPF callbacks ── */

    /* Stub methods for C++ bridge responses — needed so dpf.js can resolve call() promises */
    readBinaryFile() {}
    writeBinaryFile() {}

    parameterChanged(index, value) {
        /* Update program number */
        if (index === IDX_PROGRAM_NUM) {
            document.getElementById('program-num-select').value = Math.round(value);
            return;
        }
        /* Update numOps */
        if (index === IDX_NUM_OPS) {
            this.numOps = Math.round(value);
            document.getElementById('num-ops-select').value = this.numOps;
            this.buildTabs();
            this.buildTabContent(Math.min(this.activeTab, this.numOps - 1));
            this.drawEnvelope();
            return;
        }
        /* Update carrier flags */
        if (index >= IDX_CARRIER_BASE && index <= IDX_CARRIER_BASE + 5) {
            this.buildTabs();
            this.drawEnvelope();
        }
        /* Update slider if it exists */
        const s = this.sliders[index];
        if (s) {
            if (s.input.tagName === 'SELECT') {
                s.input.value = Math.round(value);
            } else {
                s.input.value = value;
                if (s.val) {
                    const opParam = index % PARAMS_PER_OP;
                    s.val.textContent = OP_PARAMS[opParam].fmt(value);
                }
            }
            this.drawEnvelope();
            /* Redraw waveform preview if waveform/loop param changed */
            const opParam = index % PARAMS_PER_OP;
            if (opParam >= 10 && opParam <= 13) {
                const opIdx = Math.floor(index / PARAMS_PER_OP);
                if (opIdx === this.activeTab) this.drawWaveformPreview(opIdx);
            }
        }
    }

    programLoaded(index) {
        document.getElementById('preset-select').value = index;
    }

    /* ── Self-test: diagnose host communication ── */
    selfTest() {
        const log = [];
        log.push('=== SCSP FM Synth Self-Test ===');
        log.push('DISTRHO.env: ' + JSON.stringify(DISTRHO.env));
        log.push('TonIO available: ' + (typeof TonIO !== 'undefined' && TonIO !== null));
        log.push('window.host: ' + (typeof window.host));
        log.push('window.host.postMessage: ' + (typeof (window.host && window.host.postMessage)));

        // Test 1: Does setParameterValue work?
        log.push('\n--- Test 1: setParameterValue round-trip ---');
        const testIdx = 0 * PARAMS_PER_OP + 2; // Op0 AR
        const origVal = this.sliders[testIdx] ? parseFloat(this.sliders[testIdx].input.value) : -1;
        log.push('Op0 AR slider before: ' + origVal);
        const testVal = origVal === 25 ? 20 : 25;
        log.push('Setting Op0 AR to ' + testVal + ' via setParameterValue...');
        this.setParameterValue(testIdx, testVal);

        // Check after a delay (host round-trip is async)
        setTimeout(() => {
            const afterVal = this.sliders[testIdx] ? parseFloat(this.sliders[testIdx].input.value) : -1;
            log.push('Op0 AR slider after (100ms): ' + afterVal);
            log.push('setParameterValue works: ' + (afterVal === testVal));

            // Restore
            this.setParameterValue(testIdx, origVal);

            // Test 2: Does applyPreset work?
            log.push('\n--- Test 2: applyPreset ---');
            this.applyPreset(0); // Electric Piano
            setTimeout(() => {
                const epAR = this.sliders[testIdx] ? parseFloat(this.sliders[testIdx].input.value) : -1;
                log.push('After applyPreset(0): Op0 AR = ' + epAR + ' (expect 31)');
                log.push('applyPreset works: ' + (epAR === 31));

                const numOpsSlider = document.getElementById('num-ops-select');
                log.push('numOps selector: ' + (numOpsSlider ? numOpsSlider.value : 'NOT FOUND'));

                // Test 3: Does _applyPatch work with a simple patch?
                log.push('\n--- Test 3: _applyPatch ---');
                const testPatch = {
                    name: 'Test', operators: [
                        { freq_ratio: 3.0, level: 0.7, ar: 25, d1r: 10, dl: 6, d2r: 2, rr: 10,
                          feedback: 0, mdl: 0, mod_source: -1, is_carrier: true,
                          loop_mode: 1, loop_start: 0, loop_end: 1024 }
                    ]
                };
                log.push('Calling _applyPatch with 1-op patch (AR=25)...');
                this._applyPatch(testPatch);

                setTimeout(() => {
                    const patchAR = this.sliders[testIdx] ? parseFloat(this.sliders[testIdx].input.value) : -1;
                    log.push('After _applyPatch: Op0 AR = ' + patchAR + ' (expect 25)');
                    log.push('_applyPatch works: ' + (patchAR === 25));

                    const numOpsAfter = document.getElementById('num-ops-select');
                    log.push('numOps after _applyPatch: ' + (numOpsAfter ? numOpsAfter.value : 'NOT FOUND') + ' (expect 1)');

                    // Test 4: Does _applyPatch with PCM work?
                    log.push('\n--- Test 4: _applyPatch with PCM ---');
                    const pcm = new Float32Array(100);
                    for (let i = 0; i < 100; i++) pcm[i] = Math.sin(2 * Math.PI * i / 100);
                    const pcmPatch = {
                        name: 'PCM Test', operators: [
                            { freq_ratio: 1.0, level: 0.9, ar: 28, d1r: 5, dl: 3, d2r: 0, rr: 12,
                              feedback: 0, mdl: 0, mod_source: -1, is_carrier: true,
                              loop_mode: 1, loop_start: 0, loop_end: 100, pcm: pcm }
                        ]
                    };
                    log.push('Calling _applyPatch with PCM patch (AR=28, 100 samples)...');
                    this._applyPatch(pcmPatch);

                    setTimeout(() => {
                        const pcmAR = this.sliders[testIdx] ? parseFloat(this.sliders[testIdx].input.value) : -1;
                        log.push('After PCM _applyPatch: Op0 AR = ' + pcmAR + ' (expect 28)');
                        log.push('PCM _applyPatch works: ' + (pcmAR === 28));
                        log.push('customWaves[0] length: ' + (this.customWaves && this.customWaves[0] ? this.customWaves[0].length : 'none'));

                        // Restore to Electric Piano
                        this.applyPreset(0);

                        log.push('\n=== Summary ===');
                        const report = log.join('\n');
                        console.log(report);
                        alert(report);
                    }, 200);
                }, 200);
            }, 200);
        }, 200);
    }

    stateChanged(key, value) {
        if (key === 'kit_path' && value) {
            this.kitPath = value;
            const label = document.getElementById('kit-path-label');
            if (label) label.textContent = value.split('/').pop() || value.split('\\').pop() || value;
        }
    }
}

/* ── Base64 helpers for kit file I/O ── */
function _b64ToArrayBuffer(b64) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes.buffer;
}

function _arrayBufferToB64(data) {
    const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
    let bin = '';
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
}

const ui = new SCSPSynthUI();
