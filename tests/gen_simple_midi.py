#!/usr/bin/env python3
"""
gen_simple_midi.py — Generate a minimal MIDI for testing with existing TON files.

Uses only program 3 (voice 3 in mechs.ton: full key range, base=54).
Single channel, simple melody. If this plays, the SEQ pipeline works.
"""
import mido
import sys

TICKS = 480
BPM = 100

def main():
    outfile = sys.argv[1] if len(sys.argv) > 1 else 'simple_test.mid'
    mid = mido.MidiFile(type=0, ticks_per_beat=TICKS)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(BPM), time=0))

    # Use program 3 (voice 3 in mechs.ton: keys 0-127, base_note=54)
    track.append(mido.Message('program_change', channel=0, program=3, time=0))

    # Simple ascending scale: C4-C5
    notes = [60, 62, 64, 65, 67, 69, 71, 72, 72, 71, 69, 67, 65, 64, 62, 60]
    dur = TICKS  # quarter note each

    for n in notes:
        track.append(mido.Message('note_on', channel=0, note=n, velocity=100, time=0))
        track.append(mido.Message('note_off', channel=0, note=n, velocity=0, time=dur))

    track.append(mido.MetaMessage('end_of_track', time=TICKS))
    mid.save(outfile)

    duration = len(notes) * 60 / BPM
    print(f"[midi] {outfile}: {len(notes)} notes, {duration:.1f}s, program 3, ch 0")

if __name__ == '__main__':
    main()
