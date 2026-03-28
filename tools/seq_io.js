/**
 * @module seq_io
 * @description Sega Saturn SEQ file parser and builder.
 *
 * The SEQ format is a compact event stream used by the Saturn sound driver.
 * It uses extend prefix bytes (`0x88`–`0x8F`) to encode large delta/gate
 * values, and a 5-byte note-on encoding with control-byte flags.
 */

/**
 * A note-on event parsed from a SEQ file.
 * @typedef {Object} SeqNoteOnEvent
 * @property {number} absTime - Absolute time in ticks from file start
 * @property {number} ch      - MIDI channel (0–15)
 * @property {'on'}   type    - Event type
 * @property {number} note    - MIDI note number (0–127)
 * @property {number} vel     - Velocity (0–127)
 * @property {number} gate    - Note duration in ticks
 */

/**
 * A program change event parsed from a SEQ file.
 * @typedef {Object} SeqProgramChangeEvent
 * @property {number} absTime - Absolute time in ticks from file start
 * @property {number} ch      - MIDI channel (0–15)
 * @property {'pc'}   type    - Event type
 * @property {number} prog    - Program number (0–127)
 */

/**
 * Any event returned by {@link parseSEQ}.
 * @typedef {SeqNoteOnEvent|SeqProgramChangeEvent} SeqEvent
 */

/**
 * Result of parsing a Saturn SEQ bank file.
 * @typedef {Object} ParseSEQResult
 * @property {number}     resolution - Ticks per quarter note (typically 480)
 * @property {number}     bpm        - Tempo from first tempo event (default 120)
 * @property {SeqEvent[]} events     - All parsed events
 */

/**
 * Options for {@link buildSEQ}. Uses the same {@link Pattern} type defined in midi_io.js.
 * @typedef {Object} BuildSEQOptions
 * @property {Pattern[]}  patterns     - Array of pattern objects
 * @property {number[]}   song         - Ordered pattern indices defining playback order
 * @property {number}     bpm          - Tempo in beats per minute
 * @property {number}     stepsPerBeat - Grid resolution (e.g. 4 = sixteenth notes)
 * @property {number}     numChannels  - Number of tracker channels to export
 */

/**
 * Parse a Saturn SEQ bank file into an event list.
 *
 * Decodes the bank header, SEQ header, tempo events, and the full event
 * stream including all extend prefix bytes. Bank-select CC#32 events are
 * filtered out (internal to the format).
 *
 * @param {ArrayBuffer} buf - Raw SEQ file bytes
 * @returns {ParseSEQResult}
 *
 * @example
 * const seq = parseSEQ(arrayBuffer);
 * console.log(seq.bpm);            // 120
 * console.log(seq.events.length);  // number of events
 */
function parseSEQ(buf) {
    const d = new DataView(buf);
    const u8 = new Uint8Array(buf);
    let pos = 0;

    function r8() { return u8[pos++]; }
    function r16() { const v = d.getUint16(pos); pos += 2; return v; }
    function r32() { const v = d.getUint32(pos); pos += 4; return v; }

    // Bank header
    const numSongs = r16();
    const songPtr = r32();
    pos = songPtr;

    // SEQ header
    const resolution = r16();
    const numTempoEvents = r16();
    const dataOffset = r16();
    const tempoLoopOffset = r16();

    // Tempo events
    let bpm = 120;
    for (let i = 0; i < numTempoEvents; i++) {
        const stepTime = r32();
        const mspb = r32();
        if (i === 0 && mspb > 0) bpm = Math.round(60000000 / mspb);
    }

    // Jump to data section (relative to SEQ header start)
    pos = songPtr + dataOffset;

    // Parse event stream
    const events = [];
    let deltaPending = 0;
    let gatePending = 0;
    let absTick = 0;

    while (pos < u8.length) {
        const b = r8();

        // End of track
        if (b === 0x83) break;

        // Extend events
        if (b === 0x8F) { deltaPending += 0x1000; continue; }
        if (b === 0x8E) { deltaPending += 0x0800; continue; }
        if (b === 0x8D) { deltaPending += 0x0200; continue; }
        if (b === 0x8C) { deltaPending += 0x0100; continue; }
        if (b === 0x8B) { gatePending += 0x2000; continue; }
        if (b === 0x8A) { gatePending += 0x1000; continue; }
        if (b === 0x89) { gatePending += 0x0800; continue; }
        if (b === 0x88) { gatePending += 0x0200; continue; }

        const type = b & 0xF0;

        if (type < 0x80) {
            // Note-on event: control byte is b
            const ch = b & 0x0F;
            const note = r8();
            const vel = r8();
            let gate = r8();
            let delta = r8();

            if (b & 0x20) delta += 256;
            if (b & 0x40) gate += 256;

            delta += deltaPending;
            gate += gatePending;
            deltaPending = 0;
            gatePending = 0;

            absTick += delta;
            events.push({ absTime: absTick, ch, type: 'on', note, vel, gate });
        } else if (type === 0xC0) {
            // Program change
            const ch = b & 0x0F;
            const prog = r8();
            let delta = r8();
            delta += deltaPending;
            deltaPending = 0;
            gatePending = 0;
            absTick += delta;
            events.push({ absTime: absTick, ch, type: 'pc', prog });
        } else if (type === 0xB0) {
            // Control change
            const ch = b & 0x0F;
            const cc = r8();
            const val = r8();
            let delta = r8();
            delta += deltaPending;
            deltaPending = 0;
            gatePending = 0;
            absTick += delta;
        } else if (type === 0xA0) {
            // Poly pressure
            r8(); r8();
            let delta = r8();
            delta += deltaPending;
            deltaPending = 0;
            gatePending = 0;
            absTick += delta;
        } else if (type === 0xE0) {
            // Pitch bend (MSB only in SEQ)
            r8();
            let delta = r8();
            delta += deltaPending;
            deltaPending = 0;
            gatePending = 0;
            absTick += delta;
        } else if (type === 0xD0) {
            // Channel pressure
            r8();
            let delta = r8();
            delta += deltaPending;
            deltaPending = 0;
            gatePending = 0;
            absTick += delta;
        }
    }

    return { resolution, bpm, events };
}

/**
 * Build a Saturn SEQ bank file from tracker pattern data.
 *
 * Produces a complete SEQ binary with bank header, SEQ header, two tempo
 * events, bank-select CC#32 on all 16 MIDI channels, the encoded event
 * stream, and an `0x83` end-of-track marker. Uses a fixed resolution of
 * 480 ticks per quarter note.
 *
 * @param {BuildSEQOptions} options
 * @returns {Uint8Array} Complete `.seq` file ready to save
 *
 * @example
 * const seq = buildSEQ({
 *   patterns: state.patterns,
 *   song: [0, 1, 0],
 *   bpm: 120,
 *   stepsPerBeat: 4,
 *   numChannels: 8,
 * });
 * // seq is a Uint8Array containing a valid .seq file
 */
function buildSEQ({ patterns, song, bpm, stepsPerBeat, numChannels }) {
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
        events.push({
            absTick: 0,
            status: 0xC0 | parseInt(ch),
            data1: inst,
            data2: 0,
            gateTicks: 0,
        });
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
                        const next = pat.channels[ch].rows[r];
                        if (next.note !== null) { gateSteps = r - row; break; }
                    }
                    const gateTicks = Math.round(gateSteps * ticksPerStep);

                    events.push({
                        absTick: absTick,
                        status: 0x90 | ch,
                        data1: cell.note,
                        data2: cell.vol !== null ? cell.vol : 100,
                        gateTicks: gateTicks,
                    });
                }
            }
        }
        stepOffset += pat.length;
    }

    events.sort((a, b) => {
        if (a.absTick !== b.absTick) return a.absTick - b.absTick;
        const aIsNoteOn = (a.status & 0xF0) === 0x90;
        const bIsNoteOn = (b.status & 0xF0) === 0x90;
        if (!aIsNoteOn && bIsNoteOn) return -1;
        if (aIsNoteOn && !bIsNoteOn) return 1;
        return 0;
    });

    let firstMusicalTick = 0;
    for (const ev of events) {
        if ((ev.status & 0xF0) === 0x90) { firstMusicalTick = ev.absTick; break; }
    }
    const totalTicks = Math.round(stepOffset * ticksPerStep);

    const buf = [];
    function w8(v) { buf.push(v & 0xFF); }
    function w16(v) { buf.push((v >> 8) & 0xFF, v & 0xFF); }
    function w32(v) { buf.push((v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF); }

    // Bank header
    w16(1);
    w32(6);

    // SEQ header
    const tempoCount = 2;
    const dataOffset = 8 + tempoCount * 8;
    w16(resolution);
    w16(tempoCount);
    w16(dataOffset);
    w16(8 + 8);

    // Tempo events
    w32(firstMusicalTick);
    w32(mspb);
    w32(totalTicks - firstMusicalTick);
    w32(mspb);

    // Bank select CC#32 = 1 on all 16 channels
    for (let ch = 0; ch < 16; ch++) {
        w8(0xB0 | ch); w8(0x20); w8(1); w8(0x00);
    }

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

            w8(ctl);
            w8(ev.data1);
            w8(ev.data2);
            w8(gate & 0xFF);
            w8(delta & 0xFF);
        } else {
            while (delta >= 256) { w8(0x8C); delta -= 256; }
            w8(ev.status);
            if (evType === 0xB0 || evType === 0xA0) {
                w8(ev.data1); w8(ev.data2);
            } else if (evType === 0xE0) {
                w8(ev.data2);
            } else {
                w8(ev.data1);
            }
            w8(delta & 0xFF);
        }
    }

    w8(0x83); // end of track
    return new Uint8Array(buf);
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { parseSEQ, buildSEQ };
}
