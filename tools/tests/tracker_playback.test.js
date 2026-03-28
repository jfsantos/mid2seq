const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const TrackerState = require('../tracker_state.js');
const TrackerPlayback = require('../tracker_playback.js');

// Mock engine that records calls
function createMockEngine() {
    return {
        calls: [],
        triggerNote: function(ch, note, instIdx, inst) {
            this.calls.push({ fn: 'triggerNote', ch: ch, note: note, instIdx: instIdx });
        },
        releaseChannel: function(ch) {
            this.calls.push({ fn: 'releaseChannel', ch: ch });
        },
        releaseAll: function() {
            this.calls.push({ fn: 'releaseAll' });
        },
        getSampleRate: function() { return 44100; },
    };
}

function makeState(patterns, song, instruments) {
    var state = TrackerState.create(instruments || [{ name: 'Test', operators: [{ ar: 31 }] }]);
    if (patterns) {
        state.patterns = patterns;
        state.song = song || [0];
    }
    return state;
}

function makePatternWithNotes(len, noteMap) {
    // noteMap: { ch: [[row, note, vel], ...] }
    var state = TrackerState.create();
    var pat = TrackerState.createEmptyPattern(state, len);
    for (var ch in noteMap) {
        for (var i = 0; i < noteMap[ch].length; i++) {
            var entry = noteMap[ch][i];
            var row = entry[0], note = entry[1], vel = entry[2];
            pat.channels[parseInt(ch)].rows[row] = { note: note, inst: null, vol: vel || null };
        }
    }
    return pat;
}

describe('TrackerPlayback.create', () => {
    it('returns a playback object with required fields', () => {
        var engine = createMockEngine();
        var state = makeState();
        var pb = TrackerPlayback.create(state, engine);
        assert.equal(pb.playing, false);
        assert.equal(typeof pb.start, 'function');
        assert.equal(typeof pb.stop, 'function');
        assert.equal(typeof pb.processBlock, 'function');
        assert.equal(typeof pb.updateTempo, 'function');
    });
});

describe('Playback start/stop', () => {
    it('start sets playing to true', () => {
        var engine = createMockEngine();
        var state = makeState();
        var pb = TrackerPlayback.create(state, engine);
        pb.start(0, 0);
        assert.equal(pb.playing, true);
    });

    it('start initializes position', () => {
        var engine = createMockEngine();
        var state = makeState();
        var pb = TrackerPlayback.create(state, engine);
        pb.start(5, 2);
        assert.equal(pb.currentRow, 5);
        assert.equal(pb.currentSongSlot, 2);
    });

    it('stop sets playing to false', () => {
        var engine = createMockEngine();
        var state = makeState();
        var pb = TrackerPlayback.create(state, engine);
        pb.start(0, 0);
        pb.stop();
        assert.equal(pb.playing, false);
    });

    it('stop calls engine.releaseAll', () => {
        var engine = createMockEngine();
        var state = makeState();
        var pb = TrackerPlayback.create(state, engine);
        pb.start(0, 0);
        pb.stop();
        assert.ok(engine.calls.some(function(c) { return c.fn === 'releaseAll'; }));
    });

    it('stop fires onStop callback', () => {
        var engine = createMockEngine();
        var state = makeState();
        var pb = TrackerPlayback.create(state, engine);
        var stopped = false;
        pb.onStop = function() { stopped = true; };
        pb.start(0, 0);
        pb.stop();
        assert.ok(stopped);
    });
});

describe('Playback tempo', () => {
    it('updateTempo computes samplesPerStep from BPM', () => {
        var engine = createMockEngine();
        var state = makeState();
        state.bpm = 120;
        state.stepsPerBeat = 4;
        var pb = TrackerPlayback.create(state, engine);
        pb.updateTempo();
        // 44100 * 60 / 120 / 4 = 5512.5, rounded to 5513
        assert.equal(pb.samplesPerStep, Math.round(44100 * 60 / 120 / 4));
    });

    it('changing BPM updates samplesPerStep', () => {
        var engine = createMockEngine();
        var state = makeState();
        state.bpm = 60;
        state.stepsPerBeat = 4;
        var pb = TrackerPlayback.create(state, engine);
        pb.updateTempo();
        var slow = pb.samplesPerStep;
        state.bpm = 240;
        pb.updateTempo();
        assert.ok(pb.samplesPerStep < slow);
    });
});

describe('Playback processBlock', () => {
    it('triggers notes when stepping through a pattern', () => {
        var engine = createMockEngine();
        var pat = makePatternWithNotes(4, { 0: [[0, 60, 100]] });
        var state = makeState([pat], [0]);
        state.bpm = 120;
        state.stepsPerBeat = 4;
        var pb = TrackerPlayback.create(state, engine);
        TrackerState.resetChannelState();
        pb.start(0, 0);

        // Process enough samples to trigger at least the first row
        pb.processBlock(pb.samplesPerStep + 1);

        var triggers = engine.calls.filter(function(c) { return c.fn === 'triggerNote'; });
        assert.ok(triggers.length >= 1, 'at least one note triggered');
        assert.equal(triggers[0].note, 60);
        assert.equal(triggers[0].ch, 0);
    });

    it('advances row on each step', () => {
        var engine = createMockEngine();
        var pat = makePatternWithNotes(8, {});
        var state = makeState([pat], [0]);
        state.bpm = 120;
        state.stepsPerBeat = 4;
        var pb = TrackerPlayback.create(state, engine);
        pb.start(0, 0);

        // Process 3 steps worth of samples
        pb.processBlock(pb.samplesPerStep * 3 + 1);
        assert.ok(pb.currentRow >= 3);
    });

    it('fires onRowChange callback', () => {
        var engine = createMockEngine();
        var pat = makePatternWithNotes(4, {});
        var state = makeState([pat], [0]);
        state.bpm = 120;
        state.stepsPerBeat = 4;
        var pb = TrackerPlayback.create(state, engine);
        var rowChanges = [];
        pb.onRowChange = function(row, slot) { rowChanges.push({ row: row, slot: slot }); };
        pb.start(0, 0);

        pb.processBlock(pb.samplesPerStep * 2 + 1);
        assert.ok(rowChanges.length >= 2);
    });

    it('wraps to next song slot at pattern end', () => {
        var engine = createMockEngine();
        var pat = makePatternWithNotes(2, {}); // very short pattern
        var state = makeState([pat, pat], [0, 1]);
        state.bpm = 120;
        state.stepsPerBeat = 4;
        var pb = TrackerPlayback.create(state, engine);
        pb.start(0, 0);

        // Process enough to pass the 2-row pattern
        pb.processBlock(pb.samplesPerStep * 3 + 1);
        assert.equal(pb.currentSongSlot, 1);
    });

    it('loops song when reaching the end', () => {
        var engine = createMockEngine();
        var pat = makePatternWithNotes(1, {}); // 1-row pattern
        var state = makeState([pat], [0]);
        state.bpm = 120;
        state.stepsPerBeat = 4;
        var pb = TrackerPlayback.create(state, engine);
        pb.start(0, 0);

        pb.processBlock(pb.samplesPerStep * 3 + 1);
        assert.equal(pb.currentSongSlot, 0); // looped back
    });

    it('handles note-off events (note = -1)', () => {
        var engine = createMockEngine();
        var pat = makePatternWithNotes(4, { 0: [[0, 60, 100], [2, -1]] });
        var state = makeState([pat], [0]);
        state.bpm = 120;
        state.stepsPerBeat = 4;
        var pb = TrackerPlayback.create(state, engine);
        TrackerState.resetChannelState();
        pb.start(0, 0);

        // Process through row 0 (note on) and row 2 (note off)
        pb.processBlock(pb.samplesPerStep * 3 + 1);

        var releases = engine.calls.filter(function(c) { return c.fn === 'releaseChannel' && c.ch === 0; });
        assert.ok(releases.length >= 1, 'channel 0 released on note-off');
    });

    it('respects muted channels', () => {
        var engine = createMockEngine();
        var pat = makePatternWithNotes(4, { 0: [[0, 60, 100]] });
        var state = makeState([pat], [0]);
        state.bpm = 120;
        state.stepsPerBeat = 4;
        var pb = TrackerPlayback.create(state, engine);
        TrackerState.resetChannelState();
        TrackerState.toggleMute(0); // mute channel 0

        pb.start(0, 0);
        pb.processBlock(pb.samplesPerStep + 1);

        var triggers = engine.calls.filter(function(c) { return c.fn === 'triggerNote'; });
        assert.equal(triggers.length, 0, 'muted channel should not trigger');
    });
});
