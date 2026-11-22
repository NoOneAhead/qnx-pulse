/* QNX-Pulse Mission Control Studio — Frontend Controller */
(function () {
  "use strict";

  const state = {
    scenarios: [],
    currentScenarioId: null,
    artifacts: { trace_text: "", slog2_text: "", buildfile_text: "", secpol_text: "" },
    traceAnalysis: null,
    auditResult: null,
    copilot: null,
    ganttZoom: 1,
    logFilter: "ALL",
    findingFilter: "ALL",
    selectedIpcItem: null,
  };

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  function esc(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showToast(msg) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.add("hidden"), 3000);
  }

  async function apiJson(url, opts = {}) {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`HTTP ${res.status}: ${errText}`);
    }
    return res.json();
  }

  /* ---------------- Tab Switching ---------------- */
  function activateTab(tabName) {
    $$(".tab-btn").forEach((btn) => {
      const isMatch = btn.dataset.tab === tabName;
      btn.classList.toggle("active", isMatch);
      btn.setAttribute("aria-selected", isMatch ? "true" : "false");
    });
    $$(".tab-panel").forEach((panel) => {
      panel.classList.toggle("active", panel.id === `tab-${tabName}`);
    });
  }

  /* ---------------- Load Scenarios ---------------- */
  async function init() {
    bindEvents();
    try {
      const data = await apiJson("/api/scenarios");
      state.scenarios = data.scenarios || [];
      const select = $("#scenarioSelect");
      select.innerHTML = state.scenarios
        .map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`)
        .join("");
      if (state.scenarios.length > 0) {
        await loadScenario(state.scenarios[0].id);
      }
    } catch (err) {
      showToast("Failed to connect to QNX-Pulse API: " + err.message);
    }
  }

  async function loadScenario(scenarioId) {
    state.currentScenarioId = scenarioId;
    $("#scenarioSelect").value = scenarioId;
    try {
      const data = await apiJson(`/api/scenarios/${encodeURIComponent(scenarioId)}`);
      state.artifacts = data.artifacts;
      state.traceAnalysis = data.trace_analysis;
      state.auditResult = data.audit_result;
      state.copilot = data.copilot;
      state.selectedIpcItem = null;

      $("#scenarioDomain").textContent = data.meta.domain || "QNX 8.0";
      $("#scenarioTarget").textContent = `${data.trace_analysis.header.sysname} ${data.trace_analysis.header.sys_release} • ${data.meta.arch || data.trace_analysis.header.machine}`;
      $("#scenarioTagline").textContent = data.meta.tagline || data.meta.description || "";

      $("#buildfileEditor").value = state.artifacts.buildfile_text || "";
      $("#secpolEditor").value = state.artifacts.secpol_text || "";

      renderAll();
    } catch (err) {
      showToast("Error loading scenario: " + err.message);
    }
  }

  function renderAll() {
    renderHeaderAndKpis();
    renderIncidentAlerts();
    renderGanttChart();
    renderCoreUtilization();
    renderLatencyHistogram();
    renderThreadsTable();
    renderSlog2Feed();
    renderIpcTopology();
    renderAuditPanel();
    renderCopilotPanel();
  }

  /* ---------------- Header & KPIs ---------------- */
  function renderHeaderAndKpis() {
    const tr = state.traceAnalysis;
    const au = state.auditResult;
    if (!tr) return;

    const healthClass =
      tr.health_status === "HEALTHY"
        ? "healthy"
        : tr.health_status === "DEGRADED"
        ? "degraded"
        : "critical";

    const hp = $("#headerHealthPill");
    hp.className = `pill pill-${healthClass}`;
    hp.textContent = `RT Health: ${tr.health_score}/100`;

    $("#traceMetaSummary").textContent =
      `File: ${tr.header.file_name} | Events: ${tr.total_events} | Window: ${(tr.duration_us / 1000).toFixed(2)} ms | CPUs: ${tr.header.cpu_num}`;

    $("#kpiHealth").textContent = `${tr.health_score}/100`;
    $("#kpiHealth").className = `kpi-value val-${healthClass}`;
    $("#kpiHealthStatus").textContent = tr.health_status;

    $("#kpiInversions").textContent = String(tr.priority_inversions.length);
    $("#kpiInversions").className = `kpi-value ${tr.priority_inversions.length ? "val-critical" : "val-healthy"}`;

    $("#kpiIrqStorms").textContent = String(tr.irq_storms.length);
    $("#kpiIrqStorms").className = `kpi-value ${tr.irq_storms.length ? "val-critical" : "val-healthy"}`;

    $("#kpiDeadlineMisses").textContent = String(tr.deadline_misses.length);
    $("#kpiDeadlineMisses").className = `kpi-value ${tr.deadline_misses.length ? "val-critical" : "val-healthy"}`;

    if (au) {
      const gClass = au.grade === "A" || au.grade === "B" ? "healthy" : au.grade === "C" ? "degraded" : "critical";
      const gp = $("#headerGradePill");
      gp.className = `pill pill-${gClass}`;
      gp.textContent = `Secpol: Grade ${au.grade} (${au.overall_score})`;

      $("#kpiAuditGrade").textContent = `Grade ${au.grade}`;
      $("#kpiAuditGrade").className = `kpi-value val-${gClass}`;
      $("#kpiAuditScore").textContent = `${au.overall_score}/100 • ${au.findings.length} finding(s)`;

      const badge = $("#auditCountBadge");
      badge.textContent = String(au.findings.length);
      badge.classList.toggle("clean", au.findings.length === 0);
    }
  }

  /* ---------------- Incident Alerts ---------------- */
  function renderIncidentAlerts() {
    const tr = state.traceAnalysis;
    const container = $("#incidentAlerts");
    if (!tr) return;

    const cards = [];
    for (const pi of tr.priority_inversions) {
      cards.push(`
        <div class="incident-card">
          <div class="incident-head">
            <div class="incident-title"><span class="badge badge-crimson">${esc(pi.id)} PRIORITY INVERSION</span> ${esc(pi.high_prio_client)} [prio ${pi.high_prio}] stalled ${(pi.duration_us / 1000).toFixed(2)} ms on ${esc(pi.blocked_server)} [prio ${pi.server_prio}]</div>
            <button class="btn btn-xs btn-outline jump-copilot-btn" type="button">View C Fix in Copilot →</button>
          </div>
          <div class="incident-body">${esc(pi.explanation)} <br><span class="mono" style="color:#fda4af">Root Mechanism: ${esc(pi.mechanism)}</span></div>
        </div>
      `);
    }
    for (const st of tr.irq_storms) {
      cards.push(`
        <div class="incident-card warn">
          <div class="incident-head">
            <div class="incident-title"><span class="badge badge-amber">${esc(st.id)} IRQ STORM</span> ${esc(st.irq_vector)} on CPU:0${st.cpu} fired ${st.count}× (${Math.round(st.rate_hz).toLocaleString()} Hz, ${st.cpu_share_pct}% CPU)</div>
            <button class="btn btn-xs btn-outline jump-copilot-btn" type="button">View IST &amp; Affinity Fix →</button>
          </div>
          <div class="incident-body">${esc(st.explanation)}</div>
        </div>
      `);
    }
    for (const dm of tr.deadline_misses) {
      cards.push(`
        <div class="incident-card">
          <div class="incident-head">
            <div class="incident-title"><span class="badge badge-crimson">${esc(dm.id)} DEADLINE MISS</span> ${esc(dm.thread_label)} Frame #${esc(dm.frame_id || "?")} — ${(dm.actual_us / 1000).toFixed(2)} ms vs ${(dm.deadline_us / 1000).toFixed(2)} ms budget (+${(dm.overrun_us / 1000).toFixed(2)} ms)</div>
          </div>
          <div class="incident-body"><strong>Correlated Root Cause:</strong> ${esc(dm.root_cause)}</div>
        </div>
      `);
    }

    if (cards.length === 0) {
      cards.push(`
        <div class="incident-card healthy">
          <div class="incident-head">
            <div class="incident-title"><span class="badge badge-emerald">ALL REAL-TIME INVARIANTS NOMINAL</span> Zero priority inversions, zero IRQ storms, and zero deadline misses across ${tr.total_events} kernel events.</div>
          </div>
          <div class="incident-body">QNX 8.0 synchronous IPC priority inheritance and core partitioning are verified healthy.</div>
        </div>
      `);
    }

    container.innerHTML = cards.join("");
    container.querySelectorAll(".jump-copilot-btn").forEach((b) =>
      b.addEventListener("click", () => activateTab("copilot"))
    );
  }

  /* ---------------- Gantt Scheduler SVG ---------------- */
  function renderGanttChart() {
    const tr = state.traceAnalysis;
    const svg = $("#ganttSvg");
    if (!tr || !tr.threads.length) {
      svg.innerHTML = "";
      return;
    }

    const leftPad = 215;
    const rightPad = 24;
    const topPad = 46;
    const rowH = 34;
    const baseW = 1040 * state.ganttZoom;
    const plotW = baseW - leftPad - rightPad;
    const totalDur = Math.max(tr.duration_us, 1);

    const rows = tr.threads.map((t) => ({
      key: t.key,
      label: t.thread_label,
      prio: `${t.min_priority}-${t.max_priority}`,
    }));
    const hasIrq = tr.irq_events && tr.irq_events.length > 0;
    if (hasIrq) {
      rows.push({ key: "__IRQ__", label: "HW Interrupts (INT_ENTR)", prio: "ISR" });
    }

    const totalH = topPad + rows.length * rowH + 22;
    svg.setAttribute("width", String(baseW));
    svg.setAttribute("height", String(totalH));
    svg.setAttribute("viewBox", `0 0 ${baseW} ${totalH}`);

    const xOf = (us) => leftPad + (us / totalDur) * plotW;

    const parts = [];
    // Time grid ticks
    const tickCount = 8 * state.ganttZoom;
    for (let i = 0; i <= tickCount; i++) {
      const us = (totalDur / tickCount) * i;
      const x = xOf(us);
      parts.push(`<line x1="${x.toFixed(1)}" y1="${topPad - 6}" x2="${x.toFixed(1)}" y2="${totalH - 12}" stroke="rgba(148,163,184,0.14)" stroke-dasharray="3 3"/>`);
      const label = totalDur >= 2000 ? `${(us / 1000).toFixed(1)}ms` : `${Math.round(us)}us`;
      parts.push(`<text x="${x.toFixed(1)}" y="16" fill="#93a4bf" font-size="10" font-family="monospace" text-anchor="middle">${label}</text>`);
    }

    // Priority inversion background highlight bands
    for (const pi of tr.priority_inversions) {
      const x1 = xOf(pi.start_us);
      const w = Math.max(4, xOf(pi.end_us) - x1);
      const badgeW = 186;
      const badgeX = x1 + w / 2 - badgeW / 2;
      parts.push(`<rect x="${x1.toFixed(1)}" y="${topPad}" width="${w.toFixed(1)}" height="${rows.length * rowH}" fill="rgba(244,63,94,0.13)" stroke="rgba(244,63,94,0.55)" stroke-dasharray="4 3"/>`);
      parts.push(`<rect x="${badgeX.toFixed(1)}" y="22" width="${badgeW}" height="18" rx="9" fill="#2a0f1c" stroke="#f43f5e" stroke-width="1"/>`);
      parts.push(`<text x="${(x1 + w / 2).toFixed(1)}" y="34" fill="#fda4af" font-size="10" font-weight="700" font-family="monospace" text-anchor="middle">${esc(pi.id)} INVERSION (${(pi.duration_us / 1000).toFixed(2)}ms)</text>`);
    }

    // Row backgrounds & labels
    const rowIdxByKey = {};
    rows.forEach((r, idx) => {
      rowIdxByKey[r.key] = idx;
      const y = topPad + idx * rowH;
      parts.push(`<rect x="0" y="${y}" width="${baseW}" height="${rowH}" fill="${idx % 2 === 0 ? "rgba(255,255,255,0.015)" : "transparent"}"/>`);
      parts.push(`<line x1="0" y1="${y + rowH}" x2="${baseW}" y2="${y + rowH}" stroke="rgba(56,189,248,0.08)"/>`);
      const shortLbl = r.label.length > 26 ? r.label.slice(0, 24) + "…" : r.label;
      parts.push(`<text x="10" y="${y + 21}" fill="#e2e8f0" font-size="11" font-family="monospace">${esc(shortLbl)}</text>`);
      parts.push(`<text x="${leftPad - 8}" y="${y + 21}" fill="#38bdf8" font-size="10" font-family="monospace" text-anchor="end">P:${esc(r.prio)}</text>`);
    });

    // Thread segments
    const colorMap = {
      RUNNING: "#00d4ff",
      READY: "#f59e0b",
      REPLY: "#f43f5e",
      SEND: "#fb7185",
      MUTEX: "#fb923c",
      RECEIVE: "rgba(148,163,184,0.16)",
      NANOSLEEP: "rgba(148,163,184,0.08)",
    };

    for (const seg of tr.timeline_segments) {
      if (seg.state === "NANOSLEEP" || seg.state === "RECEIVE") continue;
      const idx = rowIdxByKey[`${seg.pid}:${seg.tid}`];
      if (idx === undefined) continue;
      const y = topPad + idx * rowH + 6;
      const x = xOf(seg.start_us);
      const w = Math.max(3, xOf(seg.end_us) - x);
      const fill = colorMap[seg.state] || "#64748b";
      const h = seg.state === "RUNNING" ? 21 : 15;
      const yAdj = seg.state === "RUNNING" ? y : y + 3;
      const tip = `${seg.thread_label} | ${seg.state} | CPU:0${seg.cpu} | Prio ${seg.priority} | ${seg.start_us.toFixed(0)}–${seg.end_us.toFixed(0)} us (${seg.duration_us.toFixed(1)} us)`;
      parts.push(`<rect class="gantt-seg" data-tip="${esc(tip)}" x="${x.toFixed(1)}" y="${yAdj}" width="${w.toFixed(1)}" height="${h}" rx="3" fill="${fill}" fill-opacity="${seg.state === "RUNNING" ? "0.9" : "0.78"}" stroke="rgba(255,255,255,0.2)" stroke-width="0.6"/>`);
    }

    // IRQ ticks on IRQ swimlane
    if (hasIrq) {
      const irqY = topPad + rowIdxByKey["__IRQ__"] * rowH + 5;
      for (const irq of tr.irq_events) {
        const x = xOf(irq.start_us);
        const w = Math.max(3, xOf(irq.end_us) - x);
        const tip = `IRQ ${irq.irq} (${irq.vector}) on CPU:0${irq.cpu} | ${irq.duration_us.toFixed(1)} us | Preempted: ${irq.preempted_thread || "idle"}`;
        parts.push(`<rect class="gantt-seg" data-tip="${esc(tip)}" x="${x.toFixed(1)}" y="${irqY}" width="${w.toFixed(1)}" height="23" rx="2" fill="#c084fc" stroke="#f43f5e" stroke-width="0.8"/>`);
      }
    }

    // Deadline miss vertical markers
    for (const dm of tr.deadline_misses) {
      const x = xOf(dm.timestamp_us);
      parts.push(`<line x1="${x.toFixed(1)}" y1="${topPad}" x2="${x.toFixed(1)}" y2="${totalH - 12}" stroke="#f43f5e" stroke-width="2"/>`);
      parts.push(`<circle cx="${x.toFixed(1)}" cy="${topPad + 2}" r="4.5" fill="#f43f5e"/>`);
    }

    svg.innerHTML = parts.join("");

    // Bind hover tooltip
    const tooltip = $("#ganttTooltip");
    svg.querySelectorAll(".gantt-seg").forEach((rect) => {
      rect.addEventListener("mouseenter", (e) => {
        tooltip.textContent = rect.dataset.tip;
        tooltip.classList.remove("hidden");
        tooltip.style.left = `${Math.min(window.innerWidth - 360, e.clientX + 14)}px`;
        tooltip.style.top = `${e.clientY - 38}px`;
      });
      rect.addEventListener("mousemove", (e) => {
        tooltip.style.left = `${Math.min(window.innerWidth - 360, e.clientX + 14)}px`;
        tooltip.style.top = `${e.clientY - 38}px`;
      });
      rect.addEventListener("mouseleave", () => tooltip.classList.add("hidden"));
    });
  }

  /* ---------------- Core Utilization & Latency Histogram ---------------- */
  function renderCoreUtilization() {
    const tr = state.traceAnalysis;
    const el = $("#coreUtilContainer");
    if (!tr) return;

    el.innerHTML = tr.cores
      .map((c) => {
        const busyOnly = Math.max(0, c.utilization_pct - c.irq_pct);
        return `
          <div class="core-row">
            <div class="core-row-head mono">
              <span><strong>CPU:0${c.cpu}</strong> (${c.context_switches} ctx switches)</span>
              <span>Total: <strong>${c.utilization_pct.toFixed(1)}%</strong> ${c.irq_pct > 0 ? `<span style="color:#fb7185">(IRQ ${c.irq_pct.toFixed(1)}%)</span>` : ""}</span>
            </div>
            <div class="bar-track">
              <div class="bar-busy" style="width:${Math.min(100, busyOnly).toFixed(1)}%"></div>
              <div class="bar-irq" style="width:${Math.min(100, c.irq_pct).toFixed(1)}%"></div>
            </div>
          </div>
        `;
      })
      .join("");
  }

  function renderLatencyHistogram() {
    const tr = state.traceAnalysis;
    const svg = $("#histogramSvg");
    if (!tr) return;

    const buckets = tr.latency_histogram || [];
    const maxCount = Math.max(1, ...buckets.map((b) => b.count));
    const w = 540, h = 210, padL = 34, padR = 14, padT = 18, padB = 42;
    const plotW = w - padL - padR;
    const plotH = h - padT - padB;
    const barSlot = plotW / Math.max(1, buckets.length);

    const parts = [
      `<line x1="${padL}" y1="${padT + plotH}" x2="${w - padR}" y2="${padT + plotH}" stroke="rgba(148,163,184,0.35)"/>`,
    ];

    buckets.forEach((b, idx) => {
      const bh = (b.count / maxCount) * plotH;
      const x = padL + idx * barSlot + 8;
      const bw = Math.max(14, barSlot - 16);
      const y = padT + plotH - bh;
      const isHot = b.lo_us >= 2500 && b.count > 0;
      const fill = isHot ? "#f43f5e" : "#00d4ff";
      parts.push(`<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(2, bh).toFixed(1)}" rx="4" fill="${fill}" fill-opacity="0.85"/>`);
      if (b.count > 0) {
        parts.push(`<text x="${(x + bw / 2).toFixed(1)}" y="${(y - 5).toFixed(1)}" fill="#e2e8f0" font-size="11" font-family="monospace" text-anchor="middle">${b.count}</text>`);
      }
      parts.push(`<text x="${(x + bw / 2).toFixed(1)}" y="${h - 16}" fill="#93a4bf" font-size="10" font-family="monospace" text-anchor="middle">${esc(b.bucket)}</text>`);
    });

    svg.innerHTML = parts.join("");
  }

  /* ---------------- Threads Table & slog2 ---------------- */
  function renderThreadsTable() {
    const tr = state.traceAnalysis;
    const tbody = $("#threadsTable tbody");
    if (!tr) return;

    tbody.innerHTML = tr.threads
      .map((t) => {
        const prioBoosted = t.max_priority > t.min_priority;
        const prioCell = prioBoosted
          ? `<span class="badge badge-emerald mono">${t.min_priority} → ${t.max_priority} (PI)</span>`
          : `<span class="mono">${t.base_priority}</span>`;
        const missCell =
          t.deadline_misses > 0
            ? `<span class="badge badge-crimson">${t.deadline_misses} MISS</span>`
            : `<span style="color:#34d399">0</span>`;
        return `
          <tr>
            <td class="mono">${esc(t.thread_label)}</td>
            <td>${prioCell}</td>
            <td class="mono">${esc(t.policy)}</td>
            <td class="num">${t.activations}</td>
            <td class="num">${t.wcet_us.toFixed(1)}</td>
            <td class="num">${t.p95_us.toFixed(1)}</td>
            <td class="num">${t.p99_us.toFixed(1)}</td>
            <td class="num">${t.jitter_us.toFixed(1)}</td>
            <td class="num">${t.ipc_blocked_us.toFixed(1)} us</td>
            <td class="num">${t.preemptions}</td>
            <td class="num">${missCell}</td>
          </tr>
        `;
      })
      .join("");
  }

  function renderSlog2Feed() {
    const tr = state.traceAnalysis;
    const el = $("#slog2Container");
    if (!tr) return;
    const logs = (tr.correlated_logs || []).filter((l) => {
      if (state.logFilter === "ALL") return true;
      if (state.logFilter === "CRITICAL") return l.severity === "CRITICAL" || l.severity === "ERROR";
      return l.severity === state.logFilter;
    });

    if (!logs.length) {
      el.innerHTML = `<div class="empty-hint">No slog2info messages match the active filter.</div>`;
      return;
    }

    el.innerHTML = logs
      .map(
        (l) => `
        <div class="slog2-line">
          <span class="slog2-ts">${esc(l.timestamp_str)}</span>
          <span class="slog2-sev sev-${esc(l.severity)}">${esc(l.severity)}</span>
          <span style="color:#93c5fd">${esc(l.buffer_set)}.${l.pid}/${esc(l.buffer_name)}</span>
          <span>${esc(l.message)}</span>
        </div>
      `
      )
      .join("");
  }

  /* ---------------- IPC & Resource Manager Topology ---------------- */
  function renderIpcTopology() {
    const tr = state.traceAnalysis;
    const svg = $("#ipcGraphSvg");
    const tbody = $("#ipcEdgesTable tbody");
    if (!tr || !tr.ipc_topology) return;

    const { nodes, edges } = tr.ipc_topology;

    // Position nodes cleanly across active columns so canvas is balanced with zero dead whitespace
    const buckets = [
      nodes.filter((n) => n.role === "CLIENT"),
      nodes.filter((n) => n.role === "HYBRID" || n.role === "KERNEL"),
      nodes.filter((n) => n.role === "RESMGR"),
    ].filter((col) => col.length > 0);

    const colCenters =
      buckets.length === 1
        ? [420]
        : buckets.length === 2
        ? [210, 630]
        : [140, 420, 700];

    const positions = {};
    buckets.forEach((list, colIdx) => {
      const spacing = 400 / (list.length + 1);
      list.forEach((n, idx) => {
        positions[n.id] = { x: colCenters[colIdx], y: 34 + spacing * (idx + 1) };
      });
    });

    const nodeMap = Object.fromEntries(nodes.map((n) => [n.id, n]));
    const parts = [
      `<defs>
        <marker id="arrow-cyan" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#00d4ff"/>
        </marker>
        <marker id="arrow-red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#f43f5e"/>
        </marker>
        <marker id="arrow-emerald" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#10b981"/>
        </marker>
      </defs>`,
    ];

    // Draw edges
    edges.forEach((e, idx) => {
      const p1 = positions[e.source];
      const p2 = positions[e.target];
      if (!p1 || !p2) return;
      const dx = p2.x - p1.x;
      const dy = p2.y - p1.y;
      const dist = Math.hypot(dx, dy) || 1;
      const padX = Math.abs(dx) > 40 ? 90 : 0;
      const padY = Math.abs(dx) > 40 ? 18 : 34;
      const sx = p1.x + (dx / dist) * padX;
      const sy = p1.y + (dy / dist) * padY;
      const ex = p2.x - (dx / dist) * padX;
      const ey = p2.y - (dy / dist) * padY;
      const sameCol = Math.abs(dx) < 30;
      const bend = sameCol ? 132 : 0;
      const mx = (sx + ex) / 2 + bend;
      const my = (sy + ey) / 2 + (sameCol ? 0 : (idx % 2 === 0 ? -24 : 18));
      // Evaluate quadratic Bezier point at t so labels never collide with each other or middle nodes
      const t = sameCol ? 0.5 : (e.kind === "PULSE_ASYNC" ? 0.66 : 0.46);
      const mt = 1 - t;
      const lx = mt * mt * sx + 2 * mt * t * mx + t * t * ex;
      const ly = mt * mt * sy + 2 * mt * t * my + t * t * ey;

      const stroke = e.has_inversion ? "#f43f5e" : e.kind === "PULSE_ASYNC" ? "#00d4ff" : "#10b981";
      const marker = e.has_inversion ? "url(#arrow-red)" : e.kind === "PULSE_ASYNC" ? "url(#arrow-cyan)" : "url(#arrow-emerald)";
      const dash = e.kind === "PULSE_ASYNC" ? 'stroke-dasharray="6 4"' : "";

      parts.push(`
        <g class="ipc-edge-group" data-edge-idx="${idx}" style="cursor:pointer">
          <path d="M ${sx.toFixed(1)} ${sy.toFixed(1)} Q ${mx.toFixed(1)} ${my.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}"
            fill="none" stroke="${stroke}" stroke-width="${e.has_inversion ? 3.2 : 2.2}" ${dash} marker-end="${marker}"/>
          <rect x="${(lx - 66).toFixed(1)}" y="${(ly - 11).toFixed(1)}" width="132" height="22" rx="5"
            fill="#0a1222" stroke="${stroke}" stroke-width="1"/>
          <text x="${lx.toFixed(1)}" y="${(ly + 3).toFixed(1)}" fill="${stroke}" font-size="10" font-family="monospace" font-weight="700" text-anchor="middle">
            ${e.kind === "PULSE_ASYNC" ? `PULSE ×${e.count}` : `${e.has_inversion ? "INVERSION " : ""}${(e.max_latency_us >= 1000 ? (e.max_latency_us / 1000).toFixed(2) + "ms" : Math.round(e.max_latency_us) + "us")}`}
          </text>
        </g>
      `);
    });

    // Draw nodes
    nodes.forEach((n) => {
      const p = positions[n.id];
      if (!p) return;
      const stroke = n.has_anomaly ? "#f43f5e" : n.role === "RESMGR" ? "#10b981" : n.role === "CLIENT" ? "#00d4ff" : "#f59e0b";
      const fill = n.has_anomaly ? "rgba(244,63,94,0.14)" : "#0f1a30";
      const sub = n.resource_paths.length ? n.resource_paths[0] : `PID ${n.pid} • Prio ${n.priority_range}`;
      parts.push(`
        <g class="ipc-node-group" data-node-id="${esc(n.id)}" style="cursor:pointer">
          <rect x="${(p.x - 86).toFixed(1)}" y="${(p.y - 31).toFixed(1)}" width="172" height="62" rx="10"
            fill="${fill}" stroke="${stroke}" stroke-width="${n.has_anomaly ? 2.4 : 1.6}"/>
          <text x="${p.x}" y="${p.y - 9}" fill="#f1f5f9" font-size="12.5" font-weight="700" font-family="monospace" text-anchor="middle">${esc(n.name)}</text>
          <text x="${p.x}" y="${p.y + 8}" fill="${stroke}" font-size="10.5" font-family="monospace" text-anchor="middle">${esc(sub)}</text>
          <text x="${p.x}" y="${p.y + 23}" fill="#93a4bf" font-size="10" font-family="monospace" text-anchor="middle">${esc(n.role)} • Prio ${esc(n.priority_range)}</text>
        </g>
      `);
    });

    svg.innerHTML = parts.join("");

    // Bind inspector click handlers
    svg.querySelectorAll(".ipc-node-group").forEach((g) => {
      g.addEventListener("click", () => {
        const n = nodeMap[g.dataset.nodeId];
        if (n) showIpcNodeInspector(n);
      });
    });
    svg.querySelectorAll(".ipc-edge-group").forEach((g) => {
      g.addEventListener("click", () => {
        const e = edges[Number(g.dataset.edgeIdx)];
        if (e) showIpcEdgeInspector(e, nodeMap);
      });
    });

    // Auto-select hottest edge or anomalous node for immediate rich inspector display
    const hotEdge = edges.find((e) => e.has_inversion) || edges[0];
    if (hotEdge) showIpcEdgeInspector(hotEdge, nodeMap);

    // Populate summary edges table
    tbody.innerHTML = edges
      .map((e) => {
        const s = nodeMap[e.source]?.name || e.source;
        const t = nodeMap[e.target]?.name || e.target;
        const piBadge =
          e.kind === "PULSE_ASYNC"
            ? `<span class="badge badge-cyan">Async Pulse</span>`
            : e.has_inversion
            ? `<span class="badge badge-crimson">DISABLED</span>`
            : `<span class="badge badge-emerald">Inherited</span>`;
        return `
          <tr>
            <td class="mono">${esc(s)} → ${esc(t)}</td>
            <td class="mono">${esc(e.kind)}</td>
            <td class="num">${e.count}</td>
            <td class="num">${e.max_latency_us.toFixed(1)}</td>
            <td>${piBadge}</td>
          </tr>
        `;
      })
      .join("");
  }

  function showIpcNodeInspector(n) {
    $("#ipcInspector").innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <strong class="mono" style="font-size:15px">${esc(n.name)}</strong>
        <span class="badge ${n.has_anomaly ? "badge-crimson" : "badge-cyan"}">${esc(n.role)}</span>
      </div>
      <div class="mono" style="font-size:12px;color:#93a4bf;margin-bottom:8px">PID: ${n.pid} | Priority Range: ${esc(n.priority_range)} | CPU Share: ${n.avg_cpu_pct}%</div>
      ${n.resource_paths.length ? `<div style="margin-bottom:8px"><strong>Resource Paths:</strong> <code class="mono" style="color:#34d399">${esc(n.resource_paths.join(", "))}</code></div>` : ""}
      ${n.anomaly_note ? `<div class="incident-card" style="margin-top:8px"><strong>Anomaly:</strong> ${esc(n.anomaly_note)}</div>` : `<div style="color:#34d399;font-size:12px">No IPC anomalies observed on this process.</div>`}
    `;
  }

  function showIpcEdgeInspector(e, nodeMap) {
    const s = nodeMap[e.source]?.name || e.source;
    const t = nodeMap[e.target]?.name || e.target;
    $("#ipcInspector").innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <strong class="mono" style="font-size:14px">${esc(s)} → ${esc(t)}</strong>
        <span class="badge ${e.has_inversion ? "badge-crimson" : "badge-emerald"}">${esc(e.kind)}</span>
      </div>
      <div class="mono" style="font-size:12px;line-height:1.8">
        Messages: <strong>${e.count}</strong><br>
        Avg Latency: <strong>${e.avg_latency_us.toFixed(1)} us</strong><br>
        p99 Latency: <strong>${e.p99_latency_us.toFixed(1)} us</strong><br>
        Max Latency: <strong style="color:${e.has_inversion ? "#fb7185" : "#34d399"}">${e.max_latency_us.toFixed(1)} us</strong><br>
        Priority Inheritance: <strong>${e.kind === "PULSE_ASYNC" ? "N/A (Async Pulse)" : e.priority_inherited ? "ACTIVE (Kernel Boosted)" : "DISABLED (_NTO_CHF_FIXED_PRIORITY)"}</strong>
        ${e.rcvid_samples.length ? `<br>Sample rcvids: <span style="color:#93c5fd">${esc(e.rcvid_samples.join(", "))}</span>` : ""}
      </div>
    `;
  }

  /* ---------------- Buildfile & Secpol Auditor ---------------- */
  function renderAuditPanel() {
    const au = state.auditResult;
    if (!au) return;

    const ring = $("#auditGradeRing");
    ring.textContent = au.grade;
    ring.className = `grade-ring grade-${au.grade}`;
    $("#auditHeadline").textContent = `Security & Boot Score: ${au.overall_score}/100 (Grade ${au.grade})`;

    if (au.buildfile_summary) {
      const b = au.buildfile_summary;
      $("#buildfileMetaBar").textContent =
        `Arch: ${b.arch || "?"} | Kernel: ${b.kernel_binary || "?"} | secpolpush: ${b.has_secpolpush ? "line " + b.secpolpush_line : "MISSING"} | Services: ${b.services.length}`;
    }
    if (au.secpol_summary) {
      const s = au.secpol_summary;
      $("#secpolMetaBar").textContent =
        `Types: ${s.types.length} | Attach rules: ${s.attach_rules.length} | Least-privilege score: ${s.least_privilege_score}/100`;
    }

    const filtered = au.findings.filter((f) => state.findingFilter === "ALL" || f.severity === state.findingFilter);
    const listEl = $("#auditFindingsList");
    if (!filtered.length) {
      listEl.innerHTML = `<div class="incident-card healthy"><strong>All Checks Passed!</strong> Zero QNX 8.0 buildfile or secpol security findings in this view.</div>`;
    } else {
      listEl.innerHTML = filtered
        .map(
          (f) => `
          <div class="finding-item ${esc(f.severity)}">
            <div class="finding-head">
              <div class="finding-title">
                <span class="badge ${f.severity === "CRITICAL" ? "badge-crimson" : f.severity === "HIGH" ? "badge-amber" : "badge-cyan"}">${esc(f.severity)}</span>
                <span class="mono" style="margin:0 6px;color:#38bdf8">${esc(f.rule_id)}</span>
                ${esc(f.title)}
              </div>
              <div class="finding-meta">${esc(f.source)} : line ${f.line} • ${esc(f.standard_ref)}</div>
            </div>
            <div class="finding-desc">${esc(f.description)}</div>
            <div class="finding-rem"><strong>Fix:</strong> ${esc(f.remediation)}</div>
          </div>
        `
        )
        .join("");
    }

    // Colorized Unified Diff
    const diffEl = $("#hardenedDiffView");
    if (!au.hardened_diff || !au.hardened_diff.trim()) {
      diffEl.innerHTML = `<span style="color:#34d399">Policy already matches hardened least-privilege QNX 8.0 baseline (no diff).</span>`;
    } else {
      diffEl.innerHTML = au.hardened_diff
        .split("\n")
        .map((line) => {
          if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) {
            return `<span class="diff-hdr">${esc(line)}</span>`;
          }
          if (line.startsWith("+")) return `<span class="diff-add">${esc(line)}</span>`;
          if (line.startsWith("-")) return `<span class="diff-del">${esc(line)}</span>`;
          return `<span>${esc(line)}\n</span>`;
        })
        .join("");
    }
  }

  async function runLiveAudit() {
    const buildfile_text = $("#buildfileEditor").value;
    const secpol_text = $("#secpolEditor").value;
    try {
      state.auditResult = await apiJson("/api/audit/security-boot", {
        method: "POST",
        body: JSON.stringify({ buildfile_text, secpol_text }),
      });
      state.artifacts.buildfile_text = buildfile_text;
      state.artifacts.secpol_text = secpol_text;
      renderHeaderAndKpis();
      renderAuditPanel();
      showToast(`Live audit complete: Score ${state.auditResult.overall_score}/100 (Grade ${state.auditResult.grade})`);
    } catch (err) {
      showToast("Audit error: " + err.message);
    }
  }

  /* ---------------- Copilot ---------------- */
  function renderCopilotPanel() {
    const cp = state.copilot;
    const out = $("#copilotOutput");
    if (!cp) return;

    const modeBadge = $("#copilotModeBadge");
    modeBadge.textContent = cp.mode === "llm" ? `BYO-LLM (${cp.model})` : `Offline Deterministic (${cp.model})`;

    const safetyClass = cp.safety_assessment.startsWith("PASS")
      ? "safety-pass"
      : cp.safety_assessment.startsWith("CONDITIONAL")
      ? "safety-cond"
      : "safety-fail";

    const rcHtml = (cp.root_causes || [])
      .map(
        (r) => `
        <div class="finding-item ${esc(r.severity || "HIGH")}" style="margin-bottom:8px">
          <div class="finding-head">
            <div class="finding-title"><span class="badge ${r.severity === "CRITICAL" ? "badge-crimson" : "badge-amber"}">${esc(r.category)}</span> ${esc(r.title)}</div>
          </div>
          <div class="finding-desc">${esc(r.detail)}</div>
        </div>
      `
      )
      .join("");

    const planHtml = (cp.action_plan || [])
      .map(
        (a) => `
        <li style="margin-bottom:8px">
          <strong>Step ${a.step} (${esc(a.owner)}):</strong> ${esc(a.action)}
          <div style="color:#34d399;font-size:12px">Expected Impact: ${esc(a.impact)}</div>
        </li>
      `
      )
      .join("");

    const patchHtml = (cp.code_patches || [])
      .map(
        (p) => `
        <div class="card">
          <div class="card-header">
            <div>
              <h2>${esc(p.title)}</h2>
              <p class="card-desc mono">${esc(p.file)}</p>
            </div>
            <button class="btn btn-xs btn-outline copy-patch-btn" data-code="${esc(p.code)}" type="button">Copy Snippet</button>
          </div>
          <pre class="code-patch mono">${esc(p.code)}</pre>
        </div>
      `
      )
      .join("");

    out.innerHTML = `
      <div class="card">
        <h2>Executive Diagnosis</h2>
        <p style="margin:8px 0 0;font-size:13.5px">${esc(cp.summary)}</p>
        <div class="safety-banner ${safetyClass}">${esc(cp.safety_assessment)}</div>
      </div>
      ${rcHtml ? `<div class="card"><h2 style="margin-bottom:10px">Identified Root Causes</h2>${rcHtml}</div>` : ""}
      ${planHtml ? `<div class="card"><h2 style="margin-bottom:8px">Prioritized Remediation Plan</h2><ol style="margin:0;padding-left:20px">${planHtml}</ol></div>` : ""}
      ${patchHtml}
    `;

    out.querySelectorAll(".copy-patch-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        navigator.clipboard?.writeText(btn.dataset.code || "");
        showToast("Copied QNX 8.0 remediation patch to clipboard.");
      });
    });
  }

  async function askCopilot(questionText) {
    const q = questionText !== undefined ? questionText : $("#copilotQuestionInput").value;
    try {
      state.copilot = await apiJson("/api/copilot/diagnose", {
        method: "POST",
        body: JSON.stringify({
          question: q,
          trace_text: state.artifacts.trace_text,
          slog2_text: state.artifacts.slog2_text,
          buildfile_text: $("#buildfileEditor").value,
          secpol_text: $("#secpolEditor").value,
          llm_provider: $("#llmProvider").value,
          llm_model: $("#llmModel").value || null,
          llm_api_key: $("#llmApiKey").value || null,
          llm_base_url: $("#llmBaseUrl").value || null,
        }),
      });
      renderCopilotPanel();
      showToast("Diagnostic synthesis updated.");
    } catch (err) {
      showToast("Copilot error: " + err.message);
    }
  }

  /* ---------------- Custom Trace & Compliance Export ---------------- */
  async function analyzeCustomTrace() {
    const trace_text = $("#customTraceInput").value;
    const slog2_text = $("#customSlog2Input").value;
    if (!trace_text.trim()) {
      showToast("Paste QNX 8.0 traceprinter output first.");
      return;
    }
    try {
      state.traceAnalysis = await apiJson("/api/analyze/trace", {
        method: "POST",
        body: JSON.stringify({
          trace_text,
          slog2_text,
          scenario_id: "custom",
          scenario_name: "Custom QNX 8.0 Kernel Trace",
        }),
      });
      state.artifacts.trace_text = trace_text;
      state.artifacts.slog2_text = slog2_text;
      $("#scenarioDomain").textContent = "Custom Upload";
      $("#scenarioTagline").textContent = "Live parsed QNX 8.0 traceprinter stream";
      renderAll();
      activateTab("timeline");
      showToast(`Parsed ${state.traceAnalysis.total_events} QNX 8.0 trace events.`);
    } catch (err) {
      showToast("Parse error: " + err.message);
    }
  }

  async function fetchComplianceReport(download) {
    const standard = $("#reportStandard").value;
    const format = $("#reportFormat").value;
    try {
      const res = await fetch("/api/reports/compliance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          trace_text: state.artifacts.trace_text,
          slog2_text: state.artifacts.slog2_text,
          buildfile_text: $("#buildfileEditor").value,
          secpol_text: $("#secpolEditor").value,
          standard,
          format,
        }),
      });
      const text = await res.text();
      $("#reportPreview").textContent = text;
      if (download) {
        const ext = format === "json" ? "json" : "md";
        const blob = new Blob([text], { type: format === "json" ? "application/json" : "text/markdown" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `qnx-pulse-audit-${state.currentScenarioId || "custom"}-${standard.toLowerCase()}.${ext}`;
        a.click();
        URL.revokeObjectURL(url);
        showToast(`Downloaded ${a.download}`);
      }
    } catch (err) {
      showToast("Export error: " + err.message);
    }
  }

  /* ---------------- Event Bindings ---------------- */
  function bindEvents() {
    $$(".tab-btn").forEach((btn) =>
      btn.addEventListener("click", () => activateTab(btn.dataset.tab))
    );

    $("#scenarioSelect").addEventListener("change", (e) => loadScenario(e.target.value));

    $$(".zoom-btn").forEach((btn) =>
      btn.addEventListener("click", () => {
        state.ganttZoom = Number(btn.dataset.zoom) || 1;
        $$(".zoom-btn").forEach((b) => b.classList.toggle("active", b === btn));
        renderGanttChart();
      })
    );

    $$(".log-filter").forEach((btn) =>
      btn.addEventListener("click", () => {
        state.logFilter = btn.dataset.sev;
        $$(".log-filter").forEach((b) => b.classList.toggle("active", b === btn));
        renderSlog2Feed();
      })
    );

    $$(".finding-filter").forEach((btn) =>
      btn.addEventListener("click", () => {
        state.findingFilter = btn.dataset.sev;
        $$(".finding-filter").forEach((b) => b.classList.toggle("active", b === btn));
        renderAuditPanel();
      })
    );

    $("#runAuditBtn").addEventListener("click", runLiveAudit);
    $("#applyHardenedBtn").addEventListener("click", async () => {
      if (state.auditResult?.hardened_secpol) {
        $("#secpolEditor").value = state.auditResult.hardened_secpol;
        await runLiveAudit();
        showToast("Applied auto-hardened least-privilege QNX 8.0 secpol policy!");
      }
    });
    $("#copyHardenedBtn").addEventListener("click", () => {
      if (state.auditResult?.hardened_secpol) {
        navigator.clipboard?.writeText(state.auditResult.hardened_secpol);
        showToast("Copied hardened QNX 8.0 secpol policy.");
      }
    });

    $("#askCopilotBtn").addEventListener("click", () => askCopilot());
    $("#copilotQuestionInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") askCopilot();
    });
    $$(".prompt-chip").forEach((chip) =>
      chip.addEventListener("click", () => {
        $("#copilotQuestionInput").value = chip.dataset.q;
        askCopilot(chip.dataset.q);
      })
    );

    $("#analyzeCustomBtn").addEventListener("click", analyzeCustomTrace);
    $("#loadExampleIntoUploadBtn").addEventListener("click", () => {
      $("#customTraceInput").value = state.artifacts.trace_text || "";
      $("#customSlog2Input").value = state.artifacts.slog2_text || "";
      showToast("Loaded active scenario trace into editor.");
    });

    $("#previewReportBtn").addEventListener("click", () => fetchComplianceReport(false));
    $("#downloadReportBtn").addEventListener("click", () => fetchComplianceReport(true));
    $("#quickExportBtn").addEventListener("click", () => {
      activateTab("upload");
      fetchComplianceReport(false);
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
