#!/usr/bin/env node
/**
 * test_ton_io.js — Automated tests for TON import/export and the
 * _applyPatch parameter mapping used by the VST UI.
 *
 * Tests:
 * 1. TON round-trip: export → import preserves all operator parameters
 * 2. Import of real-world TON files produces valid operator data
 * 3. _applyPatch parameter mapping: imported patch → setParameterValue calls
 *    must produce the exact same calls as applyPreset for equivalent data
 * 4. Multi-voice: all programs from a TON file are independently addressable
 */

const TonIO = require('./ton_io.js');
const fs = require('fs');
const path = require('path');

const MAX_OPS = 6;
const PARAMS_PER_OP = 14;
const IDX_NUM_OPS = MAX_OPS * PARAMS_PER_OP;       // 84
const IDX_CARRIER_BASE = IDX_NUM_OPS + 1;           // 85
const IDX_PROGRAM_NUM = IDX_CARRIER_BASE + 6;       // 91

let passed = 0, failed = 0;

function assert(condition, msg) {
    if (!condition) {
        console.error('  FAIL:', msg);
        failed++;
    } else {
        passed++;
    }
}

function assertClose(a, b, tol, msg) {
    if (Math.abs(a - b) > tol) {
        console.error('  FAIL:', msg, '(got', a, 'expected', b, 'tol', tol, ')');
        failed++;
    } else {
        passed++;
    }
}

/* ── Waveform generator (same as ui.js / fm_editor.py) ── */
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
    default: return genAdditive(n, [[1, 1.0]]);
    }
}

/**
 * Simulate what _applyPatch should produce: an array of
 * { index, value } calls to setParameterValue + setState calls.
 * This is the SPEC — what the DSP needs to receive.
 */
function simulateApplyPatch(patch) {
    const ops = patch.operators;
    const n = Math.min(ops.length, MAX_OPS);
    const paramCalls = [];
    const stateCalls = [];

    paramCalls.push({ index: IDX_NUM_OPS, value: n });

    for (let i = 0; i < MAX_OPS; i++) {
        const b = i * PARAMS_PER_OP;
        if (i < n) {
            const o = ops[i];
            paramCalls.push({ index: b + 0,  value: o.freq_ratio || 1 });
            paramCalls.push({ index: b + 1,  value: o.level !== undefined ? o.level : 0.8 });
            paramCalls.push({ index: b + 2,  value: o.ar !== undefined ? o.ar : 31 });
            paramCalls.push({ index: b + 3,  value: o.d1r || 0 });
            paramCalls.push({ index: b + 4,  value: o.dl || 0 });
            paramCalls.push({ index: b + 5,  value: o.d2r || 0 });
            paramCalls.push({ index: b + 6,  value: o.rr !== undefined ? o.rr : 14 });
            paramCalls.push({ index: b + 7,  value: o.feedback || 0 });
            paramCalls.push({ index: b + 8,  value: o.mdl || 0 });
            paramCalls.push({ index: b + 9,  value: (o.mod_source !== undefined ? o.mod_source : -1) + 1 });
            paramCalls.push({ index: b + 10, value: 0 }); // waveform — overridden by setState for imported PCM
            paramCalls.push({ index: b + 11, value: o.loop_mode !== undefined ? o.loop_mode : 1 });
            paramCalls.push({ index: b + 12, value: o.loop_start || 0 });
            paramCalls.push({ index: b + 13, value: o.pcm ? o.pcm.length : (o.loop_end || 1024) });
            paramCalls.push({ index: IDX_CARRIER_BASE + i, value: o.is_carrier ? 1 : 0 });

            if (o.pcm && o.pcm.length > 0) {
                stateCalls.push({ key: 'wave_' + i, samplesLength: o.pcm.length });
            }
        } else {
            // Defaults for unused slots
            paramCalls.push({ index: b + 0,  value: 1 });
            paramCalls.push({ index: b + 1,  value: 0.8 });
            paramCalls.push({ index: b + 2,  value: 31 });
            paramCalls.push({ index: b + 3,  value: 0 });
            paramCalls.push({ index: b + 4,  value: 0 });
            paramCalls.push({ index: b + 5,  value: 0 });
            paramCalls.push({ index: b + 6,  value: 14 });
            paramCalls.push({ index: b + 7,  value: 0 });
            paramCalls.push({ index: b + 8,  value: 0 });
            paramCalls.push({ index: b + 9,  value: 0 });
            paramCalls.push({ index: b + 10, value: 0 });
            paramCalls.push({ index: b + 11, value: 1 });
            paramCalls.push({ index: b + 12, value: 0 });
            paramCalls.push({ index: b + 13, value: 1024 });
            paramCalls.push({ index: IDX_CARRIER_BASE + i, value: 0 });
        }
    }
    return { paramCalls, stateCalls };
}

/**
 * Simulate what applyPreset produces for a PRESET_DATA entry.
 */
function simulateApplyPreset(preset) {
    const paramCalls = [];
    paramCalls.push({ index: IDX_NUM_OPS, value: preset.n });
    for (let i = 0; i < MAX_OPS; i++) {
        const o = i < preset.n ? preset.ops[i] : {r:1,l:0.8,ar:31,d1r:0,dl:0,d2r:0,rr:14,fb:0,mdl:0,ms:-1,c:0};
        const b = i * PARAMS_PER_OP;
        paramCalls.push({ index: b + 0,  value: o.r });
        paramCalls.push({ index: b + 1,  value: o.l });
        paramCalls.push({ index: b + 2,  value: o.ar });
        paramCalls.push({ index: b + 3,  value: o.d1r });
        paramCalls.push({ index: b + 4,  value: o.dl });
        paramCalls.push({ index: b + 5,  value: o.d2r });
        paramCalls.push({ index: b + 6,  value: o.rr });
        paramCalls.push({ index: b + 7,  value: o.fb });
        paramCalls.push({ index: b + 8,  value: o.mdl });
        paramCalls.push({ index: b + 9,  value: o.ms + 1 });
        paramCalls.push({ index: b + 10, value: o.wv || 0 });
        paramCalls.push({ index: b + 11, value: o.lm !== undefined ? o.lm : 1 });
        paramCalls.push({ index: b + 12, value: o.ls || 0 });
        paramCalls.push({ index: b + 13, value: o.le || 1024 });
        paramCalls.push({ index: IDX_CARRIER_BASE + i, value: o.c });
    }
    return { paramCalls, stateCalls: [] };
}

/* ═══════════════════════════════════════════════════════════════ */
/* TEST 1: TON round-trip preserves operator parameters          */
/* ═══════════════════════════════════════════════════════════════ */
console.log('\n=== Test 1: TON round-trip ===');
{
    const epiano = {
        name: 'E.Piano', operators: [
            { freq_ratio: 2.0, level: 0.9, ar: 31, d1r: 12, dl: 8, d2r: 0, rr: 14,
              mdl: 0, mod_source: -1, feedback: 0, is_carrier: false, waveform: 0, loop_mode: 1, loop_start: 0, loop_end: -1 },
            { freq_ratio: 1.0, level: 0.8, ar: 31, d1r: 8, dl: 4, d2r: 0, rr: 12,
              mdl: 8, mod_source: 0, feedback: 0, is_carrier: true, waveform: 0, loop_mode: 1, loop_start: 0, loop_end: -1 },
        ]
    };
    const ton = TonIO.exportTon([epiano], generateWaveform);
    const result = TonIO.importTon(ton.buffer);
    assert(result.patches.length === 1, 'Should have 1 voice');

    const ops = result.patches[0].operators;
    assert(ops.length === 2, 'Should have 2 operators');

    // Op 0: modulator, freq_ratio=2.0
    assertClose(ops[0].freq_ratio, 2.0, 0.01, 'Op0 freq_ratio');
    assertClose(ops[0].level, 0.9, 0.02, 'Op0 level');  // TL quantization
    assert(ops[0].ar === 31, 'Op0 AR=' + ops[0].ar);
    assert(ops[0].d1r === 12, 'Op0 D1R=' + ops[0].d1r);
    assert(ops[0].dl === 8, 'Op0 DL=' + ops[0].dl);
    assert(ops[0].d2r === 0, 'Op0 D2R=' + ops[0].d2r);
    assert(ops[0].rr === 14, 'Op0 RR=' + ops[0].rr);
    assert(ops[0].is_carrier === false, 'Op0 should be modulator');
    assert(ops[0].mod_source === -1, 'Op0 mod_source=' + ops[0].mod_source);

    // Op 1: carrier, freq_ratio=1.0
    assertClose(ops[1].freq_ratio, 1.0, 0.01, 'Op1 freq_ratio');
    assertClose(ops[1].level, 0.8, 0.02, 'Op1 level');
    assert(ops[1].ar === 31, 'Op1 AR=' + ops[1].ar);
    assert(ops[1].d1r === 8, 'Op1 D1R=' + ops[1].d1r);
    assert(ops[1].dl === 4, 'Op1 DL=' + ops[1].dl);
    assert(ops[1].rr === 12, 'Op1 RR=' + ops[1].rr);
    assert(ops[1].mdl === 8, 'Op1 MDL=' + ops[1].mdl);
    assert(ops[1].mod_source === 0, 'Op1 mod_source=' + ops[1].mod_source);
    assert(ops[1].is_carrier === true, 'Op1 should be carrier');

    // PCM data should be present
    assert(ops[0].pcm && ops[0].pcm.length > 0, 'Op0 should have PCM data');
    assert(ops[1].pcm && ops[1].pcm.length > 0, 'Op1 should have PCM data');
}

/* ═══════════════════════════════════════════════════════════════ */
/* TEST 2: Import real-world TON files                           */
/* ═══════════════════════════════════════════════════════════════ */
console.log('\n=== Test 2: Real-world TON import ===');
{
    const testDir = path.join(__dirname, '..', 'test_ton');
    if (fs.existsSync(testDir)) {
        const files = fs.readdirSync(testDir).filter(f => f.endsWith('.TON'));
        for (const file of files) {
            const buf = fs.readFileSync(path.join(testDir, file));
            const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
            try {
                const result = TonIO.importTon(ab);
                assert(result.patches.length > 0, file + ': should have voices (got ' + result.patches.length + ')');
                for (let vi = 0; vi < result.patches.length; vi++) {
                    const p = result.patches[vi];
                    assert(p.operators.length > 0, file + ' voice ' + vi + ': should have operators');
                    for (let oi = 0; oi < p.operators.length; oi++) {
                        const o = p.operators[oi];
                        assert(o.ar >= 0 && o.ar <= 31, file + ' v' + vi + ' op' + oi + ': AR in range (got ' + o.ar + ')');
                        assert(o.d1r >= 0 && o.d1r <= 31, file + ' v' + vi + ' op' + oi + ': D1R in range (got ' + o.d1r + ')');
                        assert(o.dl >= 0 && o.dl <= 31, file + ' v' + vi + ' op' + oi + ': DL in range (got ' + o.dl + ')');
                        assert(o.rr >= 0 && o.rr <= 31, file + ' v' + vi + ' op' + oi + ': RR in range (got ' + o.rr + ')');
                        assert(o.level >= 0 && o.level <= 1.01, file + ' v' + vi + ' op' + oi + ': level in range (got ' + o.level + ')');
                        assert(o.pcm instanceof Float32Array, file + ' v' + vi + ' op' + oi + ': pcm is Float32Array');
                    }
                }
            } catch (err) {
                assert(false, file + ': import threw: ' + err.message);
            }
        }
    } else {
        console.log('  (skipping — test_ton/ directory not found)');
    }
}

/* ═══════════════════════════════════════════════════════════════ */
/* TEST 3: _applyPatch parameter mapping matches applyPreset     */
/* ═══════════════════════════════════════════════════════════════ */
console.log('\n=== Test 3: _applyPatch produces correct setParameterValue calls ===');
{
    // Create a TON from the Electric Piano preset, then import it,
    // and verify the _applyPatch output matches applyPreset.
    const preset = { name:'Electric Piano', n:2, ops:[
        {r:2.0,l:0.9,ar:31,d1r:12,dl:8,d2r:0,rr:14,fb:0,mdl:0,ms:-1,c:0},
        {r:1.0,l:0.8,ar:31,d1r:6,dl:2,d2r:0,rr:14,fb:0,mdl:9,ms:0,c:1}]};

    // Build the equivalent TonIO patch
    const tonPatch = {
        name: 'Electric Piano', operators: [
            { freq_ratio: 2.0, level: 0.9, ar: 31, d1r: 12, dl: 8, d2r: 0, rr: 14,
              mdl: 0, mod_source: -1, feedback: 0, is_carrier: false, waveform: 0, loop_mode: 1 },
            { freq_ratio: 1.0, level: 0.8, ar: 31, d1r: 6, dl: 2, d2r: 0, rr: 14,
              mdl: 9, mod_source: 0, feedback: 0, is_carrier: true, waveform: 0, loop_mode: 1 },
        ]
    };

    // Export → import round trip
    const ton = TonIO.exportTon([tonPatch], generateWaveform);
    const imported = TonIO.importTon(ton.buffer);
    const importedPatch = imported.patches[0];

    const applyResult = simulateApplyPatch(importedPatch);
    const presetResult = simulateApplyPreset(preset);

    // Check that numOps matches
    const numOpsApply = applyResult.paramCalls.find(c => c.index === IDX_NUM_OPS);
    const numOpsPreset = presetResult.paramCalls.find(c => c.index === IDX_NUM_OPS);
    assert(numOpsApply.value === numOpsPreset.value,
        'numOps: apply=' + numOpsApply.value + ' preset=' + numOpsPreset.value);

    // Check envelope params for each active operator
    const envParams = [2, 3, 4, 5, 6]; // AR, D1R, DL, D2R, RR
    const paramNames = ['ratio', 'level', 'AR', 'D1R', 'DL', 'D2R', 'RR', 'feedback', 'MDL', 'modSrc'];
    for (let i = 0; i < 2; i++) {
        const b = i * PARAMS_PER_OP;
        for (const p of envParams) {
            const applyVal = applyResult.paramCalls.find(c => c.index === b + p);
            const presetVal = presetResult.paramCalls.find(c => c.index === b + p);
            assert(applyVal.value === presetVal.value,
                'Op' + i + ' param[' + p + ']: apply=' + applyVal.value + ' preset=' + presetVal.value);
        }

        // Check carrier flag
        const carrApply = applyResult.paramCalls.find(c => c.index === IDX_CARRIER_BASE + i);
        const carrPreset = presetResult.paramCalls.find(c => c.index === IDX_CARRIER_BASE + i);
        assert(carrApply.value === carrPreset.value,
            'Op' + i + ' carrier: apply=' + carrApply.value + ' preset=' + carrPreset.value);

        // Check MDL
        const mdlApply = applyResult.paramCalls.find(c => c.index === b + 8);
        const mdlPreset = presetResult.paramCalls.find(c => c.index === b + 8);
        assert(mdlApply.value === mdlPreset.value,
            'Op' + i + ' MDL: apply=' + mdlApply.value + ' preset=' + mdlPreset.value);

        // Check mod source
        const msApply = applyResult.paramCalls.find(c => c.index === b + 9);
        const msPreset = presetResult.paramCalls.find(c => c.index === b + 9);
        assert(msApply.value === msPreset.value,
            'Op' + i + ' modSrc: apply=' + msApply.value + ' preset=' + msPreset.value);
    }

    // Verify that imported patch has PCM and setState would be called
    assert(applyResult.stateCalls.length === 2, 'Should have 2 setState calls for PCM, got ' + applyResult.stateCalls.length);
    for (const sc of applyResult.stateCalls) {
        assert(sc.samplesLength > 0, 'setState ' + sc.key + ' should have samples');
    }

    // Check that level round-trips within TL quantization tolerance
    const lvlApply0 = applyResult.paramCalls.find(c => c.index === 0 * PARAMS_PER_OP + 1);
    assertClose(lvlApply0.value, 0.9, 0.02, 'Op0 level after round-trip');
    const lvlApply1 = applyResult.paramCalls.find(c => c.index === 1 * PARAMS_PER_OP + 1);
    assertClose(lvlApply1.value, 0.8, 0.02, 'Op1 level after round-trip');

    // Check that freq_ratio round-trips
    const ratApply0 = applyResult.paramCalls.find(c => c.index === 0 * PARAMS_PER_OP + 0);
    assertClose(ratApply0.value, 2.0, 0.01, 'Op0 freq_ratio after round-trip');
    const ratApply1 = applyResult.paramCalls.find(c => c.index === 1 * PARAMS_PER_OP + 0);
    assertClose(ratApply1.value, 1.0, 0.01, 'Op1 freq_ratio after round-trip');
}

/* ═══════════════════════════════════════════════════════════════ */
/* TEST 4: All programs in a multi-voice TON are addressable     */
/* ═══════════════════════════════════════════════════════════════ */
console.log('\n=== Test 4: Multi-voice TON ===');
{
    const testDir = path.join(__dirname, '..', 'test_ton');
    const kitPath = path.join(testDir, 'KITFM.TON');
    if (fs.existsSync(kitPath)) {
        const buf = fs.readFileSync(kitPath);
        const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
        const result = TonIO.importTon(ab);

        assert(result.patches.length === 16, 'KITFM.TON should have 16 voices, got ' + result.patches.length);

        // Voice 0 is a 2-op FM patch
        assert(result.patches[0].operators.length === 2, 'Voice 0 should have 2 ops');
        assert(result.patches[0].operators[0].is_carrier === false, 'Voice 0 Op0 is modulator');
        assert(result.patches[0].operators[1].is_carrier === true, 'Voice 0 Op1 is carrier');

        // extractVoice should return individual voices
        for (let i = 0; i < result.patches.length; i++) {
            const voice = TonIO.extractVoice(ab, i);
            assert(voice !== null, 'extractVoice(' + i + ') should not be null');
            assert(voice.operators.length === result.patches[i].operators.length,
                'extractVoice(' + i + ') op count matches');
        }

        // extractVoice beyond range returns null
        assert(TonIO.extractVoice(ab, 99) === null, 'extractVoice(99) should be null');

        // Each voice's parameters should produce valid _applyPatch calls
        for (let i = 0; i < Math.min(result.patches.length, 6); i++) {
            const sim = simulateApplyPatch(result.patches[i]);
            const numOps = sim.paramCalls.find(c => c.index === IDX_NUM_OPS);
            assert(numOps.value === result.patches[i].operators.length,
                'Voice ' + i + ' numOps=' + numOps.value + ' matches ops count');
            assert(sim.stateCalls.length === result.patches[i].operators.length,
                'Voice ' + i + ' setState calls=' + sim.stateCalls.length + ' matches ops');
        }
    } else {
        console.log('  (skipping — KITFM.TON not found)');
    }
}

/* ═══════════════════════════════════════════════════════════════ */
/* TEST 5: mergeTon preserves other voices                       */
/* ═══════════════════════════════════════════════════════════════ */
console.log('\n=== Test 5: mergeTon preserves other voices ===');
{
    const patch0 = { name: 'P0', operators: [
        { freq_ratio: 2.0, level: 0.9, ar: 31, d1r: 12, dl: 8, d2r: 0, rr: 14,
          mdl: 0, mod_source: -1, is_carrier: false, waveform: 0, loop_mode: 1 },
        { freq_ratio: 1.0, level: 0.8, ar: 31, d1r: 8, dl: 4, d2r: 0, rr: 12,
          mdl: 8, mod_source: 0, is_carrier: true, waveform: 0, loop_mode: 1 },
    ]};
    const patch1 = { name: 'P1', operators: [
        { freq_ratio: 0.5, level: 0.95, ar: 28, d1r: 4, dl: 2, d2r: 0, rr: 10,
          mdl: 0, mod_source: -1, is_carrier: true, waveform: 0, loop_mode: 1 },
    ]};

    const ton1 = TonIO.exportTon([patch0, patch1], generateWaveform);
    const before = TonIO.importTon(ton1.buffer);

    // Merge a new patch at slot 0
    const newPatch = { name: 'New', operators: [
        { freq_ratio: 3.0, level: 0.7, ar: 25, d1r: 10, dl: 6, d2r: 0, rr: 14,
          mdl: 0, mod_source: -1, is_carrier: true, waveform: 0, loop_mode: 1 },
    ]};
    const ton2 = TonIO.mergeTon(ton1.buffer, 0, newPatch, generateWaveform);
    const after = TonIO.importTon(ton2.buffer);

    assert(after.patches.length === 2, 'Should still have 2 voices');
    // Slot 0 should be updated
    assert(after.patches[0].operators.length === 1, 'Slot 0 now has 1 op');
    assert(after.patches[0].operators[0].ar === 25, 'Slot 0 AR updated to 25, got ' + after.patches[0].operators[0].ar);
    // Slot 1 should be preserved
    assert(after.patches[1].operators.length === 1, 'Slot 1 still has 1 op');
    assert(after.patches[1].operators[0].ar === 28, 'Slot 1 AR preserved at 28, got ' + after.patches[1].operators[0].ar);
    assertClose(after.patches[1].operators[0].level, 0.95, 0.02, 'Slot 1 level preserved');
}

/* ═══════════════════════════════════════════════════════════════ */
/* TEST 6: _applyPatch call structure matches applyPreset        */
/* ═══════════════════════════════════════════════════════════════ */
console.log('\n=== Test 6: _applyPatch call structure matches applyPreset ===');
{
    // Mock UI that records setParameterValue and setState calls
    function createMockUI() {
        const paramLog = [];
        const stateLog = [];
        return {
            customWaves: {},
            setParameterValue(index, value) { paramLog.push({ index, value }); },
            setState(key, value) { stateLog.push({ key, valueLen: value.length }); },
            paramLog,
            stateLog,
        };
    }

    // Extract applyPreset logic as standalone function
    function runApplyPreset(ui, preset) {
        ui.setParameterValue(IDX_NUM_OPS, preset.n);
        for (let i = 0; i < MAX_OPS; i++) {
            const o = i < preset.n ? preset.ops[i] : {r:1,l:0.8,ar:31,d1r:0,dl:0,d2r:0,rr:14,fb:0,mdl:0,ms:-1,c:0};
            const b = i * PARAMS_PER_OP;
            ui.setParameterValue(b + 0, o.r);
            ui.setParameterValue(b + 1, o.l);
            ui.setParameterValue(b + 2, o.ar);
            ui.setParameterValue(b + 3, o.d1r);
            ui.setParameterValue(b + 4, o.dl);
            ui.setParameterValue(b + 5, o.d2r);
            ui.setParameterValue(b + 6, o.rr);
            ui.setParameterValue(b + 7, o.fb);
            ui.setParameterValue(b + 8, o.mdl);
            ui.setParameterValue(b + 9, o.ms + 1);
            ui.setParameterValue(b + 10, o.wv || 0);
            ui.setParameterValue(b + 11, o.lm !== undefined ? o.lm : 1);
            ui.setParameterValue(b + 12, o.ls || 0);
            ui.setParameterValue(b + 13, o.le || 1024);
            ui.setParameterValue(IDX_CARRIER_BASE + i, o.c);
        }
    }

    // Extract _applyPatch logic as standalone function (must match ui.js exactly)
    function runApplyPatch(ui, patch) {
        if (!patch || !patch.operators) return;
        const ops = patch.operators;
        const n = Math.min(ops.length, MAX_OPS);
        ui.customWaves = {};
        for (let i = 0; i < n; i++) {
            const o = ops[i];
            if (o.pcm && o.pcm.length > 0) {
                ui.customWaves[i] = o.pcm;
                const int16 = new Int16Array(o.pcm.length);
                for (let s = 0; s < o.pcm.length; s++) {
                    int16[s] = Math.max(-32768, Math.min(32767, Math.round(o.pcm[s] * 32767)));
                }
                const bytes = new Uint8Array(int16.buffer);
                let raw = '';
                for (let s = 0; s < bytes.length; s++) raw += String.fromCharCode(bytes[s]);
                // btoa not available in Node, use Buffer
                ui.setState('wave_' + i, Buffer.from(raw, 'binary').toString('base64'));
            }
        }
        ui.setParameterValue(IDX_NUM_OPS, n);
        for (let i = 0; i < MAX_OPS; i++) {
            const b = i * PARAMS_PER_OP;
            if (i < n) {
                const o = ops[i];
                ui.setParameterValue(b + 0,  o.freq_ratio || 1);
                ui.setParameterValue(b + 1,  o.level !== undefined ? o.level : 0.8);
                ui.setParameterValue(b + 2,  o.ar !== undefined ? o.ar : 31);
                ui.setParameterValue(b + 3,  o.d1r || 0);
                ui.setParameterValue(b + 4,  o.dl || 0);
                ui.setParameterValue(b + 5,  o.d2r || 0);
                ui.setParameterValue(b + 6,  o.rr !== undefined ? o.rr : 14);
                ui.setParameterValue(b + 7,  o.feedback || 0);
                ui.setParameterValue(b + 8,  o.mdl || 0);
                ui.setParameterValue(b + 9,  (o.mod_source !== undefined ? o.mod_source : -1) + 1);
                ui.setParameterValue(b + 10, 0);
                ui.setParameterValue(b + 11, o.loop_mode !== undefined ? o.loop_mode : 1);
                ui.setParameterValue(b + 12, o.loop_start || 0);
                ui.setParameterValue(b + 13, o.pcm ? o.pcm.length : (o.loop_end || 1024));
                ui.setParameterValue(IDX_CARRIER_BASE + i, o.is_carrier ? 1 : 0);
            } else {
                ui.setParameterValue(b + 0,  1);
                ui.setParameterValue(b + 1,  0.8);
                ui.setParameterValue(b + 2,  31);
                ui.setParameterValue(b + 3,  0);
                ui.setParameterValue(b + 4,  0);
                ui.setParameterValue(b + 5,  0);
                ui.setParameterValue(b + 6,  14);
                ui.setParameterValue(b + 7,  0);
                ui.setParameterValue(b + 8,  0);
                ui.setParameterValue(b + 9,  0);
                ui.setParameterValue(b + 10, 0);
                ui.setParameterValue(b + 11, 1);
                ui.setParameterValue(b + 12, 0);
                ui.setParameterValue(b + 13, 1024);
                ui.setParameterValue(IDX_CARRIER_BASE + i, 0);
            }
        }
    }

    // Build a preset equivalent to Electric Piano
    const preset = { n:2, ops:[
        {r:2.0,l:0.9,ar:31,d1r:12,dl:8,d2r:0,rr:14,fb:0,mdl:0,ms:-1,c:0},
        {r:1.0,l:0.8,ar:31,d1r:6,dl:2,d2r:0,rr:14,fb:0,mdl:9,ms:0,c:1}]};

    // Export the same as TON, then import
    const tonPatch = { name: 'EP', operators: [
        { freq_ratio:2.0, level:0.9, ar:31, d1r:12, dl:8, d2r:0, rr:14, feedback:0, mdl:0, mod_source:-1, is_carrier:false, waveform:0, loop_mode:1 },
        { freq_ratio:1.0, level:0.8, ar:31, d1r:6, dl:2, d2r:0, rr:14, feedback:0, mdl:9, mod_source:0, is_carrier:true, waveform:0, loop_mode:1 },
    ]};
    const ton = TonIO.exportTon([tonPatch], generateWaveform);
    const imported = TonIO.importTon(ton.buffer).patches[0];

    // Run both through mocks
    const presetUI = createMockUI();
    runApplyPreset(presetUI, preset);

    const patchUI = createMockUI();
    runApplyPatch(patchUI, imported);

    // Both should produce same number of setParameterValue calls
    assert(presetUI.paramLog.length === patchUI.paramLog.length,
        'Same number of setParameterValue calls: preset=' + presetUI.paramLog.length + ' patch=' + patchUI.paramLog.length);

    // Both should set the same param indices in the same order
    let indexMismatch = false;
    for (let i = 0; i < presetUI.paramLog.length; i++) {
        if (presetUI.paramLog[i].index !== patchUI.paramLog[i].index) {
            console.error('  FAIL: call ' + i + ' index mismatch: preset=' + presetUI.paramLog[i].index + ' patch=' + patchUI.paramLog[i].index);
            indexMismatch = true;
            failed++;
            break;
        }
    }
    if (!indexMismatch) passed++;

    // Compare envelope params (should be identical)
    for (let i = 0; i < presetUI.paramLog.length; i++) {
        const pp = presetUI.paramLog[i];
        const ap = patchUI.paramLog[i];
        const paramInOp = pp.index % PARAMS_PER_OP;
        // Envelope params (2-6) should match exactly
        if (pp.index < MAX_OPS * PARAMS_PER_OP && paramInOp >= 2 && paramInOp <= 6) {
            assert(pp.value === ap.value,
                'Param[' + pp.index + '] (op' + Math.floor(pp.index/PARAMS_PER_OP) + ' ' +
                ['ratio','level','AR','D1R','DL','D2R','RR'][paramInOp] +
                '): preset=' + pp.value + ' patch=' + ap.value);
        }
        // MDL and mod_source (8, 9) should match exactly
        if (pp.index < MAX_OPS * PARAMS_PER_OP && (paramInOp === 8 || paramInOp === 9)) {
            assert(pp.value === ap.value,
                'Param[' + pp.index + '] (op' + Math.floor(pp.index/PARAMS_PER_OP) +
                (paramInOp === 8 ? ' MDL' : ' modSrc') +
                '): preset=' + pp.value + ' patch=' + ap.value);
        }
        // Carrier flags should match
        if (pp.index >= IDX_CARRIER_BASE && pp.index < IDX_CARRIER_BASE + MAX_OPS) {
            assert(pp.value === ap.value,
                'Carrier[' + (pp.index - IDX_CARRIER_BASE) + ']: preset=' + pp.value + ' patch=' + ap.value);
        }
    }

    // _applyPatch should also produce setState calls for PCM uploads
    assert(patchUI.stateLog.length === 2, 'Should have 2 setState calls for waveform upload, got ' + patchUI.stateLog.length);
    assert(patchUI.stateLog[0].key === 'wave_0', 'First setState key=' + patchUI.stateLog[0].key);
    assert(patchUI.stateLog[1].key === 'wave_1', 'Second setState key=' + patchUI.stateLog[1].key);
    assert(patchUI.stateLog[0].valueLen > 0, 'wave_0 has data');
    assert(patchUI.stateLog[1].valueLen > 0, 'wave_1 has data');
}

/* ═══════════════════════════════════════════════════════════════ */
/* Summary                                                        */
/* ═══════════════════════════════════════════════════════════════ */
console.log('\n' + '='.repeat(50));
console.log('Passed: ' + passed + '  Failed: ' + failed);
if (failed > 0) {
    process.exit(1);
} else {
    console.log('All tests passed!');
}

/* ═══════════════════════════════════════════════════════════════ */
/* TEST 7: Imported PCM must be resampled to 1024 for tracker    */
/* ═══════════════════════════════════════════════════════════════ */
console.log('\n=== Test 7: PCM resampling for tracker ===');
{
    // Simulate what saturn_kit.py does: 100-sample waveforms
    const patch = { name: 'Short', operators: [
        { freq_ratio: 1.0, level: 0.8, ar: 31, d1r: 6, dl: 2, d2r: 0, rr: 14,
          mdl: 0, mod_source: -1, is_carrier: true, waveform: 0, loop_mode: 1 },
    ]};
    // Export with 1024-sample waveforms (tracker default)
    const ton = TonIO.exportTon([patch], generateWaveform);
    const imported = TonIO.importTon(ton.buffer);
    const op = imported.patches[0].operators[0];

    assert(op.pcm.length === 1024, 'Exported with 1024 samples, got ' + op.pcm.length);

    // Now test with a real TON file that has short waveforms
    const testDir = path.join(__dirname, '..', 'test_ton');
    const kitPath = path.join(testDir, 'KITFM.TON');
    if (fs.existsSync(kitPath)) {
        const buf = fs.readFileSync(kitPath);
        const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
        const result = TonIO.importTon(ab);

        // Check PCM lengths — real TON files have short waveforms (100 samples for A4)
        const shortOps = [];
        for (const p of result.patches) {
            for (const o of p.operators) {
                if (o.pcm && o.pcm.length !== 1024) shortOps.push(o.pcm.length);
            }
        }
        assert(shortOps.length > 0, 'KITFM.TON has short waveforms: ' + shortOps.slice(0,5).join(','));

        // Verify resampling produces correct length
        function resampleTo1024(pcm) {
            if (pcm.length === 1024) return pcm;
            const out = new Float32Array(1024);
            const ratio = pcm.length / 1024;
            for (let i = 0; i < 1024; i++) {
                const srcIdx = i * ratio;
                const idx = Math.floor(srcIdx);
                const frac = srcIdx - idx;
                const s0 = pcm[idx] || 0;
                const s1 = pcm[Math.min(idx + 1, pcm.length - 1)] || 0;
                out[i] = s0 + (s1 - s0) * frac;
            }
            return out;
        }

        // Test resampling preserves waveform character
        const testOp = result.patches[0].operators[0];
        const resampled = resampleTo1024(testOp.pcm);
        assert(resampled.length === 1024, 'Resampled to 1024');

        // Check resampled waveform isn't all zeros
        let maxVal = 0;
        for (let i = 0; i < 1024; i++) if (Math.abs(resampled[i]) > maxVal) maxVal = Math.abs(resampled[i]);
        assert(maxVal > 0.01, 'Resampled waveform has content (peak=' + maxVal.toFixed(3) + ')');

        // Verify pitch math: with 1024-sample waveform, base freq is 44100/1024
        // freq_ratio=1.0 should give opBaseNote = SINE_BASE_NOTE
        // Playing C4 (60) should give correct pitch
        const SINE_BASE_NOTE = 69 + 12 * Math.log2(44100 / 1024 / 440);
        const opBaseNote = SINE_BASE_NOTE - 12 * Math.log2(testOp.freq_ratio);
        const semi = 60 - opBaseNote; // playing C4
        const octave = Math.floor(semi / 12);
        const frac = semi - octave * 12;
        const expectedFreq = (44100 / 1024) * Math.pow(2, semi / 12);
        assertClose(expectedFreq, 261.6, 2.0, 'C4 pitch with 1024-sample waveform: ' + expectedFreq.toFixed(1) + ' Hz');
    }
}
