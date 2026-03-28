/**
 * @module scsp_engine
 * @description SCSP (Saturn Custom Sound Processor) sound engine for Bebhionn tracker.
 * Wraps all SCSP-specific code as an IIFE implementing the SoundEngine interface.
 * Provides FM synthesis, waveform generation, voice allocation, TON bank import/export,
 * and a DOM-based instrument editor. Communicates with an Emscripten-compiled SCSP
 * emulator via WASM for real-time audio rendering.
 *
 * @typedef {Object} SoundEngine
 * @property {function(): Promise<void>} init
 * @property {function(Object): void} startAudio
 * @property {function(number, number, number, Object): void} triggerNote
 * @property {function(number): void} releaseChannel
 * @property {function(): void} releaseAll
 * @property {function(ArrayBuffer, string): {instruments: Object[], message: string}} importBank
 * @property {function(Object[]): ?Uint8Array} exportBank
 * @property {function(HTMLElement, Object, number, function): void} renderInstEditor
 * @property {function(): Object} createDefaultInstrument
 * @property {function(): Object[]} getPresets
 * @property {function(): number} getSampleRate
 */
var SCSPEngine = (function() {
    'use strict';

    // ── Constants ──────────────────────────────────────────────────────

    /** @constant {number} SAMPLE_RATE - Audio sample rate in Hz */
    var SAMPLE_RATE = 44100;
    /** @constant {number} WAVE_LEN - Default waveform length in samples */
    var WAVE_LEN = 1024;
    /** @constant {number} WAVE_BYTES - Default waveform size in bytes (16-bit samples) */
    var WAVE_BYTES = WAVE_LEN * 2;
    /** @constant {number} SINE_BASE_FREQ - Base frequency of a WAVE_LEN-sample waveform at SAMPLE_RATE */
    var SINE_BASE_FREQ = SAMPLE_RATE / WAVE_LEN;
    /** @constant {number} SINE_BASE_NOTE - MIDI note corresponding to SINE_BASE_FREQ */
    var SINE_BASE_NOTE = 69 + 12 * Math.log2(SINE_BASE_FREQ / 440);
    /** @constant {string[]} WAVE_NAMES - Names of the 10 built-in waveform types */
    var WAVE_NAMES = ['Sine','Sawtooth','Square','Triangle','Organ','Brass','Strings','Piano','Flute','Bass'];
    /** @constant {number} MAX_SLOTS - Maximum number of SCSP sound slots */
    var MAX_SLOTS = 32;
    /** @constant {number} SCSP_RAM_SIZE - Total SCSP RAM in bytes (512KB) */
    var SCSP_RAM_SIZE = 512 * 1024;

    // ── State ──────────────────────────────────────────────────────────
    var scsp = null, scspReady = false;
    var actx = null, fmNode = null, fmGain = null;
    var playbackRef = null;
    var waveStore = { waves: [], nextOffset: 0 };

    // ── Preset instruments ─────────────────────────────────────────────
    var PRESET_INSTRUMENTS = [
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

    // ── Internal functions ─────────────────────────────────────────────

    /**
     * @description Generate a waveform via additive synthesis, normalized to [-1, 1].
     * @param {number} n - Number of samples to generate
     * @param {Array<[number, number]>} harmonics - Array of [harmonic_number, amplitude] pairs
     * @returns {Float32Array} Peak-normalized waveform samples
     */
    function genAdditive(n, harmonics) {
        var out = new Float32Array(n);
        for (var k = 0; k < harmonics.length; k++) {
            var h = harmonics[k][0], a = harmonics[k][1];
            for (var i = 0; i < n; i++) out[i] += a * Math.sin(2 * Math.PI * h * i / n);
        }
        var peak = 0;
        for (var i = 0; i < n; i++) if (Math.abs(out[i]) > peak) peak = Math.abs(out[i]);
        if (peak > 0) for (var i = 0; i < n; i++) out[i] /= peak;
        return out;
    }

    /**
     * @description Generate one of 10 named waveforms by type index.
     * 0=Sine, 1=Sawtooth, 2=Square, 3=Triangle, 4=Organ, 5=Brass,
     * 6=Strings, 7=Piano, 8=Flute, 9=Bass.
     * @param {number} type - Waveform type index (0-9)
     * @param {number} n - Number of samples to generate
     * @returns {Float32Array} Generated waveform samples
     */
    function generateWaveform(type, n) {
        switch (type) {
        case 0: return genAdditive(n, [[1, 1.0]]);
        case 1: return genAdditive(n, Array.from({length:15}, function(_, i) { return [i+1, (((i+1)%2===0)?-1:1)/(i+1)]; }));
        case 2: return genAdditive(n, Array.from({length:8}, function(_, i) { return [2*i+1, 1.0/(2*i+1)]; }));
        case 3: return genAdditive(n, Array.from({length:8}, function(_, i) { return [2*i+1, ((i%2===0)?1:-1)/((2*i+1)*(2*i+1))]; }));
        case 4: return genAdditive(n, [[1,1],[2,0.8],[3,0.6],[4,0.3],[6,0.2],[8,0.15],[10,0.1]]);
        case 5: return genAdditive(n, [[1,1],[2,0.3],[3,0.7],[4,0.15],[5,0.5],[6,0.1],[7,0.3],[9,0.15]]);
        case 6: return genAdditive(n, Array.from({length:20}, function(_, i) { return [i+1, 1.0/Math.pow(i+1, 1.2)]; }));
        case 7: return genAdditive(n, [[1,1],[2,0.7],[3,0.4],[4,0.25],[5,0.15],[6,0.1],[7,0.08],[8,0.05]]);
        case 8: return genAdditive(n, [[1,1],[2,0.15],[3,0.05]]);
        case 9: return genAdditive(n, [[1,1],[2,0.5],[3,0.2],[4,0.1]]);
        default: return new Float32Array(n);
        }
    }

    /**
     * @description Store a waveform in SCSP RAM as 16-bit PCM. Converts float samples
     * to signed 16-bit and writes them at the next available offset.
     * @param {number} ramPtr - Pointer to SCSP RAM base in WASM heap
     * @param {Float32Array} floatSamples - Waveform samples in [-1, 1] range
     * @param {number} loopStart - Loop start point in samples
     * @param {number} loopEnd - Loop end point in samples
     * @param {number} loopMode - SCSP loop control mode (0=off, 1=forward, 2=reverse, 3=alternating)
     * @returns {number} Waveform ID, or 0 if RAM is full
     */
    function waveStoreAdd(ramPtr, floatSamples, loopStart, loopEnd, loopMode) {
        var offset = waveStore.nextOffset;
        var len = floatSamples.length;
        var byteSize = len * 2;
        if (offset + byteSize > SCSP_RAM_SIZE) {
            console.warn('waveStoreAdd: skipping, would exceed 512KB RAM');
            return 0;
        }
        for (var i = 0; i < len; i++) {
            var val = Math.round(floatSamples[i] * 32767);
            scsp.HEAPU8[ramPtr + offset + i * 2]     = val & 0xFF;
            scsp.HEAPU8[ramPtr + offset + i * 2 + 1] = (val >> 8) & 0xFF;
        }
        var id = waveStore.waves.length;
        waveStore.waves.push({ offset: offset, length: len, loopStart: loopStart, loopEnd: loopEnd, loopMode: loopMode });
        waveStore.nextOffset = offset + byteSize;
        return id;
    }

    // ── Voice allocator ────────────────────────────────────────────────

    var voiceAlloc = {
        voices: [],
        time: 0,
        allocate: function(ch, note, numOps) {
            this.release(ch);
            var used = new Set();
            for (var v = 0; v < this.voices.length; v++)
                for (var s = 0; s < this.voices[v].slots.length; s++) used.add(this.voices[v].slots[s]);
            var startSlot = -1;
            for (var s = 0; s <= MAX_SLOTS - numOps; s++) {
                var ok = true;
                for (var j = 0; j < numOps; j++) { if (used.has(s + j)) { ok = false; break; } }
                if (ok) { startSlot = s; break; }
            }
            if (startSlot < 0) {
                if (this.voices.length > 0) {
                    this.voices.sort(function(a, b) { return a.time - b.time; });
                    var stolen = this.voices.shift();
                    for (var s2 = 0; s2 < stolen.slots.length; s2++) scsp._scsp_key_off(stolen.slots[s2]);
                    startSlot = stolen.slots[0];
                } else {
                    startSlot = 0;
                }
            }
            var slots = [];
            for (var j2 = 0; j2 < numOps; j2++) slots.push(startSlot + j2);
            this.voices.push({ ch: ch, note: note, slots: slots, time: this.time++ });
            return slots;
        },
        release: function(ch, note) {
            var idx = note !== undefined
                ? this.voices.findIndex(function(v) { return v.ch === ch && v.note === note; })
                : this.voices.findIndex(function(v) { return v.ch === ch; });
            if (idx >= 0) {
                var v = this.voices[idx];
                for (var s = 0; s < v.slots.length; s++) scsp._scsp_key_off(v.slots[s]);
                this.voices.splice(idx, 1);
            }
        },
        releaseAll: function() {
            for (var v = 0; v < this.voices.length; v++)
                for (var s = 0; s < this.voices[v].slots.length; s++) scsp._scsp_key_off(this.voices[v].slots[s]);
            this.voices = [];
        }
    };

    // ── resetSCSP ──────────────────────────────────────────────────────

    /**
     * @description Reset SCSP emulator state: re-initialize hardware, release all voices,
     * clear waveform store, and reload the 10 built-in waveforms into RAM.
     */
    function resetSCSP() {
        scsp._scsp_init();
        voiceAlloc.releaseAll();
        waveStore.waves = [];
        waveStore.nextOffset = 0;
        var ramPtr = scsp._scsp_get_ram_ptr();
        for (var t = 0; t < WAVE_NAMES.length; t++) {
            var samples = generateWaveform(t, WAVE_LEN);
            waveStoreAdd(ramPtr, samples, 0, WAVE_LEN, 1);
        }
    }

    // ── programSlot ────────────────────────────────────────────────────

    /**
     * @description Compute and program SCSP registers for a slot from high-level operator
     * parameters. Handles pitch calculation (octave + FNS), envelope registers (AR/D1R/D2R/DL/RR),
     * total level, FM modulation ring buffer offsets (MDL/MDXSL/MDYSL), feedback, and
     * direct-output routing. Modulators are forced to use the default 1024-sample waveform.
     * @param {number} slot - SCSP slot index (0-31)
     * @param {Object} op - High-level operator parameters (freq_ratio, level, ar, d1r, etc.)
     * @param {number} midiNote - MIDI note number to play (0-127)
     * @param {Object[]} allOps - All operators in the instrument (for resolving mod_source)
     */
    function programSlot(slot, op, midiNote, allOps) {
        var wid = op.waveform || 0;
        var wav = waveStore.waves[wid] || waveStore.waves[0];

        var lsa = op.loop_start >= 0 ? op.loop_start : wav.loopStart;
        var lea = op.loop_end > 0 ? op.loop_end : wav.loopEnd;
        var lpctl = op.loop_mode >= 0 ? op.loop_mode : wav.loopMode;
        var sa = wav.offset;

        var usesFM = (op.mod_source >= 0 && op.mdl >= 5) || op.feedback > 0;
        var isMod = !op.is_carrier;
        if (usesFM || isMod) {
            if (wav.length !== WAVE_LEN) {
                wav = waveStore.waves[0];
                sa = wav.offset;
            }
            lsa = 0; lea = WAVE_LEN; lpctl = 1;
        }

        var wavLen = wav.length || WAVE_LEN;
        var wavBaseFreq = SAMPLE_RATE / wavLen;
        var wavBaseNote = 69 + 12 * Math.log2(wavBaseFreq / 440);

        var opBaseNote;
        if (op.freq_fixed > 0) {
            opBaseNote = wavBaseNote + 12 * Math.log2(op.freq_fixed / wavBaseFreq);
        } else {
            opBaseNote = wavBaseNote - 12 * Math.log2(op.freq_ratio || 1);
        }
        var semi = midiNote - opBaseNote;
        var octave = Math.max(-8, Math.min(7, Math.floor(semi / 12)));
        var frac = semi - octave * 12;
        var fns = Math.max(0, Math.min(1023, Math.round(1024 * (Math.pow(2, frac / 12) - 1))));
        var octBits = ((octave & 0xF) << 11) | (fns & 0x3FF);

        var d0 = (lpctl << 5) | ((sa >> 16) & 0xF);
        var d4 = ((op.d2r & 0x1F) << 11) | ((op.d1r & 0x1F) << 6) | (op.ar & 0x1F);
        var d5 = ((op.dl & 0x1F) << 5) | (op.rr & 0x1F);

        var tl;
        if (op.is_carrier) {
            tl = Math.max(0, Math.min(255, Math.round((1.0 - op.level) * 255)));
        } else {
            tl = Math.round(24 + (1.0 - op.level) * 56);
        }
        var d6 = tl & 0xFF;

        var mdl = 0, mdxsl = 0, mdysl = 0;
        if (op.mod_source >= 0 && op.mdl >= 5) {
            var modOp = allOps[op.mod_source];
            var modTL = Math.round(24 + (1.0 - modOp.level) * 56);
            var segaDB = 0;
            if(modTL&1) segaDB-=0.4; if(modTL&2) segaDB-=0.8; if(modTL&4) segaDB-=1.5;
            if(modTL&8) segaDB-=3; if(modTL&16) segaDB-=6; if(modTL&32) segaDB-=12;
            if(modTL&64) segaDB-=24; if(modTL&128) segaDB-=48;
            var tlLin = Math.pow(10, segaDB / 20);
            var ringPeak = 32767 * 4 * tlLin / 2;
            var targetBeta = Math.min(modOp.level * Math.PI, 2.5);
            var needed = targetBeta * 1024 / (ringPeak * 2 * Math.PI);
            mdl = Math.max(0, Math.min(15, Math.round(16 + Math.log2(Math.max(needed, 1e-10)))));
            var maxSafe = 1024 / (ringPeak * 2);
            var maxMDL = Math.floor(15 + Math.log2(Math.max(maxSafe, 1e-10)));
            mdl = Math.min(mdl, maxMDL);
            var dist = (op.mod_source - slot) & 63;
            mdxsl = dist; mdysl = dist;
        }
        if (op.feedback > 0) {
            var fbDist = (-32) & 63;
            var myTL = tl;
            var segaDB2 = 0;
            if(myTL&1) segaDB2-=0.4; if(myTL&2) segaDB2-=0.8; if(myTL&4) segaDB2-=1.5;
            if(myTL&8) segaDB2-=3; if(myTL&16) segaDB2-=6; if(myTL&32) segaDB2-=12;
            if(myTL&64) segaDB2-=24; if(myTL&128) segaDB2-=48;
            var tlLin2 = Math.pow(10, segaDB2 / 20);
            var ringPeak2 = 32767 * 4 * tlLin2 / 2;
            var targetBeta2 = op.feedback * Math.PI;
            var needed2 = targetBeta2 * 1024 / (ringPeak2 * 2 * Math.PI);
            var fbMdl = Math.max(0, Math.min(15, Math.round(16 + Math.log2(Math.max(needed2, 1e-10)))));
            if (mdl > 0) { mdysl = fbDist; mdl = Math.max(mdl, fbMdl); }
            else { mdl = fbMdl; mdxsl = fbDist; mdysl = fbDist; }
        }
        var d7 = ((mdl & 0xF) << 12) | ((mdxsl & 0x3F) << 6) | (mdysl & 0x3F);

        var disdl = op.is_carrier ? 7 : 0;
        var dipan = 16;
        var dB = ((disdl & 0x7) << 13) | ((dipan & 0x1F) << 8);

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

    // ── programSlotRaw ─────────────────────────────────────────────────

    /**
     * @description Program a SCSP slot from raw TON register data. Only recalculates
     * pitch (octave + FNS) and FM ring buffer offsets; all other register values are
     * used as-is from the imported TON file.
     * @param {number} slot - SCSP slot index (0-31)
     * @param {Object} rawRegs - Raw register values (d0, d4, d5, d7, tl, dB, baseNote, lsa, lea, sa)
     * @param {number} midiNote - MIDI note number to play (0-127)
     * @param {number} sa - Sample address (byte offset in SCSP RAM)
     * @param {number} slotBase - First slot index of this voice (for relative mod_source calculation)
     * @param {number} opIndex - Operator index within the instrument
     * @param {number} wavLen - Waveform length in samples (for clamping loop points)
     * @param {number} modSource - Modulation source operator index, or -1 for none/feedback
     */
    function programSlotRaw(slot, rawRegs, midiNote, sa, slotBase, opIndex, wavLen, modSource) {
        var semi = midiNote - rawRegs.baseNote;
        var octave = Math.max(-8, Math.min(7, Math.floor(semi / 12)));
        var frac = semi - octave * 12;
        var fns = Math.max(0, Math.min(1023, Math.round(1024 * (Math.pow(2, frac / 12) - 1))));
        var octBits = ((octave & 0xF) << 11) | (fns & 0x3FF);

        var d0 = (rawRegs.d0 & 0xE0) | ((sa >> 16) & 0xF);
        var lsa = Math.min(rawRegs.lsa, wavLen);
        var lea = Math.min(rawRegs.lea, wavLen);

        var d7 = rawRegs.d7;
        var mdl = (d7 >> 12) & 0xF;
        if (mdl > 0 && modSource >= 0) {
            var modSlot = slotBase + modSource;
            var mdxsl = (modSlot - slot) & 63;
            var mdysl = mdxsl;
            d7 = ((mdl & 0xF) << 12) | ((mdxsl & 0x3F) << 6) | (mdysl & 0x3F);
        } else if (mdl > 0) {
            var fbDist = 32;
            d7 = ((mdl & 0xF) << 12) | ((fbDist & 0x3F) << 6) | (fbDist & 0x3F);
        }

        scsp._scsp_write_slot(slot, 0x0, d0);
        scsp._scsp_write_slot(slot, 0x1, sa & 0xFFFF);
        scsp._scsp_write_slot(slot, 0x2, lsa);
        scsp._scsp_write_slot(slot, 0x3, lea);
        scsp._scsp_write_slot(slot, 0x4, rawRegs.d4);
        scsp._scsp_write_slot(slot, 0x5, rawRegs.d5);
        scsp._scsp_write_slot(slot, 0x6, rawRegs.tl);
        scsp._scsp_write_slot(slot, 0x7, d7);
        scsp._scsp_write_slot(slot, 0x8, octBits);
        scsp._scsp_write_slot(slot, 0x9, 0);
        scsp._scsp_write_slot(slot, 0xA, 0);
        scsp._scsp_write_slot(slot, 0xB, rawRegs.dB & 0xFF00);
    }

    // ── syncRawRegs ────────────────────────────────────────────────────

    /**
     * @description Sync high-level operator parameters back to raw SCSP registers.
     * Called when the user edits a parameter in the instrument editor, so that
     * subsequent programSlotRaw calls reflect the changes.
     * @param {Object} op - Operator object with both high-level params and a rawRegs sub-object
     */
    function syncRawRegs(op) {
        if (!op.rawRegs) return;
        if (op.freq_ratio > 0) {
            var ratioSemitones = Math.round(12 * Math.log2(op.freq_ratio));
            op.rawRegs.baseNote = Math.max(0, Math.min(127, 69 - ratioSemitones));
        }
        op.rawRegs.tl = Math.max(0, Math.min(255, Math.round((1.0 - (op.level || 0)) * 128)));
        var ar = Math.round(op.ar || 0) & 0x1F;
        var d1r = Math.round(op.d1r || 0) & 0x1F;
        var d2r = Math.round(op.d2r || 0) & 0x1F;
        op.rawRegs.d4 = (d2r << 11) | (d1r << 6) | ar;
        var krs = (op.rawRegs.d5 >> 10) & 0xF;
        var dl = Math.round(op.dl || 0) & 0x1F;
        var rr = Math.round(op.rr || 0) & 0x1F;
        op.rawRegs.d5 = (krs << 10) | (dl << 5) | rr;
        var mdl = Math.round(op.mdl || 0) & 0xF;
        op.rawRegs.d7 = (op.rawRegs.d7 & 0x0FFF) | (mdl << 12);
        var disdl = op.is_carrier ? 7 : 0;
        var dipan = (op.rawRegs.dB >> 8) & 0x1F;
        op.rawRegs.dB = ((disdl << 5) | dipan) << 8 | (op.rawRegs.dB & 0xFF);
        op.rawRegs.lsa = op.loop_start || 0;
        op.rawRegs.lea = op.loop_end || 1024;
        var lpctl = (op.loop_mode !== undefined ? op.loop_mode : 1) & 3;
        op.rawRegs.d0 = (op.rawRegs.d0 & 0x1F) | (lpctl << 5);
    }

    // ── _triggerNote ───────────────────────────────────────────────────

    /**
     * @description Play a note: allocate voice slots via the voice allocator, program each
     * operator's slot (using raw or high-level path), then key-on all slots.
     * @param {number} ch - Channel number (used for voice allocation/release tracking)
     * @param {number} midiNote - MIDI note number (0-127)
     * @param {number} instIdx - Instrument index (for logging only)
     * @param {Object} inst - Instrument object with an operators array
     */
    function _triggerNote(ch, midiNote, instIdx, inst) {
        if (!inst) { console.warn('[triggerNote] no inst at', instIdx); return; }
        var ops = inst.operators;
        var slots = voiceAlloc.allocate(ch, midiNote, ops.length);
        var slotBase = slots[0];
        for (var i = 0; i < ops.length; i++) {
            var op = ops[i];
            if (op.rawRegs) {
                if (op.useTonSA) {
                    var origSA = ((op.rawRegs.d0 & 0x0F) << 16) | op.rawRegs.sa;
                    programSlotRaw(slots[i], op.rawRegs, midiNote, origSA, slotBase, i, op.rawRegs.lea, op.mod_source);
                } else {
                    var wav = waveStore.waves[op.waveform || 0] || waveStore.waves[0];
                    programSlotRaw(slots[i], op.rawRegs, midiNote, wav.offset, slotBase, i, wav.length, op.mod_source);
                }
            } else {
                programSlot(slots[i], op, midiNote, ops);
            }
        }
        for (var s = 0; s < slots.length; s++) scsp._scsp_key_on(slots[s]);
    }

    // ── _importBank ────────────────────────────────────────────────────

    /**
     * @description Import a TON file: byte-swap and copy into SCSP RAM, parse instrument
     * definitions via TonIO, then reload built-in waveforms after the TON data.
     * On error, resets to preset instruments.
     * @param {ArrayBuffer} arrayBuffer - Raw TON file contents
     * @param {string} label - Display name for status messages (e.g. filename)
     * @returns {{instruments: ?Object[], message: string}} Parsed instruments and status message
     */
    function _importBank(arrayBuffer, label) {
        try {
            scsp._scsp_init();
            voiceAlloc.releaseAll();
            var ramPtr = scsp._scsp_get_ram_ptr();
            var tonBytes = new Uint8Array(arrayBuffer);

            if (tonBytes.length > SCSP_RAM_SIZE) {
                return { instruments: null, message: label + ' exceeds 512KB SCSP RAM' };
            }

            if (ramPtr + tonBytes.length > scsp.HEAPU8.length) {
                return { instruments: null, message: 'TON too large for WASM heap' };
            }

            // Byte-swap entire file (BE->LE) into SCSP RAM
            for (var i = 0; i < tonBytes.length - 1; i += 2) {
                scsp.HEAPU8[ramPtr + i]     = tonBytes[i + 1];
                scsp.HEAPU8[ramPtr + i + 1] = tonBytes[i];
            }

            var result = TonIO.importTon(arrayBuffer);

            // Reset waveStore and load built-in waveforms after TON data
            waveStore.waves = [];
            waveStore.nextOffset = tonBytes.length;
            for (var t = 0; t < WAVE_NAMES.length; t++) {
                var samples = generateWaveform(t, WAVE_LEN);
                waveStoreAdd(ramPtr, samples, 0, WAVE_LEN, 1);
            }

            var instruments = [];
            for (var pi = 0; pi < result.patches.length; pi++) {
                var p = result.patches[pi];
                instruments.push({
                    name: p.name || ('Voice ' + pi),
                    operators: p.operators.map(function(o) {
                        return {
                            freq_ratio: o.freq_ratio || 1, freq_fixed: 0,
                            level: o.level !== undefined ? o.level : 0.8,
                            ar: o.ar !== undefined ? o.ar : 31, d1r: o.d1r || 0, dl: o.dl || 0,
                            d2r: o.d2r || 0, rr: o.rr !== undefined ? o.rr : 14,
                            mdl: o.mdl || 0, mod_source: o.mod_source !== undefined ? o.mod_source : -1,
                            feedback: o.feedback || 0, is_carrier: o.is_carrier !== undefined ? o.is_carrier : true,
                            waveform: 0, loop_mode: o.loop_mode !== undefined ? o.loop_mode : 1,
                            loop_start: o.loop_start || 0, loop_end: o.loop_end || 1024,
                            rawRegs: o.rawRegs || null,
                            useTonSA: true,
                        };
                    })
                });
            }

            scspReady = true;
            return { instruments: instruments, message: 'Loaded ' + instruments.length + ' instruments from ' + label + ' (' + Math.round(tonBytes.length/1024) + 'KB)' };
        } catch (err) {
            console.error('TON load error:', err);
            resetSCSP();
            scspReady = true;
            return { instruments: JSON.parse(JSON.stringify(PRESET_INSTRUMENTS)), message: 'Error loading ' + label + ': ' + err.message + ' — reset to presets' };
        }
    }

    // ── _renderInstEditor ──────────────────────────────────────────────

    /**
     * @description Build SCSP-specific instrument editor DOM. Renders operator tabs
     * (with add/remove), parameter sliders (ratio, level, AR, D1R, DL, D2R, RR, FB, MDL),
     * mod source and waveform dropdowns, carrier toggle, and a test-note button.
     * Each parameter change calls syncRawRegs to keep raw registers in sync.
     * @param {HTMLElement} container - DOM element to render into (cleared first)
     * @param {Object} inst - Instrument object with operators array
     * @param {number} selectedOp - Currently selected operator index
     * @param {function} onChange - Callback invoked when any parameter changes
     */
    function _renderInstEditor(container, inst, selectedOp, onChange) {
        container.innerHTML = '';
        if (!inst) return;

        // Operator tabs
        var tabBar = document.createElement('div');
        tabBar.style.marginBottom = '4px';
        for (var i = 0; i < inst.operators.length; i++) {
            var tab = document.createElement('span');
            tab.className = 'op-tab' + (i === selectedOp ? ' sel' : '') + (inst.operators[i].is_carrier ? ' carrier' : '');
            tab.textContent = 'Op' + (i + 1);
            tab.onclick = (function(idx) { return function() { _renderInstEditor(container, inst, idx, onChange); }; })(i);
            tabBar.appendChild(tab);
        }
        var addOp = document.createElement('span');
        addOp.className = 'op-tab'; addOp.textContent = '+';
        addOp.onclick = function() {
            if (inst.operators.length >= 6) return;
            inst.operators.push({ freq_ratio:1.0, freq_fixed:0, level:0.8, ar:31, d1r:0, dl:0, d2r:0, rr:14, mdl:0, mod_source:-1, feedback:0, is_carrier:true, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 });
            _renderInstEditor(container, inst, inst.operators.length - 1, onChange);
            if (onChange) onChange();
        };
        tabBar.appendChild(addOp);
        if (inst.operators.length > 1) {
            var rmOp = document.createElement('span');
            rmOp.className = 'op-tab'; rmOp.textContent = '-';
            rmOp.onclick = function() {
                inst.operators.splice(selectedOp, 1);
                var newSel = selectedOp >= inst.operators.length ? inst.operators.length - 1 : selectedOp;
                _renderInstEditor(container, inst, newSel, onChange);
                if (onChange) onChange();
            };
            tabBar.appendChild(rmOp);
        }
        container.appendChild(tabBar);

        var op = inst.operators[selectedOp];
        if (!op) return;

        var params = [
            { key:'freq_ratio', label:'Ratio', min:0.5, max:16, step:0.001, fmt: function(v) { return v.toFixed(3); } },
            { key:'level', label:'Level', min:0, max:1, step:0.01, fmt: function(v) { return v.toFixed(2); } },
            { key:'ar', label:'AR', min:0, max:31, step:1, fmt: function(v) { return Math.round(v); } },
            { key:'d1r', label:'D1R', min:0, max:31, step:1, fmt: function(v) { return Math.round(v); } },
            { key:'dl', label:'DL', min:0, max:31, step:1, fmt: function(v) { return Math.round(v); } },
            { key:'d2r', label:'D2R', min:0, max:31, step:1, fmt: function(v) { return Math.round(v); } },
            { key:'rr', label:'RR', min:0, max:31, step:1, fmt: function(v) { return Math.round(v); } },
            { key:'feedback', label:'FB', min:0, max:0.5, step:0.01, fmt: function(v) { return v.toFixed(2); } },
            { key:'mdl', label:'MDL', min:0, max:15, step:1, fmt: function(v) { return Math.round(v); } },
        ];

        for (var pi = 0; pi < params.length; pi++) {
            var p = params[pi];
            var row = document.createElement('div'); row.className = 'op-param';
            var lbl = document.createElement('label'); lbl.textContent = p.label;
            var inp = document.createElement('input'); inp.type = 'range';
            inp.min = p.min; inp.max = p.max; inp.step = p.step; inp.value = op[p.key] || 0;
            var val = document.createElement('span'); val.className = 'val'; val.textContent = p.fmt(op[p.key] || 0);
            (function(p2, inp2, val2) {
                inp2.oninput = function() { op[p2.key] = parseFloat(inp2.value); val2.textContent = p2.fmt(op[p2.key]); syncRawRegs(op); };
            })(p, inp, val);
            row.appendChild(lbl); row.appendChild(inp); row.appendChild(val);
            container.appendChild(row);
        }

        // Mod source dropdown
        var msRow = document.createElement('div'); msRow.className = 'op-param';
        var msLbl = document.createElement('label'); msLbl.textContent = 'Mod';
        var msSel = document.createElement('select');
        var msNone = document.createElement('option'); msNone.value = -1; msNone.textContent = 'None'; msSel.appendChild(msNone);
        for (var mi = 0; mi < inst.operators.length; mi++) {
            if (mi === selectedOp) continue;
            var o = document.createElement('option'); o.value = mi; o.textContent = 'Op' + (mi + 1); msSel.appendChild(o);
        }
        msSel.value = op.mod_source;
        msSel.onchange = function() { op.mod_source = parseInt(msSel.value); syncRawRegs(op); };
        msRow.appendChild(msLbl); msRow.appendChild(msSel); container.appendChild(msRow);

        // Waveform dropdown
        var wvRow = document.createElement('div'); wvRow.className = 'op-param';
        var wvLbl = document.createElement('label'); wvLbl.textContent = 'Wave';
        var wvSel = document.createElement('select');
        for (var wi = 0; wi < WAVE_NAMES.length; wi++) {
            var wo = document.createElement('option'); wo.value = wi; wo.textContent = WAVE_NAMES[wi]; wvSel.appendChild(wo);
        }
        wvSel.value = op.waveform || 0;
        wvSel.onchange = function() { op.waveform = parseInt(wvSel.value); syncRawRegs(op); };
        wvRow.appendChild(wvLbl); wvRow.appendChild(wvSel); container.appendChild(wvRow);

        // Carrier toggle
        var cRow = document.createElement('div'); cRow.className = 'op-param';
        var cLbl = document.createElement('label'); cLbl.textContent = 'Carrier';
        var cChk = document.createElement('input'); cChk.type = 'checkbox'; cChk.checked = op.is_carrier;
        cChk.onchange = function() { op.is_carrier = cChk.checked; syncRawRegs(op); _renderInstEditor(container, inst, selectedOp, onChange); };
        cRow.appendChild(cLbl); cRow.appendChild(cChk); container.appendChild(cRow);

        // Test button
        var testRow = document.createElement('div'); testRow.style.marginTop = '8px';
        var testBtn = document.createElement('button');
        testBtn.textContent = 'Test (C-4)';
        testBtn.style.cssText = 'background:#2a4a2e;color:#8c8;border:1px solid #4a4;padding:4px 12px;cursor:pointer;border-radius:3px;font-family:inherit;font-size:10px;';
        testBtn.onclick = function() {
            api.init().then(function() {
                if (playbackRef) api.startAudio(playbackRef);
                _triggerNote(99, 60, 0, inst);
                setTimeout(function() { voiceAlloc.release(99); }, 500);
            });
        };
        testRow.appendChild(testBtn);
        container.appendChild(testRow);
    }

    // ── Public API ─────────────────────────────────────────────────────

    /** @type {SoundEngine} */
    var api = {
        /** @constant {string[]} Built-in waveform names */
        WAVE_NAMES: WAVE_NAMES,
        /** @constant {number} Default waveform length in samples */
        WAVE_LEN: WAVE_LEN,

        /** @description Initialize SCSP WASM module and load built-in waveforms. No-op if already ready.
         *  @returns {Promise<void>} */
        init: function() {
            if (scspReady) return Promise.resolve();
            if (typeof SCSP_WASM_B64 === 'undefined' || !SCSP_WASM_B64) return Promise.reject(new Error('No SCSP WASM'));
            var wasmBytes = Uint8Array.from(atob(SCSP_WASM_B64), function(c) { return c.charCodeAt(0); });
            return SCSPModule({ wasmBinary: wasmBytes.buffer }).then(function(mod) {
                scsp = mod;
                resetSCSP();
                scspReady = true;
            });
        },

        /** @description Create AudioContext, ScriptProcessor node, and audio chain (gain -> LPF -> compressor). Stores playback ref for sequencer tick processing.
         *  @param {Object} playback - Playback controller with playing flag and processBlock method */
        startAudio: function(playback) {
            playbackRef = playback;
            if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: SAMPLE_RATE });
            if (actx.state === 'suspended') actx.resume();
            if (!fmNode && scspReady) {
                fmNode = actx.createScriptProcessor(2048, 0, 2);
                fmGain = actx.createGain();
                fmGain.gain.value = 0.35;
                var lpf = actx.createBiquadFilter();
                lpf.type = 'lowpass';
                lpf.frequency.value = 16000;
                lpf.Q.value = 0.707;
                var compressor = actx.createDynamicsCompressor();
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
                    var outL = e.outputBuffer.getChannelData(0);
                    var outR = e.outputBuffer.numberOfChannels > 1 ? e.outputBuffer.getChannelData(1) : outL;
                    var n = outL.length;
                    if (!scspReady) { for (var i = 0; i < n; i++) { outL[i] = 0; outR[i] = 0; } return; }
                    if (playbackRef && playbackRef.playing) playbackRef.processBlock(n);
                    var bufPtr = scsp._scsp_render(n);
                    var heap16 = new Int16Array(scsp.HEAP16.buffer, bufPtr, n * 2);
                    for (var i = 0; i < n; i++) {
                        outL[i] = heap16[i * 2] / 32768.0;
                        outR[i] = heap16[i * 2 + 1] / 32768.0;
                    }
                };
            }
        },

        /** @description Trigger a note on the given channel.
         *  @param {number} ch - Channel number
         *  @param {number} midiNote - MIDI note (0-127)
         *  @param {number} instIdx - Instrument index
         *  @param {Object} inst - Instrument object */
        triggerNote: function(ch, midiNote, instIdx, inst) {
            _triggerNote(ch, midiNote, instIdx, inst);
        },

        /** @description Release (key-off) all voices on a channel.
         *  @param {number} ch - Channel number */
        releaseChannel: function(ch) {
            voiceAlloc.release(ch);
        },

        /** @description Release all active voices across all channels. */
        releaseAll: function() {
            voiceAlloc.releaseAll();
        },

        /** @description Import a TON bank file into SCSP RAM.
         *  @param {ArrayBuffer} arrayBuffer - Raw TON file data
         *  @param {string} label - Display name for messages
         *  @returns {{instruments: ?Object[], message: string}} */
        importBank: function(arrayBuffer, label) {
            return _importBank(arrayBuffer, label);
        },

        /** @description Export instruments to TON binary format via TonIO.
         *  @param {Object[]} instruments - Array of instrument objects
         *  @returns {?Uint8Array} TON file bytes, or null if TonIO unavailable */
        exportBank: function(instruments) {
            if (!TonIO) return null;
            return TonIO.exportTon(instruments, generateWaveform);
        },

        /** @description Render SCSP instrument editor into a DOM container.
         *  @param {HTMLElement} container - Target element
         *  @param {Object} inst - Instrument to edit
         *  @param {number} selectedOp - Active operator tab index
         *  @param {function} onChange - Change callback */
        renderInstEditor: function(container, inst, selectedOp, onChange) {
            _renderInstEditor(container, inst, selectedOp, onChange);
        },

        /** @description Create a new single-operator default instrument.
         *  @returns {Object} Instrument with one carrier operator */
        createDefaultInstrument: function() {
            return { name: 'New', operators: [{ freq_ratio:1.0, freq_fixed:0, level:0.8, ar:31, d1r:0, dl:0, d2r:0, rr:14, mdl:0, mod_source:-1, feedback:0, is_carrier:true, waveform:0, loop_mode:1, loop_start:0, loop_end:1024 }] };
        },

        /** @description Get deep copies of all preset instruments.
         *  @returns {Object[]} Array of preset instrument objects */
        getPresets: function() {
            return JSON.parse(JSON.stringify(PRESET_INSTRUMENTS));
        },

        /** @description Get the engine sample rate.
         *  @returns {number} Sample rate in Hz (44100) */
        getSampleRate: function() {
            return SAMPLE_RATE;
        },

        /** @description Exposed waveform generator for TON export. See {@link generateWaveform}. */
        generateWaveform: generateWaveform,
    };

    return api;
})();
