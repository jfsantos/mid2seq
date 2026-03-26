/**
 * ton_io.js — Saturn TON file import/export for FM patch editors.
 *
 * Provides two main functions:
 *   exportTon(patches, generateWaveformFn) → Uint8Array
 *   importTon(arrayBuffer) → { patches, pcmChunks }
 *
 * Compatible with saturn_kit.py TON format.
 * Used by both the web FM editor (fm_editor.py) and the VST UI (ui.js).
 */

const TonIO = (function () {
  'use strict';

  const SAMPLE_RATE = 44100; // SCSP playback rate
  const WAVE_LEN = 1024;    // FM waveforms must be 1024 samples

  /** MIDI note → frequency in Hz */
  function midiToFreq(note) {
    return 440 * Math.pow(2, (note - 69) / 12);
  }

  /** Cycle length for a given base note at 44100 Hz (matches saturn_kit.py) */
  function cycleLengthForNote(baseNote) {
    return Math.round(SAMPLE_RATE / midiToFreq(baseNote));
  }

  /** Convert Float32Array [-1,1] → big-endian int16 Uint8Array */
  function floatToBE16(samples, amplitude) {
    if (amplitude === undefined) amplitude = 0.9;
    const pcm = new Uint8Array(samples.length * 2);
    for (let i = 0; i < samples.length; i++) {
      let val = Math.max(-32768, Math.min(32767, Math.round(samples[i] * amplitude * 32767)));
      if (val < 0) val += 65536;
      pcm[i * 2]     = (val >> 8) & 0xFF;
      pcm[i * 2 + 1] = val & 0xFF;
    }
    return pcm;
  }

  /**
   * Build a 32-byte TON layer entry.
   */
  function makeLayer(opts) {
    const layer = new Uint8Array(0x20);
    layer[0x00] = 0;    // start_note
    layer[0x01] = 127;  // end_note

    // byte 2: FMCB at bit 5
    if (opts.fmcb) layer[0x02] |= (1 << 5);

    // byte 3: LPCTL | SA high bits
    const lpctl = opts.loop ? 1 : 0;
    layer[0x03] = (lpctl << 5) | ((opts.saOffset >> 16) & 0xF);

    // bytes 4-5: SA low (big-endian)
    const saLow = opts.saOffset & 0xFFFF;
    layer[0x04] = (saLow >> 8) & 0xFF;
    layer[0x05] = saLow & 0xFF;

    // bytes 6-7: LSA (big-endian)
    layer[0x06] = (opts.lsa >> 8) & 0xFF;
    layer[0x07] = opts.lsa & 0xFF;

    // bytes 8-9: LEA (big-endian)
    layer[0x08] = (opts.lea >> 8) & 0xFF;
    layer[0x09] = opts.lea & 0xFF;

    // bytes A-B: D2R/D1R/AR
    layer[0x0A] = ((opts.d2r & 0x1F) << 3) | ((opts.d1r >> 2) & 0x7);
    layer[0x0B] = ((opts.d1r & 0x3) << 6) | (opts.ar & 0x1F);

    // bytes C-D: KRS/DL/RR
    layer[0x0C] = ((opts.dl >> 3) & 0x3);
    layer[0x0D] = ((opts.dl & 0x7) << 5) | (opts.rr & 0x1F);

    // byte F: TL
    layer[0x0F] = opts.tl & 0xFF;

    // byte 10: MDL (high nibble)
    layer[0x10] = (opts.mdl & 0xF) << 4;

    // byte 17: ISEL=0, IMXL=7
    layer[0x17] = 7;

    // byte 18: DISDL | DIPAN
    layer[0x18] = (opts.disdl & 0x7) << 5;

    // byte 19: base_note
    layer[0x19] = opts.baseNote & 0x7F;

    // byte 1A: fine_tune
    layer[0x1A] = 0;

    // byte 1B: FM generator/layer links
    if (opts.fmLayer >= 0) {
      layer[0x1B] = (1 << 7) | (opts.fmLayer & 0x7F);
    }

    return layer;
  }

  /**
   * Export patches to a TON binary.
   *
   * @param {Array} patches - Array of patch objects:
   *   { name, operators: [{ freq_ratio, level, ar, d1r, dl, d2r, rr,
   *     mdl, mod_source, feedback, is_carrier, waveform, loop_mode,
   *     loop_start, loop_end }] }
   * @param {Function} generateWaveformFn - function(typeIndex, numSamples) → Float32Array
   * @param {Object} [customWaves] - map of "patchIdx:opIdx" → Float32Array for custom waveforms
   * @returns {Uint8Array} TON file bytes
   */
  function exportTon(patches, generateWaveformFn, customWaves) {
    const voices = [];
    const pcmChunks = [];
    let pcmOffset = 0;

    // Waveform cache: key → { offset, length }
    const waveCache = {};

    function getWavePcm(waveType, patchIdx, opIdx) {
      // Check for custom waveform
      const customKey = patchIdx + ':' + opIdx;
      if (customWaves && customWaves[customKey]) {
        const samples = customWaves[customKey];
        const pcm = floatToBE16(samples);
        const off = pcmOffset;
        pcmChunks.push(pcm);
        pcmOffset += pcm.length;
        return { offset: off, length: samples.length };
      }

      // Named waveform — deduplicate
      const cacheKey = 'builtin:' + waveType;
      if (waveCache[cacheKey]) return waveCache[cacheKey];

      const samples = generateWaveformFn(waveType, WAVE_LEN);
      const pcm = floatToBE16(samples);
      const off = pcmOffset;
      pcmChunks.push(pcm);
      pcmOffset += pcm.length;
      const entry = { offset: off, length: samples.length };
      waveCache[cacheKey] = entry;
      return entry;
    }

    for (let pi = 0; pi < patches.length; pi++) {
      const patch = patches[pi];
      const ops = patch.operators;
      if (!ops || ops.length === 0) continue;

      const layersData = [];

      for (let oi = 0; oi < ops.length; oi++) {
        const op = ops[oi];

        // Resolve waveform type index
        let waveType = 0;
        if (typeof op.waveform === 'number') {
          waveType = op.waveform;
        } else if (typeof op.waveform === 'string') {
          const NAMES = ['sine','sawtooth','square','triangle','organ','brass','strings','piano','flute','bass'];
          const idx = NAMES.indexOf(op.waveform.toLowerCase());
          if (idx >= 0) waveType = idx;
        }

        const wave = getWavePcm(waveType, pi, oi);

        // Loop points
        const lsa = op.loop_start || 0;
        let lea = op.loop_end;
        if (lea === undefined || lea === null || lea < 0) lea = wave.length;
        const loop = (op.loop_mode !== undefined ? op.loop_mode : 1) !== 0;

        // Base note from freq ratio
        let baseNote = 69;
        if (op.freq_ratio && op.freq_ratio > 0) {
          const ratioSemitones = Math.round(12 * Math.log2(op.freq_ratio));
          baseNote = Math.max(0, Math.min(127, 69 - ratioSemitones));
        }

        // TL from level
        const tl = Math.max(0, Math.min(255, Math.round((1.0 - (op.level !== undefined ? op.level : 0.8)) * 128)));

        // Modulator layer index
        const fmLayer = (op.mod_source !== undefined && op.mod_source >= 0) ? op.mod_source : -1;

        const layer = makeLayer({
          saOffset: wave.offset,
          lsa: lsa,
          lea: lea,
          loop: loop,
          baseNote: baseNote,
          ar: op.ar !== undefined ? op.ar : 31,
          d1r: op.d1r || 0,
          dl: op.dl || 0,
          d2r: op.d2r || 0,
          rr: op.rr !== undefined ? op.rr : 14,
          tl: tl,
          disdl: op.is_carrier ? 7 : 0,
          mdl: op.mdl || 0,
          fmcb: op.is_carrier,
          fmLayer: fmLayer,
        });

        layersData.push(layer);
      }

      // Voice header (4 bytes)
      const voiceHdr = new Uint8Array(4);
      voiceHdr[0] = 2; // bend_range = 2
      voiceHdr[2] = ops.length - 1; // nlayers - 1

      // Concatenate header + layers
      const voiceData = new Uint8Array(4 + layersData.length * 0x20);
      voiceData.set(voiceHdr, 0);
      for (let li = 0; li < layersData.length; li++) {
        voiceData.set(layersData[li], 4 + li * 0x20);
      }
      voices.push(voiceData);
    }

    // Fixed tables
    // VL table (from mechs.ton — known good)
    const vl = new Uint8Array([25, 16, 54, 9, 49, 102, 19, 93, 122, 43]);
    // Mixer: channels 0,2 → left, 1,3 → right
    const mixer = new Uint8Array(0x12);
    mixer[0] = (7 << 5) | 0x1F; // EFREG0 → left, full level
    mixer[1] = (7 << 5) | 0x0F; // EFREG1 → right, full level
    const peg = new Uint8Array(0x0A);
    const plfo = new Uint8Array(0x04);

    // Calculate offsets
    const headerSize = 8 + voices.length * 2;
    const mixerOff = headerSize;
    const vlOff = mixerOff + mixer.length;
    const pegOff = vlOff + vl.length;
    const plfoOff = pegOff + peg.length;

    let voiceOff = plfoOff + plfo.length;
    const voiceOffsets = [];
    for (let i = 0; i < voices.length; i++) {
      voiceOffsets.push(voiceOff);
      voiceOff += voices[i].length;
    }

    const pcmBase = voiceOff;

    // Adjust SA in each voice layer to include pcmBase
    for (let i = 0; i < voices.length; i++) {
      const va = voices[i];
      const nlayers = va[2] + 1; // nlayers stored as (n-1)
      for (let li = 0; li < nlayers; li++) {
        const loff = 4 + li * 0x20;
        const oldSa = ((va[loff + 0x03] & 0xF) << 16) |
                       (va[loff + 0x04] << 8) |
                        va[loff + 0x05];
        const newSa = pcmBase + oldSa;
        va[loff + 0x03] = (va[loff + 0x03] & 0xF0) | ((newSa >> 16) & 0xF);
        va[loff + 0x04] = (newSa >> 8) & 0xFF;
        va[loff + 0x05] = newSa & 0xFF;
      }
    }

    // Build header (big-endian uint16 offsets)
    const hdr = new Uint8Array(headerSize);
    const hdrView = new DataView(hdr.buffer);
    hdrView.setUint16(0, mixerOff);
    hdrView.setUint16(2, vlOff);
    hdrView.setUint16(4, pegOff);
    hdrView.setUint16(6, plfoOff);
    for (let i = 0; i < voiceOffsets.length; i++) {
      hdrView.setUint16(8 + i * 2, voiceOffsets[i]);
    }

    // Calculate total size
    let totalPcm = 0;
    for (let i = 0; i < pcmChunks.length; i++) totalPcm += pcmChunks[i].length;
    const totalSize = pcmBase + totalPcm;

    // Assemble final TON
    const ton = new Uint8Array(totalSize);
    let pos = 0;
    ton.set(hdr, pos); pos += hdr.length;
    ton.set(mixer, pos); pos += mixer.length;
    ton.set(vl, pos); pos += vl.length;
    ton.set(peg, pos); pos += peg.length;
    ton.set(plfo, pos); pos += plfo.length;
    for (let i = 0; i < voices.length; i++) {
      ton.set(voices[i], pos);
      pos += voices[i].length;
    }
    for (let i = 0; i < pcmChunks.length; i++) {
      ton.set(pcmChunks[i], pos);
      pos += pcmChunks[i].length;
    }

    return ton;
  }

  /**
   * Import a TON file and return patches with embedded PCM data.
   *
   * @param {ArrayBuffer} buffer - TON file contents
   * @returns {Object} { patches: [{ name, operators: [{ freq_ratio, level, ar, d1r, dl, d2r, rr,
   *   mdl, mod_source, is_carrier, loop_mode, loop_start, loop_end, pcm: Float32Array }] }] }
   */
  function importTon(buffer) {
    const data = new Uint8Array(buffer);
    const view = new DataView(buffer);

    const offMix = view.getUint16(0);
    const nvoices = (offMix - 8) / 2;

    const patches = [];

    for (let vi = 0; vi < nvoices; vi++) {
      const voff = view.getUint16(8 + vi * 2);
      const nlayers = (data[voff + 2] << 24 >> 24) + 1; // signed byte + 1

      const operators = [];

      for (let li = 0; li < nlayers; li++) {
        const loff = voff + 4 + li * 0x20;

        // Parse layer fields (same layout as tonview.py)
        const lpctl = (data[loff + 0x03] >> 5) & 3;
        const pcm8b = (data[loff + 0x03] >> 4) & 1;
        const saAddr = ((data[loff + 0x03] & 0xF) << 16) | view.getUint16(loff + 0x04);
        const lsa = view.getUint16(loff + 0x06);
        const lea = view.getUint16(loff + 0x08);

        const d2r = data[loff + 0x0A] >> 3;
        const d1r = ((data[loff + 0x0A] & 0x7) << 2) | (data[loff + 0x0B] >> 6);
        const ar = data[loff + 0x0B] & 0x1F;
        const dl = ((data[loff + 0x0C] & 0x3) << 3) | (data[loff + 0x0D] >> 5);
        const rr = data[loff + 0x0D] & 0x1F;
        const tl = data[loff + 0x0F];

        const mdl = (data[loff + 0x10] >> 4) & 0xF;
        const mdxsl = ((data[loff + 0x10] & 0xF) << 2) | (data[loff + 0x11] >> 6);
        const mdysl = data[loff + 0x11] & 0x3F;

        const disdl = data[loff + 0x18] >> 5;
        const baseNote = data[loff + 0x19];

        // FM layer link
        const fmByte = data[loff + 0x1B];
        const hasFmLink = (fmByte & 0x80) !== 0;
        const fmLayer = fmByte & 0x7F;

        // Reverse-map: base_note → freq_ratio
        // base_note = 69 - round(12 * log2(ratio))
        // → ratio = 2^((69 - base_note) / 12)
        const freqRatio = Math.pow(2, (69 - baseNote) / 12);
        // Round to nice values
        const roundedRatio = Math.round(freqRatio * 1000) / 1000;

        // Reverse-map: TL → level
        // tl = (1 - level) * 128 → level = 1 - tl/128
        const level = Math.max(0, Math.min(1, parseFloat((1.0 - tl / 128).toFixed(3))));

        // Is carrier?
        const isCarrier = disdl > 0;

        // Mod source from FM layer link
        const modSource = hasFmLink ? fmLayer : -1;

        // Detect self-feedback: MDXSL=32 or MDYSL=32
        const hasFeedback = (mdxsl === 32 || mdysl === 32);
        const feedback = hasFeedback ? 0.3 : 0; // default feedback level

        // Extract PCM samples (big-endian int16 → Float32Array)
        const sampleSize = pcm8b ? 1 : 2;
        const numSamples = lea > 0 ? lea : 0;
        const pcm = new Float32Array(numSamples);
        for (let si = 0; si < numSamples; si++) {
          const addr = saAddr + si * sampleSize;
          if (addr + sampleSize > data.length) break;
          let val;
          if (pcm8b) {
            val = (data[addr] << 24 >> 24) / 128; // signed byte → float
          } else {
            // Big-endian signed int16 → float
            let raw = (data[addr] << 8) | data[addr + 1];
            if (raw >= 32768) raw -= 65536;
            val = raw / 32768;
          }
          pcm[si] = val;
        }

        // Store raw SCSP slot register words for direct playback (bypasses programSlot).
        // These match the TON layer layout which maps directly to SCSP registers.
        // The Saturn driver copies these directly — no recomputation.
        var rawRegs = {
          d0: (lpctl << 5) | ((saAddr >> 16) & 0xF), // LPCTL + SA high
          sa: saAddr & 0xFFFF,                         // SA low
          lsa: lsa,
          lea: lea,
          d4: (data[loff + 0x0A] << 8) | data[loff + 0x0B], // D2R|D1R|AR
          d5: (data[loff + 0x0C] << 8) | data[loff + 0x0D], // KRS|DL|RR
          tl: tl,
          d7: (data[loff + 0x10] << 8) | data[loff + 0x11], // MDL|MDXSL|MDYSL
          d8: (data[loff + 0x12] << 8) | data[loff + 0x13], // OCT|FNS
          dB: (data[loff + 0x18] << 8) | data[loff + 0x19], // DISDL|DIPAN + base_note
          baseNote: baseNote,
        };

        operators.push({
          freq_ratio: roundedRatio,
          level: level,
          ar: ar,
          d1r: d1r,
          dl: dl,
          d2r: d2r,
          rr: rr,
          mdl: mdl,
          mod_source: modSource,
          feedback: feedback,
          is_carrier: isCarrier,
          loop_mode: lpctl,
          loop_start: lsa,
          loop_end: lea,
          pcm8b: pcm8b ? true : false,
          pcm: pcm,
          rawRegs: rawRegs, // raw SCSP register data for direct slot programming
        });
      }

      patches.push({
        name: 'Voice ' + (vi + 1),
        operators: operators,
      });
    }

    return { patches: patches };
  }

  /**
   * Extract a single voice from a TON file by program number.
   *
   * @param {ArrayBuffer} buffer - TON file contents
   * @param {number} programNumber - voice index to extract
   * @returns {Object|null} patch object or null if not found
   */
  function extractVoice(buffer, programNumber) {
    var result = importTon(buffer);
    if (programNumber < result.patches.length) {
      return result.patches[programNumber];
    }
    return null;
  }

  /**
   * Merge a single patch into an existing TON file at a specific program slot.
   * Reads the existing TON, replaces the voice at programNumber, rebuilds.
   * Preserves PCM data from all other voices.
   *
   * @param {ArrayBuffer} existingBuffer - existing TON file (or null for new kit)
   * @param {number} programNumber - voice slot to replace (0-based)
   * @param {Object} newPatch - patch to insert: { name, operators: [...] }
   * @param {Function} generateWaveformFn - waveform generator for new patch
   * @param {Object} [newCustomWaves] - custom waves for the new patch (keyed by opIdx)
   * @returns {Uint8Array} new TON file bytes
   */
  function mergeTon(existingBuffer, programNumber, newPatch, generateWaveformFn, newCustomWaves) {
    var patches;
    var existingPcm = {}; // "patchIdx:opIdx" → Float32Array

    if (existingBuffer && existingBuffer.byteLength > 0) {
      var existing = importTon(existingBuffer);
      patches = existing.patches;

      // Collect PCM from all existing voices (except the one being replaced)
      for (var pi = 0; pi < patches.length; pi++) {
        if (pi === programNumber) continue;
        for (var oi = 0; oi < patches[pi].operators.length; oi++) {
          var pcm = patches[pi].operators[oi].pcm;
          if (pcm && pcm.length > 0) {
            existingPcm[pi + ':' + oi] = pcm;
          }
        }
      }
    } else {
      patches = [];
    }

    // Pad with empty voices if needed
    while (patches.length <= programNumber) {
      patches.push({
        name: 'Empty',
        operators: [{
          freq_ratio: 1, level: 0, ar: 31, d1r: 0, dl: 0, d2r: 0, rr: 14,
          mdl: 0, mod_source: -1, feedback: 0, is_carrier: true,
          waveform: 0, loop_mode: 1, loop_start: 0, loop_end: WAVE_LEN,
        }],
      });
    }

    // Replace the target slot
    patches[programNumber] = newPatch;

    // Add custom waves for the new patch
    if (newCustomWaves) {
      for (var key in newCustomWaves) {
        existingPcm[programNumber + ':' + key] = newCustomWaves[key];
      }
    }

    // Strip pcm from operator objects before export (exportTon doesn't expect it)
    for (var pi2 = 0; pi2 < patches.length; pi2++) {
      for (var oi2 = 0; oi2 < patches[pi2].operators.length; oi2++) {
        delete patches[pi2].operators[oi2].pcm;
      }
    }

    return exportTon(patches, generateWaveformFn, existingPcm);
  }

  return {
    exportTon: exportTon,
    importTon: importTon,
    mergeTon: mergeTon,
    extractVoice: extractVoice,
    WAVE_LEN: WAVE_LEN,
  };
})();

if (typeof module !== 'undefined' && module.exports) {
  module.exports = TonIO;
}
