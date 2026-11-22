/*
 * QNX-Pulse Lock-Free Telemetry Ring Buffer, Formatters & Watchdog Header
 *
 * Zero dynamic heap allocation on the hot path: all storage is fixed-capacity
 * inline within qnxp_ring_t, synchronized with C11 <stdatomic.h> acquire/release
 * fences and per-slot generation counters to prevent torn reads on wrap-around.
 */

#ifndef QNX_PULSE_TELEMETRY_RING_H
#define QNX_PULSE_TELEMETRY_RING_H

#include "qnx_pulse_protocol.h"

#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Fixed compile-time maximum slot capacity (must be a power of 2). */
#define QNXP_RING_CAPACITY 1024U

typedef struct qnxp_ring {
    uint32_t             capacity;                       /* Active capacity (power of 2) */
    uint32_t             mask;                           /* capacity - 1                 */
    _Atomic uint64_t     write_idx;                      /* Monotonic producer cursor    */
    _Atomic uint64_t     read_idx;                       /* Monotonic consumer cursor    */
    _Atomic uint32_t     next_seq;                       /* Monotonic event seq counter  */
    _Atomic uint64_t     total_captured;                 /* Cumulative pushed events     */
    _Atomic uint64_t     total_dropped;                  /* Cumulative overwritten slots */
    _Atomic uint64_t     total_read;                     /* Cumulative popped events     */
    _Atomic uint64_t     inversions_detected;            /* Flagged priority inversions  */
    _Atomic uint64_t     last_event_ts_ns;               /* Timestamp of newest event    */
    _Atomic uint64_t     slot_gen[QNXP_RING_CAPACITY];   /* Per-slot seqlock generation  */
    qnxp_event_t         slots[QNXP_RING_CAPACITY];      /* Inline fixed event storage   */
} qnxp_ring_t;

/* Initialize ring buffer with default capacity (QNXP_RING_CAPACITY). */
int qnxp_ring_init(qnxp_ring_t *ring);

/*
 * Initialize ring buffer with a caller-selected power-of-two capacity
 * (2 <= capacity <= QNXP_RING_CAPACITY). Returns 0 on success, -1 on error.
 */
int qnxp_ring_init_capacity(qnxp_ring_t *ring, uint32_t capacity);

/* Reset buffered events and counters (preserves configured capacity). */
void qnxp_ring_reset(qnxp_ring_t *ring);

/*
 * Push an event into the ring buffer deterministically without blocking or
 * heap allocation. On full buffer, overwrites the oldest unread slot and
 * increments total_dropped.
 * Returns 0 if pushed without drop, 1 if an older slot was overwritten,
 * or -1 on invalid arguments.
 */
int qnxp_ring_push(qnxp_ring_t *ring, const qnxp_event_t *ev);

/*
 * Pop the oldest unread event from the ring buffer (lock-free, tear-free).
 * Returns 1 if an event was popped, 0 if the ring is empty, -1 on error.
 */
int qnxp_ring_pop(qnxp_ring_t *ring, qnxp_event_t *out_ev);

/*
 * Pop up to max_count events into out_events[].
 * Returns number of events popped (0..max_count).
 */
uint32_t qnxp_ring_pop_batch(qnxp_ring_t *ring, qnxp_event_t *out_events, uint32_t max_count);

/* Current approximate count of unread buffered events. */
uint32_t qnxp_ring_buffered(const qnxp_ring_t *ring);

/* Populate a qnxp_stats_t snapshot from the ring's atomic counters. */
void qnxp_ring_get_stats(const qnxp_ring_t *ring,
                         uint32_t tracing_active,
                         uint32_t output_format,
                         qnxp_stats_t *out_stats);

/*
 * Format a single event into an authentic QNX 8.0 traceprinter-compatible line
 * (without trailing newline).
 * Returns characters written (excluding NUL) on success, or -1 if invalid or
 * buffer too small.
 */
int qnxp_format_traceprinter(const qnxp_event_t *ev, char *buf, size_t buf_size);

/*
 * Format a single event into a compact JSON object suitable for NDJSON
 * streaming to the QNX-Pulse host workbench (without trailing newline).
 * Returns characters written (excluding NUL) on success, or -1 if invalid or
 * buffer too small.
 */
int qnxp_format_ndjson(const qnxp_event_t *ev, char *buf, size_t buf_size);

/* Helper string accessors for event class and subtype names. */
const char *qnxp_event_class_name(uint8_t event_class);
const char *qnxp_event_type_name(uint8_t event_type);

/*
 * Real-time inline priority-inversion watchdog.
 *
 * Flags when a higher-priority client thread blocks waiting on a lower-priority
 * server thread whose effective priority failed to inherit the client's
 * priority (for example, when the server channel was created with
 * _NTO_CHF_FIXED_PRIORITY or delegates work across a non-inheriting queue).
 *
 * Returns 1 if priority inversion is detected, 0 if healthy.
 */
int qnxp_check_ipc_inversion(uint32_t client_pid,
                             uint32_t client_tid,
                             uint8_t client_priority,
                             uint32_t server_pid,
                             uint32_t server_tid,
                             uint8_t server_eff_priority,
                             uint32_t channel_flags,
                             qnxp_inversion_alert_t *out_alert);

/*
 * Convenience helper: inspects an IPC/scheduling telemetry event, runs the
 * inline watchdog, annotates ev->flags (QNXP_FLAG_PRIO_INVERSION /
 * QNXP_FLAG_FIXED_PRIORITY) on detection, and populates optional out_alert.
 * Returns 1 if inversion detected, 0 otherwise.
 */
int qnxp_evaluate_event_inversion(qnxp_event_t *ev,
                                  uint32_t channel_flags,
                                  qnxp_inversion_alert_t *out_alert);

#ifdef __cplusplus
}
#endif

#endif /* QNX_PULSE_TELEMETRY_RING_H */
