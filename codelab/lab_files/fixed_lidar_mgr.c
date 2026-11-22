/*
 * fixed_lidar_mgr.c — QNX SDP 8.0 /dev/lidar_fusion Resource Manager (FIXED)
 *
 * ZERO-JITTER FIX: Removes `_NTO_CHF_FIXED_PRIORITY` from ChannelCreate().
 * QNX 8.0 synchronous IPC Priority Inheritance is now ACTIVE: when adas_aeb
 * (prio 52) sends _IO_READ via MsgSend(), procnto-smp-instr atomically boosts
 * this server thread from prio 18 -> 52 until MsgReply(), preventing medium-
 * priority preemption by can_telemetry (prio 30).
 *
 * Build (QNX SDP 8.0 x86_64):
 *   qcc -Vgcc_ntox86_64 -Wall -Wextra -O2 -o lidar_mgr fixed_lidar_mgr.c -lslog2 -lsecpol
 *
 * Build (QNX SDP 8.0 aarch64le / Raspberry Pi 5):
 *   qcc -Vgcc_ntoaarch64le -Wall -Wextra -O2 -o lidar_mgr fixed_lidar_mgr.c -lslog2 -lsecpol
 */

#include <errno.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include <sys/dispatch.h>
#include <sys/iofunc.h>
#include <sys/neutrino.h>
#include <sys/procmgr.h>
#include <sys/slog2.h>
#include <sys/stat.h>
#include <secpol/secpol.h>

#define LIDAR_DEV_PATH        "/dev/lidar_fusion"
#define LIDAR_BASE_PRIO       18
#define FUSION_WORK_NS        900000ULL /* 0.9 ms deterministic voxel clustering budget */

/* Structured payload returned when adas_aeb calls read() on /dev/lidar_fusion */
typedef struct {
    uint32_t frame_seq;
    uint64_t timestamp_ns;
    float    nearest_obstacle_m;
    float    closing_vel_mps;
    uint8_t  aeb_trigger;
    int32_t  server_prio_at_reply;
} lidar_obstacle_frame_t;

static slog2_buffer_t g_slog_buf = NULL;
static uint32_t       g_frame_seq = 0;

/* Monotonic nanosecond clock helper */
static uint64_t now_monotonic_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ((uint64_t)ts.tv_sec * 1000000000ULL) + (uint64_t)ts.tv_nsec;
}

/* Simulates deterministic LiDAR point-cloud voxel clustering (~0.9 ms CPU work) */
static void run_voxel_clustering_work(uint64_t duration_ns) {
    volatile uint64_t accum = 0;
    uint64_t start_ns = now_monotonic_ns();
    while ((now_monotonic_ns() - start_ns) < duration_ns) {
        for (int i = 0; i < 64; ++i) {
            accum += (uint64_t)(i * 17U) ^ (accum >> 3);
        }
    }
    (void)accum;
}

/* Initialize QNX 8.0 slogger2 structured logging buffer */
static int init_slog2(void) {
    slog2_buffer_set_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));

    cfg.buffer_set_name              = "lidar_fusion";
    cfg.num_buffers                  = 1;
    cfg.verbosity_level              = SLOG2_INFO;
    cfg.buffer_config[0].buffer_name = "main";
    cfg.buffer_config[0].num_pages   = 4; /* 4 x 4 KB pages */

    if (slog2_register(&cfg, &g_slog_buf, 0) == -1) {
        perror("slog2_register");
        return -1;
    }
    slog2_set_default_buffer(g_slog_buf);
    return 0;
}

/*
 * Drop startup privileges after resmgr_attach():
 *   1. Transition QNX secpol type: lidar_mgr_t -> lidar_mgr_run_t ("run")
 *   2. Irreversibly lock out setup abilities with procmgr_ability(PROCMGR_AOP_LOCK)
 */
static int drop_startup_privileges(void) {
    if (secpol_transition_type(NULL, "run", 0) == -1) {
        slog2f(g_slog_buf, 100, SLOG2_WARNING,
               "secpol_transition_type('run') skipped/failed: %s (errno=%d); applying procmgr_ability lock",
               strerror(errno), errno);
    } else {
        slog2f(g_slog_buf, 100, SLOG2_INFO,
               "secpol transition succeeded: lidar_mgr_t -> lidar_mgr_run_t");
    }

    /* Defense-in-depth: permanently deny & lock dangerous abilities */
    if (procmgr_ability(
            0,
            PROCMGR_ADN_NONROOT | PROCMGR_AOP_DENY | PROCMGR_AOP_LOCK | PROCMGR_AID_PATHSPACE,
            PROCMGR_ADN_NONROOT | PROCMGR_AOP_DENY | PROCMGR_AOP_LOCK | PROCMGR_AID_PUBLIC_CHANNEL,
            PROCMGR_ADN_NONROOT | PROCMGR_AOP_DENY | PROCMGR_AOP_LOCK | PROCMGR_AID_FORK,
            PROCMGR_ADN_NONROOT | PROCMGR_AOP_DENY | PROCMGR_AOP_LOCK | PROCMGR_AID_SPAWN,
            PROCMGR_ADN_ROOT    | PROCMGR_AOP_DENY | PROCMGR_AOP_LOCK | PROCMGR_AID_EOL) == -1) {
        slog2f(g_slog_buf, 101, SLOG2_ERROR,
               "procmgr_ability lock failed: %s", strerror(errno));
        return -1;
    }
    return 0;
}

/* Custom _IO_READ handler invoked synchronously when a client calls read() */
static int io_read(resmgr_context_t *ctp, io_read_t *msg, RESMGR_OCB_T *ocb) {
    int status = iofunc_read_verify(ctp, msg, ocb, NULL);
    if (status != EOK) {
        return status;
    }

    if ((msg->i.xtype & _IO_XTYPE_MASK) != _IO_XTYPE_NONE) {
        return ENOSYS;
    }

    /* Execute 0.9 ms point-cloud fusion compute (now boosted to client's priority!) */
    run_voxel_clustering_work(FUSION_WORK_NS);

    /* Query our CURRENT effective priority inside the kernel (expect 52 for adas_aeb!) */
    struct sched_param sp;
    memset(&sp, 0, sizeof(sp));
    SchedGet(0, 0, &sp);

    lidar_obstacle_frame_t frame;
    frame.frame_seq            = ++g_frame_seq;
    frame.timestamp_ns         = now_monotonic_ns();
    frame.nearest_obstacle_m   = 14.2f;
    frame.closing_vel_mps      = 18.5f;
    frame.aeb_trigger          = 1U;
    frame.server_prio_at_reply = sp.sched_priority;

    size_t nbytes = sizeof(frame);
    if (msg->i.nbytes < nbytes) {
        nbytes = msg->i.nbytes;
    }

    slog2f(g_slog_buf, 200, SLOG2_INFO,
           "frame=%u reply_prio=%d obstacle=%.1fm aeb=%u (PRIORITY INHERITANCE ACTIVE)",
           frame.frame_seq, frame.server_prio_at_reply,
           frame.nearest_obstacle_m, frame.aeb_trigger);

    if (MsgReply(ctp->rcvid, (int)nbytes, &frame, nbytes) == -1) {
        return errno;
    }

    ocb->attr->flags |= IOFUNC_ATTR_ATIME | IOFUNC_ATTR_DIRTY_TIME;
    return _RESMGR_NOREPLY;
}

int main(void) {
    if (init_slog2() != 0) {
        return EXIT_FAILURE;
    }

    /* Set baseline server thread priority to 18 (SCHED_FIFO) */
    struct sched_param sp;
    memset(&sp, 0, sizeof(sp));
    sp.sched_priority = LIDAR_BASE_PRIO;
    if (SchedSet(0, 0, SCHED_FIFO, &sp) == -1) {
        slog2f(g_slog_buf, 102, SLOG2_WARNING,
               "SchedSet(prio=%d) failed: %s (continuing with inherited priority)",
               LIDAR_BASE_PRIO, strerror(errno));
    }

    /* =========================================================================
     * FIX: Omitting _NTO_CHF_FIXED_PRIORITY restores QNX 8.0 default priority
     * inheritance! When adas_aeb (prio 52) sends _IO_READ, the microkernel
     * automatically elevates this server thread from 18 -> 52 until MsgReply().
     * ========================================================================= */
    int chid = ChannelCreate(_NTO_CHF_UNBLOCK | _NTO_CHF_DISCONNECT);
    if (chid == -1) {
        perror("ChannelCreate");
        return EXIT_FAILURE;
    }

    dispatch_t *dpp = dispatch_create_channel(chid, 0);
    if (dpp == NULL) {
        perror("dispatch_create_channel");
        return EXIT_FAILURE;
    }

    resmgr_connect_funcs_t connect_funcs;
    resmgr_io_funcs_t      io_funcs;
    iofunc_attr_t          attr;
    resmgr_attr_t          resmgr_attr;

    memset(&resmgr_attr, 0, sizeof(resmgr_attr));
    resmgr_attr.nparts_max   = 1;
    resmgr_attr.msg_max_size = 2048;

    iofunc_func_init(_RESMGR_CONNECT_NFUNCS, &connect_funcs,
                     _RESMGR_IO_NFUNCS, &io_funcs);
    io_funcs.read = io_read;

    iofunc_attr_init(&attr, S_IFCHR | 0444, NULL, NULL);
    attr.nbytes = sizeof(lidar_obstacle_frame_t);

    if (resmgr_attach(dpp, &resmgr_attr, LIDAR_DEV_PATH, _FTYPE_ANY, 0,
                      &connect_funcs, &io_funcs, &attr) == -1) {
        perror("resmgr_attach");
        return EXIT_FAILURE;
    }

    /* Drop startup privileges now that /dev/lidar_fusion is registered */
    if (drop_startup_privileges() != 0) {
        return EXIT_FAILURE;
    }

    slog2f(g_slog_buf, 103, SLOG2_INFO,
           "Mounted %s (base_prio=%d, Priority Inheritance ENABLED)",
           LIDAR_DEV_PATH, LIDAR_BASE_PRIO);

    dispatch_context_t *ctp = dispatch_context_alloc(dpp);
    if (ctp == NULL) {
        perror("dispatch_context_alloc");
        return EXIT_FAILURE;
    }

    /* Main synchronous IPC receive/dispatch loop */
    for (;;) {
        if ((ctp = dispatch_block(ctp)) == NULL) {
            perror("dispatch_block");
            return EXIT_FAILURE;
        }
        dispatch_handler(ctp);
    }

    return EXIT_SUCCESS;
}
