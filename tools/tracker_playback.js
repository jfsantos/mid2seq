/**
 * @module tracker_playback
 * @description Step sequencer for the tracker. No DOM dependencies.
 * Calls the sound engine via the SoundEngine interface for note triggering.
 */

var TrackerPlayback = (function () {
    'use strict';

    // In Node.js, TrackerState must be required; in browser it's a global.
    var _TrackerState = (typeof TrackerState !== 'undefined') ? TrackerState : require('./tracker_state.js');

    /**
     * Create a playback instance.
     *
     * @param {Object} state - TrackerState state object (read for patterns, song, bpm, stepsPerBeat, instruments)
     * @param {Object} engine - SoundEngine implementation (triggerNote, releaseChannel, releaseAll, getSampleRate)
     * @returns {Object} Playback object
     */
    function create(state, engine) {
        var pb = {
            playing: false,
            currentRow: 0,
            currentSongSlot: 0,
            samplePos: 0,
            samplesPerStep: 0,
            pendingOffs: [],

            /** Callback fired when the current row changes during playback. Set by UI. */
            onRowChange: null,
            /** Callback fired when playback stops. Set by UI. */
            onStop: null,

            /**
             * Start playback from a given position.
             * @param {number} row - Starting row
             * @param {number} songSlot - Starting song slot
             */
            start: function (row, songSlot) {
                this.playing = true;
                this.currentRow = row;
                this.currentSongSlot = songSlot;
                this.samplePos = 0;
                this.pendingOffs = [];
                this.updateTempo();
            },

            /**
             * Stop playback and release all notes.
             */
            stop: function () {
                this.playing = false;
                this.pendingOffs = [];
                engine.releaseAll();
                if (this.onStop) this.onStop();
            },

            /**
             * Recalculate samples-per-step from current BPM and stepsPerBeat.
             */
            updateTempo: function () {
                var sampleRate = engine.getSampleRate();
                this.samplesPerStep = Math.round(sampleRate * 60 / state.bpm / state.stepsPerBeat);
            },

            /**
             * Process an audio block. Called from the engine's audio callback.
             * Advances the sequencer and triggers notes at step boundaries.
             * @param {number} numSamples - Number of samples in this block
             */
            processBlock: function (numSamples) {
                var remaining = numSamples;
                while (remaining > 0) {
                    var untilNext = this.samplesPerStep - this.samplePos;
                    if (untilNext <= 0) {
                        var pat = state.patterns[state.song[this.currentSongSlot]];
                        this.triggerRow(this.currentRow, pat);
                        this.currentRow++;
                        if (this.currentRow >= pat.length) {
                            this.currentRow = 0;
                            this.currentSongSlot++;
                            if (this.currentSongSlot >= state.song.length) {
                                this.currentSongSlot = 0; // loop song
                            }
                        }
                        this.samplePos = 0;
                        if (this.onRowChange) this.onRowChange(this.currentRow, this.currentSongSlot);
                        continue;
                    }
                    var advance = Math.min(remaining, untilNext);
                    this.samplePos += advance;
                    remaining -= advance;
                }
            },

            /**
             * Trigger notes for a single pattern row.
             * @param {number} row
             * @param {Object} pat - Pattern object
             */
            triggerRow: function (row, pat) {
                var NUM_CHANNELS = _TrackerState.NUM_CHANNELS;
                // Process pending note-offs that expire at this position
                var curPos = this.currentSongSlot * 10000 + row;
                this.pendingOffs = this.pendingOffs.filter(function (off) {
                    if (off.pos <= curPos) {
                        engine.releaseChannel(off.ch);
                        return false;
                    }
                    return true;
                });

                for (var ch = 0; ch < NUM_CHANNELS; ch++) {
                    if (!_TrackerState.isChannelAudible(ch)) continue;
                    var cell = pat.channels[ch].rows[row];
                    if (cell.note === -1) {
                        engine.releaseChannel(ch);
                    } else if (cell.note !== null) {
                        var instIdx = cell.inst !== null ? cell.inst : pat.channels[ch].defaultInst;
                        engine.releaseChannel(ch); // release previous note first
                        var inst = state.instruments[instIdx];
                        engine.triggerNote(ch, cell.note, instIdx, inst);

                        // Schedule note-off: find next note on this channel or end of pattern
                        var gateRows = pat.length - row;
                        for (var r = row + 1; r < pat.length; r++) {
                            if (pat.channels[ch].rows[r].note !== null) {
                                gateRows = r - row;
                                break;
                            }
                        }
                        var offPos = this.currentSongSlot * 10000 + row + gateRows;
                        this.pendingOffs.push({ pos: offPos, ch: ch });
                    }
                }
            }
        };

        return pb;
    }

    var api = { create: create };

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }

    return api;
})();
