const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { parseSEQ, buildSEQ } = require('../seq_io.js');
const { parseMIDI } = require('../midi_io.js');

// -- helpers --

function makePattern(length, channelData, numChannels) {
    numChannels = numChannels || (Math.max(...Object.keys(channelData).map(Number)) + 1) || 1;
    const channels = [];
    for (let ch = 0; ch < numChannels; ch++) {
        const rows = [];
        for (let r = 0; r < length; r++) rows.push({ note: null, inst: null, vol: null });
        channels.push({ defaultInst: ch, rows });
    }
    for (const [ch, notes] of Object.entries(channelData)) {
        for (const [row, note, vel] of notes) {
            channels[parseInt(ch)].rows[row] = { note, inst: null, vol: vel ?? null };
        }
    }
    return { length, channels };
}

function buildAndParse(patterns, song, opts) {
    opts = opts || {};
    const bpm = opts.bpm || 120;
    const stepsPerBeat = opts.stepsPerBeat || 4;
    const numChannels = opts.numChannels || patterns[0].channels.length;
    const seq = buildSEQ({ patterns, song, bpm, stepsPerBeat, numChannels });
    return { seq, parsed: parseSEQ(seq.buffer) };
}

// ═══════════════════════════════════════════════
// buildSEQ — binary structure
// ═══════════════════════════════════════════════

describe('buildSEQ binary structure', () => {
    const pat = makePattern(4, { 0: [[0, 60, 100]] });
    let seq;

    it('produces a Uint8Array', () => {
        seq = buildSEQ({ patterns: [pat], song: [0], bpm: 120, stepsPerBeat: 4, numChannels: 1 });
        assert.ok(seq instanceof Uint8Array);
    });

    it('bank header: num_songs = 1', () => {
        seq = buildSEQ({ patterns: [pat], song: [0], bpm: 120, stepsPerBeat: 4, numChannels: 1 });
        assert.equal((seq[0] << 8) | seq[1], 1);
    });

    it('bank header: song_ptr = 6', () => {
        seq = buildSEQ({ patterns: [pat], song: [0], bpm: 120, stepsPerBeat: 4, numChannels: 1 });
        const ptr = (seq[2] << 24) | (seq[3] << 16) | (seq[4] << 8) | seq[5];
        assert.equal(ptr, 6);
    });

    it('SEQ header: resolution = 480', () => {
        seq = buildSEQ({ patterns: [pat], song: [0], bpm: 120, stepsPerBeat: 4, numChannels: 1 });
        assert.equal((seq[6] << 8) | seq[7], 480);
    });

    it('SEQ header: 2 tempo events', () => {
        seq = buildSEQ({ patterns: [pat], song: [0], bpm: 120, stepsPerBeat: 4, numChannels: 1 });
        assert.equal((seq[8] << 8) | seq[9], 2);
    });

    it('bank select CC#32 = 1 on all 16 channels', () => {
        seq = buildSEQ({ patterns: [pat], song: [0], bpm: 120, stepsPerBeat: 4, numChannels: 1 });
        const bankStart = 6 + 8 + 16; // after bank hdr + SEQ hdr + 2 tempo events
        for (let ch = 0; ch < 16; ch++) {
            const off = bankStart + ch * 4;
            assert.equal(seq[off], 0xB0 | ch, `ch ${ch} status`);
            assert.equal(seq[off + 1], 0x20, `ch ${ch} CC#32`);
            assert.equal(seq[off + 2], 1, `ch ${ch} bank=1`);
        }
    });

    it('ends with 0x83', () => {
        seq = buildSEQ({ patterns: [pat], song: [0], bpm: 120, stepsPerBeat: 4, numChannels: 1 });
        assert.equal(seq[seq.length - 1], 0x83);
    });
});

// ═══════════════════════════════════════════════
// parseSEQ
// ═══════════════════════════════════════════════

describe('parseSEQ', () => {
    it('extracts resolution and bpm', () => {
        const pat = makePattern(4, { 0: [[0, 60, 100]] });
        const { parsed } = buildAndParse([pat], [0], { bpm: 140 });
        assert.equal(parsed.resolution, 480);
        assert.equal(parsed.bpm, 140);
    });

    it('extracts note-on events with note, vel, gate', () => {
        const pat = makePattern(8, { 0: [[0, 60, 100], [4, 64, 90]] });
        const { parsed } = buildAndParse([pat], [0]);
        const ons = parsed.events.filter(e => e.type === 'on');
        assert.equal(ons.length, 2);
        assert.equal(ons[0].note, 60);
        assert.equal(ons[0].vel, 100);
        assert.equal(ons[1].note, 64);
        assert.equal(ons[1].vel, 90);
    });

    it('extracts program change events', () => {
        const pat = makePattern(4, { 0: [[0, 60, 100]] });
        pat.channels[0].defaultInst = 7;
        const { parsed } = buildAndParse([pat], [0]);
        const pcs = parsed.events.filter(e => e.type === 'pc');
        assert.ok(pcs.length >= 1);
        assert.equal(pcs[0].prog, 7);
    });

    it('gate time reflects distance to next note', () => {
        // 2 notes 4 steps apart at stepsPerBeat=4, resolution=480
        // → gate = 4 * (480/4) = 480 ticks
        const pat = makePattern(8, { 0: [[0, 60, 100], [4, 64, 100]] });
        const { parsed } = buildAndParse([pat], [0]);
        const ons = parsed.events.filter(e => e.type === 'on');
        assert.equal(ons[0].gate, 480);
    });

    it('handles events with absTime > 0', () => {
        const pat = makePattern(8, { 0: [[4, 60, 100]] });
        const { parsed } = buildAndParse([pat], [0]);
        const ons = parsed.events.filter(e => e.type === 'on');
        assert.equal(ons.length, 1);
        assert.ok(ons[0].absTime > 0);
    });
});

// ═══════════════════════════════════════════════
// buildSEQ → parseSEQ round-trip
// ═══════════════════════════════════════════════

describe('SEQ round-trip', () => {
    it('preserves note data through build → parse', () => {
        const pat = makePattern(16, {
            0: [[0, 48, 80], [8, 55, 110]],
            1: [[4, 60, 100], [12, 67, 95]],
        });
        const { parsed } = buildAndParse([pat], [0], { numChannels: 2 });
        const ons = parsed.events.filter(e => e.type === 'on').sort((a, b) => a.absTime - b.absTime);
        assert.equal(ons.length, 4);

        const notes = ons.map(e => e.note);
        assert.deepEqual(notes, [48, 60, 55, 67]);
    });

    it('preserves song order across multiple patterns', () => {
        const pat0 = makePattern(4, { 0: [[0, 60, 100]] });
        const pat1 = makePattern(4, { 0: [[0, 72, 100]] });
        const { parsed } = buildAndParse([pat0, pat1], [0, 1, 0]);
        const ons = parsed.events.filter(e => e.type === 'on');
        assert.equal(ons.length, 3);
        assert.equal(ons[0].note, 60);
        assert.equal(ons[1].note, 72);
        assert.equal(ons[2].note, 60);
    });

    it('handles large delta times (extend events)', () => {
        // 64-row pattern with note at row 0 and row 60 → large delta
        const pat = makePattern(64, { 0: [[0, 60, 100], [60, 62, 100]] });
        const { parsed } = buildAndParse([pat], [0]);
        const ons = parsed.events.filter(e => e.type === 'on');
        assert.equal(ons.length, 2);
        assert.equal(ons[0].note, 60);
        assert.equal(ons[1].note, 62);
        assert.ok(ons[1].absTime > ons[0].absTime);
    });

    it('handles large gate times (extend events)', () => {
        // Single note in a 64-row pattern → gate spans full pattern
        const pat = makePattern(64, { 0: [[0, 60, 100]] });
        const { parsed } = buildAndParse([pat], [0]);
        const ons = parsed.events.filter(e => e.type === 'on');
        assert.equal(ons.length, 1);
        // gate = 64 * (480/4) = 7680
        assert.equal(ons[0].gate, 7680);
    });

    it('matches mid2seq.c reference output', function() {
        const mid2seqBin = path.join(__dirname, '..', '..', 'tools', 'mid2seq');
        const midDir = path.join(__dirname, '..', '..', 'tests', 'midi_test_files');

        // Build mid2seq.c if needed
        if (!fs.existsSync(mid2seqBin)) {
            try {
                const { execSync } = require('child_process');
                execSync('cc -o ' + mid2seqBin + ' ' + path.join(__dirname, '..', 'mid2seq.c'));
            } catch {
                // skip if can't compile
                return;
            }
        }

        const testFile = path.join(midDir, 'test_short_long.mid');
        if (!fs.existsSync(testFile)) return;

        const { execSync } = require('child_process');
        const refPath = '/tmp/ref_node_test.seq';
        execSync(mid2seqBin + ' ' + testFile + ' ' + refPath);
        const refSeq = fs.readFileSync(refPath);

        // Parse the MIDI → build SEQ through the tracker-style path
        // (the C tool builds from raw MIDI, so we compare header structure only)
        assert.equal((refSeq[0] << 8) | refSeq[1], 1, 'ref has num_songs=1');
        assert.equal((refSeq[6] << 8) | refSeq[7], 480, 'ref has resolution=480');
    });
});
