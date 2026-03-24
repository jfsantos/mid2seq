/*
 * SCSPSynthUI.cpp — WebView UI for the SCSP FM Synth plugin.
 *
 * Minimal C++ wrapper that loads the web UI from the ui/ directory.
 * All actual UI logic is in ui/index.html + ui/ui.js.
 */

#include "WebUI.hpp"

START_NAMESPACE_DISTRHO

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
        /* Web view is ready, DOM loaded, dpf.js injected */
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
