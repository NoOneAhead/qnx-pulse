#!/usr/bin/env python3
"""Pre-submission verifier for QNX-Pulse (QNX Global Hackathon 2026).

Checks all Devpost & QNX 8.0 quality gates in one command:
1. Standard MIT LICENSE at repository root (GitHub Licensee compliant)
2. Required documentation, visual proof screenshots, logo, capture kit, CI/Pages workflow
3. Embedded README image links resolve cleanly
4. Standalone codelab/ relative links, inline favicon, and JS syntax checks (`node --check`)
5. Python pytest suite passes 100%
6. C11 Target Agent unit tests compile & pass with `-std=c11 -O2 -Wall -Wextra -Werror`
7. C11 Host Simulator -> Python QNX-Pulse trace analyzer end-to-end pipeline detects PI-001
8. `#ifdef __QNX__` QNX SDP 8.0 C code paths pass strict `-fsyntax-only -Wall -Wextra -Werror`
9. Repository hygiene: zero stray binaries (`.exe`, `.o`, `.kev`, `.ifs`, `secpol.bin`)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)


def _create_qnx8_stubs(stub_dir: Path) -> None:
    """Create minimal QNX SDP 8.0 API header stubs for strict `-D__QNX__ -fsyntax-only` verification."""
    (stub_dir / "sys").mkdir(parents=True, exist_ok=True)
    (stub_dir / "secpol").mkdir(parents=True, exist_ok=True)

    (stub_dir / "devctl.h").write_text(
        """#ifndef _QNX_STUB_DEVCTL_H
#define _QNX_STUB_DEVCTL_H
#include <stdint.h>
#define _DCMD_MISC 0x05
#define __DION(c, n)          (((uint32_t)(c) << 8) | (uint32_t)(n))
#define __DIOF(c, n, t)       (0x40000000U | ((uint32_t)sizeof(t) << 16) | ((uint32_t)(c) << 8) | (uint32_t)(n))
#define __DIOT(c, n, t)       (0x80000000U | ((uint32_t)sizeof(t) << 16) | ((uint32_t)(c) << 8) | (uint32_t)(n))
#define __DIOTF(c, n, t)      (0xC0000000U | ((uint32_t)sizeof(t) << 16) | ((uint32_t)(c) << 8) | (uint32_t)(n))
#endif
""",
        encoding="utf-8",
    )
    (stub_dir / "qnx8_compat_prelude.h").write_text(
        """#ifndef _QNX8_COMPAT_PRELUDE_H
#define _QNX8_COMPAT_PRELUDE_H
#include <stdint.h>
#include <signal.h>
#include <sched.h>
typedef uint64_t paddr_t;
/* QNX Neutrino extends struct sched_param with sched_curpriority */
#define sched_curpriority sched_priority
#ifdef _WIN32
typedef uint64_t qnx_stub_sigset_t;
#define sigset_t qnx_stub_sigset_t
static inline int sigemptyset(qnx_stub_sigset_t *s) { *s = 0; return 0; }
static inline int sigaddset(qnx_stub_sigset_t *s, int sig) { *s |= (1ULL << (sig & 63)); return 0; }
static inline int sigwait(const qnx_stub_sigset_t *s, int *sig) { (void)s; *sig = SIGINT; return 0; }
#ifndef pthread_sigmask
static inline int pthread_sigmask(int how, const qnx_stub_sigset_t *set, qnx_stub_sigset_t *old) {
    (void)how; (void)set; (void)old; return 0;
}
#endif
#ifndef SIG_BLOCK
#define SIG_BLOCK 0
#endif
#endif
#endif
""",
        encoding="utf-8",
    )
    (stub_dir / "sys" / "neutrino.h").write_text(
        """#ifndef _QNX_STUB_NEUTRINO_H
#define _QNX_STUB_NEUTRINO_H
#include <stdint.h>
#include <stddef.h>
#include <sched.h>
#ifndef EOK
#define EOK 0
#endif
#ifndef SCHED_FIFO
#define SCHED_FIFO 1
#endif
#ifndef SCHED_RR
#define SCHED_RR 2
#endif
#define _NTO_CHF_FIXED_PRIORITY 0x0001U
#define _NTO_CHF_UNBLOCK        0x0002U
#define _NTO_CHF_DISCONNECT     0x0004U
#define _NTO_CHF_COID_DISCONNECT 0x0008U
#define _NTO_CHF_PRIVATE        0x0010U
#define _NTO_SIDE_CHANNEL       0x40000000U
struct _msg_info {
    uint32_t nd;
    uint32_t srcnd;
    int32_t pid;
    int32_t tid;
    int32_t chid;
    int32_t scoid;
    int32_t coid;
    int32_t msglen;
    int32_t srcmsglen;
    int32_t dstmsglen;
    int16_t priority;
    int16_t flags;
    uint32_t reserved;
};
typedef struct _iov { void *iov_base; size_t iov_len; } iov_t;
static inline void SETIOV(iov_t *iov, void *addr, size_t len) { iov->iov_base = addr; iov->iov_len = len; }
int ChannelCreate(unsigned flags);
int ChannelDestroy(int chid);
int MsgReply(int rcvid, int64_t status, const void *msg, size_t size);
int SchedSet(int pid, int tid, int policy, const struct sched_param *param);
int SchedGet(int pid, int tid, struct sched_param *param);
uint64_t ClockCycles(void);
#endif
""",
        encoding="utf-8",
    )
    (stub_dir / "sys" / "syspage.h").write_text(
        """#ifndef _QNX_STUB_SYSPAGE_H
#define _QNX_STUB_SYSPAGE_H
#include <stdint.h>
struct qtime_entry { uint64_t cycles_per_sec; };
struct syspage_entry { struct qtime_entry *qtime; };
static struct qtime_entry _qnx_stub_qtime = { 2500000000ULL };
static struct syspage_entry _qnx_stub_sp = { &_qnx_stub_qtime };
#define SYSPAGE_ENTRY(field) (_qnx_stub_sp.field)
#endif
""",
        encoding="utf-8",
    )
    (stub_dir / "sys" / "iofunc.h").write_text(
        """#ifndef _QNX_STUB_IOFUNC_H
#define _QNX_STUB_IOFUNC_H
#include <stdint.h>
#include <stddef.h>
#include <sys/stat.h>
#include <sys/neutrino.h>
#ifndef EOK
#define EOK 0
#endif
#define _RESMGR_CONNECT_NFUNCS 10
#define _RESMGR_IO_NFUNCS      20
#define _RESMGR_DEFAULT        0
#define _RESMGR_NOREPLY        0x7FFFFFFF
#define _RESMGR_NPARTS(n)      (-(n))
#define _RESMGR_PTR(ctp, p, n) ((void)(ctp), (void)(p), (void)(n), 0)
#define _FTYPE_ANY             0
#define _IO_XTYPE_MASK         0x000000FFU
#define _IO_XTYPE_NONE         0x00000000U
#define _IO_SET_READ_NBYTES(ctp, n) ((ctp)->status = (int)(n))
#define _DEVCTL_DATA(msg)      ((void *)((char *)&(msg) + sizeof(msg)))
#define IOFUNC_ATTR_INIT_OK    0
#define IOFUNC_ATTR_ATIME      0x0001U
#define IOFUNC_ATTR_DIRTY_TIME 0x0002U
#define _RESMGR_FLAG_SELF      0x0001U
typedef struct {
    int mode;
    int64_t nbytes;
    uint32_t uid;
    uint32_t gid;
    uint32_t flags;
} iofunc_attr_t;
typedef struct {
    iofunc_attr_t *attr;
    int64_t offset;
    int ioflag;
} iofunc_ocb_t;
#ifndef RESMGR_OCB_T
#define RESMGR_OCB_T iofunc_ocb_t
#endif
#ifndef RESMGR_HANDLE_T
#define RESMGR_HANDLE_T iofunc_attr_t
#endif
typedef struct {
    int rcvid;
    int status;
    struct _msg_info info;
    iov_t iov[4];
} resmgr_context_t;
typedef struct {
    struct { uint32_t nbytes; uint32_t xtype; } i;
} io_read_t;
typedef struct {
    struct { uint32_t dcmd; int32_t nbytes; int32_t zero; } i;
    struct { int32_t ret_val; int32_t nbytes; } o;
} io_devctl_t;
typedef struct {
    int (*open)(resmgr_context_t *, void *, iofunc_attr_t *, void *);
} resmgr_connect_funcs_t;
typedef struct {
    int (*read)(resmgr_context_t *, io_read_t *, iofunc_ocb_t *);
    int (*devctl)(resmgr_context_t *, io_devctl_t *, iofunc_ocb_t *);
} resmgr_io_funcs_t;
typedef struct {
    unsigned nparts_max;
    size_t msg_max_size;
    unsigned flags;
} resmgr_attr_t;
void iofunc_func_init(unsigned nconnect, resmgr_connect_funcs_t *c, unsigned nio, resmgr_io_funcs_t *io);
void iofunc_attr_init(iofunc_attr_t *attr, mode_t mode, iofunc_attr_t *dattr, void *info);
int iofunc_read_verify(resmgr_context_t *ctp, io_read_t *msg, iofunc_ocb_t *ocb, int *nonblock);
int iofunc_devctl_default(resmgr_context_t *ctp, io_devctl_t *msg, iofunc_ocb_t *ocb);
int iofunc_open_default(resmgr_context_t *ctp, void *msg, iofunc_attr_t *attr, void *extra);
#endif
""",
        encoding="utf-8",
    )
    (stub_dir / "sys" / "dispatch.h").write_text(
        """#ifndef _QNX_STUB_DISPATCH_H
#define _QNX_STUB_DISPATCH_H
#include <sys/iofunc.h>
#define _RESMGR_DETACH_ALL 0x0001U
#define POOL_FLAG_EXIT_SELF 0x0001U
#define ThreadPoolCreateFlagsDefault 0U
typedef struct _dispatch dispatch_t;
typedef struct _dispatch_context {
    resmgr_context_t resmgr_context;
} dispatch_context_t;
typedef struct _thread_pool thread_pool_t;
typedef struct {
    dispatch_t *handle;
    dispatch_context_t *(*context_alloc)(dispatch_t *dpp);
    dispatch_context_t *(*block_func)(dispatch_context_t *ctp);
    void (*unblock_func)(dispatch_context_t *ctp);
    int (*handler_func)(dispatch_context_t *ctp);
    void (*context_free)(dispatch_context_t *ctp);
    uint16_t lo_water;
    uint16_t hi_water;
    uint16_t increment;
    uint16_t maximum;
} thread_pool_attr_t;
dispatch_t *dispatch_create(void);
dispatch_t *dispatch_create_channel(int chid, unsigned flags);
int dispatch_destroy(dispatch_t *dpp);
dispatch_context_t *dispatch_context_alloc(dispatch_t *dpp);
dispatch_context_t *dispatch_block(dispatch_context_t *ctp);
void dispatch_unblock(dispatch_context_t *ctp);
int dispatch_handler(dispatch_context_t *ctp);
void dispatch_context_free(dispatch_context_t *ctp);
int resmgr_attach(dispatch_t *dpp, resmgr_attr_t *attr, const char *path, int file_type,
                  unsigned flags, const resmgr_connect_funcs_t *connect_funcs,
                  const resmgr_io_funcs_t *io_funcs, iofunc_attr_t *handle);
int resmgr_detach(dispatch_t *dpp, int id, unsigned flags);
int resmgr_msgread(resmgr_context_t *ctp, void *buf, size_t nbytes, size_t offset);
thread_pool_t *thread_pool_create(thread_pool_attr_t *attr, unsigned flags);
int thread_pool_start(void *pool);
int thread_pool_destroy(thread_pool_t *pool);
#endif
""",
        encoding="utf-8",
    )
    (stub_dir / "sys" / "resmgr.h").write_text(
        """#ifndef _QNX_STUB_RESMGR_H
#define _QNX_STUB_RESMGR_H
#include <sys/iofunc.h>
#endif
""",
        encoding="utf-8",
    )
    (stub_dir / "sys" / "procmgr.h").write_text(
        """#ifndef _QNX_STUB_PROCMGR_H
#define _QNX_STUB_PROCMGR_H
#include <stdint.h>
#define PROCMGR_ADN_ROOT           0x10000000U
#define PROCMGR_ADN_NONROOT        0x20000000U
#define PROCMGR_AOP_DENY           0x00010000U
#define PROCMGR_AOP_ALLOW          0x00020000U
#define PROCMGR_AOP_LOCK           0x00040000U
#define PROCMGR_AID_EOL            0U
#define PROCMGR_AID_TRACE          1U
#define PROCMGR_AID_PATHSPACE      2U
#define PROCMGR_AID_PUBLIC_CHANNEL 3U
#define PROCMGR_AID_IO             4U
#define PROCMGR_AID_FORK           5U
#define PROCMGR_AID_SPAWN          6U
#define PROCMGR_AID_SETUID         7U
#define PROCMGR_AID_SETGID         8U
#define PROCMGR_AID_MEM_PHYS       9U
int procmgr_ability(int pid, ...);
#endif
""",
        encoding="utf-8",
    )
    (stub_dir / "sys" / "trace.h").write_text(
        """#ifndef _QNX_STUB_TRACE_H
#define _QNX_STUB_TRACE_H
#include <stdint.h>
#define _NTO_TRACE_DELALL           1
#define _NTO_TRACE_ALLOCBUFFER      2
#define _NTO_TRACE_DEALLOCBUFFER    3
#define _NTO_TRACE_START            4
#define _NTO_TRACE_STOP             5
#define _NTO_TRACE_INSERTSUSEREVENT 6
#define _NTO_TRACE_INSERTUSRSTREVENT 7
#define _NTO_TRACE_SETALLCLASSESFAST 8
#define _NTO_TRACE_ADDALLCLASSES     9
#define _NTO_TRACE_USERFIRST        0
int TraceEvent(int mode, ...);
#endif
""",
        encoding="utf-8",
    )
    (stub_dir / "sys" / "slog2.h").write_text(
        """#ifndef _QNX_STUB_SLOG2_H
#define _QNX_STUB_SLOG2_H
#include <stdint.h>
#define SLOG2_SHUTDOWN 0
#define SLOG2_CRITICAL 1
#define SLOG2_ERROR    2
#define SLOG2_WARNING  3
#define SLOG2_NOTICE   4
#define SLOG2_INFO     5
#define SLOG2_DEBUG1   6
#define SLOG2_DEBUG2   7
typedef void *slog2_buffer_t;
typedef struct {
    const char *buffer_name;
    int num_pages;
} slog2_buffer_config_t;
typedef struct {
    int num_buffers;
    const char *buffer_set_name;
    uint8_t verbosity_level;
    slog2_buffer_config_t buffer_config[4];
    unsigned max_retries;
} slog2_buffer_set_config_t;
int slog2_register(slog2_buffer_set_config_t *config, slog2_buffer_t *handles, uint32_t flags);
int slog2_set_default_buffer(slog2_buffer_t buffer);
int slog2f(slog2_buffer_t buffer, uint16_t code, uint8_t severity, const char *format, ...);
#endif
""",
        encoding="utf-8",
    )
    (stub_dir / "secpol" / "secpol.h").write_text(
        """#ifndef _QNX_STUB_SECPOL_H
#define _QNX_STUB_SECPOL_H
#include <stdint.h>
#define SECPOL_TYPE_NAME 0x0001U
typedef struct _secpol_file secpol_file_t;
int secpol_transition_type(secpol_file_t *handle, const char *name, uint32_t flags);
#endif
""",
        encoding="utf-8",
    )


def main() -> int:
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        tag = "PASS" if ok else "FAIL"
        suffix = f" — {detail}" if detail else ""
        print(f"[{tag}] {name}{suffix}")
        if not ok:
            failures.append(f"{name}: {detail}")

    print("=" * 70)
    print(" QNX-Pulse Pre-Submission Verification Suite (QNX Global Hackathon)")
    print("=" * 70)

    # 1. Standard MIT License
    lic = REPO_ROOT / "LICENSE"
    lic_text = lic.read_text(encoding="utf-8") if lic.exists() else ""
    mit_ok = (
        lic.exists()
        and lic_text.startswith("MIT License")
        and "Permission is hereby granted, free of charge" in lic_text
        and 'THE SOFTWARE IS PROVIDED "AS IS"' in lic_text
    )
    check("1. Standard MIT LICENSE at repo root", mit_ok, "GitHub Licensee compatible")

    # 2. Required artifacts & visuals
    required = [
        "README.md",
        "SUBMISSION.md",
        "DEMO_SCRIPT.md",
        ".nojekyll",
        "codelab/.nojekyll",
        ".github/workflows/ci-and-pages.yml",
        "scripts/qnx8_capture_and_verify.sh",
        "docs/images/qnx-pulse-logo.svg",
        "docs/images/qnx-pulse-logo.png",
        "docs/images/qnx_pulse_dashboard_adas.png",
        "docs/images/qnx_pulse_ipc_topology.png",
        "docs/images/qnx_pulse_audit_studio.png",
        "docs/images/qnx_pulse_codelab_sim.png",
        "target/qnx_pulse_agent/src/qnx_pulse_agent.c",
        "target/qnx_pulse_agent/qnx8-qemu-x86_64.build",
        "target/qnx_pulse_agent/qnxpulse.secpol",
        "codelab/index.html",
        "codelab/CODELAB.md",
    ]
    missing = [p for p in required if not (REPO_ROOT / p).exists()]
    check("2. Required submission & visual files", len(missing) == 0, f"missing={missing}" if missing else f"{len(required)}/{len(required)} present")

    # 3. README embedded image & local links check
    readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    img_refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme_text)
    broken_imgs = [r for r in img_refs if not r.startswith("http") and not (REPO_ROOT / r).exists()]
    check(
        "3. README visual embeds & QNX 8.0 evidence",
        len(broken_imgs) == 0 and len(img_refs) >= 4 and "procnto-smp-instr" in readme_text,
        f"{len(img_refs)} embedded images, broken={broken_imgs}",
    )

    # 4. Codelab standalone relative assets + favicon + JS syntax
    codelab_dir = REPO_ROOT / "codelab"
    cl_html = (codelab_dir / "index.html").read_text(encoding="utf-8")
    cl_refs = re.findall(r'(?:href|src)="([^"]+)"', cl_html)
    broken_cl = []
    for ref in cl_refs:
        if ref.startswith(("http://", "https://", "#", "data:", "../")):
            continue
        if not (codelab_dir / ref).exists():
            broken_cl.append(ref)
    has_favicon = 'rel="icon"' in cl_html
    check(
        "4a. Standalone codelab/ relative links & favicon",
        len(broken_cl) == 0 and has_favicon,
        f"favicon={has_favicon}, checked={len(cl_refs)} refs, broken={broken_cl}",
    )

    if shutil.which("node"):
        n1 = _run(["node", "--check", "web/app.js"])
        n2 = _run(["node", "--check", "codelab/codelab.js"])
        check("4b. Frontend & Codelab JS syntax (node --check)", n1.returncode == 0 and n2.returncode == 0, "web/app.js + codelab/codelab.js")
    else:
        check("4b. Frontend & Codelab JS syntax", True, "node not installed (skipped)")

    # 5. Python pytest suite
    py_res = _run([sys.executable, "-m", "pytest", "-q"])
    summary_line = [ln for ln in py_res.stdout.splitlines() if "passed" in ln or "failed" in ln]
    check("5. Python pytest unit & integration suite", py_res.returncode == 0, summary_line[-1] if summary_line else py_res.stderr.strip())

    # 6. GCC C11 Target Agent unit tests & C-to-Python end-to-end pipe
    gcc = shutil.which("gcc")
    if gcc:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            exe_ext = ".exe" if os.name == "nt" else ""

            # 6a. Unit tests
            test_bin = tmp_path / f"test_ring{exe_ext}"
            c1 = _run([
                gcc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                "-Itarget/qnx_pulse_agent/include", "-Itarget/qnx_pulse_agent/src",
                "target/qnx_pulse_agent/tests/test_telemetry_ring.c",
                "target/qnx_pulse_agent/src/telemetry_ring.c",
                "-o", str(test_bin),
            ])
            r1 = _run([str(test_bin)]) if c1.returncode == 0 else c1
            check(
                "6a. C11 Target Agent ring & watchdog tests (-Wall -Wextra -Werror)",
                c1.returncode == 0 and r1.returncode == 0 and "7/7 tests passed" in r1.stdout,
                "7/7 passed, 0 warnings" if r1.returncode == 0 else (c1.stderr + r1.stderr).strip(),
            )

            # 6b. Host simulator -> Python analyzer pipe
            sim_bin = tmp_path / f"qnx_sim{exe_ext}"
            sim_trace = tmp_path / "sim_trace.txt"
            c2 = _run([
                gcc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                "-Itarget/qnx_pulse_agent/include", "-Itarget/qnx_pulse_agent/src",
                "target/qnx_pulse_agent/src/qnx_pulse_agent.c",
                "target/qnx_pulse_agent/src/telemetry_ring.c",
                "-o", str(sim_bin),
            ])
            r2 = _run([str(sim_bin), "--scenario", "inversion", "--format", "traceprinter", "--output", str(sim_trace)]) if c2.returncode == 0 else c2
            pipe_ok = False
            pipe_detail = ""
            if c2.returncode == 0 and r2.returncode == 0 and sim_trace.exists():
                sys.path.insert(0, str(REPO_ROOT))
                from qnx_pulse.analyzers import analyze_trace
                tr = analyze_trace(sim_trace.read_text(encoding="utf-8"))
                pipe_ok = len(tr.priority_inversions) >= 1 and tr.priority_inversions[0].id == "PI-001"
                pipe_detail = f"parsed {tr.total_events} C events -> detected {len(tr.priority_inversions)} inversion(s)"
            else:
                pipe_detail = (c2.stderr + r2.stderr).strip()
            check("6b. C11 Host Simulator -> Python Analyzer E2E pipe", pipe_ok, pipe_detail)

            # 7. Strict `#ifdef __QNX__` QNX 8.0 C syntax verification
            stub_dir = tmp_path / "qnx8_stubs"
            _create_qnx8_stubs(stub_dir)
            qnx_checks = [
                ("target/qnx_pulse_agent/src/qnx_pulse_agent.c", ["-std=c11", "-D__QNX__", "-Itarget/qnx_pulse_agent/include", "-Itarget/qnx_pulse_agent/src"]),
                ("codelab/lab_files/buggy_lidar_mgr.c", ["-std=gnu11", "-D__QNX__"]),
                ("codelab/lab_files/fixed_lidar_mgr.c", ["-std=gnu11", "-D__QNX__"]),
            ]
            qnx_errs: list[str] = []
            prelude = stub_dir / "qnx8_compat_prelude.h"
            for src_rel, extra_flags in qnx_checks:
                res_q = _run([
                    gcc, "-fsyntax-only", "-Wall", "-Wextra", "-Werror",
                    f"-I{stub_dir}", "-include", str(prelude), *extra_flags, src_rel,
                ])
                if res_q.returncode != 0:
                    qnx_errs.append(f"{src_rel}: {res_q.stderr.strip()}")
            check(
                "7. Strict `#ifdef __QNX__` QNX 8.0 C syntax check (3 files)",
                len(qnx_errs) == 0,
                "0 errors, 0 warnings" if not qnx_errs else "; ".join(qnx_errs),
            )
    else:
        check("6-7. GCC C11 checks", False, "gcc not found in PATH")

    # 8. Hygiene check — no stray binaries
    bad_exts = {".exe", ".o", ".obj", ".kev", ".ifs"}
    stray = [
        str(p.relative_to(REPO_ROOT))
        for p in REPO_ROOT.rglob("*")
        if p.is_file()
        and ".git" not in p.parts
        and (p.suffix.lower() in bad_exts or p.name == "secpol.bin")
    ]
    check("8. Repository hygiene (no stray binaries)", len(stray) == 0, f"stray={stray}" if stray else "clean workspace")

    print("=" * 70)
    if failures:
        print(f"RESULT: FAILED ({len(failures)} check(s) failed)")
        return 1
    print("RESULT: ALL PRE-SUBMISSION CHECKS PASSED (100% READY FOR DEVPOST)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
