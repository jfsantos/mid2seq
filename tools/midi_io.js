/**
 * @module midi_io
 * @description Standard MIDI file (.mid) parser and builder.
 */

/**
 * A note-on event parsed from a MIDI file.
 * @typedef {Object} MidiNoteOnEvent
 * @property {number} absTime - Absolute time in ticks from file start
 * @property {number} ch      - MIDI channel (0–15)
 * @property {'on'}   type    - Event type
 * @property {number} note    - MIDI note number (0–127)
 * @property {number} vel     - Velocity (1–127)
 */

/**
 * A note-off event parsed from a MIDI file.
 * @typedef {Object} MidiNoteOffEvent
 * @property {number} absTime - Absolute time in ticks from file start
 * @property {number} ch      - MIDI channel (0–15)
 * @property {'off'}  type    - Event type
 * @property {number} note    - MIDI note number (0–127)
 * @property {0}      vel     - Always 0
 */

/**
 * A program change event parsed from a MIDI file.
 * @typedef {Object} MidiProgramChangeEvent
 * @property {number} absTime - Absolute time in ticks from file start
 * @property {number} ch      - MIDI channel (0–15)
 * @property {'pc'}   type    - Event type
 * @property {number} prog    - Program number (0–127)
 */

/**
 * A tempo change event parsed from a MIDI file.
 * @typedef {Object} MidiTempoEvent
 * @property {number}  absTime - Absolute time in ticks from file start
 * @property {'tempo'} type    - Event type
 * @property {number}  bpm     - Beats per minute (rounded)
 * @property {number}  mspb    - Microseconds per beat (raw value from file)
 */

/**
 * Any event returned by {@link parseMIDI}.
 * @typedef {MidiNoteOnEvent|MidiNoteOffEvent|MidiProgramChangeEvent|MidiTempoEvent} MidiEvent
 */

/**
 * Result of parsing a Standard MIDI File.
 * @typedef {Object} ParseMIDIResult
 * @property {number}      format   - MIDI format (0, 1, or 2)
 * @property {number}      division - Ticks per quarter note (e.g. 480)
 * @property {MidiEvent[]} events   - All parsed events, merged from all tracks
 */

/**
 * A single row in a tracker channel grid.
 * @typedef {Object} TrackerCell
 * @property {?number} note - MIDI note (0–127), -1 for note-off, or null if empty
 * @property {?number} inst - Instrument index, or null
 * @property {?number} vol  - Velocity (0–127), or null for default (100)
 */

/**
 * A single channel within a pattern.
 * @typedef {Object} PatternChannel
 * @property {number}        defaultInst - Default instrument/program for this channel
 * @property {TrackerCell[]} rows        - One cell per row
 */

/**
 * A tracker pattern containing rows across multiple channels.
 * @typedef {Object} Pattern
 * @property {number}           length   - Number of rows
 * @property {PatternChannel[]} channels - One entry per tracker channel
 */

/**
 * Options for {@link buildMIDI}.
 * @typedef {Object} BuildMIDIOptions
 * @property {Pattern[]}  patterns     - Array of pattern objects
 * @property {number[]}   song         - Ordered pattern indices defining playback order
 * @property {number}     bpm          - Tempo in beats per minute
 * @property {number}     stepsPerBeat - Grid resolution (e.g. 4 = sixteenth notes)
 * @property {number}     numChannels  - Number of tracker channels to export
 */

/**
 * Parse a Standard MIDI File into an event list.
 *
 * Supports format 0 and format 1 (all tracks merged into one list).
 * Handles running status, SysEx, and meta events (only tempo is extracted).
 *
 * @param {ArrayBuffer} buf - Raw MIDI file bytes
 * @returns {ParseMIDIResult}
 * @throws {Error} If the buffer does not start with `MThd`
 *
 * @example
 * const midi = parseMIDI(arrayBuffer);
 * console.log(midi.division);           // 480
 * console.log(midi.events.length);      // number of parsed events
 */
function parseMIDI(buf) {
    const d = new DataView(buf);
    const u8 = new Uint8Array(buf);
    let pos = 0;

    function read32() { const v = d.getUint32(pos); pos += 4; return v; }
    function read16() { const v = d.getUint16(pos); pos += 2; return v; }
    function read8() { return u8[pos++]; }
    function readVarLen() {
        let v = 0;
        for (let i = 0; i < 4; i++) {
            const b = read8();
            v = (v << 7) | (b & 0x7F);
            if (!(b & 0x80)) break;
        }
        return v;
    }
    function readStr(n) { let s = ''; for (let i = 0; i < n; i++) s += String.fromCharCode(read8()); return s; }

    // MThd
    const hdId = readStr(4);
    if (hdId !== 'MThd') throw new Error('Not a MIDI file');
    const hdLen = read32();
    const format = read16();
    const nTracks = read16();
    const division = read16();

    const allEvents = [];

    for (let t = 0; t < nTracks; t++) {
        const trkId = readStr(4);
        const trkLen = read32();
        if (trkId !== 'MTrk') { pos += trkLen; continue; }

        const trkEnd = pos + trkLen;
        let absTime = 0;
        let runningStatus = 0;

        while (pos < trkEnd) {
            const delta = readVarLen();
            absTime += delta;

            let status = u8[pos];
            if (status & 0x80) {
                pos++;
                if (status < 0xF0) runningStatus = status;
            } else {
                status = runningStatus;
            }

            const type = status & 0xF0;
            const ch = status & 0x0F;

            if (type === 0x90) {
                const note = read8();
                const vel = read8();
                allEvents.push({ absTime, ch, type: vel > 0 ? 'on' : 'off', note, vel });
            } else if (type === 0x80) {
                const note = read8();
                read8();
                allEvents.push({ absTime, ch, type: 'off', note, vel: 0 });
            } else if (type === 0xC0) {
                const prog = read8();
                allEvents.push({ absTime, ch, type: 'pc', prog });
            } else if (type === 0xB0) {
                read8(); read8();
            } else if (type === 0xE0) {
                read8(); read8();
            } else if (type === 0xD0) {
                read8();
            } else if (type === 0xA0) {
                read8(); read8();
            } else if (status === 0xFF) {
                const metaType = read8();
                const metaLen = readVarLen();
                if (metaType === 0x51 && metaLen === 3) {
                    const uspb = (read8() << 16) | (read8() << 8) | read8();
                    allEvents.push({ absTime, type: 'tempo', bpm: Math.round(60000000 / uspb), mspb: uspb });
                } else {
                    pos += metaLen;
                }
            } else if (status === 0xF0 || status === 0xF7) {
                const sxLen = readVarLen();
                pos += sxLen;
            }
        }
        pos = trkEnd;
    }

    return { format, division, events: allEvents };
}

/**
 * Build a Standard MIDI File (format 0, single track) from tracker pattern data.
 *
 * Uses a fixed resolution of 480 ticks per quarter note. Gate time (note duration)
 * is computed from the distance to the next note on the same channel, or to the
 * end of the pattern. Includes a tempo meta event, program changes per channel,
 * note-on/off pairs, and an end-of-track marker.
 *
 * @param {BuildMIDIOptions} options
 * @returns {Uint8Array} Complete `.mid` file ready to save
 *
 * @example
 * const mid = buildMIDI({
 *   patterns: state.patterns,
 *   song: [0, 1, 0],
 *   bpm: 120,
 *   stepsPerBeat: 4,
 *   numChannels: 8,
 * });
 * // mid is a Uint8Array containing a valid .mid file
 */
function buildMIDI({ patterns, song, bpm, stepsPerBeat, numChannels }) {
    const resolution = 480;
    const ticksPerStep = resolution / stepsPerBeat;
    const mspb = Math.round(60000000 / bpm);

    const events = [];
    let stepOffset = 0;

    const channelInst = {};
    for (const patIdx of song) {
        const pat = patterns[patIdx];
        for (let ch = 0; ch < numChannels; ch++) {
            if (!(ch in channelInst)) channelInst[ch] = pat.channels[ch].defaultInst;
        }
    }
    for (const [ch, inst] of Object.entries(channelInst)) {
        events.push({ absTick: 0, type: 'pc', ch: parseInt(ch), data1: inst });
    }

    for (const patIdx of song) {
        const pat = patterns[patIdx];
        for (let row = 0; row < pat.length; row++) {
            for (let ch = 0; ch < numChannels; ch++) {
                const cell = pat.channels[ch].rows[row];
                if (cell.note !== null && cell.note >= 0) {
                    const absTick = Math.round((stepOffset + row) * ticksPerStep);
                    let gateSteps = pat.length - row;
                    for (let r = row + 1; r < pat.length; r++) {
                        if (pat.channels[ch].rows[r].note !== null) { gateSteps = r - row; break; }
                    }
                    const gateTicks = Math.round(gateSteps * ticksPerStep);
                    const vel = cell.vol !== null ? cell.vol : 100;
                    events.push({ absTick, type: 'on', ch, note: cell.note, vel, gate: gateTicks });
                }
            }
        }
        stepOffset += pat.length;
    }

    events.sort((a, b) => {
        if (a.absTick !== b.absTick) return a.absTick - b.absTick;
        if (a.type !== b.type) return a.type === 'pc' ? -1 : 1;
        return 0;
    });

    const allEvents = [];
    for (const ev of events) {
        if (ev.type === 'on') {
            allEvents.push({ absTick: ev.absTick, status: 0x90 | ev.ch, d1: ev.note, d2: ev.vel });
            allEvents.push({ absTick: ev.absTick + ev.gate, status: 0x80 | ev.ch, d1: ev.note, d2: 0 });
        } else if (ev.type === 'pc') {
            allEvents.push({ absTick: ev.absTick, status: 0xC0 | ev.ch, d1: ev.data1, d2: -1 });
        }
    }
    allEvents.sort((a, b) => a.absTick - b.absTick);

    const trk = [];
    function writeVarLen(v) {
        const bytes = [];
        bytes.push(v & 0x7F);
        v >>= 7;
        while (v > 0) {
            bytes.push((v & 0x7F) | 0x80);
            v >>= 7;
        }
        bytes.reverse();
        for (const b of bytes) trk.push(b);
    }

    writeVarLen(0);
    trk.push(0xFF, 0x51, 0x03);
    trk.push((mspb >> 16) & 0xFF, (mspb >> 8) & 0xFF, mspb & 0xFF);

    let lastTick = 0;
    for (const ev of allEvents) {
        const delta = ev.absTick - lastTick;
        lastTick = ev.absTick;
        writeVarLen(delta);
        trk.push(ev.status);
        trk.push(ev.d1);
        if (ev.d2 >= 0) trk.push(ev.d2);
    }

    writeVarLen(0);
    trk.push(0xFF, 0x2F, 0x00);

    const buf = [];
    function w8(v) { buf.push(v & 0xFF); }
    function w16(v) { buf.push((v >> 8) & 0xFF, v & 0xFF); }
    function w32(v) { buf.push((v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF); }

    [0x4D, 0x54, 0x68, 0x64].forEach(b => w8(b)); // "MThd"
    w32(6);
    w16(0);
    w16(1);
    w16(resolution);

    [0x4D, 0x54, 0x72, 0x6B].forEach(b => w8(b)); // "MTrk"
    w32(trk.length);
    for (const b of trk) w8(b);

    return new Uint8Array(buf);
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { parseMIDI, buildMIDI };
}
