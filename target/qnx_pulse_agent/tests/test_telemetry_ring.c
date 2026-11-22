/*
 * QNX-Pulse Telemetry Ring, Formatters & Watchdog C11 Unit Test Suite
 *
 * Zero external test framework dependencies. Compiles cleanly under
 * gcc -std=c11 -Wall -Wextra -Werror on Windows MinGW64, Linux, macOS, and QNX 8.0.
 */

#include "qnx_pulse_protocol.h"
#include "telemetry_ring.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int g_tests_run    = 0;
static int g_tests_failed = 0;

#define ASSERT_TRUE(expr)                                                               \
    do {                                                                                \
        if (!(expr)) {                                                                  \
            fprintf(stderr, "  FAIL [%s:%d]: assertion failed: %s\n",                   \
                    __FILE__, __LINE__, #expr);                                         \
            return 1;                                                                   \
        }                                                                               \
    } while (0)

#define ASSERT_EQ_U64(actual, expected)                                                 \
    do {                                                                                \
        uint64_t _a = (uint64_t)(actual);                                               \
        uint64_t _e = (uint64_t)(expected);                                             \
        if (_a != _e) {                                                                 \
            fprintf(stderr, "  FAIL [%s:%d]: %s == %" PRIu64 ", expected %" PRIu64 "\n",\
                    __FILE__, __LINE__, #actual, _a, _e);                               \
            return 1;                                                                   \
        }                                                                               \
    } while (0)

#define ASSERT_EQ_INT(actual, expected)                                                 \
    do {                                                                                \
        int _a = (int)(actual);                                                         \
        int _e = (int)(expected);                                                       \
        if (_a != _e) {                                                                 \
            fprintf(stderr, "  FAIL [%s:%d]: %s == %d, expected %d\n",                  \
                    __FILE__, __LINE__, #actual, _a, _e);                               \
            return 1;                                                                   \
        }                                                                               \
    } while (0)

#define RUN_TEST(fn)                                                                    \
    do {                                                                                \
        ++g_tests_run;                                                                  \
        if ((fn)() == 0) {                                                              \
            printf("  [PASS] %s\n", #fn);                                               \
        } else {                                                                        \
            ++g_tests_failed;                                                           \
            printf("  [FAIL] %s\n", #fn);                                               \
        }                                                                               \
    } while (0)

static qnxp_event_t build_sample_event(uint64_t ts_ns,
                                       qnxp_event_class_t cls,
                                       qnxp_event_type_t type,
                                       uint32_t pid,
                                       uint32_t tid,
                                       uint32_t peer_pid,
                                       uint8_t prio,
                                       uint8_t peer_prio,
                                       const char *name)
{
    qnxp_event_t ev;
    memset(&ev, 0, sizeof(ev));
    ev.timestamp_ns  = ts_ns;
    ev.cpu           = 0U;
    ev.event_class   = (uint8_t)cls;
    ev.event_type    = (uint8_t)type;
    ev.pid           = pid;
    ev.tid           = tid;
    ev.peer_pid      = peer_pid;
    ev.peer_tid      = 1U;
    ev.rcvid_or_irq  = 0x0000004FU;
    ev.priority      = prio;
    ev.peer_priority = peer_prio;
    ev.data0         = 128U;
    ev.data1         = 10000U;
    if (name != NULL) {
        (void)snprintf(ev.proc_name, sizeof(ev.proc_name), "%s", name);
    }
    return ev;
}

static int test_protocol_constants_and_sizes(void)
{
    const int cmds[] = {
        _DCMD_QNXPULSE_GET_STATS,
        _DCMD_QNXPULSE_START_TRACE,
        _DCMD_QNXPULSE_STOP_TRACE,
        _DCMD_QNXPULSE_DUMP_RING,
        _DCMD_QNXPULSE_SET_FORMAT,
        _DCMD_QNXPULSE_CLEAR_RING
    };
    size_t i;
    size_t j;

    ASSERT_EQ_U64(sizeof(qnxp_event_t), 72U);
    ASSERT_TRUE(sizeof(qnxp_ring_dump_t) <= 4096U);

    for (i = 0U; i < (sizeof(cmds) / sizeof(cmds[0])); ++i) {
        ASSERT_TRUE(cmds[i] != 0);
        for (j = i + 1U; j < (sizeof(cmds) / sizeof(cmds[0])); ++j) {
            ASSERT_TRUE(cmds[i] != cmds[j]);
        }
    }
    return 0;
}

static int test_ring_init_validation(void)
{
    qnxp_ring_t ring;
    qnxp_event_t ev;

    ASSERT_EQ_INT(qnxp_ring_init(NULL), -1);
    ASSERT_EQ_INT(qnxp_ring_init_capacity(&ring, 0U), -1);
    ASSERT_EQ_INT(qnxp_ring_init_capacity(&ring, 1U), -1);
    ASSERT_EQ_INT(qnxp_ring_init_capacity(&ring, 3U), -1);
    ASSERT_EQ_INT(qnxp_ring_init_capacity(&ring, 12U), -1);
    ASSERT_EQ_INT(qnxp_ring_init_capacity(&ring, QNXP_RING_CAPACITY * 2U), -1);

    ASSERT_EQ_INT(qnxp_ring_init_capacity(&ring, 8U), 0);
    ASSERT_EQ_U64(ring.capacity, 8U);
    ASSERT_EQ_U64(qnxp_ring_buffered(&ring), 0U);
    ASSERT_EQ_INT(qnxp_ring_pop(&ring, &ev), 0);

    ASSERT_EQ_INT(qnxp_ring_init(&ring), 0);
    ASSERT_EQ_U64(ring.capacity, QNXP_RING_CAPACITY);
    return 0;
}

static int test_zero_drop_normal_operation(void)
{
    qnxp_ring_t ring;
    qnxp_stats_t stats;
    uint32_t cycle;
    uint32_t expected_seq = 1U;

    ASSERT_EQ_INT(qnxp_ring_init_capacity(&ring, 16U), 0);

    /* Push & drain 40 cycles x 10 events = 400 events across a 16-slot ring with zero drops. */
    for (cycle = 0U; cycle < 40U; ++cycle) {
        uint32_t k;
        qnxp_event_t batch[16];
        uint32_t popped;

        for (k = 0U; k < 10U; ++k) {
            uint64_t ts = 1000000ULL + ((uint64_t)(cycle * 10U + k) * 500ULL);
            qnxp_event_t ev = build_sample_event(
                ts, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THRUNNING,
                4100U + k, 1U, 0U, 40U, 0U, "adas_worker");
            ASSERT_EQ_INT(qnxp_ring_push(&ring, &ev), 0);
        }

        ASSERT_EQ_U64(qnxp_ring_buffered(&ring), 10U);
        popped = qnxp_ring_pop_batch(&ring, batch, 16U);
        ASSERT_EQ_U64(popped, 10U);

        for (k = 0U; k < popped; ++k) {
            ASSERT_EQ_U64(batch[k].seq, expected_seq);
            ASSERT_EQ_U64(batch[k].pid, 4100U + k);
            ++expected_seq;
        }
        ASSERT_EQ_U64(qnxp_ring_buffered(&ring), 0U);
    }

    qnxp_ring_get_stats(&ring, 1U, QNXP_FMT_TRACEPRINTER, &stats);
    ASSERT_EQ_U64(stats.protocol_version, QNXP_PROTOCOL_VERSION);
    ASSERT_EQ_U64(stats.tracing_active, 1U);
    ASSERT_EQ_U64(stats.ring_capacity, 16U);
    ASSERT_EQ_U64(stats.ring_buffered, 0U);
    ASSERT_EQ_U64(stats.total_captured, 400U);
    ASSERT_EQ_U64(stats.total_read, 400U);
    ASSERT_EQ_U64(stats.total_dropped, 0U);
    return 0;
}

static int test_wrap_around_and_overflow_counting(void)
{
    qnxp_ring_t ring;
    qnxp_stats_t stats;
    qnxp_event_t out;
    uint32_t i;

    ASSERT_EQ_INT(qnxp_ring_init_capacity(&ring, 8U), 0);

    /* Push 20 events into an 8-slot ring without reading: 8 fit, 12 overwrite oldest slots. */
    for (i = 0U; i < 20U; ++i) {
        qnxp_event_t ev = build_sample_event(
            0x100000ULL + (uint64_t)i * 100ULL,
            QNXP_CLASS_COMM, QNXP_EVT_COMM_SND_MESSAGE,
            5000U + i, 1U, 4101U, 50U, 50U, "burst_sender");
        int rc = qnxp_ring_push(&ring, &ev);
        if (i < 8U) {
            ASSERT_EQ_INT(rc, 0);
        } else {
            ASSERT_EQ_INT(rc, 1);
        }
    }

    qnxp_ring_get_stats(&ring, 1U, QNXP_FMT_NDJSON, &stats);
    ASSERT_EQ_U64(stats.ring_buffered, 8U);
    ASSERT_EQ_U64(stats.total_captured, 20U);
    ASSERT_EQ_U64(stats.total_dropped, 12U);
    ASSERT_EQ_U64(stats.total_read, 0U);

    /* Remaining 8 events must be the newest 8 (seq 13..20, pid 5012..5019). */
    for (i = 0U; i < 8U; ++i) {
        ASSERT_EQ_INT(qnxp_ring_pop(&ring, &out), 1);
        ASSERT_EQ_U64(out.seq, 13U + i);
        ASSERT_EQ_U64(out.pid, 5012U + i);
    }
    ASSERT_EQ_INT(qnxp_ring_pop(&ring, &out), 0);
    ASSERT_EQ_U64(qnxp_ring_buffered(&ring), 0U);

    qnxp_ring_reset(&ring);
    qnxp_ring_get_stats(&ring, 0U, QNXP_FMT_TRACEPRINTER, &stats);
    ASSERT_EQ_U64(stats.ring_capacity, 8U);
    ASSERT_EQ_U64(stats.total_captured, 0U);
    ASSERT_EQ_U64(stats.total_dropped, 0U);
    return 0;
}

static int test_traceprinter_formatting_fidelity(void)
{
    char buf[512];
    char tiny[12];
    int n;

    /* COMM : SND_MESSAGE with inversion flags */
    {
        qnxp_event_t ev = build_sample_event(
            0x4F86E756ULL, QNXP_CLASS_COMM, QNXP_EVT_COMM_SND_MESSAGE,
            4102U, 1U, 4101U, 52U, 18U, "adas_aeb");
        ev.flags = QNXP_FLAG_PRIO_INVERSION | QNXP_FLAG_FIXED_PRIORITY;
        n = qnxp_format_traceprinter(&ev, buf, sizeof(buf));
        ASSERT_TRUE(n > 0);
        ASSERT_TRUE(strstr(buf, "t:0x4f86e756 CPU:00 COMM : SND_MESSAGE ") != NULL);
        ASSERT_TRUE(strstr(buf, "rcvid:0x0000004f") != NULL);
        ASSERT_TRUE(strstr(buf, "pid:4102") != NULL);
        ASSERT_TRUE(strstr(buf, "target_pid:4101") != NULL);
        ASSERT_TRUE(strstr(buf, "prio:52") != NULL);
        ASSERT_TRUE(strstr(buf, "peer_prio:18") != NULL);
        ASSERT_TRUE(strstr(buf, "inversion:1") != NULL);
        ASSERT_TRUE(strstr(buf, "fixed_prio:1") != NULL);
        ASSERT_EQ_INT(qnxp_format_traceprinter(&ev, tiny, sizeof(tiny)), -1);
    }

    /* COMM : REC_MESSAGE */
    {
        qnxp_event_t ev = build_sample_event(
            0x4F86E800ULL, QNXP_CLASS_COMM, QNXP_EVT_COMM_REC_MESSAGE,
            4101U, 2U, 4102U, 52U, 52U, "lidar_fusion");
        n = qnxp_format_traceprinter(&ev, buf, sizeof(buf));
        ASSERT_TRUE(n > 0);
        ASSERT_TRUE(strstr(buf, "COMM : REC_MESSAGE") != NULL);
        ASSERT_TRUE(strstr(buf, "client_pid:4102") != NULL);
    }

    /* COMM : REPLY_MESSAGE */
    {
        qnxp_event_t ev = build_sample_event(
            0x4F86F000ULL, QNXP_CLASS_COMM, QNXP_EVT_COMM_REPLY_MESSAGE,
            4101U, 2U, 4102U, 52U, 52U, "lidar_fusion");
        ev.data0 = 1400U;
        n = qnxp_format_traceprinter(&ev, buf, sizeof(buf));
        ASSERT_TRUE(n > 0);
        ASSERT_TRUE(strstr(buf, "COMM : REPLY_MESSAGE") != NULL);
        ASSERT_TRUE(strstr(buf, "latency_us:1400") != NULL);
    }

    /* THREAD : THRUNNING, THREADY, THREPLY */
    {
        qnxp_event_t ev_run = build_sample_event(
            0x4F8627B4ULL, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THRUNNING,
            4102U, 1U, 0U, 52U, 0U, "adas_aeb");
        qnxp_event_t ev_rdy = build_sample_event(
            0x4F862800ULL, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THREADY,
            4103U, 1U, 0U, 30U, 0U, "can_telemetry");
        qnxp_event_t ev_rep = build_sample_event(
            0x4F862900ULL, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THREPLY,
            4102U, 1U, 4101U, 52U, 18U, "adas_aeb");

        ASSERT_TRUE(qnxp_format_traceprinter(&ev_run, buf, sizeof(buf)) > 0);
        ASSERT_TRUE(strstr(buf, "THREAD : THRUNNING pid:4102 tid:1 priority:52") != NULL);

        ASSERT_TRUE(qnxp_format_traceprinter(&ev_rdy, buf, sizeof(buf)) > 0);
        ASSERT_TRUE(strstr(buf, "THREAD : THREADY pid:4103 tid:1 priority:30") != NULL);

        ASSERT_TRUE(qnxp_format_traceprinter(&ev_rep, buf, sizeof(buf)) > 0);
        ASSERT_TRUE(strstr(buf, "THREAD : THREPLY pid:4102 tid:1 server_pid:4101") != NULL);
    }

    /* INT : INT_ENTR, INT_EXIT and USREVENT */
    {
        qnxp_event_t ev_ie = build_sample_event(
            0x4F863000ULL, QNXP_CLASS_INT, QNXP_EVT_INT_ENTR,
            4101U, 0U, 0U, 0U, 0U, "irq");
        qnxp_event_t ev_ix = build_sample_event(
            0x4F863050ULL, QNXP_CLASS_INT, QNXP_EVT_INT_EXIT,
            4101U, 0U, 0U, 0U, 0U, "irq");
        qnxp_event_t ev_usr = build_sample_event(
            0x4F863100ULL, QNXP_CLASS_USREVENT, QNXP_EVT_USREVENT,
            4096U, 1U, 0U, 60U, 0U, "qnx_pulse_agent");
        ev_ie.rcvid_or_irq  = 0x24U;
        ev_ix.rcvid_or_irq  = 0x24U;
        ev_usr.rcvid_or_irq = QNXP_USREVENT_INVERSION;

        ASSERT_TRUE(qnxp_format_traceprinter(&ev_ie, buf, sizeof(buf)) > 0);
        ASSERT_TRUE(strstr(buf, "INT : INT_ENTR irq:0x24") != NULL);

        ASSERT_TRUE(qnxp_format_traceprinter(&ev_ix, buf, sizeof(buf)) > 0);
        ASSERT_TRUE(strstr(buf, "INT : INT_EXIT irq:0x24") != NULL);

        ASSERT_TRUE(qnxp_format_traceprinter(&ev_usr, buf, sizeof(buf)) > 0);
        ASSERT_TRUE(strstr(buf, "USREVENT : EVENT event:257") != NULL);
    }

    return 0;
}

static int test_ndjson_formatting_and_escaping(void)
{
    char buf[512];
    char tiny[16];
    int n;
    qnxp_event_t ev = build_sample_event(
        1334241110ULL, QNXP_CLASS_COMM, QNXP_EVT_COMM_SND_MESSAGE,
        4102U, 1U, 4101U, 52U, 18U, "aeb\"\\mgr");
    ev.seq   = 42U;
    ev.flags = QNXP_FLAG_PRIO_INVERSION | QNXP_FLAG_FIXED_PRIORITY;

    n = qnxp_format_ndjson(&ev, buf, sizeof(buf));
    ASSERT_TRUE(n > 0);
    ASSERT_TRUE(buf[0] == '{');
    ASSERT_TRUE(buf[n - 1] == '}');
    ASSERT_TRUE(strstr(buf, "\"seq\":42") != NULL);
    ASSERT_TRUE(strstr(buf, "\"class\":\"COMM\"") != NULL);
    ASSERT_TRUE(strstr(buf, "\"event\":\"SND_MESSAGE\"") != NULL);
    ASSERT_TRUE(strstr(buf, "\"prio_inversion\":true") != NULL);
    ASSERT_TRUE(strstr(buf, "\"fixed_priority\":true") != NULL);
    ASSERT_TRUE(strstr(buf, "\"proc\":\"aeb\\\"\\\\mgr\"") != NULL);

    ASSERT_EQ_INT(qnxp_format_ndjson(&ev, tiny, sizeof(tiny)), -1);
    return 0;
}

static int test_priority_inversion_watchdog(void)
{
    qnxp_inversion_alert_t alert;
    qnxp_ring_t ring;
    qnxp_stats_t stats;
    int detected;

    /* Positive case 1: High-priority client (52) blocked on fixed-priority server (18). */
    detected = qnxp_check_ipc_inversion(
        4102U, 1U, 52U,
        4101U, 2U, 18U,
        QNXP_CHF_FIXED_PRIORITY,
        &alert);
    ASSERT_EQ_INT(detected, 1);
    ASSERT_EQ_U64(alert.detected, 1U);
    ASSERT_EQ_U64(alert.severity, 2U);
    ASSERT_EQ_U64(alert.priority_gap, 34U);
    ASSERT_TRUE(strstr(alert.reason, "_NTO_CHF_FIXED_PRIORITY") != NULL);

    /* Positive case 2: Non-fixed channel but decoupled server failed to inherit (gap=10 -> warning). */
    detected = qnxp_check_ipc_inversion(
        4102U, 1U, 40U,
        4101U, 2U, 30U,
        QNXP_CHF_NONE,
        &alert);
    ASSERT_EQ_INT(detected, 1);
    ASSERT_EQ_U64(alert.severity, 1U);
    ASSERT_EQ_U64(alert.priority_gap, 10U);

    /* Negative case 1: Healthy QNX priority inheritance (server boosted to client priority 52). */
    detected = qnxp_check_ipc_inversion(
        4102U, 1U, 52U,
        4101U, 2U, 52U,
        QNXP_CHF_NONE,
        &alert);
    ASSERT_EQ_INT(detected, 0);
    ASSERT_EQ_U64(alert.detected, 0U);

    /* Negative case 2: Lower-priority client calling higher-priority server. */
    detected = qnxp_check_ipc_inversion(
        4103U, 1U, 15U,
        4101U, 2U, 40U,
        QNXP_CHF_NONE,
        &alert);
    ASSERT_EQ_INT(detected, 0);

    /* Negative case 3: Self-thread or invalid server PID 0. */
    ASSERT_EQ_INT(qnxp_check_ipc_inversion(4102U, 1U, 52U, 4102U, 1U, 18U, QNXP_CHF_NONE, &alert), 0);
    ASSERT_EQ_INT(qnxp_check_ipc_inversion(4102U, 1U, 52U, 0U, 0U, 0U, QNXP_CHF_NONE, &alert), 0);

    /* Event evaluation helper + ring inversion counter integration. */
    ASSERT_EQ_INT(qnxp_ring_init_capacity(&ring, 16U), 0);

    {
        qnxp_event_t ev_snd = build_sample_event(
            1000ULL, QNXP_CLASS_COMM, QNXP_EVT_COMM_SND_MESSAGE,
            4102U, 1U, 4101U, 52U, 18U, "adas_aeb");
        qnxp_event_t ev_rec = build_sample_event(
            1100ULL, QNXP_CLASS_COMM, QNXP_EVT_COMM_REC_MESSAGE,
            4101U, 2U, 4102U, 18U, 52U, "lidar_fusion");
        qnxp_event_t ev_ok = build_sample_event(
            1200ULL, QNXP_CLASS_COMM, QNXP_EVT_COMM_SND_MESSAGE,
            4102U, 1U, 4101U, 52U, 52U, "adas_aeb");
        qnxp_event_t ev_run = build_sample_event(
            1300ULL, QNXP_CLASS_THREAD, QNXP_EVT_THREAD_THRUNNING,
            4102U, 1U, 0U, 52U, 0U, "adas_aeb");

        ASSERT_EQ_INT(qnxp_evaluate_event_inversion(&ev_snd, QNXP_CHF_FIXED_PRIORITY, &alert), 1);
        ASSERT_TRUE((ev_snd.flags & QNXP_FLAG_PRIO_INVERSION) != 0U);
        ASSERT_TRUE((ev_snd.flags & QNXP_FLAG_FIXED_PRIORITY) != 0U);

        ASSERT_EQ_INT(qnxp_evaluate_event_inversion(&ev_rec, QNXP_CHF_FIXED_PRIORITY, &alert), 1);
        ASSERT_TRUE((ev_rec.flags & QNXP_FLAG_PRIO_INVERSION) != 0U);

        ASSERT_EQ_INT(qnxp_evaluate_event_inversion(&ev_ok, QNXP_CHF_NONE, &alert), 0);
        ASSERT_EQ_U64(ev_ok.flags & QNXP_FLAG_PRIO_INVERSION, 0U);

        ASSERT_EQ_INT(qnxp_evaluate_event_inversion(&ev_run, QNXP_CHF_NONE, &alert), 0);

        ASSERT_EQ_INT(qnxp_ring_push(&ring, &ev_snd), 0);
        ASSERT_EQ_INT(qnxp_ring_push(&ring, &ev_rec), 0);
        ASSERT_EQ_INT(qnxp_ring_push(&ring, &ev_ok), 0);
        ASSERT_EQ_INT(qnxp_ring_push(&ring, &ev_run), 0);
    }

    qnxp_ring_get_stats(&ring, 1U, QNXP_FMT_TRACEPRINTER, &stats);
    ASSERT_EQ_U64(stats.total_captured, 4U);
    ASSERT_EQ_U64(stats.inversions_detected, 2U);
    return 0;
}

int main(void)
{
    printf("Running QNX-Pulse Telemetry Ring & Watchdog C11 Unit Tests...\n");

    RUN_TEST(test_protocol_constants_and_sizes);
    RUN_TEST(test_ring_init_validation);
    RUN_TEST(test_zero_drop_normal_operation);
    RUN_TEST(test_wrap_around_and_overflow_counting);
    RUN_TEST(test_traceprinter_formatting_fidelity);
    RUN_TEST(test_ndjson_formatting_and_escaping);
    RUN_TEST(test_priority_inversion_watchdog);

    printf("Summary: %d/%d tests passed.\n", g_tests_run - g_tests_failed, g_tests_run);
    return (g_tests_failed == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
}
