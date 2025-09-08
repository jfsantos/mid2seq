COMPILER_DIR = $(HOME)/src/joengine/Compiler/

SYSOBJS =

SYSOBJS += $(SGLLDR)/SGLAREA.O

SRCS = main.c music/mechsseq.c music/mechston.c music/mechsmap.c

OBJS = $(SRCS:.c=.o)

LIBS +=  $(SGLLDR)/SEGA_SYS.A $(SGLLDR)/LIBCD.A $(SGLLDR)/LIBSGL.A

ifeq ($(OS), Windows_NT)
	CC=$(COMPILER_DIR)/WINDOWS/bin/sh-elf-gcc.exe
	CONV=$(COMPILER_DIR)/WINDOWS/bin/sh-elf-objcopy.exe
	CUE_MAKER=JoEngineCueMaker.exe
else
	CC=$(COMPILER_DIR)/LINUX/bin/sh-none-elf-gcc-8.2.0
	CONV=$(COMPILER_DIR)/LINUX/bin/sh-none-elf-objcopy
	CUE_MAKER="$(COMPILER_DIR)/LINUX/Other Utilities/CueMaker"
	CCFLAGS+="-I$(COMPILER_DIR)/WINDOWS/sh-elf/include"
endif

ASSETS_DIR=./cd
MKISOFS=mkisofs
RM = rm -rf

SGLDIR = $(COMPILER_DIR)/COMMON/SGL_302j
SGLIDR = $(SGLDIR)/INC
SGLLDR = $(SGLDIR)/LIB_ELF

CMNDIR = $(COMPILER_DIR)/COMMON

CCFLAGS += -fkeep-inline-functions -W -Wall -Wshadow -Wbad-function-cast -Winline -Wcomment \
	-Winline -Wsign-compare -Wextra -Wno-strict-aliasing \
	-fno-common -ffast-math \
	--param max-inline-insns-single=50 -fms-extensions -std=gnu99 \
	-fmerge-all-constants -fno-ident -fno-unwind-tables -fno-asynchronous-unwind-tables \
	-fomit-frame-pointer -fstrength-reduce -frerun-loop-opt -O2 -nodefaultlibs -nostdlib -fno-builtin \
	-m2 -c

ifneq ($(OS), Windows_NT)
CCFLAGS += -flto
endif

CCFLAGS += -I$(SGLIDR)

LDFLAGS = -m2
LDFLAGS += -L$(SGLLDR)
LDFLAGS +=-Xlinker -T$(LDFILE) -Xlinker -Map \
          -Xlinker $(MPFILE) -Xlinker -e -Xlinker ___Start -nostartfiles
ifneq ($(OS), Windows_NT)
LIBS += -L.$(COMPILER_DIR)/LINUX/sh-elf/sh-elf/lib/ -Wl,--relax -lgcc
endif
DFLAGS =

TARGET   = game.elf
TARGET1  = $(TARGET:.elf=.raw)
TARGET2  = $(TARGET:.elf=.iso)
TARGET3  = $(TARGET:.elf=.cue)
MPFILE   = $(TARGET:.elf=.map)
IPFILE   = $(CMNDIR)/IP.BIN
LDFILE   = $(CMNDIR)/sgl.linker

MKISOFS_FLAGS=-quiet -sysid "SEGA SATURN" -volid "SaturnApp" -volset "SaturnApp" -sectype 2352 \
	-publisher "SEGA ENTERPRISES, LTD." -preparer "SEGA ENTERPRISES, LTD." -appid "SaturnApp" \
	-abstract "$(ASSETS_DIR)/ABS.TXT" -copyright "$(ASSETS_DIR)/CPY.TXT" -biblio "$(ASSETS_DIR)/BIB.TXT" -generic-boot $(IPFILE) \
	-full-iso9660-filenames -o $(TARGET2) $(ASSETS_DIR) $(ENTRYPOINT)

MAKEFILE = makefile

.PHONY : all clean re

all: $(TARGET) $(TARGET1) $(TARGET2) $(TARGET3)

mid2seq: 
	xxd -i music/midi.seq > music/midi.c

$(TARGET) : $(SYSOBJS) $(OBJS) $(MAKEFILE) $(LDFILE)
	$(CC) $(LDFLAGS) $(SYSOBJS) $(OBJS) $(LIBS) -o $@

$(TARGET1) : $(TARGET) $(SYSOBJS) $(OBJS) $(MAKEFILE) $(LDFILE)
	$(CONV) -O binary $(TARGET) $(TARGET1)

$(TARGET2): $(TARGET1)
	$(CONV) -O binary $(TARGET) cd/0.bin
	$(MKISOFS) $(MKISOFS_FLAGS)

$(TARGET3): $(TARGET1) $(TARGET2)
	$(CUE_MAKER)

.c.o:
	$(CC) $< $(DFLAGS) $(CCFLAGS) $(_CCFLAGS) -o $@

clean:
	$(RM) $(OBJS) $(TARGET) $(TARGET1) $(TARGET2) $(MPFILE) cd/0.bin

re: clean all
