# QNX-Pulse Target Companion Agent Makefile
#
# Supports:
#   - Authentic QNX SDP 8.0 cross-compilation via qcc (x86_64 & aarch64le)
#   - QNX 8.0 secpol compilation (secpolcompile) & IFS image generation (mkifs)
#   - Host simulation & unit test verification via gcc (Windows MinGW / Linux / macOS)

BUILD_DIR   ?= build
HOST_CC     ?= gcc
QNX_CC      ?= qcc
SECPOLC     ?= secpolcompile
MKIFS       ?= mkifs

COMMON_INC  := -Iinclude -Isrc
WARN_FLAGS  := -std=c11 -O2 -Wall -Wextra -Werror
QNX_LIBS    := -lslog2 -lsecpol

CORE_SRCS   := src/telemetry_ring.c
AGENT_SRCS  := src/qnx_pulse_agent.c $(CORE_SRCS)
TEST_SRCS   := tests/test_telemetry_ring.c $(CORE_SRCS)

ifeq ($(OS),Windows_NT)
  EXE_EXT := .exe
  ifneq (,$(findstring cmd,$(SHELL)))
    MKDIR_P = if not exist "$(BUILD_DIR)" mkdir "$(BUILD_DIR)"
    RM_RF   = if exist "$(BUILD_DIR)" rmdir /s /q "$(BUILD_DIR)"
    RUN_TEST_CMD = $(subst /,\,$(HOST_TEST_BIN))
  else
    MKDIR_P = mkdir -p "$(BUILD_DIR)"
    RM_RF   = rm -rf "$(BUILD_DIR)"
    RUN_TEST_CMD = ./$(HOST_TEST_BIN)
  endif
else
  EXE_EXT :=
  MKDIR_P = mkdir -p "$(BUILD_DIR)"
  RM_RF   = rm -rf "$(BUILD_DIR)"
  RUN_TEST_CMD = ./$(HOST_TEST_BIN)
endif

HOST_AGENT_BIN := $(BUILD_DIR)/qnx_pulse_agent_sim$(EXE_EXT)
HOST_TEST_BIN  := $(BUILD_DIR)/test_telemetry_ring$(EXE_EXT)

QNX_X86_64_BIN    := $(BUILD_DIR)/qnx_pulse_agent_x86_64
QNX_AARCH64LE_BIN := $(BUILD_DIR)/qnx_pulse_agent_aarch64le
SECPOL_BIN        := $(BUILD_DIR)/secpol.bin
IFS_QEMU_X86_64   := $(BUILD_DIR)/qnx8-qemu-x86_64.ifs
IFS_RPI5_AARCH64  := $(BUILD_DIR)/qnx8-rpi5-aarch64.ifs

.PHONY: all host-build host-test qnx-x86_64 qnx-aarch64le secpol \
        ifs-qemu-x86_64 ifs-rpi5-aarch64 clean help

all: host-build host-test

help:
	@echo "QNX-Pulse Target Companion Agent Build Targets:"
	@echo "  make host-build        Build host simulator (qnx_pulse_agent_sim) with gcc"
	@echo "  make host-test         Build and run C11 unit test suite with gcc"
	@echo "  make qnx-x86_64        Cross-compile QNX 8.0 target agent (x86_64)"
	@echo "  make qnx-aarch64le     Cross-compile QNX 8.0 target agent (aarch64le / RPi5)"
	@echo "  make secpol            Compile qnxpulse.secpol -> build/secpol.bin"
	@echo "  make ifs-qemu-x86_64   Build QEMU x86_64 QNX 8.0 IFS image via mkifs"
	@echo "  make ifs-rpi5-aarch64  Build Raspberry Pi 5 aarch64le QNX 8.0 IFS via mkifs"
	@echo "  make clean             Remove build/ artifacts"

host-build:
	$(MKDIR_P)
	$(HOST_CC) $(WARN_FLAGS) $(COMMON_INC) $(AGENT_SRCS) -o $(HOST_AGENT_BIN)

host-test:
	$(MKDIR_P)
	$(HOST_CC) $(WARN_FLAGS) $(COMMON_INC) $(TEST_SRCS) -o $(HOST_TEST_BIN)
	$(RUN_TEST_CMD)

qnx-x86_64:
	$(MKDIR_P)
	$(QNX_CC) -Vgcc_ntox86_64 $(WARN_FLAGS) $(COMMON_INC) $(AGENT_SRCS) -o $(QNX_X86_64_BIN) $(QNX_LIBS)

qnx-aarch64le:
	$(MKDIR_P)
	$(QNX_CC) -Vgcc_ntoaarch64le $(WARN_FLAGS) $(COMMON_INC) $(AGENT_SRCS) -o $(QNX_AARCH64LE_BIN) $(QNX_LIBS)

secpol:
	$(MKDIR_P)
	$(SECPOLC) -i qnxpulse.secpol -o $(SECPOL_BIN)

ifs-qemu-x86_64: qnx-x86_64 secpol
	$(MKIFS) -v qnx8-qemu-x86_64.build $(IFS_QEMU_X86_64)

ifs-rpi5-aarch64: qnx-aarch64le secpol
	$(MKIFS) -v qnx8-rpi5-aarch64.build $(IFS_RPI5_AARCH64)

clean:
	$(RM_RF)
