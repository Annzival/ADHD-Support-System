/* 置顶小窗：只呈现当前前台执行上下文与打开主窗口的入口。
 * 按 V-05 结论，恢复用置顶小窗不承载上下文选择。
 */

"use strict";

const overlayState = { config: null, timer: null };

async function loadRuntimeConfig() {
  const response = await fetch("/runtime-config.json", { cache: "no-store" });
  overlayState.config = await response.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function renderOverlay() {
  const container = document.getElementById("overlay-content");
  const config = overlayState.config;
  if (!config || !config.endpoint || !config.coreRunning) {
    container.innerHTML = '<div class="muted">智能体核心未连接…</div>';
    return;
  }
  let snapshot;
  try {
    const response = await fetch(config.endpoint + "/api/state", {
      headers: { Authorization: `Bearer ${config.token}` },
    });
    snapshot = await response.json();
  } catch (error) {
    container.innerHTML = '<div class="muted">核心未连接，等待恢复…</div>';
    return;
  }
  const parts = [];
  const session = snapshot.activeSession;
  const surfaces = snapshot.pendingSurfaces || [];
  const recovery = snapshot.pendingRecovery;
  if (session) {
    const checkpoint = session.checkpoint;
    const checkpointText = checkpoint
      ? `检查点 ${new Date(checkpoint.dueAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}${checkpoint.state === "delivered" ? "（已到）" : ""}`
      : "";
    parts.push(`
      <div class="overlay-kind">正在执行</div>
      <div class="overlay-title">${escapeHtml(session.actionTitle)}</div>
      <div class="countdown">${session.workedMinutes}<span style="font-size:14px"> 分钟</span></div>
      ${checkpointText ? `<div class="muted">${checkpointText}</div>` : ""}`);
  } else if (surfaces.length > 0) {
    const surface = surfaces[surfaces.length - 1];
    parts.push(`
      <div class="overlay-kind">到计划开始时间了</div>
      <div class="overlay-title">${escapeHtml(surface.actionTitle)}</div>
      <div class="muted">计划开始 ${new Date(surface.plannedStartAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</div>`);
  } else if (recovery) {
    parts.push(`
      <div class="overlay-kind">恢复</div>
      <div class="overlay-title">有未收束的执行上下文</div>
      <div class="muted">请在主窗口中处理。</div>`);
  } else {
    parts.push('<div class="muted">当前没有需要关注的执行上下文。</div>');
  }
  container.innerHTML = parts.join("");
}

document.getElementById("overlay-open").addEventListener("click", async () => {
  await fetch("/host-command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind: "show_main" }),
  });
});

(async function start() {
  await loadRuntimeConfig().catch(() => {});
  await renderOverlay();
  overlayState.timer = setInterval(async () => {
    await loadRuntimeConfig().catch(() => {});
    await renderOverlay();
  }, 3000);
})();
