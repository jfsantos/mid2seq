/*
 * SCSPSynthPlugin.cpp — SCSP FM Synthesizer DSP plugin.
 *
 * Supports up to 6 operators with arbitrary modulation routing.
 * Runs the aosdk SCSP emulator natively.
 */

#include "DistrhoPlugin.hpp"
#include <cstring>
#include <cmath>
#include <string>
#include <vector>

/* Minimal JSON number parser for load_patch state */
static double jsonNumber(const char* &p) {
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    char* end;
    double v = strtod(p, &end);
    p = end;
    return v;
}
static void jsonSkipTo(const char* &p, char c) {
    while (*p && *p != c) p++;
    if (*p == c) p++;
}

extern "C" {
#include "scsp_voice.h"
extern int16_t *scsp_render(int num_samples);
}

START_NAMESPACE_DISTRHO

/* ── Parameter layout ─────────────────────────────────────────── */
/* Per-operator: 14 params × 6 operators = 84 params
 * Global: numOps, carriers[6], programNum = 8 params
 * Total: 92 */

#define MAX_OPS 6
#define PARAMS_PER_OP 14

enum OpParam {
    kOpFreqRatio = 0,  /* 0.5-32 */
    kOpLevel,          /* 0-1 */
    kOpAR,             /* 0-31 */
    kOpD1R,            /* 0-31 */
    kOpDL,             /* 0-31 */
    kOpD2R,            /* 0-31 */
    kOpRR,             /* 0-31 */
    kOpFeedback,       /* 0-0.5 */
    kOpMDL,            /* 0-15 */
    kOpModSource,      /* -1 to 5 (mapped as 0-6: 0=none, 1=op1, ...) */
    kOpWaveform,       /* 0-9 built-in (sine,saw,sq,tri,organ,brass,strings,piano,flute,bass) */
    kOpLoopMode,       /* 0=off, 1=forward, 2=reverse, 3=ping-pong */
    kOpLoopStart,      /* 0-65535 sample index */
    kOpLoopEnd,        /* 0-65535 sample index */
};

enum GlobalParam {
    kNumOps = MAX_OPS * PARAMS_PER_OP,    /* 84: 1-6 */
    kIsCarrier0,                           /* 85 */
    kIsCarrier1,                           /* 86 */
    kIsCarrier2,                           /* 87 */
    kIsCarrier3,                           /* 88 */
    kIsCarrier4,                           /* 89 */
    kIsCarrier5,                           /* 90 */
    kProgramNumber,                        /* 91 */
    kParameterCount                        /* 92 */
};

static inline int opParamIndex(int op, int param) {
    return op * PARAMS_PER_OP + param;
}

/* ── Preset patches ───────────────────────────────────────────── */
struct Preset {
    const char *name;
    int numOps;
    struct { float ratio, level; int ar, d1r, dl, d2r, rr; float fb; int mdl, modSrc, isCarrier; } ops[MAX_OPS];
};

static const Preset kPresets[] = {
    { "Electric Piano", 2, {
        { 2.0f, 0.9f, 31,12,8,0,14, 0.0f, 0,-1, 0 },
        { 1.0f, 0.8f, 31, 6,2,0,14, 0.0f, 9, 0, 1 },
    }},
    { "Bell", 2, {
        { 3.5f, 0.9f, 31, 4,2,0, 8, 0.0f, 0,-1, 0 },
        { 1.0f, 0.7f, 31, 2,0,0, 6, 0.0f,11, 0, 1 },
    }},
    { "Brass", 2, {
        { 1.0f, 0.8f, 24, 4,2,0,14, 0.3f, 0,-1, 0 },
        { 1.0f, 0.8f, 22, 2,0,0,14, 0.0f, 9, 0, 1 },
    }},
    { "Organ", 2, {
        { 1.0f, 0.7f, 31, 0,0,0,20, 0.6f, 0,-1, 0 },
        { 1.0f, 0.8f, 31, 0,0,0,20, 0.0f, 8, 0, 1 },
    }},
    { "FM Bass", 2, {
        { 1.0f, 0.9f, 31,14,10,0,14,0.2f, 0,-1, 0 },
        { 1.0f, 0.9f, 31, 6, 4,0,14,0.0f,10, 0, 1 },
    }},
    { "Strings", 2, {
        { 1.002f,0.5f, 20, 0,0,0,16, 0.0f, 0,-1, 0 },
        { 1.0f, 0.7f, 18, 0,0,0,14, 0.0f, 7, 0, 1 },
    }},
    { "Clavinet", 2, {
        { 3.0f, 0.9f, 31,16,14,0,18, 0.0f, 0,-1, 0 },
        { 1.0f, 0.8f, 31,10, 6,0,16, 0.0f,10, 0, 1 },
    }},
    { "Marimba", 2, {
        { 4.0f, 0.8f, 31,18,16,0,20, 0.0f, 0,-1, 0 },
        { 1.0f, 0.8f, 31, 8, 4,0,12, 0.0f, 9, 0, 1 },
    }},
    { "Electric Piano 2", 3, {
        { 14.0f, 0.4f, 31,14,12,0,16, 0.0f, 0,-1, 0 },
        {  1.0f, 0.7f, 31,10, 6,0,14, 0.0f, 8, 0, 0 },
        {  1.0f, 0.8f, 31, 4, 2,0,12, 0.0f, 9, 1, 1 },
    }},
    { "Metallic", 3, {
        { 1.414f, 0.6f, 31, 6,3,0,10, 0.4f, 0,-1, 0 },
        { 3.82f,  0.5f, 31, 8,4,0,12, 0.0f, 0,-1, 0 },
        { 1.0f,   0.7f, 31, 4,2,0,10, 0.0f,10, 0, 1 },
    }},
    { "4-Op E.Piano", 4, {
        { 5.0f, 0.3f, 31,16,14,0,16, 0.2f, 0,-1, 0 },
        { 1.0f, 0.5f, 31,12, 8,0,14, 0.0f, 7, 0, 0 },
        { 1.0f, 0.7f, 31, 8, 4,0,12, 0.0f, 8, 1, 0 },
        { 1.0f, 0.8f, 31, 4, 2,0,12, 0.0f, 9, 2, 1 },
    }},
    { "Sine", 1, {
        { 1.0f, 0.8f, 31, 0,0,0,14, 0.0f, 0,-1, 1 },
    }},
};
static const int kNumPresets = sizeof(kPresets) / sizeof(kPresets[0]);

/* ── Plugin ───────────────────────────────────────────────────── */

class SCSPSynthPlugin : public Plugin
{
public:
    SCSPSynthPlugin()
        : Plugin(kParameterCount, kNumPresets, 3 + MAX_OPS /* patch + wave_0..wave_5 + kit_path + load_patch */)
    {
        std::memset(&fAlloc, 0, sizeof(fAlloc));
        std::memset(&fWaveStore, 0, sizeof(fWaveStore));
        for (int i = 0; i < MAX_OPS; i++) fCustomWaveIds[i] = -1;
        scsp_voice_init(&fWaveStore);
        loadProgram(0);
    }

    const char* getLabel()   const override { return "SCSPFMSynth"; }
    const char* getMaker()   const override { return "mid2seq"; }
    const char* getLicense()  const override { return "MAME (non-commercial)"; }
    uint32_t    getVersion() const override { return d_version(0, 2, 0); }
    int64_t     getUniqueId() const override { return d_cconst('S','C','F','M'); }

    void initAudioPort(const bool input, uint32_t index, AudioPort& port) override
    {
        port.groupId = kPortGroupStereo;
        Plugin::initAudioPort(input, index, port);
    }

    /* ── Parameters ── */
    void initParameter(uint32_t index, Parameter& param) override
    {
        param.hints = kParameterIsAutomatable;

        if (index < MAX_OPS * PARAMS_PER_OP) {
            int op = index / PARAMS_PER_OP;
            int p  = index % PARAMS_PER_OP;
            char buf[32];

            switch (p) {
            case kOpFreqRatio:  std::snprintf(buf,32,"Op%d Ratio",op+1);    param.name=buf; param.ranges={0.5f,32.f,1.f}; break;
            case kOpLevel:      std::snprintf(buf,32,"Op%d Level",op+1);    param.name=buf; param.ranges={0.f,1.f,0.8f}; break;
            case kOpAR:         std::snprintf(buf,32,"Op%d AR",op+1);       param.name=buf; param.hints|=kParameterIsInteger; param.ranges={0,31,31}; break;
            case kOpD1R:        std::snprintf(buf,32,"Op%d D1R",op+1);      param.name=buf; param.hints|=kParameterIsInteger; param.ranges={0,31,0}; break;
            case kOpDL:         std::snprintf(buf,32,"Op%d DL",op+1);       param.name=buf; param.hints|=kParameterIsInteger; param.ranges={0,31,0}; break;
            case kOpD2R:        std::snprintf(buf,32,"Op%d D2R",op+1);      param.name=buf; param.hints|=kParameterIsInteger; param.ranges={0,31,0}; break;
            case kOpRR:         std::snprintf(buf,32,"Op%d RR",op+1);       param.name=buf; param.hints|=kParameterIsInteger; param.ranges={0,31,14}; break;
            case kOpFeedback:   std::snprintf(buf,32,"Op%d Feedback",op+1); param.name=buf; param.ranges={0.f,0.5f,0.f}; break;
            case kOpMDL:        std::snprintf(buf,32,"Op%d MDL",op+1);      param.name=buf; param.hints|=kParameterIsInteger; param.ranges={0,15,0}; break;
            case kOpModSource:  std::snprintf(buf,32,"Op%d ModSrc",op+1);   param.name=buf; param.hints|=kParameterIsInteger; param.ranges={0,6,0}; break;
            case kOpWaveform:   std::snprintf(buf,32,"Op%d Waveform",op+1); param.name=buf; param.hints|=kParameterIsInteger; param.ranges={0,(float)(SCSP_NUM_BUILTINS-1),0}; break;
            case kOpLoopMode:   std::snprintf(buf,32,"Op%d LoopMode",op+1); param.name=buf; param.hints|=kParameterIsInteger; param.ranges={0,3,1}; break;
            case kOpLoopStart:  std::snprintf(buf,32,"Op%d LoopStart",op+1);param.name=buf; param.hints|=kParameterIsInteger; param.ranges={0,65535,0}; break;
            case kOpLoopEnd:    std::snprintf(buf,32,"Op%d LoopEnd",op+1);  param.name=buf; param.hints|=kParameterIsInteger; param.ranges={0,65535,(float)SCSP_WAVE_LEN}; break;
            }
        } else if (index == kNumOps) {
            param.name = "Num Operators";
            param.hints |= kParameterIsInteger;
            param.ranges = {1, 6, 2};
        } else if (index >= kIsCarrier0 && index <= kIsCarrier5) {
            char buf[32];
            std::snprintf(buf, 32, "Op%d Carrier", (int)(index - kIsCarrier0 + 1));
            param.name = buf;
            param.hints |= kParameterIsInteger | kParameterIsBoolean;
            param.ranges = {0, 1, (index == kIsCarrier0 + 1) ? 1.f : 0.f}; /* op2 carrier by default */
        } else if (index == kProgramNumber) {
            param.name = "Program Number";
            param.hints |= kParameterIsInteger;
            param.ranges = {0, 15, 0};
        }
    }

    float getParameterValue(uint32_t index) const override
    {
        return (index < kParameterCount) ? fParams[index] : 0.f;
    }

    void setParameterValue(uint32_t index, float value) override
    {
        if (index < kParameterCount) {
            fParams[index] = value;
            rebuildOps();
        }
    }

    /* ── Programs ── */
    void initProgramName(uint32_t index, String& name) override
    {
        if (index < (uint32_t)kNumPresets)
            name = kPresets[index].name;
    }

    void loadProgram(uint32_t index) override
    {
        if (index >= (uint32_t)kNumPresets) return;
        const Preset& pr = kPresets[index];

        /* Clear all params to defaults */
        for (int i = 0; i < kParameterCount; i++) fParams[i] = 0.f;

        fParams[kNumOps] = (float)pr.numOps;

        for (int i = 0; i < pr.numOps && i < MAX_OPS; i++) {
            const auto& o = pr.ops[i];
            fParams[opParamIndex(i, kOpFreqRatio)]  = o.ratio;
            fParams[opParamIndex(i, kOpLevel)]      = o.level;
            fParams[opParamIndex(i, kOpAR)]         = (float)o.ar;
            fParams[opParamIndex(i, kOpD1R)]        = (float)o.d1r;
            fParams[opParamIndex(i, kOpDL)]         = (float)o.dl;
            fParams[opParamIndex(i, kOpD2R)]        = (float)o.d2r;
            fParams[opParamIndex(i, kOpRR)]         = (float)o.rr;
            fParams[opParamIndex(i, kOpFeedback)]   = o.fb;
            fParams[opParamIndex(i, kOpMDL)]        = (float)o.mdl;
            fParams[opParamIndex(i, kOpModSource)]  = (float)(o.modSrc + 1); /* -1→0, 0→1, ... */
            fParams[opParamIndex(i, kOpWaveform)]   = 0.f; /* sine default for all presets */
            fParams[opParamIndex(i, kOpLoopMode)]   = 1.f; /* forward loop */
            fParams[opParamIndex(i, kOpLoopStart)]  = 0.f;
            fParams[opParamIndex(i, kOpLoopEnd)]    = 1024.f;
            fParams[kIsCarrier0 + i]                = (float)o.isCarrier;
        }
        /* Default inactive ops */
        for (int i = pr.numOps; i < MAX_OPS; i++) {
            fParams[opParamIndex(i, kOpFreqRatio)] = 1.f;
            fParams[opParamIndex(i, kOpLevel)]     = 0.8f;
            fParams[opParamIndex(i, kOpAR)]        = 31.f;
            fParams[opParamIndex(i, kOpRR)]        = 14.f;
            fParams[opParamIndex(i, kOpWaveform)]  = 0.f;
            fParams[opParamIndex(i, kOpLoopMode)]  = 1.f;
            fParams[opParamIndex(i, kOpLoopStart)] = 0.f;
            fParams[opParamIndex(i, kOpLoopEnd)]   = 1024.f;
        }
        rebuildOps();
    }

    /* ── State (patch + custom waveforms) ── */
    void initState(uint32_t index, State& state) override
    {
        if (index == 0) {
            state.key = "patch"; state.label = "Patch data"; state.defaultValue = "";
        } else if (index >= 1 && index <= MAX_OPS) {
            char buf[16];
            std::snprintf(buf, 16, "wave_%d", (int)(index - 1));
            state.key = buf;
            state.label = buf;
            state.defaultValue = "";
        } else if (index == 1 + MAX_OPS) {
            state.key = "kit_path"; state.label = "Kit file path"; state.defaultValue = "";
        } else if (index == 2 + MAX_OPS) {
            state.key = "load_patch"; state.label = "Load patch data"; state.defaultValue = "";
        }
    }

    void setState(const char* key, const char* value) override
    {
        /* Handle kit_path state */
        if (std::strcmp(key, "kit_path") == 0) {
            fKitPath = value ? value : "";
            return;
        }
        /* Handle load_patch: JSON with operator params + base64 PCM.
         * Format: "numOps|op0_ratio,op0_level,op0_ar,op0_d1r,op0_dl,op0_d2r,op0_rr,op0_fb,op0_mdl,op0_ms,op0_carrier,op0_lm,op0_ls,op0_le,op0_pcmLen,op0_pcmB64|op1_...|..."
         * This bypasses the setParameterValue round-trip entirely. */
        if (std::strcmp(key, "load_patch") == 0) {
            if (!value || !value[0]) return;
            const char* p = value;

            /* Parse numOps */
            int numOps = (int)jsonNumber(p);
            if (numOps < 1) numOps = 1;
            if (numOps > MAX_OPS) numOps = MAX_OPS;

            /* Clear all params */
            for (int i = 0; i < kParameterCount; i++) fParams[i] = 0.f;
            fParams[kNumOps] = (float)numOps;

            /* Parse each operator */
            for (int i = 0; i < numOps && *p; i++) {
                jsonSkipTo(p, '|');
                float ratio   = (float)jsonNumber(p); jsonSkipTo(p, ',');
                float level   = (float)jsonNumber(p); jsonSkipTo(p, ',');
                float ar      = (float)jsonNumber(p); jsonSkipTo(p, ',');
                float d1r     = (float)jsonNumber(p); jsonSkipTo(p, ',');
                float dl      = (float)jsonNumber(p); jsonSkipTo(p, ',');
                float d2r     = (float)jsonNumber(p); jsonSkipTo(p, ',');
                float rr      = (float)jsonNumber(p); jsonSkipTo(p, ',');
                float fb      = (float)jsonNumber(p); jsonSkipTo(p, ',');
                float mdl     = (float)jsonNumber(p); jsonSkipTo(p, ',');
                float ms      = (float)jsonNumber(p); jsonSkipTo(p, ',');
                float carrier = (float)jsonNumber(p); jsonSkipTo(p, ',');
                float lm      = (float)jsonNumber(p); jsonSkipTo(p, ',');
                float ls      = (float)jsonNumber(p); jsonSkipTo(p, ',');
                float le      = (float)jsonNumber(p); jsonSkipTo(p, ',');
                int pcmLen    = (int)jsonNumber(p);   jsonSkipTo(p, ',');

                fParams[opParamIndex(i, kOpFreqRatio)] = ratio;
                fParams[opParamIndex(i, kOpLevel)]     = level;
                fParams[opParamIndex(i, kOpAR)]        = ar;
                fParams[opParamIndex(i, kOpD1R)]       = d1r;
                fParams[opParamIndex(i, kOpDL)]        = dl;
                fParams[opParamIndex(i, kOpD2R)]       = d2r;
                fParams[opParamIndex(i, kOpRR)]        = rr;
                fParams[opParamIndex(i, kOpFeedback)]  = fb;
                fParams[opParamIndex(i, kOpMDL)]       = mdl;
                fParams[opParamIndex(i, kOpModSource)] = ms;
                fParams[kIsCarrier0 + i]               = carrier;
                fParams[opParamIndex(i, kOpLoopMode)]  = lm;
                fParams[opParamIndex(i, kOpLoopStart)] = ls;
                fParams[opParamIndex(i, kOpLoopEnd)]   = le;

                /* Load PCM waveform if present */
                if (pcmLen > 0) {
                    /* Remaining text until next | or end is base64 PCM */
                    const char* b64start = p;
                    const char* b64end = b64start;
                    while (*b64end && *b64end != '|') b64end++;
                    std::string b64str(b64start, b64end - b64start);
                    p = b64end;

                    std::vector<uint8_t> raw = decodeBase64(b64str.c_str());
                    int numSamples = (int)(raw.size() / 2);
                    if (numSamples > 0) {
                        const int16_t *samples = reinterpret_cast<const int16_t*>(raw.data());
                        int waveId = scsp_wave_store_add(&fWaveStore, samples, numSamples,
                                                          0, numSamples, 1);
                        if (waveId >= 0) {
                            fCustomWaveIds[i] = waveId;
                            fParams[opParamIndex(i, kOpWaveform)] = (float)waveId;
                            fParams[opParamIndex(i, kOpLoopEnd)]  = (float)numSamples;
                        }
                    }
                }
            }

            /* Default inactive ops */
            for (int i = numOps; i < MAX_OPS; i++) {
                fParams[opParamIndex(i, kOpFreqRatio)] = 1.f;
                fParams[opParamIndex(i, kOpLevel)]     = 0.8f;
                fParams[opParamIndex(i, kOpAR)]        = 31.f;
                fParams[opParamIndex(i, kOpRR)]        = 14.f;
                fParams[opParamIndex(i, kOpWaveform)]  = 0.f;
                fParams[opParamIndex(i, kOpLoopMode)]  = 1.f;
                fParams[opParamIndex(i, kOpLoopEnd)]   = 1024.f;
            }

            rebuildOps();
            return;
        }
        /* Handle custom waveform: key = "wave_N", value = base64-encoded int16 LE */
        if (std::strncmp(key, "wave_", 5) == 0) {
            int opIdx = key[5] - '0';
            if (opIdx < 0 || opIdx >= MAX_OPS || !value || !value[0]) return;

            /* Decode base64 */
            std::vector<uint8_t> raw = decodeBase64(value);
            if (raw.size() < 4) return;

            int numSamples = (int)(raw.size() / 2);
            const int16_t *samples = reinterpret_cast<const int16_t*>(raw.data());

            /* Add to wave store */
            int waveId = scsp_wave_store_add(&fWaveStore, samples, numSamples,
                                              0, numSamples, 1 /* forward loop */);
            if (waveId >= 0) {
                fCustomWaveIds[opIdx] = waveId;
                /* Update the operator's waveform_id parameter */
                fParams[opParamIndex(opIdx, kOpWaveform)] = (float)waveId;
                fParams[opParamIndex(opIdx, kOpLoopEnd)]  = (float)numSamples;
                rebuildOps();
            }
        }
    }

    String getState(const char* key) const override
    {
        if (std::strcmp(key, "kit_path") == 0) {
            return String(fKitPath.c_str());
        }
        return String();
    }

    /* ── Audio + MIDI ── */
    void run(const float**, float** outputs, uint32_t frames,
             const MidiEvent* midiEvents, uint32_t midiEventCount) override
    {
        uint32_t eventIdx = 0, framesDone = 0;
        while (framesDone < frames) {
            uint32_t nextFrame = frames;
            if (eventIdx < midiEventCount) {
                nextFrame = midiEvents[eventIdx].frame;
                if (nextFrame > frames) nextFrame = frames;
            }
            uint32_t toRender = nextFrame - framesDone;
            if (toRender > 0) {
                int16_t *buf = scsp_render((int)toRender);
                for (uint32_t i = 0; i < toRender; i++) {
                    outputs[0][framesDone + i] = buf[i * 2]     / 32768.0f;
                    outputs[1][framesDone + i] = buf[i * 2 + 1] / 32768.0f;
                }
                framesDone += toRender;
            }
            while (eventIdx < midiEventCount && midiEvents[eventIdx].frame <= framesDone) {
                handleMidi(midiEvents[eventIdx]);
                eventIdx++;
            }
        }
    }

private:
    float fParams[kParameterCount];
    scsp_fm_op_t fOps[MAX_OPS];
    int fNumOps;
    scsp_voice_alloc_t fAlloc;
    scsp_wave_store_t fWaveStore;
    int fCustomWaveIds[MAX_OPS]; /* per-op custom wave store IDs, -1 = none */
    std::string fKitPath;

    static std::vector<uint8_t> decodeBase64(const char *input)
    {
        static const uint8_t T[128] = {
            64,64,64,64,64,64,64,64,64,64,64,64,64,64,64,64,
            64,64,64,64,64,64,64,64,64,64,64,64,64,64,64,64,
            64,64,64,64,64,64,64,64,64,64,64,62,64,64,64,63,
            52,53,54,55,56,57,58,59,60,61,64,64,64,64,64,64,
            64, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9,10,11,12,13,14,
            15,16,17,18,19,20,21,22,23,24,25,64,64,64,64,64,
            64,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,
            41,42,43,44,45,46,47,48,49,50,51,64,64,64,64,64
        };
        std::vector<uint8_t> out;
        int val = 0, bits = -8;
        for (const char *p = input; *p; p++) {
            unsigned char c = (unsigned char)*p;
            if (c >= 128 || T[c] >= 64) continue;
            val = (val << 6) | T[c];
            bits += 6;
            if (bits >= 0) { out.push_back((uint8_t)((val >> bits) & 0xFF)); bits -= 8; }
        }
        return out;
    }

    void rebuildOps()
    {
        fNumOps = (int)fParams[kNumOps];
        if (fNumOps < 1) fNumOps = 1;
        if (fNumOps > MAX_OPS) fNumOps = MAX_OPS;

        for (int i = 0; i < fNumOps; i++) {
            fOps[i].freq_ratio  = fParams[opParamIndex(i, kOpFreqRatio)];
            fOps[i].freq_fixed  = 0;
            fOps[i].level       = fParams[opParamIndex(i, kOpLevel)];
            fOps[i].ar          = (int)fParams[opParamIndex(i, kOpAR)];
            fOps[i].d1r         = (int)fParams[opParamIndex(i, kOpD1R)];
            fOps[i].dl          = (int)fParams[opParamIndex(i, kOpDL)];
            fOps[i].d2r         = (int)fParams[opParamIndex(i, kOpD2R)];
            fOps[i].rr          = (int)fParams[opParamIndex(i, kOpRR)];
            fOps[i].feedback    = fParams[opParamIndex(i, kOpFeedback)];
            fOps[i].mdl         = (int)fParams[opParamIndex(i, kOpMDL)];
            int src = (int)fParams[opParamIndex(i, kOpModSource)];
            fOps[i].mod_source  = src > 0 ? src - 1 : -1;
            fOps[i].is_carrier  = (int)fParams[kIsCarrier0 + i];
            fOps[i].waveform_id = (int)fParams[opParamIndex(i, kOpWaveform)];
            fOps[i].loop_mode   = (int)fParams[opParamIndex(i, kOpLoopMode)];
            fOps[i].loop_start  = (int)fParams[opParamIndex(i, kOpLoopStart)];
            fOps[i].loop_end    = (int)fParams[opParamIndex(i, kOpLoopEnd)];
        }
    }

    void handleMidi(const MidiEvent& ev)
    {
        if (ev.size < 1) return;
        const uint8_t *d = ev.size > MidiEvent::kDataSize ? ev.dataExt : ev.data;
        uint8_t status = d[0] & 0xF0;
        uint8_t note   = (ev.size > 1) ? d[1] : 0;
        uint8_t vel    = (ev.size > 2) ? d[2] : 0;

        switch (status) {
        case 0x90:
            if (vel > 0) scsp_voice_note_on(&fAlloc, fOps, fNumOps, note, &fWaveStore);
            else         scsp_voice_note_off(&fAlloc, note);
            break;
        case 0x80:
            scsp_voice_note_off(&fAlloc, note);
            break;
        case 0xB0:
            if (note == 120 || note == 123) scsp_voice_all_off(&fAlloc);
            break;
        }
    }

    DISTRHO_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(SCSPSynthPlugin)
};

Plugin* createPlugin() { return new SCSPSynthPlugin; }

END_NAMESPACE_DISTRHO
