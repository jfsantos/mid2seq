const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const TrackerState = require('../tracker_state.js');
const TrackerPlayback = require('../tracker_playback.js');
const { parseMIDI, buildMIDI } = require('../midi_io.js');
const { parseSEQ, buildSEQ } = require('../seq_io.js');

/**
 * Integration tests verifying the full flow:
 *   state manipulation → pattern data → format export → parse → verify
 * These simulate what the UI does without requiring a DOM.
 */

function createMockEngine() {
    return {
        notes: [],
        released: [],
        triggerNote: function(ch, note, instIdx, inst) {
            this.notes.push({ ch: ch, note: note, instIdx: instIdx, name: inst ? inst.name : null });
        },
        releaseChannel: function(ch) { this.released.push(ch); },
        releaseAll: function() { this.released.push('all'); },
        getSampleRate: function() { return 44100; },
    };
}

describe('State → SEQ export round-trip', () => {
    it('pattern notes survive export and re-import', () => {
        var state = TrackerState.create([
            { name: 'A', operators: [{ ar: 31 }] },
            { name: 'B', operators: [{ ar: 20 }] },
        ]);
        var pat = state.patterns[0];
        // Place some notes
        pat.channels[0].rows[0] = { note: 60, inst: null, vol: 100 };
        pat.channels[0].rows[8] = { note: 64, inst: null, vol: 90 };
        pat.channels[1].rows[4] = { note: 48, inst: null, vol: 80 };

        // Export to SEQ
        var seq = buildSEQ({
            patterns: state.patterns, song: state.song,
            bpm: state.bpm, stepsPerBeat: state.stepsPerBeat,
            numChannels: TrackerState.NUM_CHANNELS,
        });
        assert.ok(seq.length > 0);

        // Parse it back
        var parsed = parseSEQ(seq.buffer);
        var ons = parsed.events.filter(function(e) { return e.type === 'on'; });
        assert.equal(ons.length, 3);

        var notes = ons.map(function(e) { return e.note; }).sort();
        assert.deepEqual(notes, [48, 60, 64]);
    });
});

describe('State → MIDI export round-trip', () => {
    it('pattern notes survive export and re-import', () => {
        var state = TrackerState.create();
        var pat = state.patterns[0];
        pat.channels[0].rows[0] = { note: 60, inst: null, vol: 100 };
        pat.channels[0].rows[16] = { note: 67, inst: null, vol: 110 };

        var mid = buildMIDI({
            patterns: state.patterns, song: state.song,
            bpm: state.bpm, stepsPerBeat: state.stepsPerBeat,
            numChannels: TrackerState.NUM_CHANNELS,
        });
        var parsed = parseMIDI(mid.buffer);
        var ons = parsed.events.filter(function(e) { return e.type === 'on'; });
        assert.equal(ons.length, 2);
        assert.equal(ons[0].note, 60);
        assert.equal(ons[1].note, 67);
    });
});

describe('Multi-pattern song arrangement → export', () => {
    it('exports notes from all song slots in order', () => {
        var state = TrackerState.create();
        // Create two patterns
        var slot1 = TrackerState.newPattern(state, 0);

        // Put different notes in each
        state.patterns[0].channels[0].rows[0] = { note: 60, inst: null, vol: 100 };
        state.patterns[1].channels[0].rows[0] = { note: 72, inst: null, vol: 100 };

        // Song: [0, 1]
        var seq = buildSEQ({
            patterns: state.patterns, song: state.song,
            bpm: state.bpm, stepsPerBeat: state.stepsPerBeat,
            numChannels: TrackerState.NUM_CHANNELS,
        });
        var parsed = parseSEQ(seq.buffer);
        var ons = parsed.events.filter(function(e) { return e.type === 'on'; });
        assert.equal(ons.length, 2);
        assert.equal(ons[0].note, 60);
        assert.equal(ons[1].note, 72);
    });
});

describe('Playback integration with state and engine', () => {
    it('full playback cycle: start → process → trigger → stop', () => {
        var engine = createMockEngine();
        var state = TrackerState.create();
        TrackerState.resetChannelState();

        // Place a note
        state.patterns[0].channels[0].rows[0] = { note: 60, inst: null, vol: 100 };
        state.patterns[0].channels[0].defaultInst = 0;

        var pb = TrackerPlayback.create(state, engine);
        pb.start(0, 0);

        // Process enough to trigger at least one row
        pb.processBlock(pb.samplesPerStep + 1);

        // Verify note was triggered
        assert.ok(engine.notes.length >= 1);
        assert.equal(engine.notes[0].note, 60);
        assert.equal(engine.notes[0].ch, 0);

        // Stop
        pb.stop();
        assert.equal(pb.playing, false);
        assert.ok(engine.released.includes('all'));
    });

    it('muting a channel prevents note triggering', () => {
        var engine = createMockEngine();
        var state = TrackerState.create();
        TrackerState.resetChannelState();

        state.patterns[0].channels[0].rows[0] = { note: 60, inst: null, vol: 100 };
        state.patterns[0].channels[1].rows[0] = { note: 48, inst: null, vol: 100 };

        // Mute channel 0
        TrackerState.toggleMute(0);

        var pb = TrackerPlayback.create(state, engine);
        pb.start(0, 0);
        pb.processBlock(pb.samplesPerStep + 1);

        // Only channel 1 should have triggered
        var triggered = engine.notes.filter(function(n) { return n.ch === 0; });
        assert.equal(triggered.length, 0, 'muted channel 0 should not trigger');
        var ch1 = engine.notes.filter(function(n) { return n.ch === 1; });
        assert.ok(ch1.length >= 1, 'unmuted channel 1 should trigger');
    });
});

describe('Instrument CRUD → export consistency', () => {
    it('program changes reflect channel defaultInst after instrument operations', () => {
        var state = TrackerState.create([
            { name: 'Bass', operators: [{ ar: 31 }] },
            { name: 'Lead', operators: [{ ar: 25 }] },
        ]);

        // Set channel 0 to use instrument 1 (Lead)
        state.patterns[0].channels[0].defaultInst = 1;
        state.patterns[0].channels[0].rows[0] = { note: 60, inst: null, vol: 100 };

        var mid = buildMIDI({
            patterns: state.patterns, song: state.song,
            bpm: state.bpm, stepsPerBeat: state.stepsPerBeat,
            numChannels: TrackerState.NUM_CHANNELS,
        });
        var parsed = parseMIDI(mid.buffer);
        var pcs = parsed.events.filter(function(e) { return e.type === 'pc' && e.ch === 0; });
        assert.ok(pcs.length >= 1);
        assert.equal(pcs[0].prog, 1, 'channel 0 should have program 1 (Lead)');
    });
});

describe('Pattern resize → export', () => {
    it('shrinking pattern truncates notes beyond new length', () => {
        var state = TrackerState.create();
        state.patterns[0].channels[0].rows[0] = { note: 60, inst: null, vol: 100 };
        state.patterns[0].channels[0].rows[24] = { note: 72, inst: null, vol: 100 };

        // Shrink to 16 rows — note at row 24 should be lost
        TrackerState.resizePattern(state, 0, 16);

        var seq = buildSEQ({
            patterns: state.patterns, song: state.song,
            bpm: state.bpm, stepsPerBeat: state.stepsPerBeat,
            numChannels: TrackerState.NUM_CHANNELS,
        });
        var parsed = parseSEQ(seq.buffer);
        var ons = parsed.events.filter(function(e) { return e.type === 'on'; });
        assert.equal(ons.length, 1, 'only note at row 0 should survive');
        assert.equal(ons[0].note, 60);
    });
});
