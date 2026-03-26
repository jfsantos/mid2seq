#!/usr/bin/env node
/**
 * test_tracker_roundtrip.js — End-to-end test simulating the tracker workflow:
 *
 * 1. Load a TON file (instruments)
 * 2. Load a MIDI file (notes)
 * 3. Add a new instrument to the kit
 * 4. Add notes using the new instrument to a pattern
 * 5. Export TON (should contain original + new instrument)
 * 6. Export SEQ (should contain original MIDI notes + new notes)
 * 7. Verify the exported TON can be re-imported
 * 8. Verify the exported SEQ matches mid2seq.c format
 */

const TonIO = require('./ton_io.js');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('  FAIL: ' + msg); failed++; } else { passed++; }
}
function assertClose(a, b, tol, msg) {
    if (Math.abs(a - b) > tol) { console.error('  FAIL: ' + msg + ' (got ' + a + ' expected ' + b + ')'); failed++; } else { passed++; }
}

// ── Reuse MIDI parser and SEQ builder from test_seq_export.js ──

function parseMIDI(buf) {
    const d = new DataView(buf);
    const u8 = new Uint8Array(buf);
    let pos = 0;
    function read32() { const v = d.getUint32(pos); pos += 4; return v; }
    function read16() { const v = d.getUint16(pos); pos += 2; return v; }
    function read8() { return u8[pos++]; }
    function readVarLen() {
        let v = 0;
        for (let i = 0; i < 4; i++) { const b = read8(); v = (v << 7) | (b & 0x7F); if (!(b & 0x80)) break; }
        return v;
    }
    function readStr(n) { let s = ''; for (let i = 0; i < n; i++) s += String.fromCharCode(read8()); return s; }
    const hdId = readStr(4); if (hdId !== 'MThd') throw new Error('Not MIDI');
    read32(); const format = read16(); const nTracks = read16(); const division = read16();
    const allEvents = [];
    for (let t = 0; t < nTracks; t++) {
        const trkId = readStr(4); const trkLen = read32();
        if (trkId !== 'MTrk') { pos += trkLen; continue; }
        const trkEnd = pos + trkLen; let absTime = 0, runningStatus = 0;
        while (pos < trkEnd) {
            const delta = readVarLen(); absTime += delta;
            let status = u8[pos];
            if (status & 0x80) { pos++; if (status < 0xF0) runningStatus = status; } else { status = runningStatus; }
            const type = status & 0xF0; const ch = status & 0x0F;
            if (type === 0x90) { const note = read8(); const vel = read8(); allEvents.push({ absTime, ch, type: vel > 0 ? 'on' : 'off', note, vel, status }); }
            else if (type === 0x80) { const note = read8(); read8(); allEvents.push({ absTime, ch, type: 'off', note, vel: 0, status }); }
            else if (type === 0xC0) { const prog = read8(); allEvents.push({ absTime, ch, type: 'pc', prog, status }); }
            else if (type === 0xB0) { read8(); read8(); }
            else if (type === 0xE0) { read8(); read8(); }
            else if (type === 0xD0) { read8(); }
            else if (type === 0xA0) { read8(); read8(); }
            else if (status === 0xFF) { const mt = read8(); const ml = readVarLen(); if (mt === 0x51 && ml === 3) { const uspb = (read8()<<16)|(read8()<<8)|read8(); allEvents.push({ absTime, type: 'tempo', mspb: uspb }); } else { pos += ml; } }
            else if (status === 0xF0 || status === 0xF7) { const sl = readVarLen(); pos += sl; }
        }
        pos = trkEnd;
    }
    return { format, division, events: allEvents };
}

// ── Waveform generator ──
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
    default: return genAdditive(n, [[1, 1.0]]);
    }
}

// ── Simulate tracker state + buildSEQ ──
const NUM_CHANNELS = 8;

function createEmptyPattern(len, numInstruments) {
    const channels = [];
    for (let c = 0; c < NUM_CHANNELS; c++) {
        const rows = [];
        for (let r = 0; r < len; r++) rows.push({ note: null, inst: null, vol: null });
        channels.push({ defaultInst: Math.min(c, numInstruments - 1), rows });
    }
    return { length: len, channels };
}

function midiToState(midi, instruments, patternLength, stepsPerBeat) {
    const division = midi.division;
    const ticksPerStep = division / stepsPerBeat;
    const tempoEv = midi.events.find(e => e.type === 'tempo');
    const bpm = tempoEv ? Math.round(60000000 / tempoEv.mspb) : 120;

    const noteOns = midi.events.filter(e => e.type === 'on').sort((a, b) => a.absTime - b.absTime);
    const lastTime = noteOns.length > 0 ? Math.max(...noteOns.map(e => e.absTime)) : 0;
    const totalSteps = Math.ceil(lastTime / ticksPerStep) + 1;
    const numPatterns = Math.max(1, Math.ceil(totalSteps / patternLength));

    const usedChannels = [...new Set(noteOns.map(e => e.ch))].sort((a, b) => a - b);
    const chMap = {};
    usedChannels.forEach((midiCh, i) => { if (i < NUM_CHANNELS) chMap[midiCh] = i; });

    const patterns = [];
    const song = [];
    for (let p = 0; p < numPatterns; p++) {
        patterns.push(createEmptyPattern(patternLength, instruments.length));
        song.push(p);
    }

    for (const ev of noteOns) {
        const trackerCh = chMap[ev.ch];
        if (trackerCh === undefined) continue;
        const globalStep = Math.round(ev.absTime / ticksPerStep);
        const patIdx = Math.floor(globalStep / patternLength);
        const row = globalStep % patternLength;
        if (patIdx >= patterns.length) continue;
        const cell = patterns[patIdx].channels[trackerCh].rows[row];
        cell.note = ev.note;
        cell.vol = ev.vel;
    }

    return { bpm, stepsPerBeat, patternLength, instruments, patterns, song };
}

function buildSEQ(state) {
    const resolution = 480;
    const ticksPerStep = resolution / state.stepsPerBeat;
    const mspb = Math.round(60000000 / state.bpm);
    const events = [];

    const channelInst = {};
    for (const patIdx of state.song) {
        const pat = state.patterns[patIdx];
        for (let ch = 0; ch < NUM_CHANNELS; ch++) {
            if (!(ch in channelInst)) channelInst[ch] = pat.channels[ch].defaultInst;
        }
    }
    for (const [ch, inst] of Object.entries(channelInst)) {
        events.push({ absTick: 0, status: 0xC0 | parseInt(ch), data1: inst, data2: 0, gateTicks: 0 });
    }

    let stepOffset = 0;
    for (const patIdx of state.song) {
        const pat = state.patterns[patIdx];
        for (let row = 0; row < pat.length; row++) {
            for (let ch = 0; ch < NUM_CHANNELS; ch++) {
                const cell = pat.channels[ch].rows[row];
                if (cell.note !== null && cell.note >= 0) {
                    const absTick = Math.round((stepOffset + row) * ticksPerStep);
                    let gateSteps = pat.length - row;
                    for (let r = row + 1; r < pat.length; r++) {
                        if (pat.channels[ch].rows[r].note !== null) { gateSteps = r - row; break; }
                    }
                    events.push({
                        absTick, status: 0x90 | ch, data1: cell.note,
                        data2: cell.vol !== null ? cell.vol : 100,
                        gateTicks: Math.round(gateSteps * ticksPerStep),
                    });
                }
            }
        }
        stepOffset += pat.length;
    }

    events.sort((a, b) => {
        if (a.absTick !== b.absTick) return a.absTick - b.absTick;
        const aNote = (a.status & 0xF0) === 0x90, bNote = (b.status & 0xF0) === 0x90;
        if (!aNote && bNote) return -1;
        if (aNote && !bNote) return 1;
        return 0;
    });

    let firstMusicalTick = 0;
    for (const ev of events) { if ((ev.status & 0xF0) === 0x90) { firstMusicalTick = ev.absTick; break; } }
    const totalTicks = Math.round(stepOffset * ticksPerStep);

    const buf = [];
    function w8(v) { buf.push(v & 0xFF); }
    function w16(v) { buf.push((v >> 8) & 0xFF, v & 0xFF); }
    function w32(v) { buf.push((v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF); }

    w16(1); w32(6);
    w16(resolution); w16(2); w16(8 + 16); w16(8 + 8);
    w32(firstMusicalTick); w32(mspb);
    w32(totalTicks - firstMusicalTick); w32(mspb);
    for (let ch = 0; ch < 16; ch++) { w8(0xB0 | ch); w8(0x20); w8(1); w8(0x00); }

    let lastTick = 0;
    for (const ev of events) {
        let delta = ev.absTick - lastTick;
        lastTick = ev.absTick;
        const evType = ev.status & 0xF0;
        while (delta >= 0x1000) { w8(0x8F); delta -= 0x1000; }
        while (delta >= 0x800) { w8(0x8E); delta -= 0x800; }
        while (delta >= 0x200) { w8(0x8D); delta -= 0x200; }
        if (evType === 0x90) {
            let gate = ev.gateTicks;
            while (gate >= 0x2000) { w8(0x8B); gate -= 0x2000; }
            while (gate >= 0x1000) { w8(0x8A); gate -= 0x1000; }
            while (gate >= 0x800) { w8(0x89); gate -= 0x800; }
            while (gate >= 0x200) { w8(0x88); gate -= 0x200; }
            let ctl = ev.status & 0x0F;
            if (delta >= 256) { ctl |= 0x20; delta -= 256; }
            if (gate >= 256) { ctl |= 0x40; gate -= 256; }
            w8(ctl); w8(ev.data1); w8(ev.data2); w8(gate & 0xFF); w8(delta & 0xFF);
        } else {
            while (delta >= 256) { w8(0x8C); delta -= 256; }
            w8(ev.status);
            if (evType === 0xB0 || evType === 0xA0) { w8(ev.data1); w8(ev.data2); }
            else if (evType === 0xE0) { w8(ev.data2); }
            else { w8(ev.data1); }
            w8(delta & 0xFF);
        }
    }
    w8(0x83);
    return new Uint8Array(buf);
}

// ═══════════════════════════════════════════════════════════════
// TEST: Full round-trip
// ═══════════════════════════════════════════════════════════════

console.log('\n=== Tracker Round-Trip Test ===\n');

const tonPath = path.join(__dirname, '..', 'test_ton', 'KITFM.TON');
const midPath = path.join(__dirname, '..', 'tests', 'midi_test_files', 'test_multi_channel.mid');

if (!fs.existsSync(tonPath)) { console.log('SKIP: ' + tonPath + ' not found'); process.exit(0); }
if (!fs.existsSync(midPath)) { console.log('SKIP: ' + midPath + ' not found'); process.exit(0); }

// ── Step 1: Load TON ──
console.log('--- Step 1: Load TON ---');
const tonBuf = fs.readFileSync(tonPath);
const tonAB = tonBuf.buffer.slice(tonBuf.byteOffset, tonBuf.byteOffset + tonBuf.byteLength);
const tonResult = TonIO.importTon(tonAB);
const originalInstCount = tonResult.patches.length;
console.log('  Loaded ' + originalInstCount + ' instruments from ' + path.basename(tonPath));
assert(originalInstCount === 16, 'KITFM.TON has 16 instruments');

// Convert to tracker instrument format
const instruments = tonResult.patches.map((p, i) => ({
    name: p.name || ('Voice ' + i),
    operators: p.operators.map(o => ({
        freq_ratio: o.freq_ratio || 1, freq_fixed: 0,
        level: o.level !== undefined ? o.level : 0.8,
        ar: o.ar !== undefined ? o.ar : 31, d1r: o.d1r || 0, dl: o.dl || 0,
        d2r: o.d2r || 0, rr: o.rr !== undefined ? o.rr : 14,
        mdl: o.mdl || 0, mod_source: o.mod_source !== undefined ? o.mod_source : -1,
        feedback: o.feedback || 0, is_carrier: o.is_carrier !== undefined ? o.is_carrier : true,
        waveform: 0, loop_mode: o.loop_mode !== undefined ? o.loop_mode : 1,
        loop_start: o.loop_start || 0, loop_end: o.loop_end || 1024,
    }))
}));

// ── Step 2: Load MIDI ──
console.log('\n--- Step 2: Load MIDI ---');
const midBuf = fs.readFileSync(midPath);
const midAB = midBuf.buffer.slice(midBuf.byteOffset, midBuf.byteOffset + midBuf.byteLength);
const midi = parseMIDI(midAB);
const noteCount = midi.events.filter(e => e.type === 'on').length;
console.log('  Loaded ' + noteCount + ' notes from ' + path.basename(midPath));
assert(noteCount > 0, 'MIDI has notes');

const state = midiToState(midi, instruments, 32, 4);
console.log('  Created ' + state.patterns.length + ' patterns, BPM=' + state.bpm);
assert(state.patterns.length >= 1, 'At least 1 pattern');

// Count notes in tracker grid
let gridNotes = 0;
for (const pat of state.patterns) {
    for (let ch = 0; ch < NUM_CHANNELS; ch++) {
        for (const row of pat.channels[ch].rows) {
            if (row.note !== null && row.note >= 0) gridNotes++;
        }
    }
}
console.log('  ' + gridNotes + ' notes placed in grid');
assert(gridNotes === noteCount, 'All MIDI notes placed in grid (got ' + gridNotes + ' expected ' + noteCount + ')');

// ── Step 3: Add a new instrument ──
console.log('\n--- Step 3: Add new instrument ---');
const newInst = {
    name: 'Test Synth',
    operators: [
        { freq_ratio: 2.0, freq_fixed: 0, level: 0.9, ar: 31, d1r: 12, dl: 8, d2r: 0, rr: 14,
          mdl: 0, mod_source: -1, feedback: 0, is_carrier: false, waveform: 0, loop_mode: 1, loop_start: 0, loop_end: 1024 },
        { freq_ratio: 1.0, freq_fixed: 0, level: 0.8, ar: 31, d1r: 6, dl: 2, d2r: 0, rr: 14,
          mdl: 9, mod_source: 0, feedback: 0, is_carrier: true, waveform: 0, loop_mode: 1, loop_start: 0, loop_end: 1024 },
    ]
};
state.instruments.push(newInst);
const newInstIdx = state.instruments.length - 1;
console.log('  Added "Test Synth" as instrument ' + newInstIdx);
assert(state.instruments.length === originalInstCount + 1, 'Instrument count increased');

// ── Step 4: Add notes using new instrument ──
console.log('\n--- Step 4: Add notes with new instrument ---');
const pat0 = state.patterns[0];
// Add a melody on channel 7 using the new instrument
pat0.channels[7].defaultInst = newInstIdx;
const melody = [60, 62, 64, 65, 67, 69, 71, 72]; // C major scale
for (let i = 0; i < melody.length; i++) {
    pat0.channels[7].rows[i * 4] = { note: melody[i], inst: newInstIdx, vol: 100 };
}
console.log('  Added ' + melody.length + ' notes on channel 7');

// Count total notes now
let totalNotes = 0;
for (const pat of state.patterns) {
    for (let ch = 0; ch < NUM_CHANNELS; ch++) {
        for (const row of pat.channels[ch].rows) {
            if (row.note !== null && row.note >= 0) totalNotes++;
        }
    }
}
assert(totalNotes === gridNotes + melody.length, 'Total notes: ' + totalNotes + ' (original ' + gridNotes + ' + ' + melody.length + ' new)');

// ── Step 5: Export TON ──
console.log('\n--- Step 5: Export TON ---');
const exportedTon = TonIO.exportTon(state.instruments, generateWaveform);
assert(exportedTon.length > 0, 'TON export produced data (' + exportedTon.length + ' bytes)');

// Verify it can be re-imported
const reimported = TonIO.importTon(exportedTon.buffer);
assert(reimported.patches.length === originalInstCount + 1,
    'Re-imported TON has ' + reimported.patches.length + ' instruments (expected ' + (originalInstCount + 1) + ')');

// Verify the new instrument survived the round-trip
const reimportedNew = reimported.patches[newInstIdx];
assert(reimportedNew.operators.length === 2, 'New instrument has 2 operators');
assertClose(reimportedNew.operators[0].freq_ratio, 2.0, 0.01, 'New inst Op0 ratio');
assertClose(reimportedNew.operators[1].freq_ratio, 1.0, 0.01, 'New inst Op1 ratio');
assert(reimportedNew.operators[0].ar === 31, 'New inst Op0 AR=' + reimportedNew.operators[0].ar);
assert(reimportedNew.operators[0].d1r === 12, 'New inst Op0 D1R=' + reimportedNew.operators[0].d1r);
assert(reimportedNew.operators[0].is_carrier === false, 'New inst Op0 is modulator');
assert(reimportedNew.operators[1].is_carrier === true, 'New inst Op1 is carrier');
assert(reimportedNew.operators[1].mdl === 9, 'New inst Op1 MDL=' + reimportedNew.operators[1].mdl);
assert(reimportedNew.operators[1].mod_source === 0, 'New inst Op1 mod_source=' + reimportedNew.operators[1].mod_source);

// Verify original instruments survived
for (let i = 0; i < Math.min(6, originalInstCount); i++) {
    const orig = tonResult.patches[i];
    const reimp = reimported.patches[i];
    assert(reimp.operators.length === orig.operators.length,
        'Inst ' + i + ' op count preserved: ' + reimp.operators.length);
    for (let j = 0; j < orig.operators.length; j++) {
        assert(reimp.operators[j].ar === orig.operators[j].ar,
            'Inst ' + i + ' Op' + j + ' AR preserved: ' + reimp.operators[j].ar);
        assert(reimp.operators[j].is_carrier === orig.operators[j].is_carrier,
            'Inst ' + i + ' Op' + j + ' carrier preserved');
    }
}

// Write to file for manual inspection
fs.writeFileSync('/tmp/test_roundtrip.ton', exportedTon);
console.log('  Written to /tmp/test_roundtrip.ton');

// ── Step 6: Export SEQ ──
console.log('\n--- Step 6: Export SEQ ---');
const exportedSeq = buildSEQ(state);
assert(exportedSeq.length > 0, 'SEQ export produced data (' + exportedSeq.length + ' bytes)');

// Verify SEQ structure
assert(exportedSeq[0] === 0x00 && exportedSeq[1] === 0x01, 'SEQ bank header: num_songs=1');
assert(exportedSeq[exportedSeq.length - 1] === 0x83, 'SEQ ends with 0x83 (end of track)');

// Check resolution
const seqRes = (exportedSeq[6] << 8) | exportedSeq[7];
assert(seqRes === 480, 'SEQ resolution=480 (got ' + seqRes + ')');

// Check tempo count
const seqTempoCount = (exportedSeq[8] << 8) | exportedSeq[9];
assert(seqTempoCount === 2, 'SEQ has 2 tempo events (got ' + seqTempoCount + ')');

// Check bank select is present (16 channels × 4 bytes = 64 bytes)
const bankStart = 6 + 8 + 16; // after bank hdr + seq hdr + 2 tempo events
let bankSelectOk = true;
for (let ch = 0; ch < 16; ch++) {
    const off = bankStart + ch * 4;
    if (exportedSeq[off] !== (0xB0 | ch) || exportedSeq[off + 1] !== 0x20 || exportedSeq[off + 2] !== 1) {
        bankSelectOk = false;
        break;
    }
}
assert(bankSelectOk, 'Bank select CC#32=1 on all 16 channels');

// Count note-on events in the SEQ by scanning for patterns
// (note-ons are 5-byte sequences after optional extend bytes)
// Simple check: SEQ should be significantly larger than just headers
const headerAndBankSize = bankStart + 64; // headers + bank select
assert(exportedSeq.length > headerAndBankSize + 20, 'SEQ has event data after headers');

// Write to file for manual inspection
fs.writeFileSync('/tmp/test_roundtrip.seq', exportedSeq);
console.log('  Written to /tmp/test_roundtrip.seq');

// ── Step 7: Verify exported files work together ──
console.log('\n--- Step 7: Cross-verification ---');

// Re-import the TON and verify we can build a new state from it
const reloadBuf = fs.readFileSync('/tmp/test_roundtrip.ton');
const reloadAB = reloadBuf.buffer.slice(reloadBuf.byteOffset, reloadBuf.byteOffset + reloadBuf.byteLength);
const reloadedTon = TonIO.importTon(reloadAB);
assert(reloadedTon.patches.length === state.instruments.length,
    'Reloaded TON matches instrument count');

// Verify the SEQ file is parseable (check it doesn't have obvious corruption)
const seqBytes = fs.readFileSync('/tmp/test_roundtrip.seq');
const seqSongPtr = (seqBytes[2] << 24) | (seqBytes[3] << 16) | (seqBytes[4] << 8) | seqBytes[5];
assert(seqSongPtr === 6, 'SEQ song pointer = 6');

// Check program changes reference valid instruments
const eventStart = bankStart + 64;
let pcCount = 0;
for (let i = eventStart; i < seqBytes.length - 1; i++) {
    if ((seqBytes[i] & 0xF0) === 0xC0) {
        const prog = seqBytes[i + 1];
        assert(prog < state.instruments.length,
            'Program change prog=' + prog + ' < ' + state.instruments.length + ' instruments');
        pcCount++;
    }
}
console.log('  Found ' + pcCount + ' program changes in SEQ, all referencing valid instruments');

// ═══════════════════════════════════════════════════════════════
// Summary
// ═══════════════════════════════════════════════════════════════
console.log('\n' + '='.repeat(50));
console.log('Passed: ' + passed + '  Failed: ' + failed);
if (failed > 0) {
    console.log('SOME TESTS FAILED');
    process.exit(1);
} else {
    console.log('All tests passed!');
}
