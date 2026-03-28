const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { parseMIDI, buildMIDI } = require('../midi_io.js');

const MIDI_DIR = path.join(__dirname, '..', '..', 'tests', 'midi_test_files');

function readMidi(name) {
    const buf = fs.readFileSync(path.join(MIDI_DIR, name));
    return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

// -- helpers to build minimal tracker patterns --

function makePattern(length, channelData) {
    const numChannels = Object.keys(channelData).length || 1;
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

// ═══════════════════════════════════════════════
// parseMIDI
// ═══════════════════════════════════════════════

describe('parseMIDI', () => {
    it('rejects non-MIDI data', () => {
        const buf = new ArrayBuffer(8);
        assert.throws(() => parseMIDI(buf), /Not a MIDI file/);
    });

    it('parses format, division, and track count', () => {
        const midi = parseMIDI(readMidi('test_short_long.mid'));
        assert.equal(midi.format, 0);
        assert.equal(midi.division, 480);
    });

    it('extracts note-on and note-off events', () => {
        const midi = parseMIDI(readMidi('test_short_long.mid'));
        const ons = midi.events.filter(e => e.type === 'on');
        const offs = midi.events.filter(e => e.type === 'off');
        assert.ok(ons.length >= 2, 'at least 2 note-ons');
        assert.ok(offs.length >= 2, 'at least 2 note-offs');
    });

    it('extracts tempo events with bpm and mspb', () => {
        const midi = parseMIDI(readMidi('test_short_long.mid'));
        const tempos = midi.events.filter(e => e.type === 'tempo');
        assert.ok(tempos.length >= 1, 'has a tempo event');
        assert.equal(tempos[0].bpm, 120);
        assert.equal(tempos[0].mspb, 500000);
    });

    it('extracts program change events', () => {
        const midi = parseMIDI(readMidi('test_program_change.mid'));
        const pcs = midi.events.filter(e => e.type === 'pc');
        assert.ok(pcs.length >= 1, 'has program changes');
        assert.equal(typeof pcs[0].prog, 'number');
        assert.equal(typeof pcs[0].ch, 'number');
    });

    it('handles multi-channel files', () => {
        const midi = parseMIDI(readMidi('test_multi_channel.mid'));
        const channels = new Set(midi.events.filter(e => e.type === 'on').map(e => e.ch));
        assert.ok(channels.size >= 2, 'at least 2 channels');
    });

    it('note-off via velocity 0 is typed as off', () => {
        // MIDI spec: note-on with vel=0 is a note-off
        const midi = parseMIDI(readMidi('test_short_long.mid'));
        for (const ev of midi.events) {
            if (ev.type === 'on') assert.ok(ev.vel > 0);
            if (ev.type === 'off') assert.equal(ev.vel, 0);
        }
    });

    it('events have monotonically non-decreasing absTime per track', () => {
        const midi = parseMIDI(readMidi('test_large_delta.mid'));
        for (let i = 1; i < midi.events.length; i++) {
            assert.ok(midi.events[i].absTime >= midi.events[i - 1].absTime,
                `event ${i} time ${midi.events[i].absTime} >= ${midi.events[i - 1].absTime}`);
        }
    });
});

// ═══════════════════════════════════════════════
// buildMIDI
// ═══════════════════════════════════════════════

describe('buildMIDI', () => {
    it('produces a valid MIDI file starting with MThd', () => {
        const pat = makePattern(4, { 0: [[0, 60, 100]] });
        const mid = buildMIDI({ patterns: [pat], song: [0], bpm: 120, stepsPerBeat: 4, numChannels: 1 });
        assert.ok(mid instanceof Uint8Array);
        assert.equal(String.fromCharCode(mid[0], mid[1], mid[2], mid[3]), 'MThd');
    });

    it('produces a file that parseMIDI can read back', () => {
        const pat = makePattern(8, {
            0: [[0, 60, 100], [4, 64, 90]],
            1: [[2, 48, 80]],
        });
        const mid = buildMIDI({ patterns: [pat], song: [0], bpm: 140, stepsPerBeat: 4, numChannels: 2 });
        const parsed = parseMIDI(mid.buffer);
        assert.equal(parsed.format, 0);
        assert.equal(parsed.division, 480);
    });

    it('round-trips note data through build → parse', () => {
        const pat = makePattern(8, {
            0: [[0, 60, 100], [4, 67, 110]],
        });
        const mid = buildMIDI({ patterns: [pat], song: [0], bpm: 120, stepsPerBeat: 4, numChannels: 1 });
        const parsed = parseMIDI(mid.buffer);

        const ons = parsed.events.filter(e => e.type === 'on');
        assert.equal(ons.length, 2);
        assert.equal(ons[0].note, 60);
        assert.equal(ons[0].vel, 100);
        assert.equal(ons[1].note, 67);
        assert.equal(ons[1].vel, 110);
    });

    it('round-trips tempo', () => {
        const pat = makePattern(4, { 0: [[0, 60, 100]] });
        const mid = buildMIDI({ patterns: [pat], song: [0], bpm: 95, stepsPerBeat: 4, numChannels: 1 });
        const parsed = parseMIDI(mid.buffer);
        const tempo = parsed.events.find(e => e.type === 'tempo');
        assert.ok(tempo);
        // mspb = 60000000/95 = 631578.9... → rounds to 631579
        assert.equal(tempo.mspb, Math.round(60000000 / 95));
    });

    it('emits program change events', () => {
        const pat = makePattern(4, { 0: [[0, 60, 100]] });
        pat.channels[0].defaultInst = 5;
        const mid = buildMIDI({ patterns: [pat], song: [0], bpm: 120, stepsPerBeat: 4, numChannels: 1 });
        const parsed = parseMIDI(mid.buffer);
        const pcs = parsed.events.filter(e => e.type === 'pc');
        assert.ok(pcs.length >= 1);
        assert.equal(pcs[0].prog, 5);
    });

    it('generates note-off events from gate time', () => {
        const pat = makePattern(8, { 0: [[0, 60, 100], [4, 62, 100]] });
        const mid = buildMIDI({ patterns: [pat], song: [0], bpm: 120, stepsPerBeat: 4, numChannels: 1 });
        const parsed = parseMIDI(mid.buffer);
        const offs = parsed.events.filter(e => e.type === 'off');
        assert.ok(offs.length >= 2, 'has note-off for each note-on');
    });

    it('respects song order across multiple patterns', () => {
        const pat0 = makePattern(4, { 0: [[0, 60, 100]] });
        const pat1 = makePattern(4, { 0: [[0, 72, 100]] });
        const mid = buildMIDI({ patterns: [pat0, pat1], song: [0, 1, 0], bpm: 120, stepsPerBeat: 4, numChannels: 1 });
        const parsed = parseMIDI(mid.buffer);
        const ons = parsed.events.filter(e => e.type === 'on');
        assert.equal(ons.length, 3);
        assert.equal(ons[0].note, 60);
        assert.equal(ons[1].note, 72);
        assert.equal(ons[2].note, 60);
    });
});
