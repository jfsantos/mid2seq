#!/usr/bin/env python3
"""
gen_demo_midi.py — Generate a demo MIDI file using 4 instruments.

  Ch 0: Piano (prog 0)  — melody
  Ch 1: Strings (prog 1) — sustained chords
  Ch 2: Bass (prog 2)    — bass line
  Ch 3: Organ (prog 3)   — rhythmic accompaniment
"""

import mido
import sys

TICKS_PER_BEAT = 480
BPM = 120

def note(pitch, duration_beats, velocity=100):
    """Return (pitch, duration_in_ticks, velocity)."""
    return (pitch, int(duration_beats * TICKS_PER_BEAT), velocity)

def add_notes(track, channel, notes_list, start_beat=0):
    """Add a sequence of (pitch, dur_ticks, vel) to a track.
    Rests are represented by pitch=0."""
    current_tick = int(start_beat * TICKS_PER_BEAT)
    events = []
    for pitch, dur, vel in notes_list:
        if pitch > 0:
            events.append(('on', current_tick, pitch, vel))
            events.append(('off', current_tick + dur, pitch, 0))
        current_tick += dur

    # Sort by time, then off before on
    events.sort(key=lambda e: (e[1], 0 if e[0] == 'off' else 1))

    last_tick = 0
    for etype, tick, pitch, vel in events:
        delta = tick - last_tick
        if etype == 'on':
            track.append(mido.Message('note_on', channel=channel,
                                       note=pitch, velocity=vel, time=delta))
        else:
            track.append(mido.Message('note_off', channel=channel,
                                       note=pitch, velocity=0, time=delta))
        last_tick = tick

def add_chord(track, channel, pitches, start_beat, duration_beats, velocity=80):
    """Add a chord (multiple simultaneous notes)."""
    start_tick = int(start_beat * TICKS_PER_BEAT)
    dur_ticks = int(duration_beats * TICKS_PER_BEAT)

    events = []
    for p in pitches:
        events.append(('on', start_tick, p, velocity))
        events.append(('off', start_tick + dur_ticks, p, 0))

    events.sort(key=lambda e: (e[1], 0 if e[0] == 'off' else 1))

    last_tick = 0
    for etype, tick, pitch, vel in events:
        delta = tick - last_tick
        if etype == 'on':
            track.append(mido.Message('note_on', channel=channel,
                                       note=pitch, velocity=vel, time=delta))
        else:
            track.append(mido.Message('note_off', channel=channel,
                                       note=pitch, velocity=0, time=delta))
        last_tick = tick

def main():
    outfile = sys.argv[1] if len(sys.argv) > 1 else 'demo.mid'

    mid = mido.MidiFile(type=0, ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    # Tempo
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(BPM), time=0))

    # Program changes
    track.append(mido.Message('program_change', channel=0, program=0, time=0))   # Piano
    track.append(mido.Message('program_change', channel=1, program=1, time=0))   # Strings
    track.append(mido.Message('program_change', channel=2, program=2, time=0))   # Bass
    track.append(mido.Message('program_change', channel=3, program=3, time=0))   # Organ

    # We'll build events for each channel separately, merge, then write.
    # Simpler approach: build all events with absolute times, sort, convert to deltas.

    all_events = []  # (abs_tick, 'on'/'off', channel, pitch, velocity)

    def add(ch, pitch, start_beat, dur_beats, vel=100):
        t0 = int(start_beat * TICKS_PER_BEAT)
        t1 = t0 + int(dur_beats * TICKS_PER_BEAT)
        all_events.append((t0, 'on', ch, pitch, vel))
        all_events.append((t1, 'off', ch, pitch, 0))

    # ── 8-bar composition in C major ──

    # Bass line (Ch 2) — simple root notes, 2 bars repeated 4×
    bass_pattern = [
        (36, 0, 1),    # C2 whole note
        (36, 2, 0.5),  # C2
        (40, 2.5, 0.5),# E2
        (43, 3, 1),    # G2
        (41, 4, 1),    # F2
        (41, 6, 0.5),  # F2
        (43, 6.5, 0.5),# G2
        (36, 7, 1),    # C2
    ]
    for rep in range(4):
        offset = rep * 8
        for pitch, beat, dur in bass_pattern:
            add(2, pitch, offset + beat, dur, 90)

    # Strings (Ch 1) — sustained chords, 2 bars each
    chords = [
        ([60, 64, 67], 0, 4),    # C major (bars 1-2)
        ([60, 65, 69], 4, 4),    # F major (bars 3-4)
        ([59, 62, 67], 8, 4),    # G major (bars 5-6)
        ([60, 64, 67], 12, 4),   # C major (bars 7-8)
        ([60, 65, 69], 16, 4),   # F major
        ([59, 62, 67], 20, 4),   # G major
        ([57, 60, 64], 24, 4),   # Am
        ([60, 64, 67], 28, 4),   # C major (ending)
    ]
    for pitches, beat, dur in chords:
        for p in pitches:
            add(1, p, beat, dur, 70)

    # Piano melody (Ch 0) — simple memorable tune
    melody = [
        # Phrase 1 (bars 1-4)
        (72, 0, 1), (74, 1, 0.5), (76, 1.5, 0.5), (77, 2, 1), (76, 3, 1),
        (74, 4, 1), (72, 5, 0.5), (71, 5.5, 0.5), (69, 6, 2),
        # Phrase 2 (bars 5-8)
        (67, 8, 1), (69, 9, 0.5), (71, 9.5, 0.5), (72, 10, 1), (74, 11, 1),
        (76, 12, 1.5), (74, 13.5, 0.5), (72, 14, 2),
        # Phrase 3 (bars 9-12) — variation
        (72, 16, 0.5), (74, 16.5, 0.5), (76, 17, 1), (79, 18, 1), (77, 19, 1),
        (76, 20, 1), (74, 21, 0.5), (72, 21.5, 0.5), (71, 22, 2),
        # Phrase 4 (bars 13-16) — resolution
        (69, 24, 1), (71, 25, 0.5), (72, 25.5, 0.5), (74, 26, 1), (72, 27, 1),
        (71, 28, 0.5), (69, 28.5, 0.5), (67, 29, 1), (72, 30, 2),
    ]
    for pitch, beat, dur in melody:
        add(0, pitch, beat, dur, 95)

    # Organ accompaniment (Ch 3) — rhythmic stabs
    organ_rhythm = [
        # 2-bar pattern, repeated
        (60, 0, 0.25), (64, 0.5, 0.25), (60, 1, 0.25), (67, 1.5, 0.25),
        (60, 2, 0.25), (64, 2.5, 0.25), (60, 3, 0.5),
        (65, 4, 0.25), (69, 4.5, 0.25), (65, 5, 0.25), (69, 5.5, 0.25),
        (65, 6, 0.25), (69, 6.5, 0.25), (65, 7, 0.5),
    ]
    for rep in range(4):
        offset = rep * 8
        for pitch, beat, dur in organ_rhythm:
            add(3, pitch, offset + beat, dur, 75)

    # Sort all events: by time, then offs before ons
    all_events.sort(key=lambda e: (e[0], 0 if e[1] == 'off' else 1))

    # Convert to MIDI messages with delta times
    last_tick = 0
    for tick, etype, ch, pitch, vel in all_events:
        delta = tick - last_tick
        if etype == 'on':
            track.append(mido.Message('note_on', channel=ch, note=pitch,
                                       velocity=vel, time=delta))
        else:
            track.append(mido.Message('note_off', channel=ch, note=pitch,
                                       velocity=0, time=delta))
        last_tick = tick

    # End of track
    track.append(mido.MetaMessage('end_of_track', time=TICKS_PER_BEAT * 2))

    mid.save(outfile)
    total_beats = 32
    duration_sec = total_beats * 60 / BPM
    print(f"[midi] {outfile}: {total_beats} beats, {duration_sec:.0f}s, {BPM} BPM")
    print(f"  Ch 0: Piano melody")
    print(f"  Ch 1: String chords")
    print(f"  Ch 2: Bass line")
    print(f"  Ch 3: Organ rhythm")

if __name__ == '__main__':
    main()
