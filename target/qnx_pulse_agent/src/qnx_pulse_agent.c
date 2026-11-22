/*
 * QNX-Pulse Target Companion Agent (/dev/qnxpulse)
 *
 * Dual-target C11 implementation:
 *   - Under __QNX__: Authentic QNX SDP 8.0 POSIX Resource Manager (/dev/qnxpulse)
 *     using <sys/neutrino.h>, <sys/dispatch.h>, <sys/iofunc.h>, <sys/procmgr.h>,
 *     <sys/trace.h>, <sys/slog2.h>, <secpol/secpol.h>, and <devctl.h>.
 *     Preserves QNX IPC priority inheritance (intentionally does NOT set
 *     _NTO_CHF_FIXED_PRIORITY), drives live kernel tracing via TraceEvent(),
 *     streams lock-free ring telemetry in traceprinter or NDJSON format, and
 *     drops init privileges via secpol_transition_type(NULL, "run", 0) with a
 *     locked procmgr_ability() fallback.
 *
 *   - Under Host Simulation Mode (#else): Portable Windows/Linux/macOS CLI
 *     (qnx_pulse_agent_sim) exercising the exact same lock-free ring buffer,
 *     traceprinter/NDJSON serializers, and inline priority-inversion watchdog
 *     against realistic QNX 8.0 ADAS healthy & priority-inversion bursts.
 */

#ifdef __QNX__
#ifndef _QNX_SOURCE
#define _QNX_SOURCE 1
#endif
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#endif

#include "qnx_pulse_protocol.h"
#include "telemetry_ring.h"

#ifdef __QNX__

/*
 * Must be defined before <sys/iofunc.h> and <sys/dispatch.h> so thread_pool_attr_t
 * matches dispatch_context_alloc / dispatch_block / dispatch_handler cleanly.
 */
#define THREAD_POOL_PARAM_T dispatch_context_t

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include <devctl.h>
#include <secpol/secpol.h>
#include <sys/dispatch.h>
#include <sys/iofunc.h>
#include <sys/neutrino.h>
#include <sys/procmgr.h>
#include <sys/resmgr.h>
#include <sys/slog2.h>
#include <sys/syspage.h>
#include <sys/trace.h>

#define QNXP_SLOG_CODE          0x2026U
#define QNXP_KERNEL_TRACE_BUFS  8U
#define QNXP_IO_READ_BUF_BYTES  4096U

typedef struct qnxp_agent_ctx {
    qnxp_ring_t     ring;
    slog2_buffer_t  slog_buf;
    dispatch_t     *dpp;
    thread_pool_t  *tpp;
    int             chid;
    int             resmgr_id;
    paddr_t         trace_buf_paddr;
    _Atomic uint32_t tracing_active;
    _Atomic uint32_t output_format;
} qnxp_agent_ctx_t;

static qnxp_agent_ctx_t g_agent;

static uint64_t qnxp_now_ns(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return 0ULL;
    }
    return ((uint64_t)ts.tv_sec * 1000000000ULL) + (uint64_t)ts.tv_nsec;
}

static uint8_t qnxp_current_thread_priority(void)
{
    int policy = 0;
    struct sched_param param;

    memset(&param, 0, sizeof(param));
    if (pthread_getschedparam(pthread_self(), &policy, &param) != 0) {
        return 10U;
    }
    if (param.sched_curpriority < 0) {
        return 0U;
    }
    if (param.sched_curpriority > 255) {
        return 255U;
    }
    return (uint8_t)param.sched_curpriority;
}

static int qnxp_init_slog2(void)
{
    slog2_buffer_set_config_t cfg;

    memset(&cfg, 0, sizeof(cfg));
    cfg.num_buffers                 = 1;
    cfg.buffer_set_name             = "qnx_pulse_agent";
    cfg.verbosity_level             = SLOG2_INFO;
    cfg.max_retries                 = 3U;
    cfg.buffer_config[0].buffer_name = "telemetry";
    cfg.buffer_config[0].num_pages   = 4; /* 16 KiB circular slog2 buffer */

    if (slog2_register(&cfg, &g_agent.slog_buf, 0U) == -1) {
        fprintf(stderr, "qnx_pulse_agent: slog2_register failed: %s\n", strerror(errno));
        return -1;
    }

    (void)slog2_set_default_buffer(g_agent.slog_buf);
    slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_INFO,
           "qnx_pulse_agent initialized (pid=%d, ring_cap=%u)",
           (int)getpid(), (unsigned int)QNXP_RING_CAPACITY);
    return 0;
}

static void qnxp_record_ipc_sample(resmgr_context_t *ctp, uint8_t event_type, uint32_t data0)
{
    qnxp_event_t ev;
    qnxp_inversion_alert_t alert;
    uint8_t server_prio = qnxp_current_thread_priority();
    uint8_t client_prio = (ctp->info.priority > 0) ? (uint8_t)ctp->info.priority : 0U;

    memset(&ev, 0, sizeof(ev));
    ev.timestamp_ns  = qnxp_now_ns();
    ev.pid           = (uint32_t)getpid();
    ev.tid           = (uint32_t)pthread_self();
    ev.peer_pid      = (uint32_t)ctp->info.pid;
    ev.peer_tid      = (uint32_t)ctp->info.tid;
    ev.rcvid_or_irq  = (uint32_t)ctp->rcvid;
    ev.data0         = data0;
    ev.cpu           = 0U;
    ev.event_class   = (uint8_t)QNXP_CLASS_COMM;
    ev.event_type    = event_type;
    ev.priority      = server_prio;
    ev.peer_priority = client_prio;
    (void)snprintf(ev.proc_name, sizeof(ev.proc_name), "%s", "qnx_pulse_agent");

    /* Verify QNX IPC priority inheritance held on this live /dev/qnxpulse request. */
    if (qnxp_evaluate_event_inversion(&ev, QNXP_CHF_NONE, &alert)) {
        slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_WARNING,
               "WATCHDOG: %s", alert.reason);
        (void)TraceEvent(_NTO_TRACE_INSERTSUSEREVENT,
                         (int)QNXP_USREVENT_INVERSION,
                         (int)alert.client_pid,
                         (int)alert.priority_gap);
    }

    (void)qnxp_ring_push(&g_agent.ring, &ev);
}

static int qnxp_trace_start(void)
{
    uint32_t expected = 0U;

    if (!atomic_compare_exchange_strong(&g_agent.tracing_active, &expected, 1U)) {
        return EOK; /* Already active */
    }

    if (TraceEvent(_NTO_TRACE_ALLOCBUFFER,
                   (unsigned int)QNXP_KERNEL_TRACE_BUFS,
                   &g_agent.trace_buf_paddr) == -1) {
        int saved_err = errno;
        atomic_store(&g_agent.tracing_active, 0U);
        slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_ERROR,
               "TraceEvent(_NTO_TRACE_ALLOCBUFFER) failed: %s", strerror(saved_err));
        return saved_err;
    }

    (void)TraceEvent(_NTO_TRACE_SETALLCLASSESFAST);
    (void)TraceEvent(_NTO_TRACE_ADDALLCLASSES);

    if (TraceEvent(_NTO_TRACE_START) == -1) {
        int saved_err = errno;
        (void)TraceEvent(_NTO_TRACE_DEALLOCBUFFER);
        atomic_store(&g_agent.tracing_active, 0U);
        slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_ERROR,
               "TraceEvent(_NTO_TRACE_START) failed: %s", strerror(saved_err));
        return saved_err;
    }

    (void)TraceEvent(_NTO_TRACE_INSERTSUSEREVENT,
                     (int)QNXP_USREVENT_HEARTBEAT,
                     (int)getpid(),
                     1);

    {
        qnxp_event_t marker;
        memset(&marker, 0, sizeof(marker));
        marker.timestamp_ns = qnxp_now_ns();
        marker.pid          = (uint32_t)getpid();
        marker.tid          = (uint32_t)pthread_self();
        marker.rcvid_or_irq = QNXP_USREVENT_HEARTBEAT;
        marker.data0        = (uint32_t)getpid();
        marker.data1        = 1U;
        marker.event_class  = (uint8_t)QNXP_CLASS_USREVENT;
        marker.event_type   = (uint8_t)QNXP_EVT_USREVENT;
        marker.priority     = qnxp_current_thread_priority();
        (void)snprintf(marker.proc_name, sizeof(marker.proc_name), "%s", "qnx_pulse_agent");
        (void)qnxp_ring_push(&g_agent.ring, &marker);
    }

    slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_INFO,
           "Kernel tracing started (%u buffers allocated)", (unsigned int)QNXP_KERNEL_TRACE_BUFS);
    return EOK;
}

static int qnxp_trace_stop(void)
{
    uint32_t expected = 1U;

    if (!atomic_compare_exchange_strong(&g_agent.tracing_active, &expected, 0U)) {
        return EOK; /* Already stopped */
    }

    (void)TraceEvent(_NTO_TRACE_INSERTSUSEREVENT,
                     (int)QNXP_USREVENT_HEARTBEAT,
                     (int)getpid(),
                     0);
    (void)TraceEvent(_NTO_TRACE_STOP);
    (void)TraceEvent(_NTO_TRACE_DEALLOCBUFFER);

    slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_INFO,
           "Kernel tracing stopped and trace buffers deallocated");
    return EOK;
}

/*
 * Drop initialization privileges (pathspace, public_channel) after attaching
 * /dev/qnxpulse so the running daemon only retains nonroot + trace ability.
 */
static int qnxp_drop_privileges(void)
{
    if (secpol_transition_type(NULL, "run", 0U) == 0) {
        slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_INFO,
               "secpol_transition_type(NULL, \"run\", 0) succeeded (qnxpulse_run_t)");
        return 0;
    }

    slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_WARNING,
           "secpol_transition_type unavailable (errno=%d: %s); applying procmgr_ability lock",
           errno, strerror(errno));

    if (procmgr_ability(
            0,
            PROCMGR_ADN_NONROOT | PROCMGR_AOP_ALLOW | PROCMGR_AOP_LOCK | PROCMGR_AID_TRACE,
            PROCMGR_ADN_ROOT    | PROCMGR_AOP_DENY  | PROCMGR_AOP_LOCK | PROCMGR_AID_EOL) == -1) {
        slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_ERROR,
               "procmgr_ability fallback failed (errno=%d: %s)", errno, strerror(errno));
        return -1;
    }

    slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_INFO,
           "procmgr_ability locked: nonroot TRACE allowed, root abilities denied");
    return 0;
}

static int qnxp_io_read(resmgr_context_t *ctp, io_read_t *msg, RESMGR_OCB_T *ocb)
{
    int nonblock = 0;
    int status;
    size_t max_bytes;
    size_t total_len = 0U;
    uint32_t fmt;
    char out_buf[QNXP_IO_READ_BUF_BYTES];

    if ((status = iofunc_read_verify(ctp, msg, ocb, &nonblock)) != EOK) {
        return status;
    }

    if ((msg->i.xtype & _IO_XTYPE_MASK) != _IO_XTYPE_NONE) {
        return ENOSYS;
    }

    max_bytes = (size_t)msg->i.nbytes;
    if (max_bytes == 0U) {
        _IO_SET_READ_NBYTES(ctp, 0);
        return _RESMGR_NPARTS(0);
    }
    if (max_bytes > sizeof(out_buf)) {
        max_bytes = sizeof(out_buf);
    }

    fmt = atomic_load_explicit(&g_agent.output_format, memory_order_relaxed);

    while (total_len < max_bytes) {
        qnxp_event_t ev;
        char line[512];
        int n;

        if (qnxp_ring_pop(&g_agent.ring, &ev) <= 0) {
            break;
        }

        if (fmt == (uint32_t)QNXP_FMT_NDJSON) {
            n = qnxp_format_ndjson(&ev, line, sizeof(line));
        } else {
            n = qnxp_format_traceprinter(&ev, line, sizeof(line));
        }

        if (n < 0) {
            continue;
        }

        /* Append newline if the complete line fits into the caller's read buffer. */
        if ((total_len + (size_t)n + 1U) > max_bytes) {
            /* Push back only if nothing was written yet; otherwise stop cleanly at line boundary. */
            if (total_len == 0U) {
                return EMSGSIZE;
            }
            (void)qnxp_ring_push(&g_agent.ring, &ev);
            break;
        }

        memcpy(out_buf + total_len, line, (size_t)n);
        total_len += (size_t)n;
        out_buf[total_len++] = '\n';
    }

    if ((total_len == 0U) && nonblock) {
        return EAGAIN;
    }

    ocb->attr->flags |= IOFUNC_ATTR_ATIME;
    if (MsgReply(ctp->rcvid, (int64_t)total_len, out_buf, total_len) == -1) {
        return errno;
    }

    return _RESMGR_NOREPLY;
}

static int qnxp_io_devctl(resmgr_context_t *ctp, io_devctl_t *msg, RESMGR_OCB_T *ocb)
{
    int status;
    int ret_val = EOK;
    size_t nbytes = 0U;
    void *rx_data;

    if ((status = iofunc_devctl_default(ctp, msg, ocb)) != _RESMGR_DEFAULT) {
        return status;
    }

    rx_data = _DEVCTL_DATA(msg->i);
    qnxp_record_ipc_sample(ctp, (uint8_t)QNXP_EVT_COMM_REC_MESSAGE, (uint32_t)msg->i.dcmd);

    switch (msg->i.dcmd) {
    case _DCMD_QNXPULSE_GET_STATS: {
        qnxp_stats_t *stats = (qnxp_stats_t *)rx_data;
        if ((size_t)msg->i.nbytes < sizeof(*stats)) {
            return EINVAL;
        }
        qnxp_ring_get_stats(
            &g_agent.ring,
            atomic_load_explicit(&g_agent.tracing_active, memory_order_relaxed),
            atomic_load_explicit(&g_agent.output_format, memory_order_relaxed),
            stats);
        nbytes = sizeof(*stats);
        break;
    }

    case _DCMD_QNXPULSE_START_TRACE:
        ret_val = qnxp_trace_start();
        if (ret_val != EOK) {
            return ret_val;
        }
        break;

    case _DCMD_QNXPULSE_STOP_TRACE:
        ret_val = qnxp_trace_stop();
        if (ret_val != EOK) {
            return ret_val;
        }
        break;

    case _DCMD_QNXPULSE_DUMP_RING: {
        qnxp_ring_dump_t *dump = (qnxp_ring_dump_t *)rx_data;
        if ((size_t)msg->i.nbytes < sizeof(*dump)) {
            return EINVAL;
        }
        memset(dump, 0, sizeof(*dump));
        dump->count         = qnxp_ring_pop_batch(&g_agent.ring, dump->events, QNXP_DUMP_BATCH_MAX);
        dump->remaining     = qnxp_ring_buffered(&g_agent.ring);
        dump->dropped_total = atomic_load_explicit(&g_agent.ring.total_dropped, memory_order_relaxed);
        nbytes = sizeof(*dump);
        break;
    }

    case _DCMD_QNXPULSE_SET_FORMAT: {
        const uint32_t *requested = (const uint32_t *)rx_data;
        if ((size_t)msg->i.nbytes < sizeof(*requested)) {
            return EINVAL;
        }
        if ((*requested != (uint32_t)QNXP_FMT_TRACEPRINTER) &&
            (*requested != (uint32_t)QNXP_FMT_NDJSON)) {
            return EINVAL;
        }
        atomic_store_explicit(&g_agent.output_format, *requested, memory_order_relaxed);
        break;
    }

    case _DCMD_QNXPULSE_CLEAR_RING:
        qnxp_ring_reset(&g_agent.ring);
        break;

    default:
        return ENOTTY;
    }

    memset(&msg->o, 0, sizeof(msg->o));
    msg->o.ret_val = ret_val;
    msg->o.nbytes  = (int32_t)nbytes;

    return _RESMGR_PTR(ctp, &msg->o, sizeof(msg->o) + nbytes);
}

int main(int argc, char **argv)
{
    resmgr_attr_t          resmgr_attr;
    resmgr_connect_funcs_t connect_funcs;
    resmgr_io_funcs_t      io_funcs;
    iofunc_attr_t          attr;
    thread_pool_attr_t     pool_attr;
    sigset_t               sigset;
    int                    caught_sig = 0;
    int                    i;

    memset(&g_agent, 0, sizeof(g_agent));
    g_agent.chid      = -1;
    g_agent.resmgr_id = -1;
    atomic_init(&g_agent.tracing_active, 0U);
    atomic_init(&g_agent.output_format, (uint32_t)QNXP_FMT_TRACEPRINTER);

    for (i = 1; i < argc; ++i) {
        if ((strcmp(argv[i], "--ndjson") == 0) ||
            ((strcmp(argv[i], "--format") == 0) && ((i + 1) < argc) &&
             (strcmp(argv[i + 1], "ndjson") == 0))) {
            atomic_store(&g_agent.output_format, (uint32_t)QNXP_FMT_NDJSON);
        }
    }

    if (qnxp_ring_init(&g_agent.ring) != 0) {
        fprintf(stderr, "qnx_pulse_agent: failed to initialize telemetry ring\n");
        return EXIT_FAILURE;
    }

    (void)qnxp_init_slog2();

    /*
     * Block SIGINT/SIGTERM before spawning worker threads so only the main
     * supervisory thread handles graceful shutdown via sigwait().
     */
    sigemptyset(&sigset);
    sigaddset(&sigset, SIGINT);
    sigaddset(&sigset, SIGTERM);
    (void)pthread_sigmask(SIG_BLOCK, &sigset, NULL);

    /*
     * Create channel explicitly WITHOUT _NTO_CHF_FIXED_PRIORITY so QNX 8.0
     * microkernel synchronous IPC priority inheritance stays enabled!
     */
    g_agent.chid = ChannelCreate(_NTO_CHF_DISCONNECT | _NTO_CHF_UNBLOCK);
    if (g_agent.chid == -1) {
        slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_ERROR,
               "ChannelCreate failed: %s", strerror(errno));
        return EXIT_FAILURE;
    }

    g_agent.dpp = dispatch_create_channel(g_agent.chid, 0U);
    if (g_agent.dpp == NULL) {
        slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_ERROR,
               "dispatch_create_channel failed: %s", strerror(errno));
        ChannelDestroy(g_agent.chid);
        return EXIT_FAILURE;
    }

    memset(&resmgr_attr, 0, sizeof(resmgr_attr));
    resmgr_attr.nparts_max   = 2U;
    resmgr_attr.msg_max_size = 4096U;

    iofunc_func_init(_RESMGR_CONNECT_NFUNCS, &connect_funcs,
                     _RESMGR_IO_NFUNCS, &io_funcs);
    io_funcs.read   = qnxp_io_read;
    io_funcs.devctl = qnxp_io_devctl;

    iofunc_attr_init(&attr, S_IFCHR | S_IRUSR | S_IWUSR | S_IRGRP | S_IROTH, NULL, NULL);

    g_agent.resmgr_id = resmgr_attach(
        g_agent.dpp,
        &resmgr_attr,
        QNXP_DEVICE_PATH,
        _FTYPE_ANY,
        0U,
        &connect_funcs,
        &io_funcs,
        &attr);
    if (g_agent.resmgr_id == -1) {
        slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_ERROR,
               "resmgr_attach(%s) failed: %s", QNXP_DEVICE_PATH, strerror(errno));
        (void)dispatch_destroy(g_agent.dpp);
        return EXIT_FAILURE;
    }

    slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_INFO,
           "Attached %s with QNX IPC priority inheritance enabled", QNXP_DEVICE_PATH);

    /* Drop setup privileges (pathspace, public_channel) immediately after attach. */
    (void)qnxp_drop_privileges();

    memset(&pool_attr, 0, sizeof(pool_attr));
    pool_attr.handle        = g_agent.dpp;
    pool_attr.context_alloc = dispatch_context_alloc;
    pool_attr.block_func    = dispatch_block;
    pool_attr.handler_func  = dispatch_handler;
    pool_attr.context_free  = dispatch_context_free;
    pool_attr.lo_water      = 2;
    pool_attr.hi_water      = 4;
    pool_attr.increment     = 1;
    pool_attr.maximum       = 8;

    /*
     * Create without POOL_FLAG_EXIT_SELF so main() remains the external control
     * thread responsible for sigwait() + safe thread_pool_destroy().
     */
    g_agent.tpp = thread_pool_create(&pool_attr, 0U);
    if (g_agent.tpp == NULL) {
        slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_ERROR,
               "thread_pool_create failed: %s", strerror(errno));
        (void)resmgr_detach(g_agent.dpp, g_agent.resmgr_id, _RESMGR_DETACH_ALL);
        (void)dispatch_destroy(g_agent.dpp);
        return EXIT_FAILURE;
    }

    if (thread_pool_start(g_agent.tpp) == -1) {
        slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_ERROR,
               "thread_pool_start failed: %s", strerror(errno));
        (void)thread_pool_destroy(g_agent.tpp);
        (void)resmgr_detach(g_agent.dpp, g_agent.resmgr_id, _RESMGR_DETACH_ALL);
        (void)dispatch_destroy(g_agent.dpp);
        return EXIT_FAILURE;
    }

    slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_INFO,
           "Thread pool running (lo=2, hi=4, max=8); awaiting SIGINT/SIGTERM");

    if (sigwait(&sigset, &caught_sig) == 0) {
        slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_INFO,
               "Received signal %d; initiating graceful shutdown", caught_sig);
    }

    (void)qnxp_trace_stop();
    (void)resmgr_detach(g_agent.dpp, g_agent.resmgr_id, _RESMGR_DETACH_ALL);
    (void)thread_pool_destroy(g_agent.tpp);
    (void)dispatch_destroy(g_agent.dpp);

    slog2f(g_agent.slog_buf, QNXP_SLOG_CODE, SLOG2_INFO, "qnx_pulse_agent exited cleanly");
    return EXIT_SUCCESS;
}

#else /* Host Simulation Mode (Windows MinGW / Linux / macOS) */

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef enum sim_scenario {
    SIM_SCENARIO_HEALTHY   = 0,
    SIM_SCENARIO_INVERSION = 1
} sim_scenario_t;

static qnxp_event_t make_event(uint64_t ts_ns,
                               uint16_t cpu,
                               qnxp_event_class_t cls,
                               qnxp_event_type_t type,
                               uint32_t pid,
                               uint32_t tid,
                               uint32_t peer_pid,
                               uint32_t peer_tid,
                               uint32_t rcvid_or_irq,
                               uint8_t priority,
                               uint8_t peer_priority,
                               uint32_t data0,
                               uint32_t data1,
                               const char *proc_name)
{
    qnxp_event_t ev;
    memset(&ev, 0, sizeof(ev));
    ev.timestamp_ns  = ts_ns;
    ev.cpu           = cpu;
    ev.event_class   = (uint8_t)cls;
    ev.event_type    = (uint8_t)type;
    ev.pid           = pid;
    ev.tid           = tid;
    ev.peer_pid      = peer_pid;
    ev.peer_tid      = peer_tid;
    ev.rcvid_or_irq  = rcvid_or_irq;
    ev.priority      = priority;
    ev.peer_priority = peer_priority;
    ev.data0         = data0;
    ev.data1         = data1;
    if (proc_name != NULL) {
        (void)snprintf(ev.proc_name, sizeof(ev.proc_name), "%s", proc_name);
    }
    return ev;
}

static void push_with_watchdog(qnxp_ring_t *ring,
                               qnxp_event_t *ev,
                               uint32_t channel_flags,
                               int verbose_alerts)
{
    qnxp_inversion_alert_t alert;

    if (qnxp_evaluate_event_inversion(ev, channel_flags, &alert)) {
        if (verbose_alerts) {
            fprintf(stderr, "[qnx_pulse_agent_sim][WATCHDOG sev=%u] %s\n",
                    (unsigned int)alert.severity, alert.reason);
        }
        (void)qnxp_ring_push(ring, ev);

        /* Emit a matching USREVENT marker exactly as the QNX 8.0 target agent does. */
        {
            qnxp_event_t marker = make_event(
                ev->timestamp_ns + 500ULL,
                ev->cpu,
                QNXP_CLASS_USREVENT,
                QNXP_EVT_USREVENT,
                4096U, 1U,
                alert.server_pid, alert.server_tid,
                QNXP_USREVENT_INVERSION,
                60U, alert.server_eff_priority,
                alert.client_pid, alert.priority_gap,
                "qnx_pulse_agent");
            (void)qnxp_ring_push(ring, &marker);
        }
        return;
    }

    (void)qnxp_ring_push(ring, ev);
}

static void populate_adas_scenario(qnxp_ring_t *ring, sim_scenario_t scenario, int verbose_alerts)
{
    const uint32_t pid_lidar = 4101U; /* /dev/lidar_fusion server (base prio 18) */
    const uint32_t pid_aeb   = 4102U; /* adas_aeb safety brake client (prio 52)  */
    const uint32_t pid_can   = 4103U; /* can_telemetry medium task (prio 30)     */
    const uint32_t rcvid_ipc = 0x0000004FU;
    const uint64_t t0        = 0x4F862000ULL;

    if (scenario == SIM_SCENARIO_HEALTHY) {
        /*
         * Healthy QNX 8.0 synchronous IPC with default Priority Inheritance:
         * adas_aeb (52) -> MsgSend -> lidar_fusion (base 18, boosted to 52).
         * Medium-priority can_telemetry (30) cannot preempt lidar_fusion.
         */
        qnxp_event_t burst[] = {
            make_event(t0 + 0ULL, 0U, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THRUNNING,
                       pid_aeb, 1U, 0U, 0U, 0U, 52U, 0U, 0U, 0U, "adas_aeb"),
            make_event(t0 + 120000ULL, 0U, QNXP_CLASS_COMM, QNXP_EVT_COMM_SND_MESSAGE,
                       pid_aeb, 1U, pid_lidar, 2U, rcvid_ipc, 52U, 52U, 256U, 10000U, "adas_aeb"),
            make_event(t0 + 125000ULL, 0U, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THREPLY,
                       pid_aeb, 1U, pid_lidar, 2U, rcvid_ipc, 52U, 52U, 0U, 10000U, "adas_aeb"),
            make_event(t0 + 132000ULL, 0U, QNXP_CLASS_COMM, QNXP_EVT_COMM_REC_MESSAGE,
                       pid_lidar, 2U, pid_aeb, 1U, rcvid_ipc, 52U, 52U, 256U, 0U, "lidar_fusion"),
            make_event(t0 + 140000ULL, 0U, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THRUNNING,
                       pid_lidar, 2U, 0U, 0U, 0U, 52U, 0U, 0U, 0U, "lidar_fusion"),
            make_event(t0 + 420000ULL, 0U, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THREADY,
                       pid_can, 1U, 0U, 0U, 0U, 30U, 0U, 0U, 0U, "can_telemetry"),
            make_event(t0 + 610000ULL, 1U, QNXP_CLASS_INT, QNXP_EVT_INT_ENTR,
                       pid_lidar, 0U, 0U, 0U, 0x21U, 0U, 0U, 0U, 0U, "lidar_irq"),
            make_event(t0 + 628000ULL, 1U, QNXP_CLASS_INT, QNXP_EVT_INT_EXIT,
                       pid_lidar, 0U, 0U, 0U, 0x21U, 0U, 0U, 0U, 0U, "lidar_irq"),
            make_event(t0 + 1520000ULL, 0U, QNXP_CLASS_COMM, QNXP_EVT_COMM_REPLY_MESSAGE,
                       pid_lidar, 2U, pid_aeb, 1U, rcvid_ipc, 52U, 52U, 1400U, 10000U, "lidar_fusion"),
            make_event(t0 + 1535000ULL, 0U, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THRUNNING,
                       pid_aeb, 1U, 0U, 0U, 0U, 52U, 0U, 0U, 0U, "adas_aeb"),
            make_event(t0 + 1560000ULL, 0U, QNXP_CLASS_USREVENT, QNXP_EVT_USREVENT,
                       pid_aeb, 1U, 0U, 0U, QNXP_USREVENT_HEARTBEAT, 52U, 0U, 1400U, 10000U, "adas_aeb")
        };
        size_t i;
        for (i = 0U; i < (sizeof(burst) / sizeof(burst[0])); ++i) {
            push_with_watchdog(ring, &burst[i], QNXP_CHF_NONE, verbose_alerts);
        }
        return;
    }

    /*
     * Priority Inversion Scenario:
     * /dev/lidar_fusion erroneously set _NTO_CHF_FIXED_PRIORITY on its channel.
     * adas_aeb (52) blocks on lidar_fusion (stuck at 18); can_telemetry (30)
     * preempts lidar_fusion, causing a 12.85ms response exceeding the 10ms AEB deadline.
     */
    {
        qnxp_event_t burst[] = {
            make_event(t0 + 0ULL, 0U, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THRUNNING,
                       pid_aeb, 1U, 0U, 0U, 0U, 52U, 0U, 0U, 0U, "adas_aeb"),
            make_event(t0 + 120000ULL, 0U, QNXP_CLASS_COMM, QNXP_EVT_COMM_SND_MESSAGE,
                       pid_aeb, 1U, pid_lidar, 2U, rcvid_ipc, 52U, 18U, 256U, 10000U, "adas_aeb"),
            make_event(t0 + 125000ULL, 0U, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THREPLY,
                       pid_aeb, 1U, pid_lidar, 2U, rcvid_ipc, 52U, 18U, 0U, 10000U, "adas_aeb"),
            make_event(t0 + 135000ULL, 0U, QNXP_CLASS_COMM, QNXP_EVT_COMM_REC_MESSAGE,
                       pid_lidar, 2U, pid_aeb, 1U, rcvid_ipc, 18U, 52U, 256U, 0U, "lidar_fusion"),
            make_event(t0 + 142000ULL, 0U, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THRUNNING,
                       pid_lidar, 2U, 0U, 0U, 0U, 18U, 0U, 0U, 0U, "lidar_fusion"),
            make_event(t0 + 380000ULL, 0U, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THREADY,
                       pid_can, 1U, 0U, 0U, 0U, 30U, 0U, 0U, 0U, "can_telemetry"),
            make_event(t0 + 390000ULL, 0U, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THRUNNING,
                       pid_can, 1U, 0U, 0U, 0U, 30U, 0U, 0U, 0U, "can_telemetry"),
            make_event(t0 + 4200000ULL, 0U, QNXP_CLASS_INT, QNXP_EVT_INT_ENTR,
                       pid_can, 0U, 0U, 0U, 0x24U, 0U, 0U, 0U, 0U, "can_irq"),
            make_event(t0 + 4235000ULL, 0U, QNXP_CLASS_INT, QNXP_EVT_INT_EXIT,
                       pid_can, 0U, 0U, 0U, 0x24U, 0U, 0U, 0U, 0U, "can_irq"),
            make_event(t0 + 11850000ULL, 0U, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THRUNNING,
                       pid_lidar, 2U, 0U, 0U, 0U, 18U, 0U, 0U, 0U, "lidar_fusion"),
            make_event(t0 + 12970000ULL, 0U, QNXP_CLASS_COMM, QNXP_EVT_COMM_REPLY_MESSAGE,
                       pid_lidar, 2U, pid_aeb, 1U, rcvid_ipc, 18U, 52U, 12850U, 10000U, "lidar_fusion"),
            make_event(t0 + 12985000ULL, 0U, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THRUNNING,
                       pid_aeb, 1U, 0U, 0U, 0U, 52U, 0U, 0U, 0U, "adas_aeb"),
            make_event(t0 + 13000000ULL, 0U, QNXP_CLASS_USREVENT, QNXP_EVT_USREVENT,
                       pid_aeb, 1U, 0U, 0U, QNXP_USREVENT_DEADLINE, 52U, 0U, 12850U, 10000U, "adas_aeb")
        };
        size_t i;
        for (i = 0U; i < (sizeof(burst) / sizeof(burst[0])); ++i) {
            push_with_watchdog(ring, &burst[i], QNXP_CHF_FIXED_PRIORITY, verbose_alerts);
        }
    }
}

static void print_usage(const char *prog)
{
    fprintf(stderr,
            "Usage: %s [options]\n"
            "QNX-Pulse Target Agent Host Simulator (qnx_pulse_agent_sim)\n\n"
            "Options:\n"
            "  --format traceprinter|ndjson   Output stream format (default: traceprinter)\n"
            "  --scenario healthy|inversion   ADAS IPC trace burst (default: inversion)\n"
            "  --output <file> | -o <file>    Write telemetry stream to file instead of stdout\n"
            "  --stats                        Print ring buffer & watchdog stats to stderr\n"
            "  --help | -h                    Show this help message\n",
            prog);
}

int main(int argc, char **argv)
{
    qnxp_output_format_t format = QNXP_FMT_TRACEPRINTER;
    sim_scenario_t scenario = SIM_SCENARIO_INVERSION;
    const char *output_path = NULL;
    int print_stats = 0;
    int i;
    FILE *out = stdout;
    qnxp_ring_t ring;
    qnxp_stats_t pre_drain_stats;
    qnxp_stats_t post_drain_stats;
    qnxp_event_t ev;
    char line[512];

    for (i = 1; i < argc; ++i) {
        if ((strcmp(argv[i], "--help") == 0) || (strcmp(argv[i], "-h") == 0)) {
            print_usage(argv[0]);
            return EXIT_SUCCESS;
        } else if (strcmp(argv[i], "--format") == 0) {
            if ((i + 1) >= argc) {
                fprintf(stderr, "Error: --format requires an argument (traceprinter|ndjson)\n");
                return EXIT_FAILURE;
            }
            ++i;
            if (strcmp(argv[i], "traceprinter") == 0) {
                format = QNXP_FMT_TRACEPRINTER;
            } else if (strcmp(argv[i], "ndjson") == 0) {
                format = QNXP_FMT_NDJSON;
            } else {
                fprintf(stderr, "Error: unsupported format '%s' (expected traceprinter|ndjson)\n", argv[i]);
                return EXIT_FAILURE;
            }
        } else if (strcmp(argv[i], "--scenario") == 0) {
            if ((i + 1) >= argc) {
                fprintf(stderr, "Error: --scenario requires an argument (healthy|inversion)\n");
                return EXIT_FAILURE;
            }
            ++i;
            if (strcmp(argv[i], "healthy") == 0) {
                scenario = SIM_SCENARIO_HEALTHY;
            } else if (strcmp(argv[i], "inversion") == 0) {
                scenario = SIM_SCENARIO_INVERSION;
            } else {
                fprintf(stderr, "Error: unsupported scenario '%s' (expected healthy|inversion)\n", argv[i]);
                return EXIT_FAILURE;
            }
        } else if ((strcmp(argv[i], "--output") == 0) || (strcmp(argv[i], "-o") == 0)) {
            if ((i + 1) >= argc) {
                fprintf(stderr, "Error: %s requires a file path\n", argv[i]);
                return EXIT_FAILURE;
            }
            output_path = argv[++i];
        } else if (strcmp(argv[i], "--stats") == 0) {
            print_stats = 1;
        } else {
            fprintf(stderr, "Error: unknown argument '%s'\n", argv[i]);
            print_usage(argv[0]);
            return EXIT_FAILURE;
        }
    }

    if (qnxp_ring_init(&ring) != 0) {
        fprintf(stderr, "Error: failed to initialize telemetry ring buffer\n");
        return EXIT_FAILURE;
    }

    if (output_path != NULL) {
        out = fopen(output_path, "wb");
        if (out == NULL) {
            perror("Failed to open output file");
            return EXIT_FAILURE;
        }
    }

    populate_adas_scenario(&ring, scenario, 1);
    qnxp_ring_get_stats(&ring, 1U, (uint32_t)format, &pre_drain_stats);

    while (qnxp_ring_pop(&ring, &ev) == 1) {
        int n = (format == QNXP_FMT_NDJSON)
                    ? qnxp_format_ndjson(&ev, line, sizeof(line))
                    : qnxp_format_traceprinter(&ev, line, sizeof(line));
        if (n < 0) {
            fprintf(stderr, "Error: failed to format event seq=%" PRIu32 "\n", ev.seq);
            if (out != stdout) {
                (void)fclose(out);
            }
            return EXIT_FAILURE;
        }
        if (fprintf(out, "%s\n", line) < 0) {
            perror("Failed to write output");
            if (out != stdout) {
                (void)fclose(out);
            }
            return EXIT_FAILURE;
        }
    }

    (void)fflush(out);
    qnxp_ring_get_stats(&ring, 0U, (uint32_t)format, &post_drain_stats);

    if (print_stats || (scenario == SIM_SCENARIO_INVERSION)) {
        fprintf(stderr,
                "[qnx_pulse_agent_sim] scenario=%s format=%s captured=%" PRIu64
                " read=%" PRIu64 " dropped=%" PRIu64 " inversions=%" PRIu64
                " buffered_before=%" PRIu32 " buffered_after=%" PRIu32 "\n",
                (scenario == SIM_SCENARIO_INVERSION) ? "inversion" : "healthy",
                (format == QNXP_FMT_NDJSON) ? "ndjson" : "traceprinter",
                post_drain_stats.total_captured,
                post_drain_stats.total_read,
                post_drain_stats.total_dropped,
                post_drain_stats.inversions_detected,
                pre_drain_stats.ring_buffered,
                post_drain_stats.ring_buffered);
    }

    if (out != stdout) {
        if (fclose(out) != 0) {
            perror("Failed to close output file");
            return EXIT_FAILURE;
        }
    }

    return EXIT_SUCCESS;
}

#endif /* __QNX__ */
