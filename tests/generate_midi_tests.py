import mido
import os

# Ticks per beat (resolution) for the MIDI files.
# The SEQ format uses this value directly.
TICKS_PER_BEAT = 480

def write_midi_file(filename, track):
    """Helper function to write a MIDI track to a file."""
    # Create the output directory if it doesn't exist
    if not os.path.exists("midi_test_files"):
        os.makedirs("midi_test_files")
    
    filepath = os.path.join("midi_test_files", filename)
    mid = mido.MidiFile(type=0, ticks_per_beat=TICKS_PER_BEAT)
    mid.tracks.append(track)
    mid.save(filepath)
    print(f"Generated: {filepath}")

def create_timing_tests():
    """Generates MIDI files to test various timing scenarios."""
    
    # --- Test 1: Short vs. Long Notes ---
    # Verifies basic gate time calculation for staccato and sustained notes.
    track = mido.MidiTrack()
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120)))
    # Short note (staccato)
    track.append(mido.Message('note_on', note=60, velocity=100, time=0))
    track.append(mido.Message('note_off', note=60, velocity=0, time=TICKS_PER_BEAT // 4))
    # Long note (sustained)
    track.append(mido.Message('note_on', note=62, velocity=100, time=TICKS_PER_BEAT))
    track.append(mido.Message('note_off', note=62, velocity=0, time=TICKS_PER_BEAT * 2))
    write_midi_file("test_short_long.mid", track)

    # --- Test 2: Overlapping Notes ---
    # Verifies that a new note correctly terminates a previous note on the same key.
    track = mido.MidiTrack()
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120)))
    track.append(mido.Message('note_on', note=60, velocity=100, time=0))
    track.append(mido.Message('note_on', note=60, velocity=100, time=TICKS_PER_BEAT)) # Overlapping note
    track.append(mido.Message('note_off', note=60, velocity=0, time=TICKS_PER_BEAT))
    write_midi_file("test_overlapping.mid", track)

    # --- Test 3: Large Delta Time ---
    # Verifies generation of Step Extend opcodes (0x8D-0x8F).
    track = mido.MidiTrack()
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120)))
    track.append(mido.Message('note_on', note=60, velocity=100, time=0))
    track.append(mido.Message('note_off', note=60, velocity=0, time=TICKS_PER_BEAT))
    # Long pause (delta time > 4096)
    track.append(mido.Message('note_on', note=62, velocity=100, time=TICKS_PER_BEAT * 10))
    track.append(mido.Message('note_off', note=62, velocity=0, time=TICKS_PER_BEAT))
    write_midi_file("test_large_delta.mid", track)

    # --- Test 4: Large Gate Time ---
    # Verifies generation of Gate Extend opcodes (0x88-0x8B).
    track = mido.MidiTrack()
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120)))
    # Very long sustained note
    track.append(mido.Message('note_on', note=60, velocity=100, time=0))
    track.append(mido.Message('note_off', note=60, velocity=0, time=TICKS_PER_BEAT * 10))
    write_midi_file("test_large_gate.mid", track)

    # --- Test 5: Mid-Range Times ---
    # Verifies the use of 0x20 (delta) and 0x40 (gate) flags in the Note On event.
    track = mido.MidiTrack()
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120)))
    # Gate time between 256 and 511
    track.append(mido.Message('note_on', note=60, velocity=100, time=0))
    track.append(mido.Message('note_off', note=60, velocity=0, time=300))
    # Delta time between 256 and 511
    track.append(mido.Message('note_on', note=62, velocity=100, time=400))
    track.append(mido.Message('note_off', note=62, velocity=0, time=TICKS_PER_BEAT))
    write_midi_file("test_mid_range_time.mid", track)

def create_channel_event_tests():
    """Generates MIDI files to test various channel events."""

    # --- Test 6: Program Change ---
    # Verifies instrument switching.
    track = mido.MidiTrack()
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120)))
    track.append(mido.Message('program_change', program=0, time=0)) # Acoustic Grand Piano
    track.append(mido.Message('note_on', note=60, velocity=100, time=0))
    track.append(mido.Message('note_off', note=60, velocity=0, time=TICKS_PER_BEAT))
    track.append(mido.Message('program_change', program=40, time=0)) # Violin
    track.append(mido.Message('note_on', note=67, velocity=100, time=TICKS_PER_BEAT))
    track.append(mido.Message('note_off', note=67, velocity=0, time=TICKS_PER_BEAT))
    write_midi_file("test_program_change.mid", track)

    # --- Test 7: Control Changes ---
    # Verifies volume, pan, and modulation.
    track = mido.MidiTrack()
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120)))
    track.append(mido.Message('control_change', control=10, value=0, time=0)) # Pan left
    track.append(mido.Message('note_on', note=60, velocity=100, time=0))
    track.append(mido.Message('control_change', control=7, value=80, time=TICKS_PER_BEAT // 2)) # Lower volume
    track.append(mido.Message('control_change', control=10, value=127, time=TICKS_PER_BEAT // 2)) # Pan right
    track.append(mido.Message('note_off', note=60, velocity=0, time=TICKS_PER_BEAT))
    write_midi_file("test_control_change.mid", track)

    # --- Test 8: Pitch Bend ---
    # Verifies pitch bend event conversion.
    track = mido.MidiTrack()
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120)))
    track.append(mido.Message('note_on', note=60, velocity=100, time=0))
    track.append(mido.Message('pitchwheel', pitch=4096, time=TICKS_PER_BEAT // 2)) # Bend up
    track.append(mido.Message('pitchwheel', pitch=0, time=TICKS_PER_BEAT // 2)) # Return to center
    track.append(mido.Message('note_off', note=60, velocity=0, time=TICKS_PER_BEAT))
    write_midi_file("test_pitch_bend.mid", track)

def create_structural_tests():
    """Generates MIDI files to test structural and edge cases."""

    # --- Test 9: Multi-Channel ---
    # Verifies correct handling of multiple simultaneous channels.
    track = mido.MidiTrack()
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120)))
    # Channel 0 (Piano)
    track.append(mido.Message('program_change', channel=0, program=0, time=0))
    track.append(mido.Message('note_on', channel=0, note=60, velocity=100, time=0))
    # Channel 1 (Bass)
    track.append(mido.Message('program_change', channel=1, program=33, time=0))
    track.append(mido.Message('note_on', channel=1, note=48, velocity=110, time=0))
    # Notes off
    track.append(mido.Message('note_off', channel=0, note=60, velocity=0, time=TICKS_PER_BEAT * 2))
    track.append(mido.Message('note_off', channel=1, note=48, velocity=0, time=0))
    write_midi_file("test_multi_channel.mid", track)

    # --- Test 10: Initial Silence ---
    # Verifies the special two-part tempo track generation.
    track = mido.MidiTrack()
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120)))
    # Long rest at the start
    track.append(mido.Message('note_on', note=60, velocity=100, time=TICKS_PER_BEAT * 4))
    track.append(mido.Message('note_off', note=60, velocity=0, time=TICKS_PER_BEAT))
    write_midi_file("test_initial_silence.mid", track)

if __name__ == "__main__":
    print("Generating MIDI test files...")
    create_timing_tests()
    create_channel_event_tests()
    create_structural_tests()
    print("\nAll test files have been generated in the 'midi_test_files' folder.")


