/* 执行支持 MVP 前端逻辑。
 * 状态唯一来源是智能体核心（GET /api/state）；本脚本只做呈现与操作转发。
 */

"use strict";

const $ = (selector) => document.querySelector(selector);
const state = {
  config: null,        // {endpoint, token, coreRunning}
  snapshot: null,      // /api/state
  ws: null,
  wsWanted: false,
  view: "home",
  reimportPlanId: null,
};

// ---------------------------------------------------------------------------
// 基础设施

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

async function api(path, options = {}) {
  const { config } = state;
  if (!config || !config.endpoint) throw new Error("核心未连接");
  const response = await fetch(config.endpoint + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${config.token}`,
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = payload.message ? `${payload.message}` : `请求失败（${response.status}）`;
    throw new Error(message);
  }
  return payload;
}

async function hostCommand(kind, title = "", body = "") {
  try {
    await fetch("/host-command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, title, body }),
    });
  } catch (error) {
    console.warn("host command failed", error);
  }
}

async function loadRuntimeConfig() {
  const response = await fetch("/runtime-config.json", { cache: "no-store" });
  const payload = await response.json();
  state.config = payload;
  return payload;
}

function formatTime(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function formatDateTime(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  return date.toLocaleString("zh-CN", {
    month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function minutesUntil(iso) {
  return Math.round((new Date(iso).getTime() - Date.now()) / 60000);
}

// ---------------------------------------------------------------------------
// WebSocket：单向事件流。断开后重取连接信息（核心可能已重启并更换端点）。

function connectWebSocket() {
  if (!state.config || !state.config.endpoint) return;
  const wsUrl = state.config.endpoint.replace(/^http/, "ws") + `/api/events?token=${encodeURIComponent(state.config.token)}`;
  const socket = new WebSocket(wsUrl);
  state.ws = socket;
  socket.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message.type === "state_changed") {
        refresh();
      } else if (message.type === "notify") {
        hostCommand("notify", message.title || "执行支持", message.body || "");
        if (message.salience !== "low") {
          hostCommand("show_overlay");
        }
        refresh();
      }
    } catch (error) {
      console.warn("bad ws message", error);
    }
  };
  socket.onclose = () => {
    if (!state.wsWanted) return;
    setTimeout(async () => {
      await loadRuntimeConfig().catch(() => {});
      connectWebSocket();
      refresh().catch(() => {});
    }, 1500);
  };
  socket.onerror = () => socket.close();
}

// ---------------------------------------------------------------------------
// 渲染

function show(element, visible) {
  element.classList.toggle("hidden", !visible);
}

function setView(name) {
  state.view = name;
  for (const view of document.querySelectorAll(".view")) show(view, false);
  show($(`#view-${name}`), true);
  for (const button of document.querySelectorAll(".nav-btn")) {
    button.classList.toggle("active", button.dataset.view === name);
  }
}

function render(snapshot) {
  renderConnection();
  renderRecovery(snapshot);
  renderPendingClosure(snapshot);
  renderActiveSession(snapshot);
  renderPendingSurfaces(snapshot);
  renderResumable(snapshot);
  renderQuietUnresolved(snapshot);
  renderEmptyState(snapshot);
  renderPlan(snapshot);
  renderSettings(snapshot);
}

function renderConnection() {
  const connected = state.config && state.config.coreRunning;
  show($("#connection-banner"), !connected);
}

function renderEmptyState(snapshot) {
  const hasSomething =
    snapshot.pendingRecovery ||
    snapshot.pendingClosure ||
    snapshot.activeSession ||
    (snapshot.pendingSurfaces || []).length > 0 ||
    (snapshot.resumable || []).length > 0 ||
    (snapshot.quietUnresolved || []).length > 0;
  show($("#home-empty"), !hasSomething);
}

function renderRecovery(snapshot) {
  const container = $("#recovery-banner");
  const recovery = snapshot.pendingRecovery;
  if (!recovery) { show(container, false); return; }
  show(container, true);
  const basis = recovery.basis || {};
  const options = [];
  if (basis.hasActiveSession) {
    options.push(`<button class="primary" data-recovery="continue_previous">回到上次执行</button>`);
  } else if (basis.hasResumePacket) {
    options.push(`<button class="primary" data-recovery="continue_previous">继续上次执行</button>`);
  }
  if ((basis.missedActionIds || []).length > 0) {
    options.push(`<button class="primary" data-recovery="handle_previous">处理上一项</button>`);
  }
  if (basis.nextScheduledActionId) {
    options.push(`<button data-recovery="follow_plan">按当前计划继续</button>`);
  }
  options.push(`<button data-recovery="defer">暂不决定</button>`);
  const missed = (basis.missedActionTitles || []).map(escapeHtml).join("、");
  const resumeTitle = basis.resumePacket ? escapeHtml(basis.resumePacket.actionTitle) : "";
  const parts = [];
  parts.push(`<strong>欢迎回来。</strong>上次离开时有未收束的执行上下文，恢复后由你决定接下来做什么。`);
  if (basis.hasActiveSession) parts.push(`<div class="muted">有一场执行会话仍在进行中。</div>`);
  if (basis.hasResumePacket) parts.push(`<div class="muted">“${resumeTitle}”曾暂停并保存了恢复包。</div>`);
  if (missed) parts.push(`<div class="muted">“${missed}”的开始时间已过，结果仍是未知——这不代表失败。</div>`);
  container.innerHTML = `
    <div class="banner card-attention">
      <div>${parts.join("")}</div>
      <div class="card-actions">${options.join("")}</div>
      <div class="muted" style="font-size:12px;margin-top:8px">“暂不决定”不会改变任何执行事实；下方会保留安静的被动入口。</div>
    </div>`;
  container.querySelectorAll("[data-recovery]").forEach((button) => {
    button.addEventListener("click", () => decideRecovery(recovery.id, button.dataset.recovery, basis));
  });
}

async function decideRecovery(recoveryId, choice, basis) {
  try {
    const result = await api(`/api/recovery/${recoveryId}/decide`, {
      method: "POST",
      body: JSON.stringify({ choice }),
    });
    if (choice === "continue_previous" && result.needsDuration && result.resumeActionId) {
      openDurationModal("继续上次执行", async (minutes) => {
        await api(`/api/actions/${result.resumeActionId}/resume`, {
          method: "POST",
          body: JSON.stringify({ remainingMinutes: minutes }),
        });
      });
    }
    await refresh();
  } catch (error) {
    alert(error.message);
  }
}

function renderPendingClosure(snapshot) {
  const container = $("#pending-closure");
  const action = snapshot.pendingClosure;
  if (!action) { show(container, false); return; }
  show(container, true);
  const kindText = action.pendingKind === "paused" ? "已暂停并保存恢复包" : "已报告完成";
  container.innerHTML = `
    <div class="banner banner-ok">
      <strong>${kindText}：</strong>${escapeHtml(action.title)}
      <div class="muted" style="font-size:13px">花 10 秒收尾，或者直接跳过——两者都是完整结束。</div>
      <div class="card-actions">
        <button class="primary" data-closure="fill">收尾确认</button>
        <button data-closure="skip">跳过收尾</button>
      </div>
    </div>`;
  container.querySelector('[data-closure="fill"]').addEventListener("click", () => openClosureModal(action, false));
  container.querySelector('[data-closure="skip"]').addEventListener("click", () => openClosureModal(action, true));
}

function renderActiveSession(snapshot) {
  const container = $("#active-session");
  const session = snapshot.activeSession;
  if (!session) { show(container, false); return; }
  show(container, true);
  const checkpoint = session.checkpoint;
  const checkpointState = checkpoint ? checkpoint.state : null;
  const checkpointDue = checkpoint ? formatTime(checkpoint.dueAt) : "";
  const buttons = [];
  if (checkpoint && checkpointState === "delivered") {
    buttons.push(`<button class="primary" data-checkpoint="${checkpoint.id}" data-kind="completed">已经完成</button>`);
    buttons.push(`<button data-checkpoint="${checkpoint.id}" data-kind="continue">继续并确认下一检查时间</button>`);
    buttons.push(`<button data-checkpoint="${checkpoint.id}" data-kind="pause">暂停并保存恢复包</button>`);
  } else {
    buttons.push(`<button class="primary" data-early="complete">标记完成</button>`);
    buttons.push(`<button data-early="pause">暂停并保存恢复包</button>`);
  }
  container.innerHTML = `
    <div class="card card-attention">
      <div><span class="chip">执行中</span>${checkpointState === "delivered" ? '<span class="chip">检查点已到</span>' : ""}</div>
      <h3 class="card-title">${escapeHtml(session.actionTitle)}</h3>
      <div class="card-sub">
        已进行约 ${session.workedMinutes} 分钟 · ${checkpoint ? `检查点 ${checkpointDue}（第 ${checkpoint.seq} 次）` : ""}
      </div>
      <div class="card-actions">${buttons.join("")}</div>
    </div>`;
  container.querySelectorAll("[data-checkpoint]").forEach((button) => {
    button.addEventListener("click", () => respondCheckpoint(button.dataset.checkpoint, button.dataset.kind, session));
  });
  container.querySelector('[data-early="complete"]')?.addEventListener("click", () => {
    const checkpointId = session.checkpoint ? session.checkpoint.id : null;
    if (checkpointId) {
      respondCheckpoint(checkpointId, "completed", session);
    }
  });
  container.querySelector('[data-early="pause"]').addEventListener("click", async () => {
    const note = prompt("给恢复包留一句话（可留空）", "") ?? "";
    try {
      await api(`/api/sessions/${session.id}/pause`, { method: "POST", body: JSON.stringify({ note }) });
      await refresh();
    } catch (error) { alert(error.message); }
  });
}

async function respondCheckpoint(checkpointId, kind, session) {
  try {
    if (kind === "continue") {
      openDurationModal("继续并确认下一检查时间", async (minutes) => {
        await api(`/api/checkpoints/${checkpointId}/respond`, {
          method: "POST",
          body: JSON.stringify({ response: "continue", nextCheckpointMinutes: minutes }),
        });
      });
      return;
    }
    if (kind === "pause") {
      const note = prompt("给恢复包留一句话（可留空）", "") ?? "";
      await api(`/api/checkpoints/${checkpointId}/respond`, {
        method: "POST", body: JSON.stringify({ response: "pause", note }),
      });
      await refresh();
      return;
    }
    await api(`/api/checkpoints/${checkpointId}/respond`, {
      method: "POST", body: JSON.stringify({ response: "completed" }),
    });
    await refresh();
  } catch (error) { alert(error.message); }
}

function renderPendingSurfaces(snapshot) {
  const container = $("#pending-surfaces");
  const surfaces = snapshot.pendingSurfaces || [];
  container.innerHTML = surfaces.map((surface) => {
    const quiet = surface.deliveryMode === "quiet_suppressed";
    const estimateNote = surface.estimatedMinutes
      ? `预计 ${surface.estimatedMinutes} 分钟`
      : "未确认预计时长";
    return `
      <div class="card card-attention">
        <div><span class="chip ${quiet ? "chip-quiet" : ""}">${quiet ? "安静时段 · 被动等待" : "到计划开始时间了"}</span></div>
        <h3 class="card-title">${escapeHtml(surface.actionTitle)}</h3>
        <div class="card-sub">计划开始 ${formatDateTime(surface.plannedStartAt)} · ${estimateNote}</div>
        <div class="card-actions">
          <button class="primary" data-surface="${surface.interventionId}" data-op="start_now">立即开始</button>
          <button data-surface="${surface.interventionId}" data-op="already_started">我已经开始了</button>
          <button data-surface="${surface.interventionId}" data-op="reschedule">改到具体时间</button>
          <button data-surface="${surface.interventionId}" data-op="skip_today">今天不做</button>
        </div>
      </div>`;
  }).join("");
  container.querySelectorAll("[data-surface]").forEach((button) => {
    button.addEventListener("click", () => respondSurface(button.dataset.surface, button.dataset.op));
  });
}

async function respondSurface(interventionId, op) {
  try {
    if (op === "start_now" || op === "already_started") {
      const send = (minutes) =>
        api(`/api/interventions/${interventionId}/respond`, {
          method: "POST",
          body: JSON.stringify({ response: op, estimatedMinutes: minutes }),
        }).then(() => {
          hostCommand("hide_overlay");
          return refresh();
        });
      const snapshotNow = state.snapshot;
      const surface = (snapshotNow.pendingSurfaces || []).find((item) => item.interventionId === interventionId);
      // 已有适用且经用户确认的预计时长时直接采用；否则先由用户确认本次时长。
      if (op === "start_now" && surface && surface.estimatedMinutes) {
        await send(surface.estimatedMinutes);
        return;
      }
      openDurationModal(
        op === "start_now" ? "立即开始" : "我已经开始",
        send,
        op === "already_started" ? "从现在起多久后检查一次？" : "这次预计做多久？",
      );
      return;
    }
    if (op === "reschedule") {
      openRescheduleModal(async (iso) => {
        await api(`/api/interventions/${interventionId}/respond`, {
          method: "POST",
          body: JSON.stringify({ response: "rescheduled", plannedStartAt: iso }),
        });
      });
      return;
    }
    await api(`/api/interventions/${interventionId}/respond`, {
      method: "POST", body: JSON.stringify({ response: op }),
    });
    hostCommand("hide_overlay");
    await refresh();
  } catch (error) { alert(error.message); }
}

function renderResumable(snapshot) {
  const container = $("#resumable");
  const items = snapshot.resumable || [];
  if (items.length === 0) { show(container, false); return; }
  show(container, true);
  container.innerHTML = `
    <h2>已暂停</h2>
    <div class="stack">${items.map((action) => `
      <div class="card">
        <h3 class="card-title">${escapeHtml(action.title)}</h3>
        <div class="card-sub">保存了恢复包，可以从上次的地方继续。</div>
        <div class="card-actions">
          <button class="primary" data-resume="${action.id}">继续上次执行</button>
          <button data-skip="${action.id}">今天不做</button>
        </div>
      </div>`).join("")}
    </div>`;
  container.querySelectorAll("[data-resume]").forEach((button) => {
    button.addEventListener("click", () => {
      openDurationModal("继续上次执行", async (minutes) => {
        await api(`/api/actions/${button.dataset.resume}/resume`, {
          method: "POST", body: JSON.stringify({ remainingMinutes: minutes }),
        });
        await refresh();
      }, "从现在起多久后检查一次？");
    });
  });
  container.querySelectorAll("[data-skip]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api(`/api/actions/${button.dataset.skip}/skip-today`, { method: "POST", body: "{}" });
      await refresh();
    });
  });
}

function renderQuietUnresolved(snapshot) {
  const container = $("#quiet-unresolved");
  const items = snapshot.quietUnresolved || [];
  if (items.length === 0) { show(container, false); return; }
  show(container, true);
  container.innerHTML = `
    <h2 class="section-gap">过往未决</h2>
    <p class="muted">这些安排的开始时间已过、没有明确结果。它们不是失败记录；你可以改期重试或明确放下。</p>
    <div class="stack">${items.map((action) => `
      <div class="card">
        <span class="chip chip-quiet">结果未知</span>
        <h3 class="card-title" style="margin-top:6px">${escapeHtml(action.title)}</h3>
        <div class="card-sub">原定 ${formatDateTime(action.plannedStartAt)}</div>
        <div class="card-actions">
          <button data-resched="${action.id}">改到具体时间</button>
          <button data-giveup="${action.id}">今天不做</button>
        </div>
      </div>`).join("")}
    </div>`;
  container.querySelectorAll("[data-resched]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = items.find((item) => item.id === button.dataset.resched);
      const intervention = action.latestIntervention;
      if (!intervention || intervention.state === "expired") {
        openRescheduleModal(async (iso) => {
          await api(`/api/actions/${action.id}/reschedule`, {
            method: "POST", body: JSON.stringify({ plannedStartAt: iso }),
          });
          await refresh();
        });
      }
    });
  });
  container.querySelectorAll("[data-giveup]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = items.find((item) => item.id === button.dataset.giveup);
      await api(`/api/actions/${action.id}/skip-today`, { method: "POST", body: "{}" });
      await refresh();
    });
  });
}

// ---------------------------------------------------------------------------
// 方案视图（导入 + 审阅工作区）

function renderPlan(snapshot) {
  const hasEnabled = snapshot.plan && snapshot.plan.status === "enabled";
  const planView = snapshot.plan && snapshot.plan.status === "draft" ? snapshot.plan : null;
  const draft = planView ? snapshot.draft : null;
  const showReview = !!planView && !!draft;
  show($("#plan-no-active"), !showReview && !hasEnabled);
  show($("#review-head-note"), showReview && hasEnabled);
  show($("#plan-review"), !!showReview);
  if (!showReview) return;
  const container = $("#plan-review");
  $("#review-source").textContent = findSource(snapshot);
  show($("#review-generating"), draft.status === "generating" || draft.generating);
  const failed = draft.status === "failed";
  show($("#review-failed"), failed);
  if (failed) $("#review-failed").textContent = `草案生成失败：${draft.error || "未知原因"}。你可以重试或更换模型配置。`;
  show($("#review-stale"), !!draft.stale);
  $("#review-status").textContent = draft.status === "ready" ? "草案已生成，请逐项确认" : "";

  const data = draft.draft;
  if (!data) { $("#review-draft").innerHTML = '<div class="muted">尚无草案内容。</div>'; return; }
  const candidates = (data.candidateActions || []).map((candidate) => renderCandidate(candidate)).join("") ||
    '<div class="muted">模型没有给出候选行动。你可以手动添加。</div>';
  $("#review-draft").innerHTML = `
    <div class="draft-section">
      <h4>原文明确的信息</h4>
      <ul>${(data.originalPoints || []).map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ul>
    </div>
    <div class="draft-section">
      <h4>Agent 派生内容（仅供参考）</h4>
      <ul>${(data.derivedPoints || []).map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ul>
    </div>
    <div class="draft-section">
      <h4>仍待你解决的缺口</h4>
      <ul>${(data.gaps || []).map((point) => `<li>${escapeHtml(point)}</li>`).join("") || "<li>无</li>"}</ul>
    </div>
    <div class="draft-section">
      <h4>候选下一步行动（至少逐项确认第一项及其计划开始时间）</h4>
      ${candidates}
      <button class="ghost" id="btn-add-candidate">+ 手动添加候选</button>
    </div>`;

  const ready = draft.status === "ready" && !draft.stale;
  const button = $("#btn-enable");
  button.disabled = !ready;
  button.onclick = () => openEnableModal(snapshot);
  $("#btn-regenerate").onclick = async () => {
    try {
      await api(`/api/plans/${planView.id}/draft/regenerate`, { method: "POST", body: "{}" });
      await refresh();
    } catch (error) { alert(error.message); }
  };
  const addBtn = $("#btn-add-candidate");
  if (addBtn) {
    addBtn.addEventListener("click", async () => {
      try {
        await api(`/api/plans/${planView.id}/draft`, {
          method: "PATCH",
          body: JSON.stringify({ candidateActions: [{ localId: `c${Date.now()}`, title: "新行动", origin: "derived" }] }),
        });
        await refresh();
      } catch (error) { alert(error.message); }
    });
  }
  bindCandidateControls(planView.id);
}

function findSource(snapshot) {
  return (snapshot.plan && snapshot.plan.sourceText) || state.sourceCache || "（原文未缓存，请重新导入）";
}

function renderCandidate(candidate) {
  const startValue = candidate.plannedStartAt ? toLocalInputValue(candidate.plannedStartAt) : "";
  return `
    <div class="draft-candidate ${candidate.userConfirmed ? "confirmed" : ""}" data-local-id="${escapeHtml(candidate.localId)}">
      <div>${candidate.userConfirmed ? '<span class="chip">已确认</span>' : ""}
        ${candidate.origin === "original" ? '<span class="chip chip-quiet">原文</span>' : '<span class="chip chip-quiet">派生</span>'}</div>
      <div class="row">
        <input class="grow" data-field="title" value="${escapeHtml(candidate.title)}" placeholder="行动标题">
        <input data-field="start" type="datetime-local" value="${startValue}">
        <input data-field="estimate" type="number" min="1" max="1440" style="max-width:110px"
               value="${candidate.estimatedMinutes ?? ""}" placeholder="预计(分)">
      </div>
      ${candidate.sourceRef ? `<div class="muted" style="font-size:12px;margin-top:6px">依据：${escapeHtml(candidate.sourceRef)}</div>` : ""}
      <div class="row">
        <button class="primary" data-act="confirm">确认这一项</button>
        ${candidate.userConfirmed ? '<button data-act="unconfirm">取消确认</button>' : ""}
        <button class="danger" data-act="remove">移除</button>
      </div>
    </div>`;
}

function bindCandidateControls(planId) {
  document.querySelectorAll(".draft-candidate").forEach((node) => {
    const localId = node.dataset.localId;
    const confirmButton = node.querySelector('[data-act="confirm"]');
    if (confirmButton) {
      confirmButton.addEventListener("click", async () => {
        const title = node.querySelector('[data-field="title"]').value.trim();
        const startRaw = node.querySelector('[data-field="start"]').value;
        const estimateRaw = node.querySelector('[data-field="estimate"]').value;
        if (!title) { alert("标题不能为空"); return; }
        if (!startRaw) { alert("请先选择计划开始时间"); return; }
        const payload = {
          title,
          plannedStartAt: new Date(startRaw).toISOString(),
          ...(estimateRaw ? { estimatedMinutes: Number(estimateRaw) } : {}),
        };
        try {
          await api(`/api/plans/${planId}/candidates/${localId}/confirm`, { method: "POST", body: JSON.stringify(payload) });
          await refresh();
        } catch (error) { alert(error.message); }
      });
    }
    node.querySelector('[data-act="unconfirm"]')?.addEventListener("click", async () => {
      try {
        await api(`/api/plans/${planId}/candidates/${localId}/unconfirm`, { method: "POST", body: "{}" });
        await refresh();
      } catch (error) { alert(error.message); }
    });
    node.querySelector('[data-act="remove"]')?.addEventListener("click", async () => {
      try {
        const draft = state.snapshot.draft;
        const candidates = (draft.draft?.candidateActions || []).filter((item) => item.localId !== localId);
        await api(`/api/plans/${planId}/draft`, {
          method: "PATCH", body: JSON.stringify({ candidateActions: candidates }),
        });
        await refresh();
      } catch (error) { alert(error.message); }
    });
  });
}

function toLocalInputValue(iso) {
  const date = new Date(iso);
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// ---------------------------------------------------------------------------
// 设置视图

function renderSettings(snapshot) {
  const settings = snapshot.settings || {};
  $("#set-grace").value = settings.start_grace_minutes ?? "10";
  $("#set-quiet-start").value = settings.quiet_hours_start ?? "22:00";
  $("#set-quiet-end").value = settings.quiet_hours_end ?? "08:00";
  $("#set-window-end").value = settings.execution_window_end ?? "23:00";
  const model = snapshot.model || {};
  $("#model-status").textContent = model.configured
    ? `已配置：${model.modelName}（${model.baseUrlHost}）`
    : "未配置。配置后才能生成方案导入草案；不影响执行闭环。";
}

// ---------------------------------------------------------------------------
// 模态框

function openModal(html) {
  $("#modal-body").innerHTML = html;
  show($("#modal-root"), true);
}

function closeModal() {
  show($("#modal-root"), false);
  $("#modal-body").innerHTML = "";
}

function openDurationModal(title, onSubmit, promptText = "这次预计做多久？") {
  openModal(`
    <h3>${escapeHtml(title)}</h3>
    <p class="muted">${escapeHtml(promptText)}</p>
    <div class="row">
      <input id="duration-input" type="number" min="1" max="1440" value="25" style="max-width:140px"> <span>分钟</span>
    </div>
    <div class="modal-actions">
      <button id="duration-cancel">取消</button>
      <button id="duration-ok" class="primary">确认</button>
    </div>`);
  $("#duration-cancel").addEventListener("click", closeModal);
  $("#duration-ok").addEventListener("click", async () => {
    const minutes = Number($("#duration-input").value);
    if (!Number.isFinite(minutes) || minutes < 1) { alert("请输入有效的分钟数"); return; }
    closeModal();
    await onSubmit(minutes);
  });
  $("#duration-input").focus();
}

function openRescheduleModal(onSubmit) {
  const defaultTime = new Date(Date.now() + 60 * 60 * 1000);
  openModal(`
    <h3>改到具体时间</h3>
    <div class="row"><input id="reschedule-input" type="datetime-local" value="${toLocalInputValue(defaultTime.toISOString())}"></div>
    <div class="modal-actions">
      <button id="reschedule-cancel">取消</button>
      <button id="reschedule-ok" class="primary">确认改期</button>
    </div>`);
  $("#reschedule-cancel").addEventListener("click", closeModal);
  $("#reschedule-ok").addEventListener("click", async () => {
    const raw = $("#reschedule-input").value;
    if (!raw) { alert("请选择新的时间"); return; }
    closeModal();
    await onSubmit(new Date(raw).toISOString());
  });
}

function openClosureModal(action, skipped) {
  if (skipped) {
    openModal(`
      <h3>跳过收尾</h3>
      <p class="muted">系统会依据你已有的明确操作保存最小执行证据并结束本次执行。跳过完全合法。</p>
      <div class="modal-actions">
        <button id="closure-cancel">返回</button>
        <button id="closure-skip" class="primary">确认跳过</button>
      </div>`);
    $("#closure-cancel").addEventListener("click", closeModal);
    $("#closure-skip").addEventListener("click", async () => {
      closeModal();
      try {
        await api(`/api/actions/${action.id}/closure`, { method: "POST", body: JSON.stringify({ skipped: true }) });
        await refresh();
      } catch (error) { alert(error.message); }
    });
    return;
  }
  openModal(`
    <h3>收尾确认</h3>
    <p class="muted">${escapeHtml(action.title)}</p>
    <div class="row" style="gap:10px;align-items:center">
      <label style="flex:1">实际用时（分钟，可留空）<input id="closure-actual" type="number" min="0" max="1440"></label>
      <label style="flex:2">一句话备注（可留空）<input id="closure-note" type="text"></label>
    </div>
    <div class="modal-actions">
      <button id="closure-cancel">取消</button>
      <button id="closure-ok" class="primary">保存并结束</button>
    </div>`);
  $("#closure-cancel").addEventListener("click", closeModal);
  $("#closure-ok").addEventListener("click", async () => {
    const actual = $("#closure-actual").value;
    const note = $("#closure-note").value;
    closeModal();
    try {
      await api(`/api/actions/${action.id}/closure`, {
        method: "POST",
        body: JSON.stringify({
          skipped: false,
          ...(actual ? { actualMinutes: Number(actual) } : {}),
          note,
        }),
      });
      await refresh();
    } catch (error) { alert(error.message); }
  });
}

function openEnableModal(snapshot) {
  const planView = snapshot.plan;
  const data = snapshot.draft.draft || {};
  const confirmed = (data.candidateActions || []).filter((item) => item.userConfirmed);
  if (confirmed.length === 0) { alert("请先逐项确认至少一项下一步行动及其计划开始时间"); return; }
  openModal(`
    <h3>启用方案——最终确认</h3>
    <p class="muted">这是变更确认界面。确认后智能体核心会原子地建立权威用户方案与执行安排。</p>
    <div class="confirm-list">
      <strong>即将创建的执行安排</strong>
      <ul>${confirmed.map((item) => `<li>${escapeHtml(item.title)} · ${formatDateTime(item.plannedStartAt)}${item.estimatedMinutes ? ` · 约 ${item.estimatedMinutes} 分钟` : ""}</li>`).join("")}</ul>
    </div>
    <div class="confirm-list">
      <strong>仍然保留的不确定信息</strong>
      <ul>${(data.gaps || []).map((gap) => `<li>${escapeHtml(gap)}</li>`).join("") || "<li>无关键缺口</li>"}</ul>
    </div>
    <div class="confirm-list">
      <strong>来源区别</strong>
      <ul>
        <li>原文明确：${(data.originalPoints || []).length} 条</li>
        <li>Agent 派生（已由你逐项确认）：${(data.derivedPoints || []).length} 条要点 / 候选 ${(data.candidateActions || []).filter((item) => item.origin === "derived").length} 项</li>
      </ul>
    </div>
    <div class="modal-actions">
      <button id="enable-cancel">返回修改</button>
      <button id="enable-ok" class="primary">确认启用</button>
    </div>`);
  $("#enable-cancel").addEventListener("click", closeModal);
  $("#enable-ok").addEventListener("click", async () => {
    closeModal();
    try {
      await api(`/api/plans/${planView.id}/enable`, { method: "POST", body: "{}" });
      setView("home");
      await refresh();
    } catch (error) { alert(error.message); }
  });
}

// ---------------------------------------------------------------------------
// 数据流

async function refresh() {
  try {
    const snapshot = await api("/api/state");
    state.snapshot = snapshot;
    render(snapshot);
  } catch (error) {
    if (state.config) {
      // 连接信息可能已过期（核心重启）：重取一次。
      await loadRuntimeConfig().catch(() => {});
      if (state.config.coreRunning) {
        connectWebSocket();
        return refresh();
      }
    }
    renderConnection();
    throw error;
  }
}

// ---------------------------------------------------------------------------
// 事件绑定与启动

function bindStaticEvents() {
  for (const button of document.querySelectorAll(".nav-btn")) {
    button.addEventListener("click", () => {
      const target = button.dataset.view;
      if (target === "plan" && state.snapshot && state.snapshot.plan && state.snapshot.plan.status === "enabled") {
        // 已启用方案时，“我的方案”落到设置页的导入入口。
        setView("settings");
        return;
      }
      setView(target);
    });
  }

  $("#btn-import").addEventListener("click", async () => {
    const source = $("#import-source").value;
    if (!source.trim()) { alert("请先粘贴方案原文"); return; }
    try {
      state.sourceCache = source;
      await api("/api/plans", { method: "POST", body: JSON.stringify({ sourceText: source }) });
      setView("plan");
      await refresh();
    } catch (error) { alert(error.message); }
  });

  $("#btn-reimport").addEventListener("click", async () => {
    const source = $("#reimport-source").value;
    if (!source.trim()) { alert("请先粘贴新方案原文"); return; }
    try {
      state.sourceCache = source;
      state.reimportPlanId = await api("/api/plans", { method: "POST", body: JSON.stringify({ sourceText: source }) });
      state.reimportMode = true;
      setView("plan");
      await refresh();
    } catch (error) { alert(error.message); }
  });

  $("#btn-save-settings").addEventListener("click", async () => {
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          start_grace_minutes: Number($("#set-grace").value),
          quiet_hours_start: $("#set-quiet-start").value || "22:00",
          quiet_hours_end: $("#set-quiet-end").value || "08:00",
          execution_window_end: $("#set-window-end").value || "23:00",
        }),
      });
      await refresh();
      alert("干预策略已保存");
    } catch (error) { alert(error.message); }
  });

  $("#btn-save-model").addEventListener("click", async () => {
    try {
      await api("/api/model-config", {
        method: "POST",
        body: JSON.stringify({
          baseUrl: $("#model-base-url").value.trim(),
          apiKey: $("#model-api-key").value.trim(),
          modelName: $("#model-name").value.trim(),
        }),
      });
      $("#model-api-key").value = "";
      await refresh();
      alert("模型配置已保存");
    } catch (error) { alert(error.message); }
  });

  document.querySelector(".modal-backdrop").addEventListener("click", closeModal);
}

async function start() {
  bindStaticEvents();
  await loadRuntimeConfig().catch(() => {});
  connectWebSocket();
  try {
    await refresh();
  } catch (error) {
    renderConnection();
  }
  // 核心重启后端点会变化：周期性轻量同步连接信息。
  setInterval(async () => {
    const previous = state.config;
    await loadRuntimeConfig().catch(() => {});
    if (previous && state.config && previous.endpoint !== state.config.endpoint) {
      if (state.ws) { state.wsWanted = false; state.ws.close(); state.wsWanted = true; }
      connectWebSocket();
      refresh().catch(() => {});
    }
  }, 5000);
  setInterval(() => refresh().catch(() => {}), 15000);
}

start();
