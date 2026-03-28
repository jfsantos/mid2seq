#!/usr/bin/env node
/**
 * test_seq_export.js — Test that the JS SEQ encoder produces output
 * compatible with mid2seq.c for the same MIDI input.
 *
 * Tests:
 * 1. SEQ header structure (bank header, resolution, tempo events)
 * 2. Bank select CC#32 on all 16 channels
 * 3. Note-on encoding (control byte, gate/delta extend)
 * 4. Byte comparison against mid2seq.c reference output
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { parseMIDI } = require('./midi_io.js');

let passed = 0, failed = 0;
function assert(cond, msg) { if (!cond) { console.error('  FAIL: ' + msg); failed++; } else { passed++; } }

// ── Inline the SEQ builder from the tracker ──
function buildSEQFromMidi(midi) {
    const resolution = midi.division;
    const tempoEv = midi.events.find(e => e.type === 'tempo');
    const mspb = tempoEv ? tempoEv.mspb : 500000;

    // Build event list matching mid2seq.c's processing:
    // 1. Collect note-on/off events, compute gate times
    // 2. Remove note-off events (merged into note-on gate time)
    // 3. Keep program changes and CCs
    const noteOns = midi.events.filter(e => e.type === 'on');
    const noteOffs = midi.events.filter(e => e.type === 'off');
    const pcs = midi.events.filter(e => e.type === 'pc');

    // Compute gate times for each note-on
    const events = [];
    for (const ev of noteOns) {
        // Find corresponding note-off
        const off = noteOffs.find(o => o.ch === ev.ch && o.note === ev.note && o.absTime >= ev.absTime);
        const gate = off ? off.absTime - ev.absTime : resolution * 4; // default 1 bar
        events.push({
            absTick: ev.absTime,
            status: 0x90 | ev.ch,
            data1: ev.note,
            data2: ev.vel,
            gateTicks: gate,
        });
    }

    // Add program changes
    for (const ev of pcs) {
        events.push({ absTick: ev.absTime, status: 0xC0 | ev.ch, data1: ev.prog, data2: 0, gateTicks: 0 });
    }

    // Sort by time, non-note-on events first at same time
    events.sort((a, b) => {
        if (a.absTick !== b.absTick) return a.absTick - b.absTick;
        const aIsNote = (a.status & 0xF0) === 0x90;
        const bIsNote = (b.status & 0xF0) === 0x90;
        if (!aIsNote && bIsNote) return -1;
        if (aIsNote && !bIsNote) return 1;
        return 0;
    });

    // Find first musical event
    let firstMusicalTick = 0;
    for (const ev of events) {
        if ((ev.status & 0xF0) !== 0xFF) { firstMusicalTick = ev.absTick; break; }
    }
    const totalTicks = events.length > 0 ? events[events.length - 1].absTick + (events[events.length-1].gateTicks || 0) : 0;

    // Build binary (same logic as tracker's buildSEQ)
    const buf = [];
    function w8(v) { buf.push(v & 0xFF); }
    function w16(v) { buf.push((v >> 8) & 0xFF, v & 0xFF); }
    function w32(v) { buf.push((v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF); }

    // Bank header
    w16(1); w32(6);
    // SEQ header
    const tempoCount = 2;
    w16(resolution); w16(tempoCount); w16(8 + tempoCount * 8); w16(8 + 8);
    // Tempo events
    w32(firstMusicalTick); w32(mspb);
    w32(totalTicks - firstMusicalTick); w32(mspb);
    // Bank select
    for (let ch = 0; ch < 16; ch++) { w8(0xB0 | ch); w8(0x20); w8(1); w8(0x00); }

    // Event stream
    let lastTick = 0;
    for (const ev of events) {
        let delta = ev.absTick - lastTick;
        lastTick = ev.absTick;
        const evType = ev.status & 0xF0;

        while (delta >= 0x1000) { w8(0x8F); delta -= 0x1000; }
        while (delta >= 0x800)  { w8(0x8E); delta -= 0x800; }
        while (delta >= 0x200)  { w8(0x8D); delta -= 0x200; }

        if (evType === 0x90) {
            let gate = ev.gateTicks;
            while (gate >= 0x2000) { w8(0x8B); gate -= 0x2000; }
            while (gate >= 0x1000) { w8(0x8A); gate -= 0x1000; }
            while (gate >= 0x800)  { w8(0x89); gate -= 0x800; }
            while (gate >= 0x200)  { w8(0x88); gate -= 0x200; }
            let ctl = ev.status & 0x0F;
            if (delta >= 256) { ctl |= 0x20; delta -= 256; }
            if (gate >= 256)  { ctl |= 0x40; gate -= 256; }
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
// TESTS
// ═══════════════════════════════════════════════════════════════

const midDir = 'tests/midi_test_files';
const mid2seqBin = 'tools/mid2seq';

// Build mid2seq if needed
if (!fs.existsSync(mid2seqBin)) {
    console.log('Building mid2seq...');
    execSync('cc -o ' + mid2seqBin + ' tools/mid2seq.c');
}

const testFiles = ['test_short_long', 'test_large_delta', 'test_large_gate', 'test_mid_range_time'];

for (const name of testFiles) {
    const midPath = path.join(midDir, name + '.mid');
    if (!fs.existsSync(midPath)) { console.log('Skip: ' + midPath + ' not found'); continue; }

    console.log('\n=== ' + name + ' ===');

    // Generate reference with C tool
    const refPath = '/tmp/ref_' + name + '.seq';
    execSync(mid2seqBin + ' ' + midPath + ' ' + refPath);
    const refSeq = fs.readFileSync(refPath);

    // Generate with JS
    const midBuf = fs.readFileSync(midPath);
    const midAB = midBuf.buffer.slice(midBuf.byteOffset, midBuf.byteOffset + midBuf.byteLength);
    const midi = parseMIDI(midAB);
    const jsSeq = buildSEQFromMidi(midi);

    // Compare header (first 6 bytes: bank header)
    assert(jsSeq[0] === refSeq[0] && jsSeq[1] === refSeq[1], 'Bank header num_songs');
    assert(jsSeq[2] === refSeq[2] && jsSeq[3] === refSeq[3] && jsSeq[4] === refSeq[4] && jsSeq[5] === refSeq[5], 'Bank header song_ptr');

    // Compare SEQ header (bytes 6-13)
    const jsRes = (jsSeq[6] << 8) | jsSeq[7];
    const refRes = (refSeq[6] << 8) | refSeq[7];
    assert(jsRes === refRes, 'Resolution: js=' + jsRes + ' ref=' + refRes);

    const jsTempo = (jsSeq[8] << 8) | jsSeq[9];
    const refTempo = (refSeq[8] << 8) | refSeq[9];
    assert(jsTempo === refTempo, 'Tempo count: js=' + jsTempo + ' ref=' + refTempo);

    // Compare bank select section (should be identical)
    const bankSelectStart = 6 + 8 + 16; // after bank hdr + seq hdr + 2 tempo events
    let bankMatch = true;
    for (let i = bankSelectStart; i < bankSelectStart + 64; i++) {
        if (i >= jsSeq.length || i >= refSeq.length) { bankMatch = false; break; }
        if (jsSeq[i] !== refSeq[i]) { bankMatch = false; break; }
    }
    assert(bankMatch, 'Bank select CC#32 on all channels');

    // Compare full output
    const minLen = Math.min(jsSeq.length, refSeq.length);
    let firstDiff = -1;
    for (let i = 0; i < minLen; i++) {
        if (jsSeq[i] !== refSeq[i]) { firstDiff = i; break; }
    }
    if (firstDiff >= 0) {
        console.log('  First diff at byte ' + firstDiff + ': js=0x' + jsSeq[firstDiff].toString(16) + ' ref=0x' + refSeq[firstDiff].toString(16));
        console.log('  JS  length: ' + jsSeq.length);
        console.log('  Ref length: ' + refSeq.length);
        // Show context
        const ctx = 8;
        const start = Math.max(0, firstDiff - ctx);
        const end = Math.min(minLen, firstDiff + ctx);
        let jsHex = '', refHex = '';
        for (let i = start; i < end; i++) {
            jsHex += (i === firstDiff ? '[' : '') + jsSeq[i].toString(16).padStart(2, '0') + (i === firstDiff ? ']' : ' ');
            refHex += (i === firstDiff ? '[' : '') + refSeq[i].toString(16).padStart(2, '0') + (i === firstDiff ? ']' : ' ');
        }
        console.log('  JS:  ' + jsHex);
        console.log('  Ref: ' + refHex);
    }
    assert(firstDiff === -1 && jsSeq.length === refSeq.length,
        'Byte-identical: ' + (firstDiff === -1 && jsSeq.length === refSeq.length ? 'YES' : 'NO') +
        ' (js=' + jsSeq.length + ' ref=' + refSeq.length + ' bytes)');
}

console.log('\n' + '='.repeat(50));
console.log('Passed: ' + passed + '  Failed: ' + failed);
process.exit(failed > 0 ? 1 : 0);
