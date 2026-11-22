# ==============================================================================
# QNX SDP 8.0 Makefile — Zero-Jitter ADAS AEB Codelab
#
# Prerequisites:
#   source ~/qnx800/qnxsdp-env.sh   (Linux/macOS)
#   %USERPROFILE%\qnx800\qnxsdp-env.bat  (Windows)
#
# Targets:
#   make buggy       - Compile buggy /dev/lidar_fusion resource manager
#   make fixed       - Compile fixed /dev/lidar_fusion resource manager
#   make secpol      - Compile lab.secpol -> secpol.bin
#   make ifs-buggy   - Build QEMU x86_64 boot image with buggy resource manager
#   make ifs-fixed   - Build QEMU x86_64 boot image with fixed resource manager
#   make qemu-buggy  - Boot buggy QNX 8.0 image in qemu-system-x86_64
#   make qemu-fixed  - Boot fixed QNX 8.0 image in qemu-system-x86_64
#   make ARCH=aarch64le fixed  - Cross-compile for Raspberry Pi 5 (ARM64)
# ==============================================================================

ARCH        ?= x86_64
CC          := qcc
VARIANT     := -Vgcc_nto$(ARCH)
CFLAGS      := $(VARIANT) -Wall -Wextra -O2 -std=gnu11
LDFLAGS     := -lslog2 -lsecpol

SECPOLCOMPILE := secpolcompile
MKIFS         := mkifs
QEMU          := qemu-system-x86_64
QEMU_FLAGS    := -m 512M -smp 2 -nographic -serial mon:stdio -no-reboot

.PHONY: all buggy fixed secpol ifs-buggy ifs-fixed qemu-buggy qemu-fixed clean

all: buggy fixed secpol

buggy: lidar_mgr_buggy

fixed: lidar_mgr_fixed

lidar_mgr_buggy: buggy_lidar_mgr.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

lidar_mgr_fixed: fixed_lidar_mgr.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

secpol: secpol.bin

secpol.bin: lab.secpol
	$(SECPOLCOMPILE) -o $@ $<

ifs-buggy: lidar_mgr_buggy secpol.bin lab.build
	cp lidar_mgr_buggy lidar_mgr
	$(MKIFS) -v lab.build ifs-lab-buggy.bin

ifs-fixed: lidar_mgr_fixed secpol.bin lab.build
	cp lidar_mgr_fixed lidar_mgr
	$(MKIFS) -v lab.build ifs-lab-fixed.bin

qemu-buggy: ifs-buggy
	$(QEMU) $(QEMU_FLAGS) -kernel ifs-lab-buggy.bin

qemu-fixed: ifs-fixed
	$(QEMU) $(QEMU_FLAGS) -kernel ifs-lab-fixed.bin

clean:
	rm -f lidar_mgr lidar_mgr_buggy lidar_mgr_fixed secpol.bin \
	      ifs-lab-buggy.bin ifs-lab-fixed.bin
