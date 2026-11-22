/*
 * QNX-Pulse Lock-Free Telemetry Ring Buffer, Formatters & Watchdog
 *
 * Deterministic O(1) flight-recorder ring buffer with zero heap allocation on
 * the hot path, QNX 8.0 traceprinter and NDJSON serializers, and inline
 * synchronous IPC priority-inversion detection.
 */

#include "telemetry_ring.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

_Static_assert((QNXP_RING_CAPACITY >= 2U) &&
               ((QNXP_RING_CAPACITY & (QNXP_RING_CAPACITY - 1U)) == 0U),
               "QNXP_RING_CAPACITY must be a power of two >= 2");
_Static_assert(sizeof(qnxp_event_t) == 72U,
               "qnxp_event_t must remain fixed 72-byte wire layout");
_Static_assert(sizeof(qnxp_ring_dump_t) <= 4096U,
               "qnxp_ring_dump_t must fit comfortably within QNX devctl payload");

static int is_power_of_two_u32(uint32_t v)
{
    return (v >= 2U) && ((v & (v - 1U)) == 0U);
}

int qnxp_ring_init_capacity(qnxp_ring_t *ring, uint32_t capacity)
{
    uint32_t i;

    if ((ring == NULL) || !is_power_of_two_u32(capacity) || (capacity > QNXP_RING_CAPACITY)) {
        return -1;
    }

    memset(ring->slots, 0, sizeof(ring->slots));
    ring->capacity = capacity;
    ring->mask = capacity - 1U;

    atomic_init(&ring->write_idx, 0ULL);
    atomic_init(&ring->read_idx, 0ULL);
    atomic_init(&ring->next_seq, 1U);
    atomic_init(&ring->total_captured, 0ULL);
    atomic_init(&ring->total_dropped, 0ULL);
    atomic_init(&ring->total_read, 0ULL);
    atomic_init(&ring->inversions_detected, 0ULL);
    atomic_init(&ring->last_event_ts_ns, 0ULL);

    for (i = 0U; i < QNXP_RING_CAPACITY; ++i) {
        atomic_init(&ring->slot_gen[i], 0ULL);
    }

    return 0;
}

int qnxp_ring_init(qnxp_ring_t *ring)
{
    return qnxp_ring_init_capacity(ring, QNXP_RING_CAPACITY);
}

void qnxp_ring_reset(qnxp_ring_t *ring)
{
    uint32_t cap;

    if (ring == NULL) {
        return;
    }

    cap = ring->capacity;
    if (!is_power_of_two_u32(cap) || (cap > QNXP_RING_CAPACITY)) {
        cap = QNXP_RING_CAPACITY;
    }

    (void)qnxp_ring_init_capacity(ring, cap);
}

int qnxp_ring_push(qnxp_ring_t *ring, const qnxp_event_t *ev)
{
    uint64_t w;
    uint64_t r;
    uint64_t g;
    uint32_t idx;
    uint32_t seq;
    int dropped = 0;
    qnxp_event_t copy;

    if ((ring == NULL) || (ev == NULL) || (ring->capacity < 2U)) {
        return -1;
    }

    w = atomic_load_explicit(&ring->write_idx, memory_order_relaxed);
    r = atomic_load_explicit(&ring->read_idx, memory_order_acquire);

    /*
     * Real-time flight-recorder overwrite policy: never block the producer.
     * If unread count reached capacity, advance read_idx past the oldest slot
     * via CAS so concurrent consumers cannot collide with our overwrite.
     */
    while ((w >= r) && ((w - r) >= (uint64_t)ring->capacity)) {
        uint64_t next_r = r + 1ULL;
        if (atomic_compare_exchange_weak_explicit(
                &ring->read_idx, &r, next_r,
                memory_order_acq_rel, memory_order_acquire)) {
            atomic_fetch_add_explicit(&ring->total_dropped, 1ULL, memory_order_relaxed);
            dropped = 1;
            break;
        }
        /* CAS failed because consumer advanced read_idx; re-check loop condition. */
    }

    copy = *ev;
    copy.proc_name[QNXP_PROC_NAME_MAX - 1U] = '\0';
    seq = atomic_fetch_add_explicit(&ring->next_seq, 1U, memory_order_relaxed);
    copy.seq = seq;

    idx = (uint32_t)(w & (uint64_t)ring->mask);

    /* Per-slot seqlock write fence: odd = write in progress, even = committed. */
    g = atomic_load_explicit(&ring->slot_gen[idx], memory_order_relaxed);
    atomic_store_explicit(&ring->slot_gen[idx], g + 1ULL, memory_order_release);
    ring->slots[idx] = copy;
    atomic_store_explicit(&ring->slot_gen[idx], g + 2ULL, memory_order_release);

    atomic_store_explicit(&ring->write_idx, w + 1ULL, memory_order_release);
    atomic_fetch_add_explicit(&ring->total_captured, 1ULL, memory_order_relaxed);
    atomic_store_explicit(&ring->last_event_ts_ns, copy.timestamp_ns, memory_order_relaxed);

    if ((copy.flags & QNXP_FLAG_PRIO_INVERSION) != 0U) {
        atomic_fetch_add_explicit(&ring->inversions_detected, 1ULL, memory_order_relaxed);
    }

    return dropped;
}

int qnxp_ring_pop(qnxp_ring_t *ring, qnxp_event_t *out_ev)
{
    uint32_t retries;

    if ((ring == NULL) || (out_ev == NULL) || (ring->capacity < 2U)) {
        return -1;
    }

    for (retries = 0U; retries < 64U; ++retries) {
        uint64_t r = atomic_load_explicit(&ring->read_idx, memory_order_acquire);
        uint64_t w = atomic_load_explicit(&ring->write_idx, memory_order_acquire);
        uint32_t idx;
        uint64_t g1;
        uint64_t g2;
        qnxp_event_t tmp;

        if (r >= w) {
            return 0;
        }

        idx = (uint32_t)(r & (uint64_t)ring->mask);
        g1 = atomic_load_explicit(&ring->slot_gen[idx], memory_order_acquire);
        if ((g1 & 1ULL) != 0ULL) {
            /* Producer is actively updating this slot; retry. */
            continue;
        }

        tmp = ring->slots[idx];
        atomic_thread_fence(memory_order_acquire);
        g2 = atomic_load_explicit(&ring->slot_gen[idx], memory_order_acquire);
        if (g1 != g2) {
            /* Slot was overwritten while reading; retry from fresh read_idx. */
            continue;
        }

        if (atomic_compare_exchange_strong_explicit(
                &ring->read_idx, &r, r + 1ULL,
                memory_order_acq_rel, memory_order_acquire)) {
            *out_ev = tmp;
            atomic_fetch_add_explicit(&ring->total_read, 1ULL, memory_order_relaxed);
            return 1;
        }
    }

    return 0;
}

uint32_t qnxp_ring_pop_batch(qnxp_ring_t *ring, qnxp_event_t *out_events, uint32_t max_count)
{
    uint32_t popped = 0U;

    if ((ring == NULL) || (out_events == NULL) || (max_count == 0U)) {
        return 0U;
    }

    while (popped < max_count) {
        int rc = qnxp_ring_pop(ring, &out_events[popped]);
        if (rc <= 0) {
            break;
        }
        ++popped;
    }

    return popped;
}

uint32_t qnxp_ring_buffered(const qnxp_ring_t *ring)
{
    uint64_t w;
    uint64_t r;
    uint64_t diff;

    if (ring == NULL) {
        return 0U;
    }

    r = atomic_load_explicit(&ring->read_idx, memory_order_acquire);
    w = atomic_load_explicit(&ring->write_idx, memory_order_acquire);

    if (w <= r) {
        return 0U;
    }

    diff = w - r;
    if (diff > (uint64_t)ring->capacity) {
        diff = (uint64_t)ring->capacity;
    }
    return (uint32_t)diff;
}

void qnxp_ring_get_stats(const qnxp_ring_t *ring,
                         uint32_t tracing_active,
                         uint32_t output_format,
                         qnxp_stats_t *out_stats)
{
    if ((ring == NULL) || (out_stats == NULL)) {
        return;
    }

    memset(out_stats, 0, sizeof(*out_stats));
    out_stats->protocol_version    = QNXP_PROTOCOL_VERSION;
    out_stats->tracing_active      = tracing_active ? 1U : 0U;
    out_stats->ring_capacity       = ring->capacity;
    out_stats->ring_buffered       = qnxp_ring_buffered(ring);
    out_stats->total_captured      = atomic_load_explicit(&ring->total_captured, memory_order_relaxed);
    out_stats->total_dropped       = atomic_load_explicit(&ring->total_dropped, memory_order_relaxed);
    out_stats->total_read          = atomic_load_explicit(&ring->total_read, memory_order_relaxed);
    out_stats->inversions_detected = atomic_load_explicit(&ring->inversions_detected, memory_order_relaxed);
    out_stats->last_event_ts_ns    = atomic_load_explicit(&ring->last_event_ts_ns, memory_order_relaxed);
    out_stats->output_format       = output_format;
}

const char *qnxp_event_class_name(uint8_t event_class)
{
    switch ((qnxp_event_class_t)event_class) {
    case QNXP_CLASS_COMM:
        return "COMM";
    case QNXP_CLASS_THREAD:
        return "THREAD";
    case QNXP_CLASS_INT:
        return "INT";
    case QNXP_CLASS_USREVENT:
        return "USREVENT";
    default:
        return "UNKNOWN";
    }
}

const char *qnxp_event_type_name(uint8_t event_type)
{
    switch ((qnxp_event_type_t)event_type) {
    case QNXP_EVT_COMM_SND_MESSAGE:
        return "SND_MESSAGE";
    case QNXP_EVT_COMM_REC_MESSAGE:
        return "REC_MESSAGE";
    case QNXP_EVT_COMM_REPLY_MESSAGE:
        return "REPLY_MESSAGE";
    case QNXP_EVT_THREAD_THRUNNING:
        return "THRUNNING";
    case QNXP_EVT_THREAD_THREADY:
        return "THREADY";
    case QNXP_EVT_THREAD_THREPLY:
        return "THREPLY";
    case QNXP_EVT_INT_ENTR:
        return "INT_ENTR";
    case QNXP_EVT_INT_EXIT:
        return "INT_EXIT";
    case QNXP_EVT_USREVENT:
        return "EVENT";
    default:
        return "UNKNOWN";
    }
}

static size_t json_escape_string(const char *src, char *dst, size_t dst_size)
{
    size_t out = 0U;
    size_t i;

    if ((dst == NULL) || (dst_size == 0U)) {
        return 0U;
    }

    if (src == NULL) {
        dst[0] = '\0';
        return 0U;
    }

    for (i = 0U; src[i] != '\0'; ++i) {
        unsigned char c = (unsigned char)src[i];
        if ((c == '"') || (c == '\\')) {
            if (out + 2U >= dst_size) {
                break;
            }
            dst[out++] = '\\';
            dst[out++] = (char)c;
        } else if (c < 0x20U) {
            int n;
            if (out + 6U >= dst_size) {
                break;
            }
            n = snprintf(dst + out, dst_size - out, "\\u%04x", (unsigned int)c);
            if (n < 0) {
                break;
            }
            out += (size_t)n;
        } else {
            if (out + 1U >= dst_size) {
                break;
            }
            dst[out++] = (char)c;
        }
    }

    dst[out] = '\0';
    return out;
}

int qnxp_format_traceprinter(const qnxp_event_t *ev, char *buf, size_t buf_size)
{
    int written = -1;
    char safe_proc[QNXP_PROC_NAME_MAX];

    if ((ev == NULL) || (buf == NULL) || (buf_size == 0U)) {
        return -1;
    }

    memcpy(safe_proc, ev->proc_name, QNXP_PROC_NAME_MAX);
    safe_proc[QNXP_PROC_NAME_MAX - 1U] = '\0';

    switch ((qnxp_event_type_t)ev->event_type) {
    case QNXP_EVT_COMM_SND_MESSAGE:
        written = snprintf(
            buf, buf_size,
            "t:0x%08" PRIx64 " CPU:%02u COMM : SND_MESSAGE rcvid:0x%08" PRIx32
            " pid:%" PRIu32 " tid:%" PRIu32 " target_pid:%" PRIu32
            " prio:%u peer_prio:%u%s%s%s%s",
            ev->timestamp_ns,
            (unsigned int)ev->cpu,
            ev->rcvid_or_irq,
            ev->pid,
            ev->tid,
            ev->peer_pid,
            (unsigned int)ev->priority,
            (unsigned int)ev->peer_priority,
            (safe_proc[0] != '\0') ? " proc:" : "",
            (safe_proc[0] != '\0') ? safe_proc : "",
            ((ev->flags & QNXP_FLAG_PRIO_INVERSION) != 0U) ? " inversion:1" : "",
            ((ev->flags & QNXP_FLAG_FIXED_PRIORITY) != 0U) ? " fixed_prio:1" : "");
        break;

    case QNXP_EVT_COMM_REC_MESSAGE:
        written = snprintf(
            buf, buf_size,
            "t:0x%08" PRIx64 " CPU:%02u COMM : REC_MESSAGE rcvid:0x%08" PRIx32
            " pid:%" PRIu32 " tid:%" PRIu32 " client_pid:%" PRIu32
            " prio:%u peer_prio:%u%s%s%s%s",
            ev->timestamp_ns,
            (unsigned int)ev->cpu,
            ev->rcvid_or_irq,
            ev->pid,
            ev->tid,
            ev->peer_pid,
            (unsigned int)ev->priority,
            (unsigned int)ev->peer_priority,
            (safe_proc[0] != '\0') ? " proc:" : "",
            (safe_proc[0] != '\0') ? safe_proc : "",
            ((ev->flags & QNXP_FLAG_PRIO_INVERSION) != 0U) ? " inversion:1" : "",
            ((ev->flags & QNXP_FLAG_FIXED_PRIORITY) != 0U) ? " fixed_prio:1" : "");
        break;

    case QNXP_EVT_COMM_REPLY_MESSAGE:
        written = snprintf(
            buf, buf_size,
            "t:0x%08" PRIx64 " CPU:%02u COMM : REPLY_MESSAGE rcvid:0x%08" PRIx32
            " pid:%" PRIu32 " tid:%" PRIu32 " client_pid:%" PRIu32
            " prio:%u latency_us:%" PRIu32 "%s%s",
            ev->timestamp_ns,
            (unsigned int)ev->cpu,
            ev->rcvid_or_irq,
            ev->pid,
            ev->tid,
            ev->peer_pid,
            (unsigned int)ev->priority,
            ev->data0,
            (safe_proc[0] != '\0') ? " proc:" : "",
            (safe_proc[0] != '\0') ? safe_proc : "");
        break;

    case QNXP_EVT_THREAD_THRUNNING:
        written = snprintf(
            buf, buf_size,
            "t:0x%08" PRIx64 " CPU:%02u THREAD : THRUNNING pid:%" PRIu32
            " tid:%" PRIu32 " priority:%u%s%s",
            ev->timestamp_ns,
            (unsigned int)ev->cpu,
            ev->pid,
            ev->tid,
            (unsigned int)ev->priority,
            (safe_proc[0] != '\0') ? " proc:" : "",
            (safe_proc[0] != '\0') ? safe_proc : "");
        break;

    case QNXP_EVT_THREAD_THREADY:
        written = snprintf(
            buf, buf_size,
            "t:0x%08" PRIx64 " CPU:%02u THREAD : THREADY pid:%" PRIu32
            " tid:%" PRIu32 " priority:%u%s%s",
            ev->timestamp_ns,
            (unsigned int)ev->cpu,
            ev->pid,
            ev->tid,
            (unsigned int)ev->priority,
            (safe_proc[0] != '\0') ? " proc:" : "",
            (safe_proc[0] != '\0') ? safe_proc : "");
        break;

    case QNXP_EVT_THREAD_THREPLY:
        written = snprintf(
            buf, buf_size,
            "t:0x%08" PRIx64 " CPU:%02u THREAD : THREPLY pid:%" PRIu32
            " tid:%" PRIu32 " server_pid:%" PRIu32 " priority:%u server_prio:%u%s%s%s%s",
            ev->timestamp_ns,
            (unsigned int)ev->cpu,
            ev->pid,
            ev->tid,
            ev->peer_pid,
            (unsigned int)ev->priority,
            (unsigned int)ev->peer_priority,
            (safe_proc[0] != '\0') ? " proc:" : "",
            (safe_proc[0] != '\0') ? safe_proc : "",
            ((ev->flags & QNXP_FLAG_PRIO_INVERSION) != 0U) ? " inversion:1" : "",
            ((ev->flags & QNXP_FLAG_FIXED_PRIORITY) != 0U) ? " fixed_prio:1" : "");
        break;

    case QNXP_EVT_INT_ENTR:
        written = snprintf(
            buf, buf_size,
            "t:0x%08" PRIx64 " CPU:%02u INT : INT_ENTR irq:0x%" PRIx32 " pid:%" PRIu32,
            ev->timestamp_ns,
            (unsigned int)ev->cpu,
            ev->rcvid_or_irq,
            ev->pid);
        break;

    case QNXP_EVT_INT_EXIT:
        written = snprintf(
            buf, buf_size,
            "t:0x%08" PRIx64 " CPU:%02u INT : INT_EXIT irq:0x%" PRIx32 " pid:%" PRIu32,
            ev->timestamp_ns,
            (unsigned int)ev->cpu,
            ev->rcvid_or_irq,
            ev->pid);
        break;

    case QNXP_EVT_USREVENT:
        written = snprintf(
            buf, buf_size,
            "t:0x%08" PRIx64 " CPU:%02u USREVENT : EVENT event:%" PRIu32
            " pid:%" PRIu32 " tid:%" PRIu32 " d0:0x%08" PRIx32 " d1:0x%08" PRIx32 "%s%s",
            ev->timestamp_ns,
            (unsigned int)ev->cpu,
            ev->rcvid_or_irq,
            ev->pid,
            ev->tid,
            ev->data0,
            ev->data1,
            (safe_proc[0] != '\0') ? " proc:" : "",
            (safe_proc[0] != '\0') ? safe_proc : "");
        break;

    default:
        return -1;
    }

    if ((written < 0) || ((size_t)written >= buf_size)) {
        return -1;
    }
    return written;
}

int qnxp_format_ndjson(const qnxp_event_t *ev, char *buf, size_t buf_size)
{
    char safe_proc[QNXP_PROC_NAME_MAX];
    char escaped_proc[QNXP_PROC_NAME_MAX * 6U + 1U];
    int written;

    if ((ev == NULL) || (buf == NULL) || (buf_size == 0U)) {
        return -1;
    }

    memcpy(safe_proc, ev->proc_name, QNXP_PROC_NAME_MAX);
    safe_proc[QNXP_PROC_NAME_MAX - 1U] = '\0';
    (void)json_escape_string(safe_proc, escaped_proc, sizeof(escaped_proc));

    written = snprintf(
        buf, buf_size,
        "{\"seq\":%" PRIu32 ",\"ts_ns\":%" PRIu64 ",\"cpu\":%u,"
        "\"class\":\"%s\",\"event\":\"%s\","
        "\"pid\":%" PRIu32 ",\"tid\":%" PRIu32 ","
        "\"peer_pid\":%" PRIu32 ",\"peer_tid\":%" PRIu32 ","
        "\"rcvid_or_irq\":%" PRIu32 ",\"priority\":%u,\"peer_priority\":%u,"
        "\"data0\":%" PRIu32 ",\"data1\":%" PRIu32 ",\"flags\":%u,"
        "\"prio_inversion\":%s,\"fixed_priority\":%s,\"proc\":\"%s\"}",
        ev->seq,
        ev->timestamp_ns,
        (unsigned int)ev->cpu,
        qnxp_event_class_name(ev->event_class),
        qnxp_event_type_name(ev->event_type),
        ev->pid,
        ev->tid,
        ev->peer_pid,
        ev->peer_tid,
        ev->rcvid_or_irq,
        (unsigned int)ev->priority,
        (unsigned int)ev->peer_priority,
        ev->data0,
        ev->data1,
        (unsigned int)ev->flags,
        ((ev->flags & QNXP_FLAG_PRIO_INVERSION) != 0U) ? "true" : "false",
        ((ev->flags & QNXP_FLAG_FIXED_PRIORITY) != 0U) ? "true" : "false",
        escaped_proc);

    if ((written < 0) || ((size_t)written >= buf_size)) {
        return -1;
    }
    return written;
}

int qnxp_check_ipc_inversion(uint32_t client_pid,
                             uint32_t client_tid,
                             uint8_t client_priority,
                             uint32_t server_pid,
                             uint32_t server_tid,
                             uint8_t server_eff_priority,
                             uint32_t channel_flags,
                             qnxp_inversion_alert_t *out_alert)
{
    uint32_t gap = 0U;
    int fixed_prio = ((channel_flags & QNXP_CHF_FIXED_PRIORITY) != 0U);

    if (out_alert != NULL) {
        memset(out_alert, 0, sizeof(*out_alert));
        out_alert->client_pid          = client_pid;
        out_alert->client_tid          = client_tid;
        out_alert->client_priority     = client_priority;
        out_alert->server_pid          = server_pid;
        out_alert->server_tid          = server_tid;
        out_alert->server_eff_priority = server_eff_priority;
        out_alert->channel_flags       = channel_flags;
    }

    /* Require distinct endpoints and a valid server PID. */
    if ((server_pid == 0U) || ((client_pid == server_pid) && (client_tid == server_tid))) {
        return 0;
    }

    /*
     * Healthy QNX synchronous IPC (MsgSend -> MsgReceive -> MsgReply) boosts
     * the server thread's effective priority to at least client_priority.
     * Any deficit (server_eff_priority < client_priority) indicates inversion.
     */
    if (client_priority <= server_eff_priority) {
        return 0;
    }

    gap = (uint32_t)(client_priority - server_eff_priority);

    if (out_alert != NULL) {
        out_alert->detected     = 1U;
        out_alert->priority_gap = gap;
        if (fixed_prio) {
            out_alert->severity = 2U; /* Critical: explicit inheritance disablement */
            (void)snprintf(
                out_alert->reason, sizeof(out_alert->reason),
                "IPC priority inversion: client pid=%" PRIu32 " prio=%u blocked on server pid=%" PRIu32
                " eff_prio=%u (gap=%" PRIu32 "); channel has _NTO_CHF_FIXED_PRIORITY",
                client_pid, (unsigned int)client_priority,
                server_pid, (unsigned int)server_eff_priority,
                gap);
        } else {
            out_alert->severity = (gap >= 15U) ? 2U : 1U;
            (void)snprintf(
                out_alert->reason, sizeof(out_alert->reason),
                "IPC priority inversion: client pid=%" PRIu32 " prio=%u blocked on server pid=%" PRIu32
                " eff_prio=%u (gap=%" PRIu32 "); server failed to inherit client priority",
                client_pid, (unsigned int)client_priority,
                server_pid, (unsigned int)server_eff_priority,
                gap);
        }
    }

    return 1;
}

int qnxp_evaluate_event_inversion(qnxp_event_t *ev,
                                  uint32_t channel_flags,
                                  qnxp_inversion_alert_t *out_alert)
{
    int detected = 0;

    if (ev == NULL) {
        return 0;
    }

    switch ((qnxp_event_type_t)ev->event_type) {
    case QNXP_EVT_COMM_SND_MESSAGE:
    case QNXP_EVT_THREAD_THREPLY:
        if ((channel_flags & QNXP_CHF_FIXED_PRIORITY) != 0U) {
            ev->flags |= QNXP_FLAG_FIXED_PRIORITY;
        }
        /* Primary is client, peer is server. */
        detected = qnxp_check_ipc_inversion(
            ev->pid, ev->tid, ev->priority,
            ev->peer_pid, ev->peer_tid, ev->peer_priority,
            channel_flags, out_alert);
        break;

    case QNXP_EVT_COMM_REC_MESSAGE:
        if ((channel_flags & QNXP_CHF_FIXED_PRIORITY) != 0U) {
            ev->flags |= QNXP_FLAG_FIXED_PRIORITY;
        }
        /* Primary is server (effective priority in ev->priority), peer is client. */
        detected = qnxp_check_ipc_inversion(
            ev->peer_pid, ev->peer_tid, ev->peer_priority,
            ev->pid, ev->tid, ev->priority,
            channel_flags, out_alert);
        break;

    default:
        if (out_alert != NULL) {
            memset(out_alert, 0, sizeof(*out_alert));
        }
        return 0;
    }

    if (detected) {
        ev->flags |= QNXP_FLAG_PRIO_INVERSION;
    }

    return detected;
}
