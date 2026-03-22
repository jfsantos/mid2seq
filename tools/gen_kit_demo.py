#!/usr/bin/env python3
"""
gen_kit_demo.py — Generate a demo MIDI using all Saturn Kit instruments.

Structure (16 bars, 120 BPM):
  Bars 1-16: Full arrangement
    Ch 0:  Piano (prog 0)    — melody
    Ch 1:  Strings (prog 48) — sustained chords
    Ch 2:  Bass (prog 32)    — bass line
    Ch 3:  Organ (prog 16)   — rhythmic stabs
    Ch 4:  Brass (prog 56)   — counter-melody (bars 9-16)
    Ch 5:  Flute (prog 73)   — ornaments (bars 5-8)
    Ch 6:  Saw Lead (prog 81)— lead fill (bars 13-16)
    Ch 9:  Drums             — kick/snare/hihat pattern
"""

import mido
import sys

TICKS = 480
BPM = 120


def add(events, ch, pitch, start_beat, dur_beats, vel=100):
    t0 = int(start_beat * TICKS)
    t1 = t0 + int(dur_beats * TICKS)
    events.append((t0, 'on', ch, pitch, vel))
    events.append((t1, 'off', ch, pitch, 0))


def main():
    outfile = sys.argv[1] if len(sys.argv) > 1 else 'kit_demo.mid'
    mid = mido.MidiFile(type=0, ticks_per_beat=TICKS)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(BPM), time=0))

    # Program changes — program numbers match TON voice indices
    # (Saturn driver maps program number directly to voice index)
    programs = [
        (0, 0),    # Piano (voice 0)
        (1, 3),    # Strings (voice 3)
        (2, 8),    # Bass (voice 8)
        (3, 2),    # Organ (voice 2)
        (4, 4),    # Brass (voice 4)
        (5, 5),    # Flute (voice 5)
        (6, 6),    # Saw Lead (voice 6)
        (9, 12),   # Kick (voice 12, drums on ch 9)
    ]
    for ch, prog in programs:
        track.append(mido.Message('program_change', channel=ch, program=prog, time=0))

    all_events = []

    # ── Drums — each drum type on its own MIDI channel ──
    # Saturn maps program number to TON voice, so each drum needs
    # its own channel+program. We use ch 9-12 for drums.
    # (Also add program changes for each drum channel)
    track.append(mido.Message('program_change', channel=10, program=13, time=0))  # Snare
    track.append(mido.Message('program_change', channel=11, program=14, time=0))  # Hi-Hat
    track.append(mido.Message('program_change', channel=12, program=15, time=0))  # Crash

    for bar in range(16):
        b = bar * 4  # beat offset
        # Kick (ch 9, prog 12): beats 1, 3
        add(all_events, 9, 36, b + 0, 0.25, 110)
        add(all_events, 9, 36, b + 2, 0.25, 100)
        # Snare (ch 10, prog 13): beats 2, 4
        add(all_events, 10, 38, b + 1, 0.25, 105)
        add(all_events, 10, 38, b + 3, 0.25, 95)
        # Hi-hat (ch 11, prog 14): every 8th note
        for eighth in range(8):
            vel = 80 if eighth % 2 == 0 else 60
            add(all_events, 11, 42, b + eighth * 0.5, 0.2, vel)
        # Crash (ch 12, prog 15) on bar 1, 9
        if bar in (0, 8):
            add(all_events, 12, 49, b, 1.0, 90)

    # ── Bass (ch 2) — root notes, 16 bars ──
    # Chord progression: C-Am-F-G (4 bars each, repeat)
    bass_roots = [
        (36, 4), (33, 4), (29, 4), (31, 4),  # C2, A1, F1, G1
        (36, 4), (33, 4), (29, 4), (31, 4),
    ]
    beat = 0
    for root, dur_bars in bass_roots:
        for bar_i in range(dur_bars):
            b = beat + bar_i * 4
            # Eighth note pattern
            add(all_events, 2, root, b + 0, 0.4, 100)
            add(all_events, 2, root, b + 1, 0.4, 85)
            add(all_events, 2, root + 12, b + 2, 0.4, 90)
            add(all_events, 2, root, b + 3, 0.4, 85)
        beat += dur_bars * 4

    # ── Strings (ch 1) — sustained chords ──
    chords = [
        ([60, 64, 67], 0, 16),   # C major (bars 1-4)
        ([57, 60, 64], 16, 16),  # Am (bars 5-8)
        ([53, 57, 60], 32, 16),  # F (bars 9-12)
        ([55, 59, 62], 48, 16),  # G (bars 13-16)
    ]
    for pitches, start_beat, dur_beats in chords:
        for p in pitches:
            add(all_events, 1, p, start_beat, dur_beats, 70)

    # ── Piano (ch 0) — melody, all 16 bars ──
    melody = [
        # Phrase 1 (bars 1-4, over C major)
        (72, 0, 1), (74, 1, 0.5), (76, 1.5, 0.5),
        (77, 2, 1), (76, 3, 0.5), (74, 3.5, 0.5),
        (72, 4, 1.5), (71, 5.5, 0.5), (69, 6, 2),
        (0, 8, 0),  # rest
        (67, 8, 1), (69, 9, 0.5), (71, 9.5, 0.5),
        (72, 10, 1), (74, 11, 1),
        (76, 12, 1.5), (74, 13.5, 0.5), (72, 14, 2),
        # Phrase 2 (bars 5-8, over Am)
        (69, 16, 1), (71, 17, 0.5), (72, 17.5, 0.5),
        (74, 18, 1), (72, 19, 0.5), (71, 19.5, 0.5),
        (69, 20, 2), (67, 22, 1), (69, 23, 1),
        (72, 24, 1), (71, 25, 0.5), (69, 25.5, 0.5),
        (67, 26, 1), (69, 27, 1),
        (71, 28, 2), (72, 30, 2),
        # Phrase 3 (bars 9-12, over F)
        (65, 32, 1), (67, 33, 0.5), (69, 33.5, 0.5),
        (72, 34, 1), (74, 35, 1),
        (76, 36, 1.5), (74, 37.5, 0.5), (72, 38, 1), (69, 39, 1),
        (67, 40, 1), (69, 41, 0.5), (71, 41.5, 0.5),
        (72, 42, 1), (74, 43, 1),
        (76, 44, 2), (77, 46, 2),
        # Phrase 4 (bars 13-16, over G → resolve to C)
        (79, 48, 1), (77, 49, 0.5), (76, 49.5, 0.5),
        (74, 50, 1), (72, 51, 1),
        (71, 52, 1), (69, 53, 0.5), (67, 53.5, 0.5),
        (69, 54, 1), (71, 55, 1),
        (72, 56, 2), (74, 58, 1), (72, 59, 1),
        (71, 60, 1), (69, 61, 0.5), (67, 61.5, 0.5),
        (64, 62, 1), (72, 63, 1),
    ]
    for pitch, beat, dur in melody:
        if pitch > 0:
            add(all_events, 0, pitch, beat, dur, 95)

    # ── Organ (ch 3) — rhythmic stabs ──
    organ_chords = [
        ([60, 64, 67], 0, 16),
        ([57, 60, 64], 16, 16),
        ([53, 57, 60], 32, 16),
        ([55, 59, 62], 48, 16),
    ]
    for pitches, start, section_dur in organ_chords:
        for bar_off in range(section_dur // 4):
            b = start + bar_off * 4
            for p in pitches:
                add(all_events, 3, p, b + 0, 0.2, 70)
                add(all_events, 3, p, b + 0.5, 0.2, 55)
                add(all_events, 3, p, b + 2, 0.2, 65)
                add(all_events, 3, p, b + 2.5, 0.2, 55)

    # ── Brass (ch 4) — counter-melody, bars 9-16 ──
    brass = [
        (60, 32, 2), (62, 34, 2), (64, 36, 2), (65, 38, 2),
        (67, 40, 2), (65, 42, 2), (64, 44, 4),
        (67, 48, 2), (65, 50, 2), (64, 52, 2), (62, 54, 2),
        (60, 56, 4), (64, 60, 4),
    ]
    for pitch, beat, dur in brass:
        add(all_events, 4, pitch, beat, dur, 80)

    # ── Flute (ch 5) — ornaments, bars 5-8 ──
    flute = [
        (84, 16, 0.25), (86, 16.5, 0.25), (84, 17, 1),
        (81, 18, 0.5), (79, 18.5, 0.5), (81, 19, 1),
        (84, 20, 0.25), (86, 20.5, 0.25), (88, 21, 1.5),
        (86, 23, 1),
        (84, 24, 0.5), (81, 24.5, 0.5), (79, 25, 1),
        (81, 26, 2), (84, 28, 2), (79, 30, 2),
    ]
    for pitch, beat, dur in flute:
        add(all_events, 5, pitch, beat, dur, 75)

    # ── Saw Lead (ch 6) — lead fill, bars 13-16 ──
    saw = [
        (72, 48, 0.5), (76, 48.5, 0.5), (79, 49, 1),
        (84, 50, 0.5), (83, 50.5, 0.5), (79, 51, 1),
        (76, 52, 1), (74, 53, 1), (72, 54, 2),
        (79, 56, 1), (76, 57, 0.5), (74, 57.5, 0.5),
        (72, 58, 1), (74, 59, 1),
        (76, 60, 2), (72, 62, 2),
    ]
    for pitch, beat, dur in saw:
        add(all_events, 6, pitch, beat, dur, 85)

    # Sort and write
    all_events.sort(key=lambda e: (e[0], 0 if e[1] == 'off' else 1))

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

    track.append(mido.MetaMessage('end_of_track', time=TICKS * 4))

    mid.save(outfile)
    total_beats = 64
    duration = total_beats * 60 / BPM
    print(f"[midi] {outfile}: {total_beats} beats, {duration:.0f}s, {BPM} BPM")
    print(f"  Ch 0: Piano (prog 0)")
    print(f"  Ch 1: Strings (prog 48)")
    print(f"  Ch 2: Bass (prog 32)")
    print(f"  Ch 3: Organ (prog 16)")
    print(f"  Ch 4: Brass (prog 56) — bars 9-16")
    print(f"  Ch 5: Flute (prog 73) — bars 5-8")
    print(f"  Ch 6: Saw Lead (prog 81) — bars 13-16")
    print(f"  Ch 9: Drums (kick/snare/hihat/crash)")


if __name__ == '__main__':
    main()
