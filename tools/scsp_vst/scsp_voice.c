/*
 * scsp_voice.c — Voice allocation and SCSP register programming.
 *
 * Supports per-operator waveform selection from a waveform store,
 * with configurable loop points and FM safety constraints.
 */

#include "scsp_voice.h"
#include <math.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* ── SCSP API (from scsp_wasm.c) ─────────────────────────────── */
extern void     scsp_init(void);
extern uint8_t *scsp_get_ram_ptr(void);
extern void     scsp_write_slot(int slot, int reg_word, uint16_t value);
extern void     scsp_key_on(int slot);
extern void     scsp_key_off(int slot);

/* ── Constants ────────────────────────────────────────────────── */

static const double SCSP_SINE_BASE_FREQ = 44100.0 / 1024.0;
/* MIDI note for base freq 43.066 Hz */
static const double SINE_BASE_NOTE = 69.0 + 12.0 * (-3.35289);

/* TL dB per bit */
static const double TL_DB[8] = { 0.4, 0.8, 1.5, 3.0, 6.0, 12.0, 24.0, 48.0 };

/* ── Helpers ──────────────────────────────────────────────────── */

static double tl_to_linear(int tl)
{
    double db = 0.0;
    for (int b = 0; b < 8; b++)
        if (tl & (1 << b)) db -= TL_DB[b];
    return pow(10.0, db / 20.0);
}

static int compute_mdl(int mod_tl, double target_beta)
{
    double tl_lin = tl_to_linear(mod_tl);
    double ring_peak = 32767.0 * 4.0 * tl_lin / 2.0;
    if (ring_peak < 1.0) return 0;

    double needed = target_beta * 1024.0 / (ring_peak * 2.0 * M_PI);
    int mdl = (int)round(16.0 + log2(needed > 1e-10 ? needed : 1e-10));
    if (mdl < 0) mdl = 0;
    if (mdl > 15) mdl = 15;

    double max_safe = 1024.0 / (ring_peak * 2.0);
    int max_mdl = (int)floor(15.0 + log2(max_safe > 1e-10 ? max_safe : 1e-10));
    if (mdl > max_mdl) mdl = max_mdl;

    return mdl;
}

/* ── Waveform Store ───────────────────────────────────────────── */

void scsp_voice_init(scsp_wave_store_t *store)
{
    scsp_init();
    memset(store, 0, sizeof(*store));

    /* Load all built-in waveforms into RAM */
    uint8_t *ram = scsp_get_ram_ptr();
    int offsets[SCSP_NUM_BUILTINS];
    int next_free = scsp_load_builtins(ram, offsets);

    /* Populate store with built-in entries */
    for (int i = 0; i < SCSP_NUM_BUILTINS; i++) {
        store->waves[i].ram_offset = offsets[i];
        store->waves[i].length     = SCSP_WAVE_LEN;
        store->waves[i].loop_start = 0;
        store->waves[i].loop_end   = SCSP_WAVE_LEN;
        store->waves[i].loop_mode  = 1; /* forward loop */
    }
    store->num_waves = SCSP_NUM_BUILTINS;
    store->next_free_offset = next_free;
}

int scsp_wave_store_add(scsp_wave_store_t *store,
                        const int16_t *samples, int length,
                        int loop_start, int loop_end, int loop_mode)
{
    if (store->num_waves >= SCSP_MAX_WAVEFORMS) return -1;

    int offset = store->next_free_offset;
    /* Align to 2-byte boundary */
    if (offset & 1) offset++;

    /* Write samples to RAM (already LE int16) */
    uint8_t *ram = scsp_get_ram_ptr();
    for (int i = 0; i < length; i++) {
        int16_t val = samples[i];
        ram[offset + i * 2]     = (uint8_t)(val & 0xFF);
        ram[offset + i * 2 + 1] = (uint8_t)((val >> 8) & 0xFF);
    }

    int id = store->num_waves;
    store->waves[id].ram_offset = offset;
    store->waves[id].length     = length;
    store->waves[id].loop_start = loop_start;
    store->waves[id].loop_end   = loop_end;
    store->waves[id].loop_mode  = loop_mode;
    store->num_waves++;
    store->next_free_offset = offset + length * 2;

    return id;
}

/* ── Slot Programming ─────────────────────────────────────────── */

void scsp_program_slot(int slot, const scsp_fm_op_t *op, int midi_note,
                       const scsp_fm_op_t *all_ops, int num_ops,
                       const scsp_wave_store_t *store)
{
    /* Look up waveform from store */
    int wid = op->waveform_id;
    if (wid < 0 || wid >= store->num_waves) wid = 0;
    const scsp_waveform_t *wav = &store->waves[wid];

    /* Resolve loop points (per-op override or waveform default) */
    int lsa    = op->loop_start >= 0 ? op->loop_start : wav->loop_start;
    int lea    = op->loop_end >= 0   ? op->loop_end   : wav->loop_end;
    int lpctl  = op->loop_mode >= 0  ? op->loop_mode  : wav->loop_mode;
    /* Clamp to actual waveform length to prevent reading adjacent samples in RAM */
    if (lsa > wav->length) lsa = wav->length;
    if (lea > wav->length) lea = wav->length;
    int sa     = wav->ram_offset;

    /* FM constraint: if this operator participates in FM (modulator, or carrier
     * receiving modulation), enforce 1024-sample forward loop.
     * The SCSP's FM math (smp <<= 0xA) is hardcoded for 1024-sample cycles. */
    int uses_fm = (op->mod_source >= 0 && op->mdl >= 5) || op->feedback > 0.0f;
    int is_modulator = !op->is_carrier;
    if (uses_fm || is_modulator) {
        /* Must be a 1024-sample waveform */
        if (wav->length != SCSP_WAVE_LEN) {
            /* Fallback to sine if the selected waveform isn't 1024 */
            sa = store->waves[SCSP_WAVE_SINE].ram_offset;
        }
        lsa = 0;
        lea = SCSP_WAVE_LEN;
        lpctl = 1;
    }

    /* ── Pitch: OCT/FNS ── */
    double op_base_note;
    if (op->freq_fixed > 0) {
        op_base_note = SINE_BASE_NOTE + 12.0 * log2(op->freq_fixed / SCSP_SINE_BASE_FREQ);
    } else {
        op_base_note = SINE_BASE_NOTE - 12.0 * log2(op->freq_ratio > 0 ? op->freq_ratio : 1.0);
    }

    double semi = midi_note - op_base_note;
    int octave = (int)floor(semi / 12.0);
    if (octave < -8) octave = -8;
    if (octave > 7)  octave = 7;
    double frac = semi - octave * 12.0;
    int fns = (int)round(1024.0 * (pow(2.0, frac / 12.0) - 1.0));
    if (fns < 0) fns = 0;
    if (fns > 1023) fns = 1023;

    uint16_t oct_bits = (uint16_t)(((octave & 0xF) << 11) | (fns & 0x3FF));

    /* ── TL ── */
    int tl;
    if (op->is_carrier) {
        tl = (int)round((1.0 - op->level) * 255.0);
    } else {
        tl = (int)round(24.0 + (1.0 - op->level) * 56.0);
    }
    if (tl < 0) tl = 0;
    if (tl > 255) tl = 255;

    /* ── Envelope ── */
    uint16_t d4 = (uint16_t)(((op->d2r & 0x1F) << 11) |
                              ((op->d1r & 0x1F) << 6) |
                              (op->ar & 0x1F));
    uint16_t d5 = (uint16_t)(((op->dl & 0x1F) << 5) |
                              (op->rr & 0x1F));

    /* ── FM Modulation ── */
    int mdl = 0, mdxsl = 0, mdysl = 0;

    if (op->mod_source >= 0 && op->mdl >= 5 && op->mod_source < num_ops) {
        const scsp_fm_op_t *mod_op = &all_ops[op->mod_source];
        int mod_tl = (int)round(24.0 + (1.0 - mod_op->level) * 56.0);
        double target_beta = mod_op->level * M_PI;
        if (target_beta > 2.5) target_beta = 2.5;
        mdl = compute_mdl(mod_tl, target_beta);

        int dist = (op->mod_source - slot) & 63;
        mdxsl = dist;
        mdysl = dist;
    }

    if (op->feedback > 0.0f) {
        int fb_dist = (-32) & 63;
        double fb_beta = op->feedback * M_PI;
        int fb_mdl = compute_mdl(tl, fb_beta);

        if (mdl > 0) {
            mdysl = fb_dist;
            if (fb_mdl > mdl) mdl = fb_mdl;
        } else {
            mdl = fb_mdl;
            mdxsl = fb_dist;
            mdysl = fb_dist;
        }
    }

    uint16_t d7 = (uint16_t)(((mdl & 0xF) << 12) |
                              ((mdxsl & 0x3F) << 6) |
                              (mdysl & 0x3F));

    /* ── Output ── */
    int disdl = op->is_carrier ? 7 : 0;
    uint16_t d_b = (uint16_t)(((disdl & 0x7) << 13) | ((16 & 0x1F) << 8));

    /* ── SA encoding ── */
    uint16_t d0 = (uint16_t)((lpctl << 5) | ((sa >> 16) & 0xF));
    uint16_t d1 = (uint16_t)(sa & 0xFFFF);

    /* ── Write all slot registers ── */
    scsp_write_slot(slot, 0x0, d0);
    scsp_write_slot(slot, 0x1, d1);
    scsp_write_slot(slot, 0x2, (uint16_t)lsa);
    scsp_write_slot(slot, 0x3, (uint16_t)lea);
    scsp_write_slot(slot, 0x4, d4);
    scsp_write_slot(slot, 0x5, d5);
    scsp_write_slot(slot, 0x6, (uint16_t)(tl & 0xFF));
    scsp_write_slot(slot, 0x7, d7);
    scsp_write_slot(slot, 0x8, oct_bits);
    scsp_write_slot(slot, 0x9, 0x0000);
    scsp_write_slot(slot, 0xA, 0x0000);
    scsp_write_slot(slot, 0xB, d_b);
}

/* ── Voice Allocation ─────────────────────────────────────────── */

int scsp_voice_note_on(scsp_voice_alloc_t *alloc, const scsp_fm_op_t *ops,
                       int num_ops, int midi_note, const scsp_wave_store_t *store)
{
    if (num_ops < 1 || num_ops > SCSP_MAX_OPS) return -1;

    int base = -1;
    for (int s = 0; s <= SCSP_MAX_SLOTS - num_ops; s++) {
        int ok = 1;
        for (int i = 0; i < num_ops; i++)
            if (alloc->slot_used[s + i]) { ok = 0; break; }
        if (ok) { base = s; break; }
    }
    if (base < 0) return -1;

    for (int i = 0; i < num_ops; i++) {
        scsp_program_slot(base + i, &ops[i], midi_note, ops, num_ops, store);
        alloc->slot_used[base + i] = 1;
    }

    for (int i = 0; i < num_ops; i++)
        scsp_key_on(base + i);

    int vi = alloc->num_voices;
    if (vi >= SCSP_MAX_SLOTS) return -1;
    alloc->voices[vi].active = 1;
    alloc->voices[vi].midi_note = midi_note;
    alloc->voices[vi].slot_base = base;
    alloc->voices[vi].num_ops = num_ops;
    alloc->num_voices++;

    return vi;
}

void scsp_voice_note_off(scsp_voice_alloc_t *alloc, int midi_note)
{
    for (int vi = 0; vi < alloc->num_voices; vi++) {
        scsp_voice_t *v = &alloc->voices[vi];
        if (!v->active || v->midi_note != midi_note) continue;
        for (int i = 0; i < v->num_ops; i++) {
            scsp_key_off(v->slot_base + i);
            alloc->slot_used[v->slot_base + i] = 0;
        }
        v->active = 0;
    }
    int write = 0;
    for (int read = 0; read < alloc->num_voices; read++) {
        if (alloc->voices[read].active) {
            if (write != read) alloc->voices[write] = alloc->voices[read];
            write++;
        }
    }
    alloc->num_voices = write;
}

void scsp_voice_all_off(scsp_voice_alloc_t *alloc)
{
    for (int vi = 0; vi < alloc->num_voices; vi++) {
        scsp_voice_t *v = &alloc->voices[vi];
        if (!v->active) continue;
        for (int i = 0; i < v->num_ops; i++) {
            scsp_key_off(v->slot_base + i);
            alloc->slot_used[v->slot_base + i] = 0;
        }
        v->active = 0;
    }
    alloc->num_voices = 0;
}
