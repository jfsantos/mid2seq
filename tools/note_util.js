/**
 * @module note_util
 * @description MIDI note name utilities.
 */

/**
 * Note name prefixes indexed by pitch class (0–11).
 * @constant {string[]}
 */
const NOTE_NAMES = ['C-','C#','D-','D#','E-','F-','F#','G-','G#','A-','A#','B-'];

/**
 * Convert a MIDI note number to a display string.
 *
 * @param {number} midi - MIDI note number (0–127)
 * @returns {string} Note name with octave, e.g. `"C-4"`, `"F#5"`. Returns `"???"` if out of range.
 *
 * @example
 * noteName(60)  // "C-5"
 * noteName(69)  // "A-5"
 * noteName(128) // "???"
 */
function noteName(midi) {
    if (midi < 0 || midi > 127) return '???';
    return NOTE_NAMES[midi % 12] + Math.floor(midi / 12);
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { NOTE_NAMES, noteName };
}
