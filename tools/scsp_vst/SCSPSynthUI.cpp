/*
 * SCSPSynthUI.cpp — WebView UI for the SCSP FM Synth plugin.
 *
 * Loads the web UI from the ui/ directory.
 * Provides native file I/O bridge for the shared kit workflow.
 */

#include "WebUI.hpp"
#include "distrho/extra/Base64.hpp"
#include <fstream>
#include <string>
#include <vector>

START_NAMESPACE_DISTRHO

/* Base64 encode (not provided by DPF's Base64.hpp which only has decode) */
static std::string encodeBase64(const uint8_t* data, size_t len) {
    static const char T[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;
    out.reserve(((len + 2) / 3) * 4);
    for (size_t i = 0; i < len; i += 3) {
        uint32_t n = (uint32_t)data[i] << 16;
        if (i + 1 < len) n |= (uint32_t)data[i + 1] << 8;
        if (i + 2 < len) n |= data[i + 2];
        out.push_back(T[(n >> 18) & 0x3F]);
        out.push_back(T[(n >> 12) & 0x3F]);
        out.push_back((i + 1 < len) ? T[(n >> 6) & 0x3F] : '=');
        out.push_back((i + 2 < len) ? T[n & 0x3F] : '=');
    }
    return out;
}

class SCSPSynthUI : public WebUI
{
public:
    SCSPSynthUI()
        : WebUI(800 /*width*/, 600 /*height*/, "#0f0f23" /*background*/, true /*load*/)
    {
    }

    ~SCSPSynthUI() {}

protected:
    void onDocumentReady() override
    {
        /* Register file I/O handlers for the shared kit workflow */

        setFunctionHandler("readBinaryFile", 1, [this](const Variant& args, uintptr_t origin) {
            String path = args[0].getString();
            std::ifstream f(static_cast<const char*>(path), std::ios::binary | std::ios::ate);
            if (!f) {
                callback("readBinaryFile", Variant::createArray({ String("") }), origin);
                return;
            }
            std::streamsize size = f.tellg();
            f.seekg(0, std::ios::beg);
            std::vector<char> buf(size);
            if (!f.read(buf.data(), size)) {
                callback("readBinaryFile", Variant::createArray({ String("") }), origin);
                return;
            }
            /* Base64 encode the file contents */
            std::string b64str = encodeBase64(
                reinterpret_cast<const uint8_t*>(buf.data()), static_cast<size_t>(size));
            callback("readBinaryFile", Variant::createArray({ String(b64str.c_str()) }), origin);
        });

        setFunctionHandler("writeBinaryFile", 2, [this](const Variant& args, uintptr_t origin) {
            String path = args[0].getString();
            String b64 = args[1].getString();
            std::vector<uint8_t> raw = d_getChunkFromBase64String(b64);
            std::ofstream f(static_cast<const char*>(path), std::ios::binary);
            if (!f) {
                callback("writeBinaryFile", Variant::createArray({ false }), origin);
                return;
            }
            f.write(reinterpret_cast<const char*>(raw.data()), raw.size());
            f.close();
            callback("writeBinaryFile", Variant::createArray({ true }), origin);
        });
    }

    void onMessageReceived(const Variant& payload, uintptr_t source) override
    {
        (void)payload;
        (void)source;
    }

    DISTRHO_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(SCSPSynthUI)
};

UI* createUI()
{
    return new SCSPSynthUI;
}

END_NAMESPACE_DISTRHO
