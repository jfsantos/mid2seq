const { describe, it } = require('node:test');
const assert = require('node:assert/strict');

// SCSPEngine is browser-only (references AudioContext, document, atob, etc.)
// but some pure functions are exposed. We load it by stubbing browser globals.
const vm = require('vm');
const fs = require('fs');
const path = require('path');

// Minimal browser stubs so the IIFE can execute
const sandbox = {
    console: console,
    Math: Math,
    Array: Array,
    Float32Array: Float32Array,
    Uint8Array: Uint8Array,
    Int16Array: Int16Array,
    Set: Set,
    JSON: JSON,
    Promise: Promise,
    atob: function() { return ''; },
    document: { createElement: function() { return { style: {}, appendChild: function(){}, onclick: null }; } },
    window: { AudioContext: function() {} },
    setTimeout: setTimeout,
    SCSPModule: function() { return Promise.resolve(null); },
    SCSP_WASM_B64: '',
    TonIO: null,
    TrackerState: require('../tracker_state.js'),
};
sandbox.globalThis = sandbox;
sandbox.self = sandbox;

const src = fs.readFileSync(path.join(__dirname, '..', 'scsp_engine.js'), 'utf8');
vm.runInNewContext(src, sandbox);
const SCSPEngine = sandbox.SCSPEngine;

describe('SCSPEngine constants', () => {
    it('WAVE_LEN is 1024', () => {
        assert.equal(SCSPEngine.WAVE_LEN, 1024);
    });

    it('WAVE_NAMES has 10 entries', () => {
        assert.equal(SCSPEngine.WAVE_NAMES.length, 10);
        assert.equal(SCSPEngine.WAVE_NAMES[0], 'Sine');
        assert.equal(SCSPEngine.WAVE_NAMES[1], 'Sawtooth');
    });
});

describe('SCSPEngine.getSampleRate', () => {
    it('returns 44100', () => {
        assert.equal(SCSPEngine.getSampleRate(), 44100);
    });
});

describe('SCSPEngine.getPresets', () => {
    it('returns an array of 8 preset instruments', () => {
        var presets = SCSPEngine.getPresets();
        assert.equal(presets.length, 8);
    });

    it('each preset has name and operators', () => {
        var presets = SCSPEngine.getPresets();
        for (var i = 0; i < presets.length; i++) {
            assert.equal(typeof presets[i].name, 'string');
            assert.ok(Array.isArray(presets[i].operators));
            assert.ok(presets[i].operators.length >= 1);
        }
    });

    it('returns deep clones (not shared references)', () => {
        var a = SCSPEngine.getPresets();
        var b = SCSPEngine.getPresets();
        a[0].name = 'MODIFIED';
        assert.notEqual(b[0].name, 'MODIFIED');
    });

    it('preset operators have FM parameters', () => {
        var presets = SCSPEngine.getPresets();
        var op = presets[0].operators[0]; // Electric Piano modulator
        assert.equal(typeof op.freq_ratio, 'number');
        assert.equal(typeof op.ar, 'number');
        assert.equal(typeof op.d1r, 'number');
        assert.equal(typeof op.rr, 'number');
        assert.equal(typeof op.is_carrier, 'boolean');
        assert.equal(typeof op.mdl, 'number');
    });
});

describe('SCSPEngine.createDefaultInstrument', () => {
    it('returns an instrument with name and operators', () => {
        var inst = SCSPEngine.createDefaultInstrument();
        assert.equal(typeof inst.name, 'string');
        assert.ok(Array.isArray(inst.operators));
        assert.equal(inst.operators.length, 1);
    });

    it('default operator is a carrier', () => {
        var inst = SCSPEngine.createDefaultInstrument();
        assert.equal(inst.operators[0].is_carrier, true);
    });

    it('returns a fresh object each time', () => {
        var a = SCSPEngine.createDefaultInstrument();
        var b = SCSPEngine.createDefaultInstrument();
        a.name = 'X';
        assert.notEqual(b.name, 'X');
    });
});

describe('SCSPEngine.generateWaveform', () => {
    it('generates a Float32Array of the requested length', () => {
        var wave = SCSPEngine.generateWaveform(0, 1024);
        assert.ok(wave instanceof Float32Array);
        assert.equal(wave.length, 1024);
    });

    it('sine wave (type 0) is normalized to peak 1.0', () => {
        var wave = SCSPEngine.generateWaveform(0, 1024);
        var peak = 0;
        for (var i = 0; i < wave.length; i++) {
            if (Math.abs(wave[i]) > peak) peak = Math.abs(wave[i]);
        }
        assert.ok(Math.abs(peak - 1.0) < 0.001, 'peak should be ~1.0, got ' + peak);
    });

    it('generates all 10 waveform types without error', () => {
        for (var type = 0; type < 10; type++) {
            var wave = SCSPEngine.generateWaveform(type, 1024);
            assert.equal(wave.length, 1024, 'type ' + type + ' has 1024 samples');
        }
    });

    it('different types produce different waveforms', () => {
        var sine = SCSPEngine.generateWaveform(0, 256);
        var saw = SCSPEngine.generateWaveform(1, 256);
        var different = false;
        for (var i = 0; i < 256; i++) {
            if (Math.abs(sine[i] - saw[i]) > 0.01) { different = true; break; }
        }
        assert.ok(different, 'sine and sawtooth should differ');
    });

    it('unknown type returns silence', () => {
        var wave = SCSPEngine.generateWaveform(99, 128);
        assert.equal(wave.length, 128);
        var allZero = true;
        for (var i = 0; i < wave.length; i++) {
            if (wave[i] !== 0) { allZero = false; break; }
        }
        assert.ok(allZero, 'unknown type should be silence');
    });

    it('sine wave has correct period (one cycle in n samples)', () => {
        var wave = SCSPEngine.generateWaveform(0, 1024);
        // Should start near 0, reach ~1 at n/4, back to ~0 at n/2
        assert.ok(Math.abs(wave[0]) < 0.01, 'starts near zero');
        assert.ok(wave[256] > 0.9, 'peaks near n/4');
        assert.ok(Math.abs(wave[512]) < 0.01, 'crosses zero at n/2');
    });
});
