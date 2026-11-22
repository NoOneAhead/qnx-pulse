/* ==========================================================================
   Zero-Jitter QNX 8.0 Codelab — Interactive Engine
   - Step navigation, hash routing, keyboard shortcuts (Left/Right)
   - localStorage persistence for step checkmarks, theme, quiz, checklist
   - Single-pass syntax highlighter + Copy-to-Clipboard buttons
   - Step 6 Interactive QNX 8.0 Priority Inheritance SVG Gantt Simulator
   - Step 7 Interactive 4-Question Comprehension Quiz
   ========================================================================== */

(function () {
  'use strict';

  const TOTAL_STEPS = 7;
  const STORAGE_KEYS = {
    completed: 'qnx8_codelab_completed_v1',
    theme: 'qnx8_codelab_theme_v1',
    quiz: 'qnx8_codelab_quiz_v1',
    checklist: 'qnx8_codelab_checklist_v1'
  };

  /* ------------------------------------------------------------------------
     Safe Storage Helpers
     ------------------------------------------------------------------------ */
  function readStore(key, fallback) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (_err) {
      return fallback;
    }
  }

  function writeStore(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (_err) {
      /* Ignore quota / private mode errors */
    }
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  /* ------------------------------------------------------------------------
     Theme Toggle (Dark-Industrial default / Clean Light)
     ------------------------------------------------------------------------ */
  function initTheme() {
    const saved = readStore(STORAGE_KEYS.theme, 'dark');
    applyTheme(saved === 'light' ? 'light' : 'dark');

    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme') || 'dark';
        const next = current === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        writeStore(STORAGE_KEYS.theme, next);
      });
    }
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.textContent = theme === 'dark' ? '☀ Light' : '☾ Dark';
      btn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
    }
  }

  /* ------------------------------------------------------------------------
     Step Navigation & Completion Tracking
     ------------------------------------------------------------------------ */
  let currentStep = 1;
  let completedSteps = new Set(readStore(STORAGE_KEYS.completed, []));

  function getStepFromHash() {
    const m = window.location.hash.match(/^#step-(\d+)$/);
    if (m) {
      const n = parseInt(m[1], 10);
      if (n >= 1 && n <= TOTAL_STEPS) return n;
    }
    return 1;
  }

  function updateProgressUI() {
    const count = completedSteps.size;
    const pct = Math.round((count / TOTAL_STEPS) * 100);

    const fill = document.getElementById('progress-fill');
    const label = document.getElementById('progress-label');
    const topPill = document.getElementById('top-progress-pill');

    if (fill) fill.style.width = `${pct}%`;
    if (label) label.textContent = `${count} / ${TOTAL_STEPS} complete (${pct}%)`;
    if (topPill) topPill.textContent = `${count} / ${TOTAL_STEPS} done`;

    document.querySelectorAll('.step-nav-btn').forEach((btn) => {
      const step = parseInt(btn.dataset.step, 10);
      const isDone = completedSteps.has(step);
      btn.classList.toggle('completed', isDone);
      btn.classList.toggle('active', step === currentStep);
      const numEl = btn.querySelector('.step-num');
      if (numEl) {
        numEl.textContent = isDone ? '✓' : String(step);
      }
      if (step === currentStep) {
        btn.setAttribute('aria-current', 'step');
      } else {
        btn.removeAttribute('aria-current');
      }
    });
  }

  function goToStep(stepNum, options) {
    const opts = options || {};
    if (stepNum < 1 || stepNum > TOTAL_STEPS) return;
    currentStep = stepNum;

    document.querySelectorAll('.step-panel').forEach((panel) => {
      const isTarget = parseInt(panel.dataset.step, 10) === currentStep;
      panel.classList.toggle('active', isTarget);
    });

    if (opts.updateHash !== false) {
      try {
        window.history.replaceState(null, '', `#step-${currentStep}`);
      } catch (_err) {
        window.location.hash = `#step-${currentStep}`;
      }
    }

    updateProgressUI();
    closeMobileSidebar();

    if (opts.scroll !== false) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    if (currentStep === 6 && window.__qnxSimRender) {
      window.__qnxSimRender();
    }
  }

  function markStepComplete(stepNum) {
    completedSteps.add(stepNum);
    writeStore(STORAGE_KEYS.completed, Array.from(completedSteps).sort((a, b) => a - b));
    updateProgressUI();
  }

  function closeMobileSidebar() {
    const sb = document.getElementById('sidebar');
    const bd = document.getElementById('sidebar-backdrop');
    if (sb) sb.classList.remove('open');
    if (bd) bd.classList.remove('open');
  }

  function initNavigation() {
    document.querySelectorAll('.step-nav-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        goToStep(parseInt(btn.dataset.step, 10));
      });
    });

    document.querySelectorAll('[data-nav-prev]').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (currentStep > 1) goToStep(currentStep - 1);
      });
    });

    document.querySelectorAll('[data-nav-next]').forEach((btn) => {
      btn.addEventListener('click', () => {
        markStepComplete(currentStep);
        if (currentStep < TOTAL_STEPS) {
          goToStep(currentStep + 1);
        }
      });
    });

    const menuBtn = document.getElementById('menu-btn');
    const backdrop = document.getElementById('sidebar-backdrop');
    const sidebar = document.getElementById('sidebar');
    if (menuBtn && sidebar && backdrop) {
      menuBtn.addEventListener('click', () => {
        const willOpen = !sidebar.classList.contains('open');
        sidebar.classList.toggle('open', willOpen);
        backdrop.classList.toggle('open', willOpen);
      });
      backdrop.addEventListener('click', closeMobileSidebar);
    }

    window.addEventListener('hashchange', () => {
      goToStep(getStepFromHash(), { updateHash: false });
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeMobileSidebar();
        return;
      }
      const tag = (document.activeElement && document.activeElement.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.altKey || e.ctrlKey || e.metaKey) {
        return;
      }
      if (e.key === 'ArrowRight' && currentStep < TOTAL_STEPS) {
        markStepComplete(currentStep);
        goToStep(currentStep + 1);
      } else if (e.key === 'ArrowLeft' && currentStep > 1) {
        goToStep(currentStep - 1);
      }
    });

    goToStep(getStepFromHash(), { scroll: false, updateHash: false });
  }

  /* ------------------------------------------------------------------------
     Single-Pass Syntax Highlighter & Copy Buttons
     ------------------------------------------------------------------------ */
  const LANG_RULES = {
    c: [
      { cls: 'tok-cmt',   re: /\/\*[\s\S]*?\*\/|\/\/[^\n]*/ },
      { cls: 'tok-str',   re: /"(?:\\.|[^"\\])*"|<(?:sys|secpol)\/[a-zA-Z0-9_./-]+>|<[a-zA-Z0-9_]+\.h>/ },
      { cls: 'tok-macro', re: /#[ \t]*(?:include|define|ifdef|ifndef|endif|pragma)\b|\b(?:_NTO_CHF_[A-Z0-9_]+|PROCMGR_[A-Z0-9_]+|SLOG2_[A-Z0-9_]+|IOFUNC_[A-Z0-9_]+|_RESMGR_[A-Z0-9_]+|_FTYPE_[A-Z0-9_]+|_IO_[A-Z0-9_]+|SCHED_FIFO|CLOCK_MONOTONIC|EOK|ENOSYS|EXIT_SUCCESS|EXIT_FAILURE|NULL|S_IFCHR)\b/ },
      { cls: 'tok-kw',    re: /\b(?:if|else|for|while|return|static|const|struct|typedef|volatile|sizeof|void|int|char|float|unsigned|extern)\b/ },
      { cls: 'tok-type',  re: /\b(?:uint8_t|uint32_t|uint64_t|int32_t|size_t|dispatch_t|dispatch_context_t|resmgr_context_t|resmgr_attr_t|resmgr_connect_funcs_t|resmgr_io_funcs_t|iofunc_attr_t|io_read_t|RESMGR_OCB_T|slog2_buffer_t|slog2_buffer_set_config_t|lidar_obstacle_frame_t)\b/ },
      { cls: 'tok-fn',    re: /\b(?:ChannelCreate|dispatch_create_channel|dispatch_context_alloc|dispatch_block|dispatch_handler|resmgr_attach|iofunc_func_init|iofunc_attr_init|iofunc_read_verify|MsgReply|MsgSend|MsgReceive|SchedSet|SchedGet|secpol_transition_type|procmgr_ability|slog2_register|slog2_set_default_buffer|slog2f|clock_gettime)\b/ },
      { cls: 'tok-num',   re: /\b(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?(?:ULL|UL|U|f)?)\b/ }
    ],
    secpol: [
      { cls: 'tok-cmt',   re: /#[^\n]*/ },
      { cls: 'tok-kw',    re: /\b(?:type|allow_attach|allow|derive_type)\b/ },
      { cls: 'tok-type',  re: /\b(?:self:ability|channel|connect|nonroot|pathspace|public_channel|settypeid|spawn_setuid|mem_phys|interrupt|priority|trace|io)\b/ },
      { cls: 'tok-flag',  re: /\b[a-z0-9_]+_t\b/ },
      { cls: 'tok-str',   re: /\/[a-zA-Z0-9_/*.-]+/ },
      { cls: 'tok-num',   re: /\b\d+(?:-\d+)?\b/ }
    ],
    build: [
      { cls: 'tok-cmt',   re: /#[^\n]*/ },
      { cls: 'tok-str',   re: /"(?:\\.|[^"\\])*"/ },
      { cls: 'tok-macro', re: /\[[^\]]+\]/ },
      { cls: 'tok-fn',    re: /\b(?:startup-x86|procnto-smp-instr|secpolpush|secpol|slogger2|slog2info|devc-ser8250|tracelogger|traceprinter|display_msg|waitfor|reopen|on|ksh|lidar_mgr)\b/ },
      { cls: 'tok-flag',  re: /(?:^|(?<=\s))-[A-Za-z0-9]+/ },
      { cls: 'tok-num',   re: /\b0x[0-9a-fA-F]+\b/ }
    ],
    bash: [
      { cls: 'tok-cmt',   re: /#[^\n]*/ },
      { cls: 'tok-str',   re: /"(?:\\.|[^"\\])*"|'[^']*'/ },
      { cls: 'tok-fn',    re: /\b(?:qcc|mkifs|secpolcompile|secpolpush|secpol|tracelogger|traceprinter|slog2info|qemu-system-x86_64|qnx-pulse|make|pidin|on|source|scp|ssh)\b/ },
      { cls: 'tok-flag',  re: /(?:^|(?<=\s))--?[A-Za-z0-9_=-]+/ }
    ],
    trace: [
      { cls: 'tok-cmt',   re: /--[^\n]*|#.*/ },
      { cls: 'tok-macro', re: /\b(?:PROCCREATE_NAME|THRUNNING|THREPLY|THREADY|THCREATE|SND_MESSAGE|REC_MESSAGE|REPLY_MESSAGE|MSG_SENDV)\b/ },
      { cls: 'tok-kw',    re: /\b(?:PROCESS|THREAD|COMM|KER_CALL|CONTROL|SYSTEM)\b/ },
      { cls: 'tok-flag',  re: /\b(?:t:0x[0-9a-fA-F]+|CPU:\d+|pid:\d+|tid:\d+|ppid:\d+|prio:\d+|rcvid:0x[0-9a-fA-F]+)\b/ },
      { cls: 'tok-str',   re: /\b(?:name:[^\s]+|\/dev\/[a-zA-Z0-9_/-]+)\b/ }
    ]
  };

  function highlightText(raw, lang) {
    const rules = LANG_RULES[lang];
    if (!rules) return escapeHtml(raw);

    const combined = new RegExp(
      rules.map((r, i) => `(?<g${i}>${r.re.source})`).join('|'),
      'g'
    );

    let out = '';
    let lastIndex = 0;
    let match;

    while ((match = combined.exec(raw)) !== null) {
      if (match.index > lastIndex) {
        out += escapeHtml(raw.slice(lastIndex, match.index));
      }
      let matchedCls = '';
      if (match.groups) {
        for (let i = 0; i < rules.length; i++) {
          if (match.groups[`g${i}`] !== undefined) {
            matchedCls = rules[i].cls;
            break;
          }
        }
      }
      out += matchedCls
        ? `<span class="${matchedCls}">${escapeHtml(match[0])}</span>`
        : escapeHtml(match[0]);
      lastIndex = combined.lastIndex;
      if (match[0].length === 0) combined.lastIndex++;
    }

    if (lastIndex < raw.length) {
      out += escapeHtml(raw.slice(lastIndex));
    }
    return out;
  }

  function copyToClipboard(text, buttonEl) {
    const onSuccess = () => {
      const orig = buttonEl.dataset.origLabel || 'Copy';
      buttonEl.textContent = '✓ Copied';
      buttonEl.classList.add('copied');
      window.setTimeout(() => {
        buttonEl.textContent = orig;
        buttonEl.classList.remove('copied');
      }, 1600);
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(onSuccess).catch(() => {
        fallbackCopy(text, onSuccess);
      });
    } else {
      fallbackCopy(text, onSuccess);
    }
  }

  function fallbackCopy(text, callback) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      callback();
    } catch (_err) {
      /* ignore */
    }
    document.body.removeChild(ta);
  }

  function initCodeBlocks() {
    document.querySelectorAll('.code-block').forEach((block) => {
      const codeEl = block.querySelector('pre code');
      const copyBtn = block.querySelector('.copy-btn');
      if (!codeEl) return;

      const raw = codeEl.textContent.replace(/^\n/, '').replace(/\n\s*$/, '');
      codeEl.dataset.rawCode = raw;

      const lang = codeEl.dataset.lang || '';
      const skipHighlight = codeEl.dataset.noHighlight === 'true';
      if (!skipHighlight && lang && LANG_RULES[lang]) {
        codeEl.innerHTML = highlightText(raw, lang);
      }

      if (copyBtn) {
        copyBtn.dataset.origLabel = copyBtn.textContent.trim();
        copyBtn.addEventListener('click', () => {
          copyToClipboard(codeEl.dataset.rawCode || codeEl.textContent, copyBtn);
        });
      }
    });
  }

  /* ------------------------------------------------------------------------
     Step 6: Interactive QNX 8.0 Priority Inheritance SVG Gantt Simulator
     ------------------------------------------------------------------------ */
  function initPrioritySimulator() {
    const root = document.getElementById('pi-simulator');
    if (!root) return;

    const DEADLINE_MS = 10.0;
    const TOTAL_WINDOW_MS = 14.0;

    const state = {
      mode: 'buggy',       /* 'buggy' (_NTO_CHF_FIXED_PRIORITY ON) | 'fixed' (PI Active) */
      burstMs: 9.5,        /* can_telemetry CPU burst duration (2.0 .. 11.0 ms) */
      playheadMs: 14.0,    /* Current timeline scrubber position */
      playing: false,
      rafId: null,
      lastTs: 0
    };

    const btnBuggy = document.getElementById('sim-mode-buggy');
    const btnFixed = document.getElementById('sim-mode-fixed');
    const btnPlay = document.getElementById('sim-play-btn');
    const btnReset = document.getElementById('sim-reset-btn');
    const burstSlider = document.getElementById('sim-burst-slider');
    const burstVal = document.getElementById('sim-burst-val');
    const scrubSlider = document.getElementById('sim-scrub-slider');
    const scrubVal = document.getElementById('sim-scrub-val');
    const svgHost = document.getElementById('sim-svg-host');
    const traceLogEl = document.getElementById('sim-trace-log');

    const metricLatency = document.getElementById('sim-m-latency');
    const metricLatencySub = document.getElementById('sim-m-latency-sub');
    const metricLatencyCard = document.getElementById('sim-card-latency');

    const metricPrio = document.getElementById('sim-m-prio');
    const metricPrioSub = document.getElementById('sim-m-prio-sub');
    const metricPrioCard = document.getElementById('sim-card-prio');

    const metricInv = document.getElementById('sim-m-inversion');
    const metricInvSub = document.getElementById('sim-m-inversion-sub');
    const metricInvCard = document.getElementById('sim-card-inversion');

    const metricVerdict = document.getElementById('sim-m-verdict');
    const metricVerdictSub = document.getElementById('sim-m-verdict-sub');
    const metricVerdictCard = document.getElementById('sim-card-verdict');

    function computeSchedule() {
      const burst = state.burstMs;
      if (state.mode === 'buggy') {
        const preemptStart = 0.5;
        const preemptEnd = +(preemptStart + burst).toFixed(2);
        const replyAt = +(preemptEnd + 0.6).toFixed(2);
        const aebDone = +(replyAt + 0.3).toFixed(2);
        const missed = aebDone > DEADLINE_MS;
        return {
          mode: 'buggy',
          aebDone,
          replyAt,
          preemptStart,
          preemptEnd,
          inversionMs: burst,
          missed,
          slackMs: +(DEADLINE_MS - aebDone).toFixed(2),
          segments: {
            adas: [
              { start: 0.0, end: 0.2, kind: 'run', label: 'MsgSend (52)' },
              { start: 0.2, end: replyAt, kind: 'blocked', label: `THREPLY — BLOCKED (${(replyAt - 0.2).toFixed(1)} ms)` },
              { start: replyAt, end: aebDone, kind: missed ? 'late' : 'run', label: missed ? 'LATE BRAKE!' : 'AEB Brake' }
            ],
            can: [
              { start: preemptStart, end: preemptEnd, kind: 'preempt', label: `PREEMPTING CPU:00 @ prio 30 (${burst.toFixed(1)} ms)` }
            ],
            lidar: [
              { start: 0.2, end: preemptStart, kind: 'low', label: 'Prio 18' },
              { start: preemptStart, end: preemptEnd, kind: 'preempted', label: 'THREADY — PREEMPTED (Fixed Prio 18)' },
              { start: preemptEnd, end: replyAt, kind: 'low', label: 'Reply (18)' }
            ]
          },
          events: [
            { t: 0.0,  cls: '',             text: 't:00.0ms CPU:00 THREAD  : THRUNNING      pid:4102 (adas_aeb)      tid:1 prio:52' },
            { t: 0.2,  cls: '',             text: 't:00.2ms CPU:00 COMM    : SND_MESSAGE    pid:4102 -> /dev/lidar_fusion (pid:4096)' },
            { t: 0.2,  cls: '',             text: 't:00.2ms CPU:00 THREAD  : THREPLY        pid:4102 (adas_aeb)      blocked waiting for reply' },
            { t: 0.2,  cls: 'event-danger', text: 't:00.2ms CPU:00 COMM    : REC_MESSAGE    pid:4096 (lidar_fusion)  prio:18 [NO BOOST: _NTO_CHF_FIXED_PRIORITY]' },
            { t: 0.5,  cls: 'event-danger', text: 't:00.5ms CPU:00 THREAD  : THREADY        pid:4096 (lidar_fusion)  PREEMPTED at prio:18!' },
            { t: 0.5,  cls: 'event-danger', text: `t:00.5ms CPU:00 THREAD  : THRUNNING      pid:4118 (can_telemetry) prio:30 [PRIORITY INVERSION: ${burst.toFixed(1)} ms]` },
            { t: preemptEnd, cls: '',       text: `t:${preemptEnd.toFixed(1).padStart(4, '0')}ms CPU:00 THREAD  : THRUNNING      pid:4096 (lidar_fusion)  resumes voxel fusion @ prio:18` },
            { t: replyAt, cls: '',          text: `t:${replyAt.toFixed(1).padStart(4, '0')}ms CPU:00 COMM    : REPLY_MESSAGE  pid:4096 -> pid:4102 (adas_aeb)` },
            { t: aebDone, cls: missed ? 'event-danger' : 'event-boost', text: `t:${aebDone.toFixed(1).padStart(4, '0')}ms CPU:00 USREVENT: AEB_BRAKE_CMD  latency=${aebDone.toFixed(1)}ms ${missed ? '>>> ISO 26262 DEADLINE MISSED (+' + (aebDone - DEADLINE_MS).toFixed(1) + 'ms) <<<' : '(within 10.0ms deadline, high jitter)'}` }
          ]
        };
      }

      /* FIXED MODE: Priority Inheritance ACTIVE */
      const replyAt = 1.1;
      const aebDone = 1.4;
      const canStart = 1.4;
      const canEnd = +(canStart + burst).toFixed(2);
      return {
        mode: 'fixed',
        aebDone,
        replyAt,
        preemptStart: 0.5,
        preemptEnd: 1.4,
        inversionMs: 0.0,
        missed: false,
        slackMs: +(DEADLINE_MS - aebDone).toFixed(2),
        segments: {
          adas: [
            { start: 0.0, end: 0.2, kind: 'run', label: 'MsgSend' },
            { start: 0.2, end: replyAt, kind: 'blocked-ok', label: 'THREPLY (0.9ms)' },
            { start: replyAt, end: aebDone, kind: 'run', label: 'BRAKE 1.4ms' }
          ],
          can: [
            { start: 0.5, end: canStart, kind: 'ready', label: 'THREADY' },
            { start: canStart, end: canEnd, kind: 'can-safe', label: `Safe Post-AEB CAN Logging @ prio 30 (${burst.toFixed(1)} ms)` }
          ],
          lidar: [
            { start: 0.2, end: replyAt, kind: 'boosted', label: 'BOOSTED PRIO 18 → 52 (PI ACTIVE)' }
          ]
        },
        events: [
          { t: 0.0,    cls: '',            text: 't:00.0ms CPU:00 THREAD  : THRUNNING      pid:4102 (adas_aeb)      tid:1 prio:52' },
          { t: 0.2,    cls: '',            text: 't:00.2ms CPU:00 COMM    : SND_MESSAGE    pid:4102 -> /dev/lidar_fusion (pid:4096)' },
          { t: 0.2,    cls: '',            text: 't:00.2ms CPU:00 THREAD  : THREPLY        pid:4102 (adas_aeb)      blocked waiting for reply' },
          { t: 0.2,    cls: 'event-boost', text: 't:00.2ms CPU:00 COMM    : REC_MESSAGE    pid:4096 (lidar_fusion)  PRIO BOOSTED 18 -> 52 (QNX PI!)' },
          { t: 0.5,    cls: 'event-boost', text: 't:00.5ms CPU:00 THREAD  : THREADY        pid:4118 (can_telemetry) prio:30 DEFERRED (52 > 30)' },
          { t: 1.1,    cls: 'event-boost', text: 't:01.1ms CPU:00 COMM    : REPLY_MESSAGE  pid:4096 -> pid:4102     prio restored 52 -> 18' },
          { t: 1.1,    cls: '',            text: 't:01.1ms CPU:00 THREAD  : THRUNNING      pid:4102 (adas_aeb)      tid:1 prio:52' },
          { t: 1.4,    cls: 'event-boost', text: 't:01.4ms CPU:00 USREVENT: AEB_BRAKE_CMD  latency=1.4ms >>> PASS (8.6ms slack, ZERO JITTER) <<<' },
          { t: 1.4,    cls: '',            text: `t:01.4ms CPU:00 THREAD  : THRUNNING      pid:4118 (can_telemetry) prio:30 runs safely until ${canEnd.toFixed(1)}ms` }
        ]
      };
    }

    function render() {
      const sched = computeSchedule();
      const maxTime = Math.max(TOTAL_WINDOW_MS, sched.mode === 'buggy' ? sched.aebDone + 1.0 : 1.4 + state.burstMs + 0.6);

      /* Update mode buttons */
      btnBuggy.className = 'mode-btn' + (state.mode === 'buggy' ? ' active-buggy' : '');
      btnFixed.className = 'mode-btn' + (state.mode === 'fixed' ? ' active-fixed' : '');

      /* Update Telemetry HUD Cards */
      metricLatency.textContent = `${sched.aebDone.toFixed(1)} ms`;
      if (sched.missed) {
        metricLatencySub.textContent = `+${(sched.aebDone - DEADLINE_MS).toFixed(1)} ms past 10.0 ms deadline`;
        metricLatencyCard.className = 'sim-metric-card state-fail';
      } else if (state.mode === 'buggy') {
        metricLatencySub.textContent = `Only ${sched.slackMs.toFixed(1)} ms slack (unbounded jitter!)`;
        metricLatencyCard.className = 'sim-metric-card state-warn';
      } else {
        metricLatencySub.textContent = `${sched.slackMs.toFixed(1)} ms safety margin (zero jitter)`;
        metricLatencyCard.className = 'sim-metric-card state-pass';
      }

      if (state.mode === 'buggy') {
        metricPrio.textContent = '18 (Fixed)';
        metricPrioSub.textContent = '_NTO_CHF_FIXED_PRIORITY blocks PI';
        metricPrioCard.className = 'sim-metric-card state-fail';

        metricInv.textContent = `${sched.inversionMs.toFixed(1)} ms`;
        metricInvSub.textContent = 'can_telemetry (30) preempts server';
        metricInvCard.className = 'sim-metric-card state-fail';
      } else {
        metricPrio.textContent = '18 → 52';
        metricPrioSub.textContent = 'Kernel boosts server on MsgSend';
        metricPrioCard.className = 'sim-metric-card state-pass';

        metricInv.textContent = '0.0 ms';
        metricInvSub.textContent = 'Zero medium-priority preemption';
        metricInvCard.className = 'sim-metric-card state-pass';
      }

      if (sched.missed) {
        metricVerdict.textContent = 'FAIL';
        metricVerdictSub.textContent = 'ISO 26262 AEB deadline missed';
        metricVerdictCard.className = 'sim-metric-card state-fail';
      } else if (state.mode === 'buggy') {
        metricVerdict.textContent = 'AT RISK';
        metricVerdictSub.textContent = 'Inversion active — raise burst > 8.6ms';
        metricVerdictCard.className = 'sim-metric-card state-warn';
      } else {
        metricVerdict.textContent = 'PASS';
        metricVerdictSub.textContent = 'Deterministic 1.4 ms brake response';
        metricVerdictCard.className = 'sim-metric-card state-pass';
      }

      /* Build SVG Gantt Chart */
      const W = 820;
      const H = 266;
      const leftPad = 166;
      const rightPad = 24;
      const plotW = W - leftPad - rightPad;
      const topPad = 36;
      const laneH = 56;
      const barH = 34;

      const xFor = (ms) => leftPad + (Math.min(ms, maxTime) / maxTime) * plotW;
      const ph = Math.min(state.playheadMs, maxTime);

      const palette = {
        run:         { fill: '#0ea5e9', stroke: '#38bdf8', text: '#04121d' },
        late:        { fill: '#f43f5e', stroke: '#fb7185', text: '#ffffff' },
        blocked:     { fill: 'rgba(245,158,11,0.22)', stroke: '#f59e0b', text: '#fcd34d', dash: '4,3' },
        'blocked-ok':{ fill: 'rgba(56,189,248,0.16)', stroke: '#38bdf8', text: '#bae6fd', dash: '4,3' },
        preempt:     { fill: '#f97316', stroke: '#fb923c', text: '#1a0a02' },
        'can-safe':  { fill: '#334155', stroke: '#64748b', text: '#e2e8f0' },
        ready:       { fill: 'rgba(148,163,184,0.16)', stroke: '#64748b', text: '#cbd5e1', dash: '3,3' },
        low:         { fill: '#6366f1', stroke: '#818cf8', text: '#ffffff' },
        preempted:   { fill: 'rgba(244,63,94,0.18)', stroke: '#f43f5e', text: '#fda4af', dash: '4,3' },
        boosted:     { fill: '#10b981', stroke: '#34d399', text: '#021a12' }
      };

      const lanes = [
        { key: 'adas',  name: 'adas_aeb',      meta: 'PID 4102 · Prio 52', y: topPad },
        { key: 'can',   name: 'can_telemetry', meta: 'PID 4118 · Prio 30', y: topPad + laneH },
        { key: 'lidar', name: 'lidar_fusion',  meta: 'PID 4096 · Base 18', y: topPad + laneH * 2 }
      ];

      let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="QNX 8.0 Priority Inheritance Timeline Gantt Chart">`;

      /* Gridlines & Time Axis */
      const tickStep = maxTime > 15 ? 2 : 1;
      for (let t = 0; t <= Math.floor(maxTime); t += tickStep) {
        const x = xFor(t).toFixed(1);
        svg += `<line x1="${x}" y1="${topPad - 6}" x2="${x}" y2="${topPad + laneH * 3 + 6}" stroke="#1e293b" stroke-width="1"/>`;
        svg += `<text x="${x}" y="${topPad - 13}" fill="#64748b" font-family="monospace" font-size="10.5" text-anchor="middle">${t}ms</text>`;
      }

      /* Inversion highlight band in buggy mode */
      if (state.mode === 'buggy' && ph > sched.preemptStart) {
        const bx1 = xFor(sched.preemptStart);
        const bx2 = xFor(Math.min(sched.preemptEnd, ph));
        if (bx2 > bx1) {
          svg += `<rect x="${bx1.toFixed(1)}" y="${topPad - 4}" width="${(bx2 - bx1).toFixed(1)}" height="${laneH * 3 + 8}" fill="rgba(244,63,94,0.08)" stroke="none"/>`;
        }
      }

      /* Swimlanes & Segments */
      lanes.forEach((lane) => {
        const rowTop = lane.y;
        const barY = rowTop + 10;
        svg += `<rect x="8" y="${rowTop + 2}" width="${W - 16}" height="${laneH - 6}" rx="6" fill="#0d1420" stroke="#182436" stroke-width="1"/>`;
        svg += `<text x="18" y="${rowTop + 24}" fill="#e2e8f0" font-family="monospace" font-size="12" font-weight="700">${lane.name}</text>`;
        svg += `<text x="18" y="${rowTop + 40}" fill="#64748b" font-family="monospace" font-size="10">${lane.meta}</text>`;

        sched.segments[lane.key].forEach((seg) => {
          if (ph <= seg.start) return;
          const visibleEnd = Math.min(seg.end, ph);
          const x1 = xFor(seg.start);
          const x2 = xFor(visibleEnd);
          const bw = Math.max(2, x2 - x1);
          const sty = palette[seg.kind];
          const dashAttr = sty.dash ? ` stroke-dasharray="${sty.dash}"` : '';
          svg += `<rect x="${x1.toFixed(1)}" y="${barY}" width="${bw.toFixed(1)}" height="${barH}" rx="4" fill="${sty.fill}" stroke="${sty.stroke}" stroke-width="1.4"${dashAttr}/>`;
          if (bw > 56) {
            const cx = (x1 + bw / 2).toFixed(1);
            const clippedLabel = bw < 130 && seg.label.length > 16 ? seg.label.slice(0, 14) + '…' : seg.label;
            svg += `<text x="${cx}" y="${barY + 21}" fill="${sty.text}" font-family="monospace" font-size="10.2" font-weight="700" text-anchor="middle">${escapeHtml(clippedLabel)}</text>`;
          }
        });
      });

      /* IPC Handoff Arrows (MsgSend & MsgReply) */
      if (ph >= 0.2) {
        const xSend = xFor(0.2).toFixed(1);
        svg += `<line x1="${xSend}" y1="${topPad + 44}" x2="${xSend}" y2="${topPad + laneH * 2 + 10}" stroke="#38bdf8" stroke-width="1.5" stroke-dasharray="3,2"/>`;
        svg += `<circle cx="${xSend}" cy="${topPad + laneH * 2 + 10}" r="3.5" fill="#38bdf8"/>`;
      }
      if (ph >= sched.replyAt) {
        const xRep = xFor(sched.replyAt).toFixed(1);
        const col = state.mode === 'fixed' ? '#10b981' : '#f59e0b';
        svg += `<line x1="${xRep}" y1="${topPad + laneH * 2 + 10}" x2="${xRep}" y2="${topPad + 44}" stroke="${col}" stroke-width="1.5" stroke-dasharray="3,2"/>`;
        svg += `<circle cx="${xRep}" cy="${topPad + 44}" r="3.5" fill="${col}"/>`;
      }

      /* 10.0 ms Hard Real-Time Deadline Line */
      const xDead = xFor(DEADLINE_MS).toFixed(1);
      svg += `<line x1="${xDead}" y1="${topPad - 10}" x2="${xDead}" y2="${topPad + laneH * 3 + 12}" stroke="#f43f5e" stroke-width="2" stroke-dasharray="6,4"/>`;
      svg += `<rect x="${(parseFloat(xDead) - 52).toFixed(1)}" y="${topPad + laneH * 3 + 14}" width="104" height="20" rx="4" fill="#f43f5e"/>`;
      svg += `<text x="${xDead}" y="${topPad + laneH * 3 + 27.5}" fill="#ffffff" font-family="monospace" font-size="10" font-weight="700" text-anchor="middle">DEADLINE 10.0ms</text>`;

      /* Brake Completion Marker */
      if (ph >= sched.aebDone) {
        const xDone = xFor(sched.aebDone);
        const badgeCol = sched.missed ? '#f43f5e' : '#10b981';
        const badgeTxt = sched.missed
          ? `MISSED @ ${sched.aebDone.toFixed(1)}ms`
          : `BRAKE OK @ ${sched.aebDone.toFixed(1)}ms`;
        const boxX = Math.min(W - 134, Math.max(leftPad + 4, xDone - 62));
        svg += `<circle cx="${xDone.toFixed(1)}" cy="${topPad + 27}" r="5" fill="${badgeCol}" stroke="#ffffff" stroke-width="1.5"/>`;
        svg += `<rect x="${boxX.toFixed(1)}" y="4" width="124" height="19" rx="4" fill="${badgeCol}"/>`;
        svg += `<text x="${(boxX + 62).toFixed(1)}" y="16.8" fill="${sched.missed ? '#ffffff' : '#03150e'}" font-family="monospace" font-size="10" font-weight="700" text-anchor="middle">${badgeTxt}</text>`;
      }

      /* Animated Playhead Cursor */
      const xPh = xFor(ph).toFixed(1);
      svg += `<line x1="${xPh}" y1="${topPad - 6}" x2="${xPh}" y2="${topPad + laneH * 3 + 10}" stroke="#00d2ff" stroke-width="1.8"/>`;
      svg += `<circle cx="${xPh}" cy="${topPad - 6}" r="4" fill="#00d2ff"/>`;

      svg += '</svg>';
      svgHost.innerHTML = svg;

      /* Sync Scrubber UI */
      scrubSlider.max = String(maxTime.toFixed(1));
      scrubSlider.value = String(ph.toFixed(1));
      scrubVal.textContent = `${ph.toFixed(1)} ms`;
      burstVal.textContent = `${state.burstMs.toFixed(1)} ms`;

      /* Synchronized traceprinter Event Log */
      let activeIdx = -1;
      sched.events.forEach((ev, idx) => {
        if (ev.t <= ph + 0.01) activeIdx = idx;
      });

      traceLogEl.innerHTML = '';
      sched.events.forEach((ev, idx) => {
        const li = document.createElement('li');
        li.className = 'sim-trace-line' + (ev.cls ? ' ' + ev.cls : '') + (idx === activeIdx ? ' active-event' : '');
        li.textContent = ev.text;
        li.title = `Click to jump playhead to ${ev.t.toFixed(1)} ms`;
        li.addEventListener('click', () => {
          stopPlayback();
          state.playheadMs = ev.t;
          render();
        });
        traceLogEl.appendChild(li);
      });
    }

    function stopPlayback() {
      state.playing = false;
      if (state.rafId) {
        window.cancelAnimationFrame(state.rafId);
        state.rafId = null;
      }
      btnPlay.textContent = '▶ Play Trace';
    }

    function stepFrame(ts) {
      if (!state.playing) return;
      if (!state.lastTs) state.lastTs = ts;
      const dtSec = (ts - state.lastTs) / 1000;
      state.lastTs = ts;

      const sched = computeSchedule();
      const maxTime = Math.max(TOTAL_WINDOW_MS, sched.mode === 'buggy' ? sched.aebDone + 1.0 : 1.4 + state.burstMs + 0.6);
      state.playheadMs += dtSec * 3.8; /* 3.8 simulated ms per real second */
      if (state.playheadMs >= maxTime) {
        state.playheadMs = maxTime;
        render();
        stopPlayback();
        return;
      }
      render();
      state.rafId = window.requestAnimationFrame(stepFrame);
    }

    btnBuggy.addEventListener('click', () => {
      stopPlayback();
      state.mode = 'buggy';
      state.playheadMs = 14.0;
      render();
    });

    btnFixed.addEventListener('click', () => {
      stopPlayback();
      state.mode = 'fixed';
      state.playheadMs = 14.0;
      render();
    });

    btnPlay.addEventListener('click', () => {
      if (state.playing) {
        stopPlayback();
        return;
      }
      const sched = computeSchedule();
      const maxTime = Math.max(TOTAL_WINDOW_MS, sched.mode === 'buggy' ? sched.aebDone + 1.0 : 1.4 + state.burstMs + 0.6);
      if (state.playheadMs >= maxTime - 0.1) {
        state.playheadMs = 0.0;
      }
      state.playing = true;
      state.lastTs = 0;
      btnPlay.textContent = '⏸ Pause';
      state.rafId = window.requestAnimationFrame(stepFrame);
    });

    btnReset.addEventListener('click', () => {
      stopPlayback();
      state.burstMs = 9.5;
      burstSlider.value = '9.5';
      state.playheadMs = 0.0;
      render();
    });

    burstSlider.addEventListener('input', () => {
      state.burstMs = parseFloat(burstSlider.value);
      render();
    });

    scrubSlider.addEventListener('input', () => {
      stopPlayback();
      state.playheadMs = parseFloat(scrubSlider.value);
      render();
    });

    window.__qnxSimRender = render;
    render();
  }

  /* ------------------------------------------------------------------------
     Step 7: Interactive 4-Question Comprehension Quiz + Checklist
     ------------------------------------------------------------------------ */
  function initQuiz() {
    const cards = document.querySelectorAll('.quiz-card');
    if (!cards.length) return;

    let answers = readStore(STORAGE_KEYS.quiz, {});
    const scorePill = document.getElementById('quiz-score-pill');
    const banner = document.getElementById('quiz-banner');
    const resetBtn = document.getElementById('quiz-reset-btn');

    function renderQuizState() {
      let correctCount = 0;
      let answeredCount = 0;

      cards.forEach((card) => {
        const qid = card.dataset.qid;
        const correctOpt = card.dataset.correct;
        const chosen = answers[qid];
        const feedback = card.querySelector('.quiz-feedback');
        const explainCorrect = card.dataset.explainCorrect;
        const explainWrong = card.dataset.explainWrong;

        card.querySelectorAll('.quiz-opt-btn').forEach((btn) => {
          const val = btn.dataset.opt;
          btn.classList.remove('is-correct', 'is-wrong');
          if (chosen) {
            if (val === correctOpt) btn.classList.add('is-correct');
            if (val === chosen && chosen !== correctOpt) btn.classList.add('is-wrong');
          }
        });

        if (chosen) {
          answeredCount++;
          const ok = chosen === correctOpt;
          if (ok) correctCount++;
          if (feedback) {
            feedback.className = 'quiz-feedback show ' + (ok ? 'correct' : 'wrong');
            feedback.textContent = ok ? `✓ Correct — ${explainCorrect}` : `✗ Not quite — ${explainWrong}`;
          }
        } else if (feedback) {
          feedback.className = 'quiz-feedback';
          feedback.textContent = '';
        }
      });

      if (scorePill) {
        scorePill.textContent = `Score: ${correctCount} / ${cards.length}`;
      }

      if (banner) {
        const mastered = answeredCount === cards.length && correctCount === cards.length;
        banner.classList.toggle('show', mastered);
        if (mastered) {
          markStepComplete(7);
        }
      }
    }

    cards.forEach((card) => {
      const qid = card.dataset.qid;
      card.querySelectorAll('.quiz-opt-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
          answers[qid] = btn.dataset.opt;
          writeStore(STORAGE_KEYS.quiz, answers);
          renderQuizState();
        });
      });
    });

    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        answers = {};
        writeStore(STORAGE_KEYS.quiz, answers);
        renderQuizState();
      });
    }

    renderQuizState();
  }

  function initChecklist() {
    const boxes = document.querySelectorAll('[data-check-id]');
    if (!boxes.length) return;
    const saved = readStore(STORAGE_KEYS.checklist, {});
    boxes.forEach((cb) => {
      const id = cb.dataset.checkId;
      cb.checked = Boolean(saved[id]);
      cb.addEventListener('change', () => {
        saved[id] = cb.checked;
        writeStore(STORAGE_KEYS.checklist, saved);
      });
    });
  }

  /* ------------------------------------------------------------------------
     Boot
     ------------------------------------------------------------------------ */
  document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initCodeBlocks();
    initNavigation();
    initPrioritySimulator();
    initQuiz();
    initChecklist();
  });
})();
