# SCSP WASM build — compiles aosdk's SCSP emulator to WebAssembly
CC = emcc
CFLAGS = -O2 \
	-include scsp_types.h \
	-D__AO_H -DCPUINTRF_H -D_SAT_HW_H_ -DOSD_CPU_H \
	-s WASM=1 \
	-s MODULARIZE=1 \
	-s EXPORT_NAME='SCSPModule' \
	-s EXPORTED_FUNCTIONS='["_scsp_init","_scsp_get_ram_ptr","_scsp_get_ram_size","_scsp_write_reg","_scsp_write_slot","_scsp_key_on","_scsp_key_off","_scsp_render","_scsp_get_render_buf","_malloc","_free"]' \
	-s EXPORTED_RUNTIME_METHODS='["ccall","cwrap","HEAP16","HEAPU8","HEAPU16"]' \
	-s ALLOW_MEMORY_GROWTH=0 \
	-s INITIAL_MEMORY=4194304 \
	-s STACK_SIZE=65536 \
	--no-entry \
	-Wno-incompatible-pointer-types \
	-Wno-implicit-function-declaration \
	-Wno-int-conversion

SRCS = scsp_wasm.c scsp.c scspdsp.c

all: scsp.js

scsp.js: $(SRCS) scsp.h scsplfo.c scsp_types.h
	$(CC) $(CFLAGS) -o scsp.js $(SRCS)

clean:
	rm -f scsp.js scsp.wasm

.PHONY: all clean
