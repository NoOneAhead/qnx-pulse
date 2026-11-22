/*
 * QNX-Pulse Target Companion Protocol Header (QNX SDP 8.0 & Host Simulation)
 *
 * Defines the devctl(2) control plane, fixed-size zero-allocation telemetry
 * event structures, traceprinter-compatible event classes/types, and inline
 * priority-inversion watchdog descriptors shared between the QNX 8.0 target
 * resource manager (/dev/qnxpulse) and host tooling.
 */

#ifndef QNX_PULSE_PROTOCOL_H
#define QNX_PULSE_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#ifdef __QNX__
#include <devctl.h>
#include <sys/types.h>
#else
/*
 * Clean POSIX/Windows host fallback macros matching QNX <devctl.h> bit layout
 * without signed-shift UB so protocol headers compile cleanly under strict C11.
 */
#ifndef _DCMD_MISC
#define _DCMD_MISC 0x05U
#endif

#ifndef _QNXP_DEVCTL_DIR_NONE
#define _QNXP_DEVCTL_DIR_NONE 0x00U
#define _QNXP_DEVCTL_DIR_TO   0x01U
#define _QNXP_DEVCTL_DIR_FROM 0x02U
#endif

#ifndef __DION
#define __DION(d, c) \
    ((int)(((_QNXP_DEVCTL_DIR_NONE) << 30U) | \
           (((uint32_t)(d) & 0xFFU) << 8U) | \
           ((uint32_t)(c) & 0xFFU)))
#endif

#ifndef __DIOF
#define __DIOF(d, c, t) \
    ((int)(((_QNXP_DEVCTL_DIR_FROM) << 30U) | \
           ((((uint32_t)sizeof(t)) & 0x3FFFU) << 16U) | \
           (((uint32_t)(d) & 0xFFU) << 8U) | \
           ((uint32_t)(c) & 0xFFU)))
#endif

#ifndef __DIOT
#define __DIOT(d, c, t) \
    ((int)(((_QNXP_DEVCTL_DIR_TO) << 30U) | \
           ((((uint32_t)sizeof(t)) & 0x3FFFU) << 16U) | \
           (((uint32_t)(d) & 0xFFU) << 8U) | \
           ((uint32_t)(c) & 0xFFU)))
#endif

#ifndef __DIOTF
#define __DIOTF(d, c, t) \
    ((int)((((_QNXP_DEVCTL_DIR_TO | _QNXP_DEVCTL_DIR_FROM)) << 30U) | \
           ((((uint32_t)sizeof(t)) & 0x3FFFU) << 16U) | \
           (((uint32_t)(d) & 0xFFU) << 8U) | \
           ((uint32_t)(c) & 0xFFU)))
#endif
#endif /* __QNX__ */

#ifdef __cplusplus
extern "C" {
#endif

/* Protocol metadata and device path */
#define QNXP_PROTOCOL_VERSION    0x00010000U /* v1.0.0 */
#define QNXP_DEVICE_PATH         "/dev/qnxpulse"
#define QNXP_PROC_NAME_MAX       24U
#define QNXP_REASON_MAX          160U
#define QNXP_DUMP_BATCH_MAX      32U

/* QNX-Pulse user-space TraceEvent(_NTO_TRACE_INSERTSUSEREVENT) codes */
#define QNXP_USREVENT_HEARTBEAT  0x100U
#define QNXP_USREVENT_INVERSION  0x101U
#define QNXP_USREVENT_DEADLINE   0x102U

/* Channel attribute flag mirroring QNX _NTO_CHF_FIXED_PRIORITY on the wire */
#define QNXP_CHF_NONE            0x00000000U
#define QNXP_CHF_FIXED_PRIORITY  0x00000001U

/* Telemetry event flags bitmask */
#define QNXP_FLAG_NONE           0x0000U
#define QNXP_FLAG_PRIO_INVERSION 0x0001U
#define QNXP_FLAG_FIXED_PRIORITY 0x0002U
#define QNXP_FLAG_DEADLINE_RISK  0x0004U

/* Stream serialization formats supported by /dev/qnxpulse io_read */
typedef enum qnxp_output_format {
    QNXP_FMT_TRACEPRINTER = 0,
    QNXP_FMT_NDJSON       = 1
} qnxp_output_format_t;

/* QNX 8.0 traceprinter event classes */
typedef enum qnxp_event_class {
    QNXP_CLASS_COMM     = 1, /* COMM: synchronous MsgSend/MsgReceive/MsgReply */
    QNXP_CLASS_THREAD   = 2, /* THREAD: THRUNNING/THREADY/THREPLY scheduling  */
    QNXP_CLASS_INT      = 3, /* INT: INT_ENTR / INT_EXIT interrupt activity   */
    QNXP_CLASS_USREVENT = 4  /* USREVENT: TraceEvent user markers             */
} qnxp_event_class_t;

/* QNX 8.0 traceprinter event subtypes */
typedef enum qnxp_event_type {
    QNXP_EVT_COMM_SND_MESSAGE   = 1, /* COMM : SND_MESSAGE     */
    QNXP_EVT_COMM_REC_MESSAGE   = 2, /* COMM : REC_MESSAGE     */
    QNXP_EVT_COMM_REPLY_MESSAGE = 3, /* COMM : REPLY_MESSAGE   */
    QNXP_EVT_THREAD_THRUNNING   = 4, /* THREAD : THRUNNING     */
    QNXP_EVT_THREAD_THREADY     = 5, /* THREAD : THREADY       */
    QNXP_EVT_THREAD_THREPLY     = 6, /* THREAD : THREPLY       */
    QNXP_EVT_INT_ENTR           = 7, /* INT : INT_ENTR         */
    QNXP_EVT_INT_EXIT           = 8, /* INT : INT_EXIT         */
    QNXP_EVT_USREVENT           = 9  /* USREVENT : EVENT       */
} qnxp_event_type_t;

/*
 * Fixed-size, pointer-free telemetry event record (72 bytes, 8-byte aligned).
 * Safe for lock-free ring storage and direct devctl transport.
 */
typedef struct qnxp_event {
    uint64_t timestamp_ns;               /* Monotonic timestamp / cycle counter      */
    uint32_t seq;                        /* Monotonic ring sequence number           */
    uint32_t pid;                        /* Primary process ID                       */
    uint32_t tid;                        /* Primary thread ID                        */
    uint32_t peer_pid;                   /* Target server/client PID for IPC events  */
    uint32_t peer_tid;                   /* Target server/client TID (0 if unknown)  */
    uint32_t rcvid_or_irq;               /* rcvid (COMM), IRQ vector (INT), code (U) */
    uint32_t data0;                      /* Payload word 0 (bytes / latency_us / d0) */
    uint32_t data1;                      /* Payload word 1 (deadline_us / d1)        */
    uint16_t cpu;                        /* CPU core index                           */
    uint8_t  event_class;                /* qnxp_event_class_t                       */
    uint8_t  event_type;                 /* qnxp_event_type_t                        */
    uint8_t  priority;                   /* Primary thread priority (QNX 0..255)     */
    uint8_t  peer_priority;              /* Effective priority of IPC peer (0..255)  */
    uint16_t flags;                      /* QNXP_FLAG_* bitmask                      */
    char     proc_name[QNXP_PROC_NAME_MAX]; /* Short NUL-terminated process name     */
} qnxp_event_t;

/* Agent health, trace session state, and ring buffer counters */
typedef struct qnxp_stats {
    uint32_t protocol_version;           /* QNXP_PROTOCOL_VERSION                    */
    uint32_t tracing_active;             /* 1 when kernel tracing is active          */
    uint32_t ring_capacity;              /* Total fixed slot capacity                */
    uint32_t ring_buffered;              /* Unread events currently queued           */
    uint64_t total_captured;             /* Total events pushed since init/clear     */
    uint64_t total_dropped;              /* Events overwritten due to ring wrap      */
    uint64_t total_read;                 /* Total events consumed                    */
    uint64_t inversions_detected;        /* Priority inversions caught by watchdog   */
    uint64_t last_event_ts_ns;           /* Timestamp of latest pushed event         */
    uint32_t output_format;              /* Active qnxp_output_format_t              */
    uint32_t reserved;                   /* Explicit 8-byte alignment padding        */
} qnxp_stats_t;

/* Bounded batch snapshot returned by _DCMD_QNXPULSE_DUMP_RING */
typedef struct qnxp_ring_dump {
    uint32_t     count;                        /* Number of valid entries in events[] */
    uint32_t     remaining;                    /* Remaining unread events in ring     */
    uint64_t     dropped_total;                /* Cumulative drop counter             */
    qnxp_event_t events[QNXP_DUMP_BATCH_MAX];  /* Popped event batch                  */
} qnxp_ring_dump_t;

/* Real-time priority-inversion watchdog verdict */
typedef struct qnxp_inversion_alert {
    uint8_t  detected;                   /* 1 if priority inversion occurred         */
    uint8_t  severity;                   /* 0=none, 1=warning, 2=critical            */
    uint8_t  client_priority;            /* High-priority client blocked in IPC      */
    uint8_t  server_eff_priority;        /* Server effective priority (unboosted)    */
    uint32_t client_pid;
    uint32_t client_tid;
    uint32_t server_pid;
    uint32_t server_tid;
    uint32_t priority_gap;               /* client_priority - server_eff_priority    */
    uint32_t channel_flags;              /* QNXP_CHF_* flags                         */
    char     reason[QNXP_REASON_MAX];    /* Human-readable root cause summary        */
} qnxp_inversion_alert_t;

/*
 * QNX-Pulse devctl(2) commands for /dev/qnxpulse
 */
#define _DCMD_QNXPULSE_GET_STATS   __DIOF(_DCMD_MISC, 0x60U, qnxp_stats_t)
#define _DCMD_QNXPULSE_START_TRACE __DION(_DCMD_MISC, 0x61U)
#define _DCMD_QNXPULSE_STOP_TRACE  __DION(_DCMD_MISC, 0x62U)
#define _DCMD_QNXPULSE_DUMP_RING   __DIOF(_DCMD_MISC, 0x63U, qnxp_ring_dump_t)
#define _DCMD_QNXPULSE_SET_FORMAT  __DIOT(_DCMD_MISC, 0x64U, uint32_t)
#define _DCMD_QNXPULSE_CLEAR_RING  __DION(_DCMD_MISC, 0x65U)

#ifdef __cplusplus
}
#endif

#endif /* QNX_PULSE_PROTOCOL_H */
