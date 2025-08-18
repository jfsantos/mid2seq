#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Structure to hold SEQ file header information.
// The SEQ format is Big Endian.
typedef struct {
  uint16_t resolution;
  uint16_t num_tempo_events;
  uint16_t data_offset;
  uint16_t tempo_loop_offset;
} SeqHeader;

// Structure for tempo events in the SEQ file.
typedef struct {
  uint32_t step_time; // Delta time from previous tempo event
  uint32_t mspb;      // Microseconds per beat
} SeqTempoEvent;

// Structure to hold a MIDI event after being read from the file.
// This allows us to process all events before writing the final SEQ file.
typedef struct {
  uint32_t absolute_time;
  uint8_t status;
  uint8_t data1;
  uint8_t data2;
  uint32_t gate_time; // Calculated for Note On events
} TrackEvent;

// Comparison function for qsort to sort events by their absolute time.
// This is crucial because MIDI events at the same timestamp are not guaranteed
// to be in order.
int compare_events(const void *a, const void *b) {
  TrackEvent *eventA = (TrackEvent *)a;
  TrackEvent *eventB = (TrackEvent *)b;
  if (eventA->absolute_time < eventB->absolute_time)
    return -1;
  if (eventA->absolute_time > eventB->absolute_time)
    return 1;
  // For events at the same time, ensure Note Off events come first
  // to handle zero-duration notes correctly during gate calculation.
  uint8_t typeA = eventA->status & 0xF0;
  uint8_t typeB = eventB->status & 0xF0;
  if ((typeA == 0x80 || (typeA == 0x90 && eventA->data2 == 0)) &&
      (typeB != 0x80 && (typeB != 0x90 || eventB->data2 != 0)))
    return -1;
  if ((typeB == 0x80 || (typeB == 0x90 && eventB->data2 == 0)) &&
      (typeA != 0x80 && (typeA != 0x90 || eventA->data2 != 0)))
    return 1;
  return 0;
}

// Function to swap byte order for 16-bit integers.
uint16_t swap16(uint16_t val) { return (val << 8) | (val >> 8); }

// Function to swap byte order for 32-bit integers.
uint32_t swap32(uint32_t val) {
  return (val << 24) | ((val << 8) & 0x00ff0000) | ((val >> 8) & 0x0000ff00) |
         (val >> 24);
}

// Function to read a variable-length quantity from a file (used for MIDI delta
// times).
uint32_t read_variable_length(FILE *file) {
  uint32_t value = 0;
  uint8_t byte;

  if (feof(file))
    return 0;
  byte = fgetc(file);
  value = byte & 0x7F;

  while (byte & 0x80) {
    if (feof(file))
      return value;
    byte = fgetc(file);
    value = (value << 7) | (byte & 0x7F);
  }
  return value;
}

// Writes Step(Delta) Extend events (0x8D-0x8F) for any event type.
// These handle the largest chunks of time.
void write_large_delta_events(FILE *file, uint32_t *delta) {
  while (*delta >= 0x1000) {
    fputc(0x8F, file);
    *delta -= 0x1000;
  }
  while (*delta >= 0x800) {
    fputc(0x8E, file);
    *delta -= 0x800;
  }
  while (*delta >= 0x200) {
    fputc(0x8D, file);
    *delta -= 0x200;
  }
}

// Writes Gate Extend events (0x88-0x8B) for Note On events.
void write_extended_gate(FILE *file, uint32_t *gate) {
  while (*gate >= 0x2000) {
    fputc(0x8B, file);
    *gate -= 0x2000;
  }
  while (*gate >= 0x1000) {
    fputc(0x8A, file);
    *gate -= 0x1000;
  }
  while (*gate >= 0x800) {
    fputc(0x89, file);
    *gate -= 0x800;
  }
  while (*gate >= 0x200) {
    fputc(0x88, file);
    *gate -= 0x200;
  }
}

int main(int argc, char *argv[]) {
  if (argc != 3) {
    printf("Usage: %s <input.mid> <output.seq>\n", argv[0]);
    return 1;
  }

  FILE *midi_file = fopen(argv[1], "rb");
  if (!midi_file) {
    perror("Error opening MIDI file");
    return 1;
  }

  // Read MIDI header chunk
  char header_id[4];
  uint32_t header_length;
  uint16_t format;
  uint16_t num_tracks;
  uint16_t division;

  fread(header_id, 1, 4, midi_file);
  fread(&header_length, 4, 1, midi_file);
  header_length = swap32(header_length);
  fread(&format, 2, 1, midi_file);
  format = swap16(format);
  fread(&num_tracks, 2, 1, midi_file);
  num_tracks = swap16(num_tracks);
  fread(&division, 2, 1, midi_file);
  division = swap16(division);

  if (format != 0) {
    printf("This program only supports MIDI format 0.\n");
    fclose(midi_file);
    return 1;
  }

  // Read MIDI track chunk header
  char track_id[4];
  uint32_t track_length;
  fread(track_id, 1, 4, midi_file);
  fread(&track_length, 4, 1, midi_file);
  track_length = swap32(track_length);
  long track_start_pos = ftell(midi_file);

  // === PASS 1: Read all MIDI events into an in-memory array ===
  TrackEvent *events = malloc(sizeof(TrackEvent) * (track_length));
  if (!events) {
    printf("Failed to allocate memory for events.\n");
    fclose(midi_file);
    return 1;
  }
  int event_count = 0;

  SeqTempoEvent tempo_events[256];
  int tempo_count = 0;

  uint8_t last_status = 0;
  uint32_t current_time = 0;
  uint32_t last_tempo_time = 0;

  while (ftell(midi_file) < track_start_pos + track_length) {
    uint32_t delta_time = read_variable_length(midi_file);
    current_time += delta_time;

    uint8_t status = fgetc(midi_file);
    if ((status & 0x80) == 0) { // Running status
      ungetc(status, midi_file);
      status = last_status;
    }

    TrackEvent *current_event = &events[event_count];
    current_event->absolute_time = current_time;
    current_event->status = status;
    current_event->gate_time = 0;

    uint8_t event_type = status & 0xF0;

    switch (event_type) {
    case 0x90:
    case 0x80:
    case 0xB0:
    case 0xA0:
    case 0xE0:
      current_event->data1 = fgetc(midi_file);
      current_event->data2 = fgetc(midi_file);
      event_count++;
      break;

    case 0xC0:
    case 0xD0:
      current_event->data1 = fgetc(midi_file);
      current_event->data2 = 0;
      event_count++;
      break;

    case 0xF0:
      if (status == 0xFF) { // Meta Event
        uint8_t meta_type = fgetc(midi_file);
        uint8_t length = read_variable_length(midi_file);
        if (meta_type == 0x51 && tempo_count < 255) { // Set Tempo
          uint32_t mspb = 0;
          for (int i = 0; i < length; ++i)
            mspb = (mspb << 8) | fgetc(midi_file);
          tempo_events[tempo_count].step_time = current_time - last_tempo_time;
          last_tempo_time = current_time;
          tempo_events[tempo_count].mspb = mspb;
          tempo_count++;
        } else {
          fseek(midi_file, length, SEEK_CUR);
        }
      }
      break;
    }
    last_status = status;
  }
  fclose(midi_file);

  // === PASS 2: Calculate gate times ===
  int active_note_indices[16][128];
  for (int i = 0; i < 16; i++)
    for (int j = 0; j < 128; j++)
      active_note_indices[i][j] = -1;

  for (int i = 0; i < event_count; i++) {
    uint8_t event_type = events[i].status & 0xF0;
    uint8_t channel = events[i].status & 0x0F;
    uint8_t key = events[i].data1;
    uint8_t velocity = events[i].data2;

    if (event_type == 0x90 && velocity > 0) {
      if (active_note_indices[channel][key] != -1) {
        int prev_idx = active_note_indices[channel][key];
        events[prev_idx].gate_time =
            events[i].absolute_time - events[prev_idx].absolute_time;
      }
      active_note_indices[channel][key] = i;
    } else if (event_type == 0x80 || (event_type == 0x90 && velocity == 0)) {
      int note_on_index = active_note_indices[channel][key];
      if (note_on_index != -1) {
        events[note_on_index].gate_time =
            events[i].absolute_time - events[note_on_index].absolute_time;
        events[i].status = 0x00; // Mark Note Off for removal
        active_note_indices[channel][key] = -1;
      }
    }
  }

  // === PASS 3: Sort events to ensure correct delta time calculation ===
  qsort(events, event_count, sizeof(TrackEvent), compare_events);

  // === PASS 4: Find first musical event time and synthesize tempo track ===
  uint32_t first_musical_event_time = 0;
  for (int i = 0; i < event_count; i++) {
    // A musical event is anything that's not a meta event (status 0xFF)
    if (events[i].status != 0xFF) {
      first_musical_event_time = events[i].absolute_time;
      break;
    }
  }

  uint32_t total_song_time = 0;
  if (event_count > 0) {
    total_song_time = events[event_count - 1].absolute_time;
  }

  // Rebuild the tempo track based on the special SEQ file logic
  if (tempo_count > 0) {
    uint32_t mspb =
        tempo_events[0].mspb; // Keep the MSPB from the first real tempo event

    // Event 1: From time 0 until the first musical event
    tempo_events[0].step_time = first_musical_event_time;
    tempo_events[0].mspb = mspb;

    // Event 2: From the first musical event to the end of the song
    tempo_events[1].step_time = total_song_time - first_musical_event_time;
    tempo_events[1].mspb = mspb;

    tempo_count = 2; // We now have exactly two tempo events
  }

  // === WRITE SEQ FILE ===
  FILE *seq_file = fopen(argv[2], "wb");
  if (!seq_file) {
    perror("Error creating SEQ file");
    free(events);
    return 1;
  }

  // --- Write Bank Header ---
  uint16_t num_songs = swap16(1);
  uint32_t song_ptr = swap32(6);
  fwrite(&num_songs, 2, 1, seq_file);
  fwrite(&song_ptr, 4, 1, seq_file);

  // --- Write SEQ Header ---
  SeqHeader seq_header = {0};
  seq_header.resolution = swap16(division);
  seq_header.num_tempo_events = swap16(tempo_count);
  seq_header.data_offset = swap16(8 + tempo_count * 8);
  if (tempo_count > 0) {
    // Point loop offset to the start of the second (main body) tempo event
    seq_header.tempo_loop_offset = swap16(8 + (1 * 8));
  } else {
    seq_header.tempo_loop_offset = 0;
  }
  fwrite(&seq_header, sizeof(seq_header), 1, seq_file);

  // --- Write Tempo Track ---
  for (int i = 0; i < tempo_count; i++) {
    uint32_t be_step = swap32(tempo_events[i].step_time);
    uint32_t be_mspb = swap32(tempo_events[i].mspb);
    fwrite(&be_step, 4, 1, seq_file);
    fwrite(&be_mspb, 4, 1, seq_file);
  }

  // --- Write Normal Track ---
  uint32_t last_event_time = 0;
  for (int i = 0; i < event_count; i++) {
    if (events[i].status == 0x00)
      continue; // Skip processed Note Off events

    uint32_t delta_time = events[i].absolute_time - last_event_time;
    last_event_time = events[i].absolute_time;

    write_large_delta_events(seq_file, &delta_time);

    uint8_t event_type = events[i].status & 0xF0;
    uint8_t channel = events[i].status & 0x0F;

    if (event_type == 0x90) { // Note On
      uint32_t gate_time = events[i].gate_time;
      write_extended_gate(seq_file, &gate_time);

      uint8_t ctl_byte = channel;
      if (delta_time >= 256) {
        ctl_byte |= 0x20;
        delta_time -= 256;
      }
      if (gate_time >= 256) {
        ctl_byte |= 0x40;
        gate_time -= 256;
      }

      fputc(ctl_byte, seq_file);
      fputc(events[i].data1, seq_file);
      fputc(events[i].data2, seq_file);
      fputc(gate_time, seq_file);
      fputc(delta_time, seq_file);

    } else { // Handle all other event types
      while (delta_time >= 256) {
        fputc(0x8C, seq_file);
        delta_time -= 256;
      }

      fputc(events[i].status, seq_file);

      if (event_type == 0xB0 || event_type == 0xA0) { // 2 data bytes
        fputc(events[i].data1, seq_file);
        fputc(events[i].data2, seq_file);
      } else if (event_type == 0xE0) {    // Pitch Bend
        fputc(events[i].data2, seq_file); // Use MSB (data2) as the value
      } else { // 1 data byte (Program Change, Channel Pressure)
        fputc(events[i].data1, seq_file);
      }
      fputc(delta_time, seq_file);
    }
  }
  fputc(0x83, seq_file); // End of track marker

  free(events);
  fclose(seq_file);

  printf("Conversion complete.\n");
  return 0;
}
