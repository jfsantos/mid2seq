const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { NOTE_NAMES, noteName } = require('../note_util.js');

describe('NOTE_NAMES', () => {
    it('has 12 entries', () => {
        assert.equal(NOTE_NAMES.length, 12);
    });

    it('starts with C and ends with B', () => {
        assert.equal(NOTE_NAMES[0], 'C-');
        assert.equal(NOTE_NAMES[11], 'B-');
    });
});

describe('noteName', () => {
    it('converts middle C (60) to C-5', () => {
        assert.equal(noteName(60), 'C-5');
    });

    it('converts concert A (69) to A-5', () => {
        assert.equal(noteName(69), 'A-5');
    });

    it('converts MIDI 0 to C-0', () => {
        assert.equal(noteName(0), 'C-0');
    });

    it('converts MIDI 127 to G-10', () => {
        assert.equal(noteName(127), 'G-10');
    });

    it('handles sharps', () => {
        assert.equal(noteName(61), 'C#5');
        assert.equal(noteName(70), 'A#5');
    });

    it('returns ??? for out of range values', () => {
        assert.equal(noteName(-1), '???');
        assert.equal(noteName(128), '???');
    });
});
