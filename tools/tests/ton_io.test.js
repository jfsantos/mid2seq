const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const TonIO = require('../ton_io.js');

// -- helpers --

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
        case 0: return genAdditive(n, [[1, 1.0]]);                           // sine
        case 1: return genAdditive(n, Array.from({ length: 15 }, (_, i) =>   // sawtooth
            [i + 1, (((i + 1) % 2 === 0) ? -1 : 1) / (i + 1)]));
        default: return genAdditive(n, [[1, 1.0]]);
    }
}

function makeMinimalPatch(name, opts) {
    opts = opts || {};
    return {
        name: name || 'Test',
        operators: [{
            freq_ratio: opts.freq_ratio || 1,
            level: opts.level ?? 0.8,
            ar: opts.ar ?? 31,
            d1r: opts.d1r ?? 0,
            dl: opts.dl ?? 0,
            d2r: opts.d2r ?? 0,
            rr: opts.rr ?? 14,
            mdl: opts.mdl ?? 0,
            mod_source: opts.mod_source ?? -1,
            feedback: opts.feedback ?? 0,
            is_carrier: opts.is_carrier ?? true,
            waveform: opts.waveform ?? 0,
            loop_mode: opts.loop_mode ?? 1,
            loop_start: opts.loop_start ?? 0,
            loop_end: opts.loop_end ?? TonIO.WAVE_LEN,
        }],
    };
}

const TON_DIR = path.join(__dirname, '..', '..', 'test_ton');

// ═══════════════════════════════════════════════
// WAVE_LEN
// ═══════════════════════════════════════════════

describe('TonIO.WAVE_LEN', () => {
    it('equals 1024', () => {
        assert.equal(TonIO.WAVE_LEN, 1024);
    });
});

// ═══════════════════════════════════════════════
// exportTon
// ═══════════════════════════════════════════════

describe('TonIO.exportTon', () => {
    it('returns a Uint8Array', () => {
        const result = TonIO.exportTon([makeMinimalPatch()], generateWaveform);
        assert.ok(result instanceof Uint8Array);
        assert.ok(result.length > 0);
    });

    it('exports multiple patches', () => {
        const patches = [makeMinimalPatch('A'), makeMinimalPatch('B'), makeMinimalPatch('C')];
        const result = TonIO.exportTon(patches, generateWaveform);
        assert.ok(result.length > 0);
    });

    it('produces output that importTon can read', () => {
        const patch = makeMinimalPatch('Round-trip');
        const bin = TonIO.exportTon([patch], generateWaveform);
        const result = TonIO.importTon(bin.buffer);
        assert.equal(result.patches.length, 1);
    });

    it('accepts custom waveforms', () => {
        const patch = makeMinimalPatch('Custom');
        const customWave = new Float32Array(TonIO.WAVE_LEN);
        for (let i = 0; i < customWave.length; i++) customWave[i] = Math.sin(2 * Math.PI * i / customWave.length);
        const bin = TonIO.exportTon([patch], generateWaveform, { '0:0': customWave });
        assert.ok(bin.length > 0);
    });
});

// ═══════════════════════════════════════════════
// importTon
// ═══════════════════════════════════════════════

describe('TonIO.importTon', () => {
    it('returns an object with patches array', () => {
        const bin = TonIO.exportTon([makeMinimalPatch()], generateWaveform);
        const result = TonIO.importTon(bin.buffer);
        assert.ok(Array.isArray(result.patches));
    });

    it('each patch has name and operators', () => {
        const bin = TonIO.exportTon([makeMinimalPatch('TestName')], generateWaveform);
        const result = TonIO.importTon(bin.buffer);
        const patch = result.patches[0];
        assert.equal(typeof patch.name, 'string');
        assert.ok(Array.isArray(patch.operators));
        assert.ok(patch.operators.length >= 1);
    });

    it('operators have envelope parameters', () => {
        const bin = TonIO.exportTon([makeMinimalPatch('Env', { ar: 25, d1r: 10, rr: 8 })], generateWaveform);
        const result = TonIO.importTon(bin.buffer);
        const op = result.patches[0].operators[0];
        assert.equal(op.ar, 25);
        assert.equal(op.d1r, 10);
        assert.equal(op.rr, 8);
    });

    it('operators have PCM data as Float32Array', () => {
        const bin = TonIO.exportTon([makeMinimalPatch()], generateWaveform);
        const result = TonIO.importTon(bin.buffer);
        const op = result.patches[0].operators[0];
        assert.ok(op.pcm instanceof Float32Array);
        assert.ok(op.pcm.length > 0);
    });

    it('operators have rawRegs object', () => {
        const bin = TonIO.exportTon([makeMinimalPatch()], generateWaveform);
        const result = TonIO.importTon(bin.buffer);
        const op = result.patches[0].operators[0];
        assert.equal(typeof op.rawRegs, 'object');
    });

    it('round-trips carrier/modulator flag', () => {
        const patches = [
            {
                name: 'FM',
                operators: [
                    makeMinimalPatch('', { is_carrier: false, mod_source: -1 }).operators[0],
                    makeMinimalPatch('', { is_carrier: true, mdl: 9, mod_source: 0 }).operators[0],
                ],
            },
        ];
        const bin = TonIO.exportTon(patches, generateWaveform);
        const result = TonIO.importTon(bin.buffer);
        assert.equal(result.patches[0].operators[0].is_carrier, false);
        assert.equal(result.patches[0].operators[1].is_carrier, true);
    });

    it('reads a real TON file', function() {
        const tonPath = path.join(TON_DIR, 'KITFM.TON');
        if (!fs.existsSync(tonPath)) return;
        const buf = fs.readFileSync(tonPath);
        const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
        const result = TonIO.importTon(ab);
        assert.equal(result.patches.length, 16);
        for (const patch of result.patches) {
            assert.ok(patch.operators.length >= 1);
        }
    });
});

// ═══════════════════════════════════════════════
// export → import round-trip
// ═══════════════════════════════════════════════

describe('TonIO export/import round-trip', () => {
    it('preserves patch count', () => {
        const patches = [makeMinimalPatch('A'), makeMinimalPatch('B')];
        const bin = TonIO.exportTon(patches, generateWaveform);
        const result = TonIO.importTon(bin.buffer);
        assert.equal(result.patches.length, 2);
    });

    it('preserves freq_ratio', () => {
        const patch = makeMinimalPatch('Ratio', { freq_ratio: 2.0 });
        const bin = TonIO.exportTon([patch], generateWaveform);
        const result = TonIO.importTon(bin.buffer);
        assert.ok(Math.abs(result.patches[0].operators[0].freq_ratio - 2.0) < 0.05,
            'freq_ratio ~2.0, got ' + result.patches[0].operators[0].freq_ratio);
    });

    it('preserves level approximately', () => {
        const patch = makeMinimalPatch('Level', { level: 0.5 });
        const bin = TonIO.exportTon([patch], generateWaveform);
        const result = TonIO.importTon(bin.buffer);
        assert.ok(Math.abs(result.patches[0].operators[0].level - 0.5) < 0.05,
            'level ~0.5, got ' + result.patches[0].operators[0].level);
    });

    it('preserves loop_mode', () => {
        const patch = makeMinimalPatch('Loop', { loop_mode: 0 });
        const bin = TonIO.exportTon([patch], generateWaveform);
        const result = TonIO.importTon(bin.buffer);
        assert.equal(result.patches[0].operators[0].loop_mode, 0);
    });
});

// ═══════════════════════════════════════════════
// extractVoice
// ═══════════════════════════════════════════════

describe('TonIO.extractVoice', () => {
    it('returns a patch for valid index', () => {
        const bin = TonIO.exportTon([makeMinimalPatch('V0'), makeMinimalPatch('V1')], generateWaveform);
        const voice = TonIO.extractVoice(bin.buffer, 1);
        assert.ok(voice);
        assert.ok(voice.operators.length >= 1);
    });

    it('returns null for out-of-range index', () => {
        const bin = TonIO.exportTon([makeMinimalPatch()], generateWaveform);
        const voice = TonIO.extractVoice(bin.buffer, 5);
        assert.equal(voice, null);
    });
});

// ═══════════════════════════════════════════════
// mergeTon
// ═══════════════════════════════════════════════

describe('TonIO.mergeTon', () => {
    it('replaces a voice in an existing TON', () => {
        const original = TonIO.exportTon(
            [makeMinimalPatch('A', { ar: 20 }), makeMinimalPatch('B', { ar: 10 })],
            generateWaveform
        );
        const newPatch = makeMinimalPatch('B2', { ar: 31 });
        const merged = TonIO.mergeTon(original.buffer, 1, newPatch, generateWaveform);
        const result = TonIO.importTon(merged.buffer);
        assert.equal(result.patches.length, 2);
        assert.equal(result.patches[0].operators[0].ar, 20);  // A unchanged
        assert.equal(result.patches[1].operators[0].ar, 31);  // B replaced
    });

    it('creates a new kit when existingBuffer is null', () => {
        const patch = makeMinimalPatch('New');
        const merged = TonIO.mergeTon(null, 0, patch, generateWaveform);
        const result = TonIO.importTon(merged.buffer);
        assert.equal(result.patches.length, 1);
    });

    it('pads with empty voices when programNumber exceeds count', () => {
        const original = TonIO.exportTon([makeMinimalPatch('A')], generateWaveform);
        const newPatch = makeMinimalPatch('C');
        const merged = TonIO.mergeTon(original.buffer, 3, newPatch, generateWaveform);
        const result = TonIO.importTon(merged.buffer);
        assert.equal(result.patches.length, 4);
    });
});
