/*
 * test_plugin.cpp — Standalone test for SCSP FM Synth DSP.
 *
 * Directly exercises the plugin's parameter/state API without DPF,
 * simulating what _applyPatch does from the UI side.
 *
 * Build:  c++ -std=c++17 -I. -Idpfwebui/dpf/distrho -include ../scsp_wasm/scsp_types.h \
 *         -D__AO_H -DCPUINTRF_H -D_SAT_HW_H_ -DOSD_CPU_H -DTEST_PLUGIN_STANDALONE \
 *         test_plugin.cpp ../scsp_wasm/scsp_wasm.c ../scsp_wasm/scsp.c \
 *         ../scsp_wasm/scspdsp.c ../scsp_wasm/scsp_waveforms.c scsp_voice.c \
 *         -o test_plugin -lm
 * Run:    ./test_plugin
 */

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <vector>
#include <string>

/* Include the SCSP voice layer directly */
extern "C" {
#include "scsp_voice.h"
extern void scsp_init(void);
extern int16_t *scsp_render(int num_samples);
}

/* ── Replicate plugin parameter layout ── */
#define MAX_OPS 6
#define PARAMS_PER_OP 14

enum OpParam {
    kOpFreqRatio = 0, kOpLevel, kOpAR, kOpD1R, kOpDL, kOpD2R, kOpRR,
    kOpFeedback, kOpMDL, kOpModSource, kOpWaveform, kOpLoopMode,
    kOpLoopStart, kOpLoopEnd,
};
enum GlobalParam {
    kNumOps = MAX_OPS * PARAMS_PER_OP,
    kIsCarrier0, kIsCarrier1, kIsCarrier2, kIsCarrier3, kIsCarrier4, kIsCarrier5,
    kProgramNumber,
    kParameterCount
};

static float fParams[kParameterCount];
static scsp_fm_op_t fOps[MAX_OPS];
static int fNumOps;
static scsp_voice_alloc_t fAlloc;
static scsp_wave_store_t fWaveStore;

static void rebuildOps() {
    fNumOps = (int)fParams[kNumOps];
    if (fNumOps < 1) fNumOps = 1;
    if (fNumOps > MAX_OPS) fNumOps = MAX_OPS;
    for (int i = 0; i < fNumOps; i++) {
        int b = i * PARAMS_PER_OP;
        fOps[i].freq_ratio  = fParams[b + kOpFreqRatio];
        fOps[i].level       = fParams[b + kOpLevel];
        fOps[i].ar          = (int)fParams[b + kOpAR];
        fOps[i].d1r         = (int)fParams[b + kOpD1R];
        fOps[i].dl          = (int)fParams[b + kOpDL];
        fOps[i].d2r         = (int)fParams[b + kOpD2R];
        fOps[i].rr          = (int)fParams[b + kOpRR];
        fOps[i].feedback    = fParams[b + kOpFeedback];
        fOps[i].mdl         = (int)fParams[b + kOpMDL];
        int src = (int)fParams[b + kOpModSource];
        fOps[i].mod_source  = src > 0 ? src - 1 : -1;
        fOps[i].is_carrier  = (int)fParams[kIsCarrier0 + i];
        fOps[i].waveform_id = (int)fParams[b + kOpWaveform];
        fOps[i].loop_mode   = (int)fParams[b + kOpLoopMode];
        fOps[i].loop_start  = (int)fParams[b + kOpLoopStart];
        fOps[i].loop_end    = (int)fParams[b + kOpLoopEnd];
    }
}

static void setParameterValue(int index, float value) {
    if (index >= 0 && index < kParameterCount) {
        fParams[index] = value;
        rebuildOps();
    }
}

/* Simulate _applyPatch: exactly the same calls as ui.js */
struct TonOp {
    float freq_ratio, level, feedback;
    int ar, d1r, dl, d2r, rr, mdl, mod_source, loop_mode, loop_start, loop_end;
    bool is_carrier;
    int pcm_length; /* 0 = no PCM */
};

static void applyPatch(const std::vector<TonOp>& ops) {
    int n = (int)ops.size();
    if (n > MAX_OPS) n = MAX_OPS;

    /* setState for PCM would go here — skipped for DSP-only test */

    setParameterValue(kNumOps, (float)n);
    for (int i = 0; i < MAX_OPS; i++) {
        int b = i * PARAMS_PER_OP;
        if (i < n) {
            const TonOp& o = ops[i];
            setParameterValue(b + 0,  o.freq_ratio);
            setParameterValue(b + 1,  o.level);
            setParameterValue(b + 2,  (float)o.ar);
            setParameterValue(b + 3,  (float)o.d1r);
            setParameterValue(b + 4,  (float)o.dl);
            setParameterValue(b + 5,  (float)o.d2r);
            setParameterValue(b + 6,  (float)o.rr);
            setParameterValue(b + 7,  o.feedback);
            setParameterValue(b + 8,  (float)o.mdl);
            setParameterValue(b + 9,  (float)(o.mod_source + 1)); /* -1→0, 0→1 */
            setParameterValue(b + 10, 0); /* waveform */
            setParameterValue(b + 11, (float)o.loop_mode);
            setParameterValue(b + 12, (float)o.loop_start);
            setParameterValue(b + 13, (float)(o.pcm_length > 0 ? o.pcm_length : o.loop_end));
            setParameterValue(kIsCarrier0 + i, o.is_carrier ? 1.f : 0.f);
        } else {
            setParameterValue(b + 0,  1.f);
            setParameterValue(b + 1,  0.8f);
            setParameterValue(b + 2,  31.f);
            setParameterValue(b + 3,  0.f);
            setParameterValue(b + 4,  0.f);
            setParameterValue(b + 5,  0.f);
            setParameterValue(b + 6,  14.f);
            setParameterValue(b + 7,  0.f);
            setParameterValue(b + 8,  0.f);
            setParameterValue(b + 9,  0.f);
            setParameterValue(b + 10, 0.f);
            setParameterValue(b + 11, 1.f);
            setParameterValue(b + 12, 0.f);
            setParameterValue(b + 13, 1024.f);
            setParameterValue(kIsCarrier0 + i, 0.f);
        }
    }
}

/* ── Test helpers ── */
static int passed = 0, failed = 0;
#define ASSERT(cond, msg) do { if (!(cond)) { printf("  FAIL: %s\n", msg); failed++; } else { passed++; } } while(0)
#define ASSERT_EQ(a, b, msg) do { if ((a) != (b)) { printf("  FAIL: %s (got %d, expected %d)\n", msg, (int)(a), (int)(b)); failed++; } else { passed++; } } while(0)
#define ASSERT_CLOSE(a, b, tol, msg) do { if (fabs((a)-(b)) > (tol)) { printf("  FAIL: %s (got %.4f, expected %.4f)\n", msg, (double)(a), (double)(b)); failed++; } else { passed++; } } while(0)

/* Render some audio and check it's not silent */
static bool renderHasAudio(int numSamples) {
    /* Trigger a note */
    scsp_voice_note_on(&fAlloc, fOps, fNumOps, 60, &fWaveStore);
    int16_t *buf = scsp_render(numSamples);
    float maxVal = 0;
    for (int i = 0; i < numSamples * 2; i++) {
        float v = fabsf((float)buf[i]);
        if (v > maxVal) maxVal = v;
    }
    scsp_voice_note_off(&fAlloc, 60);
    scsp_render(100); /* let release finish */
    return maxVal > 100; /* not silent */
}

int main() {
    printf("\n=== SCSP FM Synth DSP Test ===\n\n");

    /* Initialize */
    memset(&fAlloc, 0, sizeof(fAlloc));
    memset(&fWaveStore, 0, sizeof(fWaveStore));
    memset(fParams, 0, sizeof(fParams));
    scsp_voice_init(&fWaveStore);

    /* ── Test 1: Electric Piano preset via applyPatch ── */
    printf("--- Test 1: Electric Piano via applyPatch ---\n");
    {
        std::vector<TonOp> ops = {
            { 2.0f, 0.9f, 0.0f,  31,12,8,0,14,  0, -1,  1, 0, 1024,  false, 0 },
            { 1.0f, 0.8f, 0.0f,  31, 6,2,0,14,  9,  0,  1, 0, 1024,  true,  0 },
        };
        applyPatch(ops);

        ASSERT_EQ(fNumOps, 2, "numOps = 2");
        ASSERT_CLOSE(fOps[0].freq_ratio, 2.0f, 0.001f, "Op0 ratio = 2.0");
        ASSERT_CLOSE(fOps[0].level, 0.9f, 0.001f, "Op0 level = 0.9");
        ASSERT_EQ(fOps[0].ar, 31, "Op0 AR = 31");
        ASSERT_EQ(fOps[0].d1r, 12, "Op0 D1R = 12");
        ASSERT_EQ(fOps[0].dl, 8, "Op0 DL = 8");
        ASSERT_EQ(fOps[0].rr, 14, "Op0 RR = 14");
        ASSERT_EQ(fOps[0].is_carrier, 0, "Op0 is modulator");
        ASSERT_EQ(fOps[0].mod_source, -1, "Op0 mod_source = -1");

        ASSERT_CLOSE(fOps[1].freq_ratio, 1.0f, 0.001f, "Op1 ratio = 1.0");
        ASSERT_CLOSE(fOps[1].level, 0.8f, 0.001f, "Op1 level = 0.8");
        ASSERT_EQ(fOps[1].ar, 31, "Op1 AR = 31");
        ASSERT_EQ(fOps[1].d1r, 6, "Op1 D1R = 6");
        ASSERT_EQ(fOps[1].dl, 2, "Op1 DL = 2");
        ASSERT_EQ(fOps[1].mdl, 9, "Op1 MDL = 9");
        ASSERT_EQ(fOps[1].mod_source, 0, "Op1 mod_source = 0");
        ASSERT_EQ(fOps[1].is_carrier, 1, "Op1 is carrier");

        ASSERT(renderHasAudio(512), "EP produces audio");
    }

    /* ── Test 2: Switch to different patch ── */
    printf("\n--- Test 2: Switch to 1-op Bass ---\n");
    {
        std::vector<TonOp> ops = {
            { 0.5f, 0.95f, 0.2f,  28, 4, 2, 0, 10,  0, -1,  1, 0, 1024,  true, 0 },
        };
        applyPatch(ops);

        ASSERT_EQ(fNumOps, 1, "numOps = 1");
        ASSERT_CLOSE(fOps[0].freq_ratio, 0.5f, 0.001f, "Op0 ratio = 0.5");
        ASSERT_EQ(fOps[0].ar, 28, "Op0 AR = 28");
        ASSERT_EQ(fOps[0].d1r, 4, "Op0 D1R = 4");
        ASSERT_EQ(fOps[0].dl, 2, "Op0 DL = 2");
        ASSERT_EQ(fOps[0].rr, 10, "Op0 RR = 10");
        ASSERT_CLOSE(fOps[0].feedback, 0.2f, 0.001f, "Op0 feedback = 0.2");
        ASSERT_EQ(fOps[0].is_carrier, 1, "Op0 is carrier");

        ASSERT(renderHasAudio(512), "Bass produces audio");
    }

    /* ── Test 3: 3-op patch ── */
    printf("\n--- Test 3: 3-op patch ---\n");
    {
        std::vector<TonOp> ops = {
            { 3.0f, 0.7f, 0.3f,  25,10,6,2,8,   0, -1,  1, 0, 1024,  false, 0 },
            { 1.0f, 0.6f, 0.0f,  22, 6,3,0,10, 10,  0,  1, 0, 1024,  true,  0 },
            { 2.0f, 0.5f, 0.0f,  28, 8,4,0,12,  7,  0,  1, 0, 1024,  true,  0 },
        };
        applyPatch(ops);

        ASSERT_EQ(fNumOps, 3, "numOps = 3");
        ASSERT_EQ(fOps[0].ar, 25, "Op0 AR = 25");
        ASSERT_EQ(fOps[1].ar, 22, "Op1 AR = 22");
        ASSERT_EQ(fOps[2].ar, 28, "Op2 AR = 28");
        ASSERT_EQ(fOps[0].is_carrier, 0, "Op0 modulator");
        ASSERT_EQ(fOps[1].is_carrier, 1, "Op1 carrier");
        ASSERT_EQ(fOps[2].is_carrier, 1, "Op2 carrier");
        ASSERT_EQ(fOps[1].mdl, 10, "Op1 MDL = 10");
        ASSERT_EQ(fOps[2].mdl, 7, "Op2 MDL = 7");

        ASSERT(renderHasAudio(512), "3-op produces audio");
    }

    /* ── Test 4: Switching patches clears old state ── */
    printf("\n--- Test 4: Patch switching clears old state ---\n");
    {
        /* Set a 3-op patch */
        std::vector<TonOp> ops3 = {
            { 2.0f, 0.9f, 0.0f,  31,12,8,0,14,  0, -1,  1, 0, 1024,  false, 0 },
            { 1.0f, 0.8f, 0.0f,  31, 6,2,0,14,  9,  0,  1, 0, 1024,  true,  0 },
            { 4.0f, 0.5f, 0.0f,  31, 4,2,0,12,  0, -1,  1, 0, 1024,  false, 0 },
        };
        applyPatch(ops3);
        ASSERT_EQ(fNumOps, 3, "Before: numOps = 3");

        /* Switch to 1-op */
        std::vector<TonOp> ops1 = {
            { 1.0f, 0.7f, 0.0f,  20, 8,4,0,12,  0, -1,  1, 0, 1024,  true, 0 },
        };
        applyPatch(ops1);
        ASSERT_EQ(fNumOps, 1, "After: numOps = 1");
        ASSERT_EQ(fOps[0].ar, 20, "Op0 AR = 20 (not stale 31)");
        ASSERT_CLOSE(fOps[0].level, 0.7f, 0.001f, "Op0 level = 0.7");

        ASSERT(renderHasAudio(512), "1-op produces audio after switch");
    }

    /* ── Summary ── */
    printf("\n==================================================\n");
    printf("Passed: %d  Failed: %d\n", passed, failed);
    if (failed > 0) {
        printf("SOME TESTS FAILED\n");
        return 1;
    }
    printf("All tests passed!\n");
    return 0;
}
