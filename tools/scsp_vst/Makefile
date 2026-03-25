#!/usr/bin/make -f
# SCSP FM Synth — VST3/CLAP/LV2 plugin
# Uses DPFWebUI for WebView-based UI

# --------------------------------------------------------------
# Project name

NAME = scsp-fm-synth

# --------------------------------------------------------------
# Project version

DPF_WEBUI_PROJECT_VERSION = 1

# --------------------------------------------------------------
# Web UI

DPF_WEBUI_INJECT_FRAMEWORK_JS = true
DPF_WEBUI_WEB_UI_PATH = ui

# --------------------------------------------------------------
# Source files

# SCSP emulator (from aosdk, compiled natively)
SCSP_DIR = ../scsp_wasm

FILES_DSP = \
	SCSPSynthPlugin.cpp \
	scsp_voice.c \
	$(SCSP_DIR)/scsp_wasm.c \
	$(SCSP_DIR)/scsp.c \
	$(SCSP_DIR)/scspdsp.c \
	$(SCSP_DIR)/scsp_waveforms.c

FILES_UI = \
	SCSPSynthUI.cpp

# Include the SCSP types header and suppress aosdk header includes
SCSP_ABS_DIR = $(abspath $(SCSP_DIR))
SCSP_FLAGS = -include $(SCSP_ABS_DIR)/scsp_types.h \
	-D__AO_H -DCPUINTRF_H -D_SAT_HW_H_ -DOSD_CPU_H

# DPF uses CFLAGS/CXXFLAGS (not BUILD_C_FLAGS) for user additions
CFLAGS += $(SCSP_FLAGS) \
	-Wno-incompatible-pointer-types \
	-Wno-implicit-function-declaration \
	-Wno-int-conversion

CXXFLAGS += $(SCSP_FLAGS) -I.

# --------------------------------------------------------------
# DPFWebUI build system

DPF_TARGET_DIR = bin
DPF_BUILD_DIR = build

include dpfwebui/Makefile.plugins.mk

# --------------------------------------------------------------
# Plugin formats to build

TARGETS += clap vst3 lv2_sep

# Copy shared ton_io.js into UI directory before building
ui/ton_io.js: ../ton_io.js
	cp $< $@

all: ui/ton_io.js $(TARGETS) $(DPF_WEBUI_TARGET)

clean:
	rm -rf $(DPF_BUILD_DIR) $(DPF_TARGET_DIR) ui/ton_io.js

.PHONY: all clean
