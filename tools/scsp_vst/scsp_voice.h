/*
 * scsp_voice.h — Voice allocation and SCSP register programming for FM synthesis.
 *
 * Supports per-operator waveform selection, loop points, and polyphonic
 * voice allocation across the SCSP's 32 slots.
 */

#ifndef SCSP_VOICE_H
#define SCSP_VOICE_H

#include <stdint.h>
#include "../scsp_wasm/scsp_waveforms.h"

#ifdef __cplusplus
extern "C" {
#endif

#define SCSP_MAX_SLOTS     32
#define SCSP_MAX_OPS       6
#define SCSP_MAX_WAVEFORMS 32

/* ── Waveform Store ───────────────────────────────────────────── */

typedef struct {
    int  ram_offset;    /* byte offset in SCSP RAM */
    int  length;        /* total samples */
    int  loop_start;    /* LSA (sample index) */
    int  loop_end;      /* LEA (sample index) */
    int  loop_mode;     /* LPCTL: 0=off, 1=forward, 2=reverse, 3=ping-pong */
} scsp_waveform_t;

typedef struct {
    scsp_waveform_t waves[SCSP_MAX_WAVEFORMS];
    int             num_waves;
    int             next_free_offset;  /* next free byte in SCSP RAM */
} scsp_wave_store_t;

/* ── Operator Definition ──────────────────────────────────────── */

typedef struct {
    float freq_ratio;   /* frequency ratio to fundamental (0.5-32) */
    float freq_fixed;   /* fixed frequency in Hz (0 = use ratio) */
    float level;        /* output level 0.0-1.0 */
    int   ar;           /* attack rate 0-31 */
    int   d1r;          /* decay 1 rate 0-31 */
    int   dl;           /* decay level 0-31 */
    int   d2r;          /* decay 2 rate 0-31 */
    int   rr;           /* release rate 0-31 */
    int   mdl;          /* modulation depth 0-15 */
    int   mod_source;   /* which op modulates this one (-1 = none) */
    float feedback;     /* self-feedback 0.0-0.5 */
    int   is_carrier;   /* 1 = audible output, 0 = modulator only */
    /* Per-operator waveform */
    int   waveform_id;  /* index into wave store (0 = sine default) */
    int   loop_start;   /* per-op override (-1 = use waveform default) */
    int   loop_end;     /* per-op override (-1 = use waveform default) */
    int   loop_mode;    /* per-op override (-1 = use waveform default) */
} scsp_fm_op_t;

/* ── Voice Tracking ───────────────────────────────────────────── */

typedef struct {
    int  active;
    int  midi_note;
    int  slot_base;
    int  num_ops;
} scsp_voice_t;

typedef struct {
    scsp_voice_t voices[SCSP_MAX_SLOTS];
    int          num_voices;
    int          slot_used[SCSP_MAX_SLOTS];
} scsp_voice_alloc_t;

/* ── API ──────────────────────────────────────────────────────── */

/*
 * Initialize the SCSP emulator and load all built-in waveforms into RAM.
 * Populates the wave store with entries for each built-in.
 */
void scsp_voice_init(scsp_wave_store_t *store);

/*
 * Add a custom waveform to the store. Writes samples to SCSP RAM.
 * Returns the waveform ID (index in store), or -1 if store is full.
 * samples: int16_t LE samples
 * length: number of samples
 * loop_start/loop_end: loop points (sample indices)
 * loop_mode: LPCTL value
 */
int scsp_wave_store_add(scsp_wave_store_t *store,
                        const int16_t *samples, int length,
                        int loop_start, int loop_end, int loop_mode);

/*
 * Program SCSP slot with operator params, using waveform from store.
 */
void scsp_program_slot(int slot, const scsp_fm_op_t *op, int midi_note,
                       const scsp_fm_op_t *all_ops, int num_ops,
                       const scsp_wave_store_t *store);

/*
 * Voice allocation: note on/off using the wave store for waveform lookup.
 */
int  scsp_voice_note_on(scsp_voice_alloc_t *alloc, const scsp_fm_op_t *ops,
                        int num_ops, int midi_note, const scsp_wave_store_t *store);
void scsp_voice_note_off(scsp_voice_alloc_t *alloc, int midi_note);
void scsp_voice_all_off(scsp_voice_alloc_t *alloc);

#ifdef __cplusplus
}
#endif

#endif /* SCSP_VOICE_H */
