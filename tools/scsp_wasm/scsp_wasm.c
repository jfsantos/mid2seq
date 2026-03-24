/*
 * scsp_wasm.c — Minimal WASM wrapper for the SCSP (YMF292-F) emulator.
 *
 * Extracts the SCSP core from aosdk and exposes a clean API for the
 * FM patch editor to call from JavaScript via Emscripten.
 *
 * Build: emcc -O2 -DLSB_FIRST -s WASM=1 -s EXPORTED_FUNCTIONS=[...] \
 *        -s MODULARIZE=1 -s EXPORT_NAME=SCSPModule --no-entry \
 *        -o scsp.js scsp_wasm.c scsp.c scspdsp.c
 */

#include <emscripten.h>

/* scsp_types.h is force-included via -include flag in the Makefile.
   It provides all types, stubs, and guard defines. */
#include "scsp.h"

/* ── Globals provided by this file ──────────────────────────────── */

/* sat_ram is declared extern in scsp_types.h — define it here */
uint8 sat_ram[512 * 1024];

/* stv_scu is referenced by scsp.c */
static UINT32 stv_scu_stub[256];
UINT32 *stv_scu = stv_scu_stub;

/* IRQ callback — no-op for standalone use */
static void dummy_irq_cb(int irq) { (void)irq; }

/* ── SCSP instance ─────────────────────────────────────────────── */

/* scsp.c declares: extern struct _SCSP SCSP; — we provide it */
/* (scsp.c also includes scsplfo.c internally) */

/* Output buffer for rendering */
#define MAX_RENDER_SAMPLES 8192
static int16_t render_buf[MAX_RENDER_SAMPLES * 2]; /* stereo interleaved */

/* ── Exported WASM API ─────────────────────────────────────────── */

EMSCRIPTEN_KEEPALIVE
void scsp_init(void) {
    /* Zero all state */
    memset(&SCSP, 0, sizeof(struct _SCSP));
    memset(sat_ram, 0, sizeof(sat_ram));

    /* Set up the interface */
    struct SCSPinterface intf;
    memset(&intf, 0, sizeof(intf));
    intf.num = 1;
    intf.region[0] = sat_ram;
    intf.mixing_level[0] = 0;
    intf.irq_callback[0] = dummy_irq_cb;

    scsp_start(&intf);

    /* Set master volume to max (MVOL=0xF) */
    SCSP_0_w(0, 0x000F, 0x0000);
}

EMSCRIPTEN_KEEPALIVE
uint8_t *scsp_get_ram_ptr(void) {
    return sat_ram;
}

EMSCRIPTEN_KEEPALIVE
uint32_t scsp_get_ram_size(void) {
    return sizeof(sat_ram);
}

/*
 * Write a 16-bit value to the SCSP register space.
 * addr: byte address in SCSP register map (0x000 - 0xFFF)
 *   Slots: 0x000-0x3FF (32 slots × 0x20 bytes each)
 *   Global: 0x400+
 */
EMSCRIPTEN_KEEPALIVE
void scsp_write_reg(uint32_t addr, uint16_t value) {
    SCSP_0_w(addr / 2, value, 0x0000);
}

/*
 * Write a slot register word directly.
 * slot: 0-31
 * reg_word: word offset within slot (0x0 - 0xF, maps to data[0x0]..data[0xF])
 * value: 16-bit register value
 */
EMSCRIPTEN_KEEPALIVE
void scsp_write_slot(int slot, int reg_word, uint16_t value) {
    int addr = slot * 0x20 + reg_word * 2;
    SCSP_0_w(addr / 2, value, 0x0000);
}

/*
 * Trigger key-on for a slot.
 * The SCSP requires EG.state == RELEASE before a slot can start.
 * We first key-off (to force RELEASE), then key-on.
 */
EMSCRIPTEN_KEEPALIVE
void scsp_key_on(int slot) {
    int addr = slot * 0x20;
    uint16_t cur = SCSP.Slots[slot].udata.data[0x0];

    /* Step 1: ensure slot is in RELEASE state by writing KEYONB=0 + KEYONEX */
    SCSP_0_w(addr / 2, (cur & ~0x0800) | 0x1000, 0x0000);

    /* Step 2: now set KEYONB=1 + KEYONEX to start the slot */
    cur = SCSP.Slots[slot].udata.data[0x0];
    SCSP_0_w(addr / 2, cur | 0x0800 | 0x1000, 0x0000);
}

/*
 * Trigger key-off for a slot.
 * Clears KEYONB bit, writes KEYONEX to execute release.
 */
EMSCRIPTEN_KEEPALIVE
void scsp_key_off(int slot) {
    int addr = slot * 0x20;
    uint16_t cur = SCSP.Slots[slot].udata.data[0x0];
    uint16_t val = (cur & ~0x0800) | 0x1000;  /* clear KEYONB, set KEYONEX */
    SCSP_0_w(addr / 2, val, 0x0000);
}

/*
 * Render audio samples.
 * Returns pointer to interleaved stereo int16 buffer (L,R,L,R,...).
 * num_samples: number of stereo sample pairs to render (max MAX_RENDER_SAMPLES).
 */
EMSCRIPTEN_KEEPALIVE
int16_t *scsp_render(int num_samples) {
    if (num_samples > MAX_RENDER_SAMPLES) num_samples = MAX_RENDER_SAMPLES;

    for (int i = 0; i < num_samples; i++) {
        stereo_sample_t sample;
        SCSP_Update(NULL, NULL, &sample);
        render_buf[i * 2]     = sample.l;
        render_buf[i * 2 + 1] = sample.r;
    }
    return render_buf;
}

/*
 * Get pointer to the render buffer (for JS to read directly from WASM heap).
 */
EMSCRIPTEN_KEEPALIVE
int16_t *scsp_get_render_buf(void) {
    return render_buf;
}
