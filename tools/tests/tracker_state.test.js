const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const TrackerState = require('../tracker_state.js');

describe('TrackerState.NUM_CHANNELS', () => {
    it('equals 8', () => {
        assert.equal(TrackerState.NUM_CHANNELS, 8);
    });
});

describe('TrackerState.KEY_NOTE_MAP', () => {
    it('maps z to 0 (C)', () => {
        assert.equal(TrackerState.KEY_NOTE_MAP['z'], 0);
    });

    it('maps q to 12 (C+1 octave)', () => {
        assert.equal(TrackerState.KEY_NOTE_MAP['q'], 12);
    });
});

describe('TrackerState.create', () => {
    it('returns a state object with all required fields', () => {
        var state = TrackerState.create();
        assert.equal(state.bpm, 120);
        assert.equal(state.stepsPerBeat, 4);
        assert.equal(state.patternLength, 32);
        assert.ok(Array.isArray(state.instruments));
        assert.ok(Array.isArray(state.patterns));
        assert.ok(Array.isArray(state.song));
        assert.ok(state.cursor);
    });

    it('initializes with one pattern', () => {
        var state = TrackerState.create();
        assert.equal(state.patterns.length, 1);
        assert.equal(state.song.length, 1);
        assert.equal(state.song[0], 0);
    });

    it('deep-clones provided instruments', () => {
        var presets = [{ name: 'Test', operators: [{ ar: 31 }] }];
        var state = TrackerState.create(presets);
        assert.equal(state.instruments[0].name, 'Test');
        // Verify it's a clone, not same reference
        state.instruments[0].name = 'Modified';
        assert.equal(presets[0].name, 'Test');
    });

    it('creates a default instrument when none provided', () => {
        var state = TrackerState.create();
        assert.ok(state.instruments.length >= 1);
        assert.equal(typeof state.instruments[0].name, 'string');
    });

    it('first pattern has correct length', () => {
        var state = TrackerState.create();
        assert.equal(state.patterns[0].length, 32);
        assert.equal(state.patterns[0].channels.length, 8);
    });
});

describe('TrackerState.createEmptyPattern', () => {
    it('creates a pattern with the specified length', () => {
        var state = TrackerState.create();
        var pat = TrackerState.createEmptyPattern(state, 16);
        assert.equal(pat.length, 16);
        assert.equal(pat.channels.length, 8);
        assert.equal(pat.channels[0].rows.length, 16);
    });

    it('cells are initialized to null', () => {
        var state = TrackerState.create();
        var pat = TrackerState.createEmptyPattern(state, 4);
        var cell = pat.channels[0].rows[0];
        assert.equal(cell.note, null);
        assert.equal(cell.inst, null);
        assert.equal(cell.vol, null);
    });

    it('clamps defaultInst to instrument count', () => {
        var state = TrackerState.create([{ name: 'A', operators: [] }]);
        var pat = TrackerState.createEmptyPattern(state, 4);
        // Only 1 instrument, so all channels should have defaultInst = 0
        for (var ch = 0; ch < 8; ch++) {
            assert.equal(pat.channels[ch].defaultInst, 0);
        }
    });
});

describe('TrackerState.getCurrentPatternIndex', () => {
    it('returns the pattern index for a song slot', () => {
        var state = TrackerState.create();
        assert.equal(TrackerState.getCurrentPatternIndex(state, 0), 0);
    });

    it('returns 0 for out-of-range slots', () => {
        var state = TrackerState.create();
        assert.equal(TrackerState.getCurrentPatternIndex(state, 99), 0);
    });
});

describe('Song arrangement', () => {
    var state;
    beforeEach(() => { state = TrackerState.create(); });

    it('addSongSlot appends a slot', () => {
        TrackerState.addSongSlot(state, 0);
        assert.equal(state.song.length, 2);
    });

    it('removeSongSlot removes a slot', () => {
        TrackerState.addSongSlot(state, 0);
        var slot = TrackerState.removeSongSlot(state, 1);
        assert.equal(state.song.length, 1);
        assert.equal(slot, 0);
    });

    it('removeSongSlot won\'t remove the last slot', () => {
        var slot = TrackerState.removeSongSlot(state, 0);
        assert.equal(state.song.length, 1);
        assert.equal(slot, 0);
    });

    it('newPattern creates a pattern and inserts a slot', () => {
        var slot = TrackerState.newPattern(state, 0);
        assert.equal(slot, 1);
        assert.equal(state.patterns.length, 2);
        assert.equal(state.song.length, 2);
        assert.equal(state.song[1], 1);
    });

    it('dupPattern duplicates the current slot reference', () => {
        var slot = TrackerState.dupPattern(state, 0);
        assert.equal(slot, 1);
        assert.equal(state.song.length, 2);
        assert.equal(state.song[0], state.song[1]); // same pattern index
        assert.equal(state.patterns.length, 1); // no new pattern created
    });
});

describe('TrackerState.resizePattern', () => {
    it('extends a pattern', () => {
        var state = TrackerState.create();
        TrackerState.resizePattern(state, 0, 64);
        assert.equal(state.patterns[0].length, 64);
        assert.equal(state.patterns[0].channels[0].rows.length, 64);
    });

    it('shrinks a pattern', () => {
        var state = TrackerState.create();
        TrackerState.resizePattern(state, 0, 8);
        assert.equal(state.patterns[0].length, 8);
        assert.equal(state.patterns[0].channels[0].rows.length, 8);
    });

    it('clamps cursor row when shrinking', () => {
        var state = TrackerState.create();
        state.cursor.row = 20;
        TrackerState.resizePattern(state, 0, 8);
        assert.equal(state.cursor.row, 7);
    });
});

describe('Instrument management', () => {
    var state;
    beforeEach(() => { state = TrackerState.create(); });

    it('addInstrument returns new index', () => {
        var idx = TrackerState.addInstrument(state, { name: 'New', operators: [] });
        assert.equal(idx, 1);
        assert.equal(state.instruments.length, 2);
    });

    it('dupInstrument clones with " copy" suffix', () => {
        var idx = TrackerState.dupInstrument(state, 0);
        assert.equal(idx, 1);
        assert.ok(state.instruments[1].name.includes('copy'));
    });

    it('delInstrument removes and returns adjusted index', () => {
        TrackerState.addInstrument(state, { name: 'B', operators: [] });
        var idx = TrackerState.delInstrument(state, 1);
        assert.equal(state.instruments.length, 1);
        assert.equal(idx, 0);
    });

    it('delInstrument won\'t delete the last instrument', () => {
        var idx = TrackerState.delInstrument(state, 0);
        assert.equal(state.instruments.length, 1);
        assert.equal(idx, 0);
    });
});

describe('Channel mute/solo', () => {
    beforeEach(() => { TrackerState.resetChannelState(); });

    it('channels start audible', () => {
        for (var ch = 0; ch < 8; ch++) {
            assert.ok(TrackerState.isChannelAudible(ch));
        }
    });

    it('toggleMute mutes a channel', () => {
        TrackerState.toggleMute(0);
        assert.equal(TrackerState.getChannelState(0), 'muted');
        assert.ok(!TrackerState.isChannelAudible(0));
    });

    it('toggleMute returns silenced channels', () => {
        var silenced = TrackerState.toggleMute(3);
        assert.ok(silenced.includes(3));
    });

    it('toggleMute unmutes when toggled again', () => {
        TrackerState.toggleMute(0);
        TrackerState.toggleMute(0);
        assert.equal(TrackerState.getChannelState(0), 'on');
        assert.ok(TrackerState.isChannelAudible(0));
    });

    it('toggleSolo solos a channel', () => {
        TrackerState.toggleSolo(2);
        assert.ok(TrackerState.isChannelAudible(2));
        assert.ok(!TrackerState.isChannelAudible(0));
        assert.ok(!TrackerState.isChannelAudible(7));
    });

    it('toggleSolo returns all non-solo channels as silenced', () => {
        var silenced = TrackerState.toggleSolo(2);
        assert.equal(silenced.length, 7); // all except ch 2
        assert.ok(!silenced.includes(2));
    });

    it('toggleSolo unsolos when toggled again', () => {
        TrackerState.toggleSolo(2);
        TrackerState.toggleSolo(2);
        // All channels should be audible again
        for (var ch = 0; ch < 8; ch++) {
            assert.ok(TrackerState.isChannelAudible(ch));
        }
    });
});
