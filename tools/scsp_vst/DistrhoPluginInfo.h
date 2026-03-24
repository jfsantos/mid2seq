/*
 * SCSP FM Synth — Saturn-accurate FM synthesis plugin.
 * Uses the aosdk SCSP (YMF292-F) emulator for hardware-accurate audio.
 */

#ifndef DISTRHO_PLUGIN_INFO_H
#define DISTRHO_PLUGIN_INFO_H

#define DISTRHO_PLUGIN_NAME    "SCSP FM Synth"
#define DISTRHO_PLUGIN_URI     "https://github.com/jfsantos/mid2seq/scsp-fm-synth"
#define DISTRHO_PLUGIN_CLAP_ID "com.mid2seq.scsp-fm-synth"

#define DISTRHO_PLUGIN_NUM_INPUTS     0
#define DISTRHO_PLUGIN_NUM_OUTPUTS    2

#define DISTRHO_PLUGIN_IS_RT_SAFE     1
#define DISTRHO_PLUGIN_IS_SYNTH       1
#define DISTRHO_PLUGIN_WANT_MIDI_INPUT  1
#define DISTRHO_PLUGIN_WANT_MIDI_OUTPUT 0
#define DISTRHO_PLUGIN_WANT_STATE     1
#define DISTRHO_PLUGIN_WANT_FULL_STATE 1
#define DISTRHO_PLUGIN_WANT_PROGRAMS  1
#define DISTRHO_PLUGIN_WANT_LATENCY   0
#define DISTRHO_PLUGIN_WANT_TIMEPOS   0
#define DISTRHO_PLUGIN_WANT_DIRECT_ACCESS 0

#define DISTRHO_PLUGIN_HAS_UI          1
#define DISTRHO_PLUGIN_HAS_EMBED_UI    1
#define DISTRHO_PLUGIN_HAS_EXTERNAL_UI 1

#define DISTRHO_UI_USE_NANOVG        0
#define DISTRHO_UI_USER_RESIZABLE    1
#define DISTRHO_UI_URI DISTRHO_PLUGIN_URI "#UI"

#endif /* DISTRHO_PLUGIN_INFO_H */
