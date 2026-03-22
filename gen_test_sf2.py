#!/usr/bin/env python3
"""
gen_test_sf2.py — Generate a small test SoundFont with basic waveforms.

Creates a GM-compatible SF2 with a few instruments suitable for testing
Saturn SEQ playback:
  Program 0: Piano (sine with attack/decay)
  Program 1: Strings (sawtooth-ish with slow attack)
  Program 2: Bass (low sine with fast attack)
  Program 3: Organ (additive harmonics, sustained)
"""

import struct
import math
import sys

SAMPLE_RATE = 22050  # Keep samples small for Saturn's 512KB RAM


def generate_samples():
    """Generate waveform data for each instrument."""
    instruments = {}

    # Piano: sine with harmonics, decaying
    n = int(SAMPLE_RATE * 0.8)
    loop_start = int(SAMPLE_RATE * 0.3)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = max(0, 1.0 - t * 0.8)
        val = 0.6 * math.sin(2 * math.pi * 440 * t)
        val += 0.25 * math.sin(2 * math.pi * 880 * t) * max(0, 1 - t * 2)
        val += 0.1 * math.sin(2 * math.pi * 1320 * t) * max(0, 1 - t * 4)
        samples.append(int(env * val * 32000))
    instruments['piano'] = {
        'samples': samples, 'root': 69, 'rate': SAMPLE_RATE,
        'loop_start': loop_start, 'loop_end': n - 1,
        'loop': True, 'attack': -7000, 'decay': -4000,
        'sustain': 300, 'release': -4000
    }

    # Strings: sawtooth approximation, slow attack
    n = int(SAMPLE_RATE * 0.5)
    loop_start = int(SAMPLE_RATE * 0.1)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        val = 0
        for h in range(1, 8):
            val += ((-1) ** (h + 1)) * math.sin(2 * math.pi * 440 * h * t) / h
        val *= 0.4
        samples.append(int(val * 32000))
    instruments['strings'] = {
        'samples': samples, 'root': 69, 'rate': SAMPLE_RATE,
        'loop_start': loop_start, 'loop_end': n - 1,
        'loop': True, 'attack': -3000, 'decay': -2000,
        'sustain': 100, 'release': -3000
    }

    # Bass: low sine
    n = int(SAMPLE_RATE * 0.5)
    loop_start = int(SAMPLE_RATE * 0.05)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        val = 0.7 * math.sin(2 * math.pi * 110 * t)
        val += 0.2 * math.sin(2 * math.pi * 220 * t)
        samples.append(int(val * 32000))
    instruments['bass'] = {
        'samples': samples, 'root': 45, 'rate': SAMPLE_RATE,
        'loop_start': loop_start, 'loop_end': n - 1,
        'loop': True, 'attack': -8000, 'decay': -3000,
        'sustain': 200, 'release': -4500
    }

    # Organ: sustained harmonics
    n = int(SAMPLE_RATE * 0.3)
    loop_start = int(SAMPLE_RATE * 0.05)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        val = 0.4 * math.sin(2 * math.pi * 440 * t)
        val += 0.3 * math.sin(2 * math.pi * 880 * t)
        val += 0.15 * math.sin(2 * math.pi * 1760 * t)
        val += 0.1 * math.sin(2 * math.pi * 2640 * t)
        samples.append(int(val * 32000))
    instruments['organ'] = {
        'samples': samples, 'root': 69, 'rate': SAMPLE_RATE,
        'loop_start': loop_start, 'loop_end': n - 1,
        'loop': True, 'attack': -9000, 'decay': -1000,
        'sustain': 0, 'release': -5000
    }

    return instruments


def write_chunk(tag, data):
    padded = data + (b'\x00' if len(data) % 2 else b'')
    return tag.encode() + struct.pack('<I', len(data)) + padded


def write_list(list_type, *chunks):
    inner = b''.join(chunks)
    return write_chunk('LIST', list_type.encode() + inner)


def build_sf2(instruments: dict) -> bytes:
    # Order: piano=0, strings=1, bass=2, organ=3
    names_order = ['piano', 'strings', 'bass', 'organ']
    preset_names = ['Piano', 'Strings', 'Bass', 'Organ']

    # Build smpl chunk (all samples concatenated, 16-bit LE)
    smpl_data = bytearray()
    sample_infos = []  # (start, end, loop_start, loop_end, rate, root, name)
    for name in names_order:
        inst = instruments[name]
        start = len(smpl_data) // 2  # sample offset
        for s in inst['samples']:
            smpl_data += struct.pack('<h', max(-32768, min(32767, s)))
        end = len(smpl_data) // 2
        ls = start + inst['loop_start']
        le = start + inst['loop_end']
        # SF2 requires 46 zero samples after each sample
        smpl_data += b'\x00\x00' * 46
        sample_infos.append((start, end, ls, le, inst['rate'], inst['root'], name))

    # shdr
    shdr = bytearray()
    for start, end, ls, le, rate, root, name in sample_infos:
        padded_name = name.encode()[:20].ljust(20, b'\x00')
        shdr += padded_name + struct.pack('<IIIIIBbHH',
                                          start, end + 46, ls, le,
                                          rate, root, 0, 1, 0)
    # EOS terminal
    shdr += b'EOS\x00'.ljust(20, b'\x00') + struct.pack('<IIIIIBbHH', 0, 0, 0, 0, 0, 0, 0, 0, 0)

    # igen — one zone per instrument, each referencing its sample
    igen = bytearray()
    igen_offsets = []  # gen start index for each instrument
    for i, name in enumerate(names_order):
        inst = instruments[name]
        igen_offsets.append(len(igen) // 4)
        # Key range 0-127
        igen += struct.pack('<HH', 43, 0x7F00)  # keyRange lo=0 hi=127
        # Sample modes
        igen += struct.pack('<HH', 54, 1 if inst['loop'] else 0)
        # Envelope
        igen += struct.pack('<Hh', 34, int(inst['attack']))
        igen += struct.pack('<Hh', 36, int(inst['decay']))
        igen += struct.pack('<Hh', 37, int(inst['sustain']))
        igen += struct.pack('<Hh', 38, int(inst['release']))
        # Sample ID
        igen += struct.pack('<HH', 53, i)
    # Terminal gen
    igen_offsets.append(len(igen) // 4)

    # ibag — one bag per instrument zone
    ibag = bytearray()
    for idx in igen_offsets:
        ibag += struct.pack('<HH', idx, 0)

    # inst headers
    inst_data = bytearray()
    bag_idx = 0
    for i, pname in enumerate(preset_names):
        padded = pname.encode()[:20].ljust(20, b'\x00')
        inst_data += padded + struct.pack('<H', bag_idx)
        bag_idx += 1
    # EOI terminal
    inst_data += b'EOI\x00'.ljust(20, b'\x00') + struct.pack('<H', bag_idx)

    # Presets: program 0=piano, 1=strings, 2=bass, 3=organ
    pgen = bytearray()
    pgen_offsets = []
    for i in range(len(names_order)):
        pgen_offsets.append(len(pgen) // 4)
        pgen += struct.pack('<HH', 41, i)  # instrument index
    pgen_offsets.append(len(pgen) // 4)

    pbag = bytearray()
    for idx in pgen_offsets:
        pbag += struct.pack('<HH', idx, 0)

    phdr = bytearray()
    for i, pname in enumerate(preset_names):
        padded = pname.encode()[:20].ljust(20, b'\x00')
        phdr += padded + struct.pack('<HHH', i, 0, i)  # preset, bank, bag
        phdr += b'\x00' * 12  # library, genre, morphology
    # EOP terminal
    phdr += b'EOP\x00'.ljust(20, b'\x00') + struct.pack('<HHH', 0, 0, len(pbag) // 4)
    phdr += b'\x00' * 12

    # Assemble SF2
    sdta = write_list('sdta', write_chunk('smpl', bytes(smpl_data)))
    pdta = write_list('pdta',
                      write_chunk('phdr', bytes(phdr)),
                      write_chunk('pbag', bytes(pbag)),
                      write_chunk('pmod', b''),
                      write_chunk('pgen', bytes(pgen)),
                      write_chunk('inst', bytes(inst_data)),
                      write_chunk('ibag', bytes(ibag)),
                      write_chunk('imod', b''),
                      write_chunk('igen', bytes(igen)),
                      write_chunk('shdr', bytes(shdr)))
    info = write_list('INFO',
                      write_chunk('ifil', struct.pack('<HH', 2, 1)),
                      write_chunk('isng', b'EMU8000\x00'),
                      write_chunk('INAM', b'Saturn Test GM\x00'))

    sfbk = b'sfbk' + info + sdta + pdta
    riff = b'RIFF' + struct.pack('<I', len(sfbk)) + sfbk
    return riff


def main():
    outfile = sys.argv[1] if len(sys.argv) > 1 else 'test_gm.sf2'
    instruments = generate_samples()
    sf2_data = build_sf2(instruments)
    with open(outfile, 'wb') as f:
        f.write(sf2_data)

    total_samples = sum(len(instruments[n]['samples']) for n in instruments)
    print(f"[sf2] {outfile}: {len(sf2_data)} bytes, {len(instruments)} instruments, "
          f"{total_samples} samples ({total_samples * 2} bytes PCM)")
    print("  Program 0: Piano (sine + harmonics, decay)")
    print("  Program 1: Strings (sawtooth, slow attack)")
    print("  Program 2: Bass (low sine, punchy)")
    print("  Program 3: Organ (additive, sustained)")


if __name__ == '__main__':
    main()
