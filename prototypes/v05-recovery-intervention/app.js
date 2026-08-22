/*
 * PROTOTYPE — 非生产实现。
 * Three carrier mappings for the recovery-intervention question, switchable
 * through ?variant=A|B|C. State below is deliberately local and disposable.
 */

const variantOrder = ["A", "B", "C"];

const variants = {
  A: {
    name: "主窗口主导",
    short: "通知只负责发现，主窗口并排解释上次与当前。",
  },
  B: {
    name: "置顶小窗主导",
    short: "小窗先给有限决定，主窗口留作完整上下文。",
  },
  C: {
    name: "系统通知主导",
    short: "通知直接选择入口，主窗口展示所选路线。",
  },
};

const actionMeta = {
  "continue-last": {
    label: "继续上次执行",
    help: "回到已有执行会话或恢复包；当前计划不会被删除。",
  },
  "handle-previous": {
    label: "处理上一项",
    help: "打开没有开始证据的上一项核对；这不是“继续上次执行”。",
  },
  "continue-current": {
    label: "按当前计划继续",
    help: "选择当前适用行动；上一项结果继续保持未知。",
  },
  defer: {
    label: "暂不决定",
    help: "结束这次主动呈现，并在主窗口保留被动入口。",
  },
};

function baseRecovery(overrides = {}) {
  return {
    trigger: "设备或智能体核心恢复后，重新依据当前时间与执行上下文生成",
    expiredInterventions: 1,
    oldInterventionsReplayed: false,
    activePresentation: true,
    passiveEntryVisible: false,
    passiveEntryOpened: false,
    decision: "未决定",
    degradation: "尚未发生",
    ...overrides,
  };
}

function baseCurrentPlan(overrides = {}) {
  return {
    label: "当前计划",
    headline: "10:30 阅读两份岗位 JD",
    status: "现在适用",
    when: "10:30–11:15",
    facts: ["这是当前可进入的下一步行动", "选择它不会改写上一项的结果"],
    ...overrides,
  };
}

function baseState(id, data) {
  return {
    prototypeOnly: true,
    scenario: id,
    scenarioLabel: data.label,
    recovery: data.recovery,
    pastContext: data.pastContext,
    currentPlan: data.currentPlan,
    availableActions: data.availableActions,
    presentation: {
      mainWindowOpen: data.mainWindowOpen,
      overlayVisible: data.overlayVisible,
      mainFocus: data.mainFocus,
    },
    actionHistory: data.actionHistory || [],
    outcome: data.outcome || "尚未进行操作。",
  };
}

const scenarioDefinitions = {
  "active-session": {
    label: "1. 活动执行会话 + 当前计划推进",
    description: "已有活动执行会话；当前计划已进入下一项。应出现“继续上次执行”，不应出现“处理上一项”。",
    create() {
      return baseState("active-session", {
        recovery: baseRecovery({ expiredInterventions: 2 }),
        pastContext: {
          type: "活动执行会话",
          headline: "09:00 整理 Python 课程大纲",
          status: "会话仍活动，等待重新进入",
          when: "09:07 已明确开始 · 检查点 10:15",
          facts: ["已有明确开始证据", "会上次执行上下文：已完成前两节目录", "下一步：补齐第三节标题"],
          result: "未关闭；不是失败或放弃",
        },
        currentPlan: baseCurrentPlan(),
        availableActions: ["continue-last", "continue-current", "defer"],
        mainWindowOpen: false,
        overlayVisible: true,
        mainFocus: "恢复入口尚未打开",
      });
    },
  },
  "resume-packet": {
    label: "2. 恢复包 + 当前计划推进",
    description: "上次会话已暂停并保存恢复包；当前计划已推进。应清楚显示恢复包不是当前计划本身。",
    create() {
      return baseState("resume-packet", {
        recovery: baseRecovery({ expiredInterventions: 1 }),
        pastContext: {
          type: "恢复包",
          headline: "09:00 整理 Python 课程大纲",
          status: "暂停时保存，等待用户选择",
          when: "09:28 保存恢复包",
          facts: ["已整理到第 3 节", "重新进入时先写目录，再检查示例链接", "没有推断后续是否完成"],
          result: "已暂停；不是当前计划或失败记录",
        },
        currentPlan: baseCurrentPlan({ headline: "10:30 复核岗位 JD 的硬性条件" }),
        availableActions: ["continue-last", "continue-current", "defer"],
        mainWindowOpen: false,
        overlayVisible: true,
        mainFocus: "恢复入口尚未打开",
      });
    },
  },
  "missed-start": {
    label: "3. 只错过计划开始（没有开始证据）",
    description: "没有活动执行会话或恢复包。上一项只能被处理 / 核对，不能被表述为“继续上次执行”。",
    create() {
      return baseState("missed-start", {
        recovery: baseRecovery({ expiredInterventions: 1 }),
        pastContext: {
          type: "上一项的未确认执行状态",
          headline: "09:00 整理 Python 课程大纲",
          status: "没有开始证据",
          when: "计划窗口已结束",
          facts: ["开始干预已失效且不补发", "沉默只表示系统不知道结果", "需要用户决定是否处理这一项"],
          result: "未知；不是未开始、拒绝、失败或放弃",
        },
        currentPlan: baseCurrentPlan(),
        availableActions: ["handle-previous", "continue-current", "defer"],
        mainWindowOpen: false,
        overlayVisible: true,
        mainFocus: "恢复入口尚未打开",
      });
    },
  },
  "merged-expired": {
    label: "4. 多个失效干预合并",
    description: "三个旧干预已经失效；本页只显示一个当前恢复入口，不把它们排队补发。",
    create() {
      return baseState("merged-expired", {
        recovery: baseRecovery({
          expiredInterventions: 3,
          trigger: "恢复后发现 3 个旧干预已错过有效时机；合并成一次当前恢复入口",
        }),
        pastContext: {
          type: "最近一项的未确认执行状态",
          headline: "昨天 16:00 汇总调研笔记",
          status: "没有开始证据",
          when: "最近一个相关计划窗口已结束",
          facts: ["更早的两个旧干预只保留为失效记录", "不逐条显示、不补发、不要求依次处理", "当前只核对最近需要辨认的上一项"],
          result: "未知；旧干预失效不等于行动被放弃",
        },
        currentPlan: baseCurrentPlan({ headline: "现在：列出下次投递需要的材料" }),
        availableActions: ["handle-previous", "continue-current", "defer"],
        mainWindowOpen: false,
        overlayVisible: true,
        mainFocus: "合并恢复入口尚未打开",
      });
    },
  },
  "after-current-plan": {
    label: "5. 已选择“按当前计划继续”后的状态",
    description: "验证选择当前计划后，上一项仍明确标为未知，而不是被静默放弃。",
    create() {
      return baseState("after-current-plan", {
        recovery: baseRecovery({
          activePresentation: false,
          decision: "已按当前计划继续",
          degradation: "恢复入口已处理，不保留主动呈现",
        }),
        pastContext: {
          type: "上一项的未确认执行状态",
          headline: "09:00 整理 Python 课程大纲",
          status: "结果仍未知",
          when: "计划窗口已结束",
          facts: ["用户选择的是当前计划，不是对上一项作出结论", "不会生成“未开始”或“已放弃”的暗示"],
          result: "未知；保留到适当的被动核对路径",
        },
        currentPlan: baseCurrentPlan({
          status: "已选为当前执行入口",
          facts: ["用户选择按当前计划继续", "当前行动已成为主窗口焦点"],
        }),
        availableActions: [],
        mainWindowOpen: true,
        overlayVisible: false,
        mainFocus: "当前计划",
        actionHistory: ["初始场景：已选择“按当前计划继续”"],
        outcome: "当前计划被选为入口；上一项仍是未知。",
      });
    },
  },
  "after-defer": {
    label: "6. 已选择“暂不决定”后寻找被动入口",
    description: "主动呈现已经结束。应能在主窗口发现一个安静的恢复入口，而不是再收到旧干预。",
    create() {
      return baseState("after-defer", {
        recovery: baseRecovery({
          activePresentation: false,
          passiveEntryVisible: true,
          decision: "暂不决定",
          degradation: "主动呈现已结束；主窗口保留静态被动入口",
        }),
        pastContext: {
          type: "恢复包",
          headline: "09:00 整理 Python 课程大纲",
          status: "暂停时保存，尚未重新进入",
          when: "09:28 保存恢复包",
          facts: ["仍可在被动入口选择继续上次", "没有新的弹出、闪烁或红点"],
          result: "暂停；没有被放弃",
        },
        currentPlan: baseCurrentPlan(),
        availableActions: ["continue-last", "continue-current"],
        mainWindowOpen: true,
        overlayVisible: false,
        mainFocus: "主窗口首页",
        actionHistory: ["初始场景：用户已选择“暂不决定”"],
        outcome: "等待用户从主窗口的被动入口重新进入。",
      });
    },
  },
};

function queryValue(name, fallback) {
  const value = new URLSearchParams(window.location.search).get(name);
  return value || fallback;
}

function validVariant(value) {
  return variants[value] ? value : "A";
}

function validScenario(value) {
  return scenarioDefinitions[value] ? value : "active-session";
}

let app = {
  variant: validVariant(queryValue("variant", "A")),
  scenario: validScenario(queryValue("scenario", "active-session")),
  state: null,
  observations: [],
  comparisons: [],
};

app.state = scenarioDefinitions[app.scenario].create();

function updateUrl() {
  const url = new URL(window.location.href);
  url.searchParams.set("variant", app.variant);
  url.searchParams.set("scenario", app.scenario);
  history.replaceState({}, "", url);
}

function selectScenario(id) {
  app.scenario = validScenario(id);
  app.state = scenarioDefinitions[app.scenario].create();
  clearAllObservationInputs();
  updateUrl();
  render();
}

function selectVariant(id) {
  app.variant = validVariant(id);
  clearCombinationObservationInputs();
  updateUrl();
  render();
}

function nextVariant(direction) {
  const currentIndex = variantOrder.indexOf(app.variant);
  const delta = direction === "previous" ? -1 : 1;
  const nextIndex = (currentIndex + delta + variantOrder.length) % variantOrder.length;
  selectVariant(variantOrder[nextIndex]);
}

function actionLabel(id) {
  return actionMeta[id]?.label || id;
}

function canChoose(id) {
  return app.state.availableActions.includes(id);
}

function actionButtons(options = {}) {
  const { className = "", includeDefer = true, actionIds = app.state.availableActions } = options;
  const ids = actionIds.filter((id) => includeDefer || id !== "defer");
  if (ids.length === 0) {
    return '<div class="empty-action">这个模拟状态不再等待恢复操作。请切换场景，或查看右侧状态确认上一项仍未被改写。</div>';
  }
  return `<div class="action-group ${className}">${ids
    .map((id) => {
      const danger = id === "defer" ? " danger-button" : "";
      return `<button type="button" class="${danger.trim()}" data-action="${id}" title="${actionMeta[id].help}">${actionMeta[id].label}</button>`;
    })
    .join("")}</div>`;
}

function contextCard(context, tone) {
  const pillClass = tone === "current" ? "current" : tone === "past" ? "past" : "unknown";
  const title = tone === "current" ? "当前计划" : "上次执行上下文";
  return `
    <section class="context-card ${tone === "current" ? "current-context" : ""}">
      <span class="state-pill ${pillClass}">${title}</span>
      <h3>${context.headline}</h3>
      <p><strong>${context.type}</strong> · ${context.status}</p>
      <dl>
        <dt>时间</dt><dd>${context.when}</dd>
        ${context.facts.map((fact) => `<dt>事实</dt><dd>${fact}</dd>`).join("")}
        <dt>结果</dt><dd>${context.result || "当前适用"}</dd>
      </dl>
    </section>`;
}

function activeNoticeBody(variant) {
  const expiredText = app.state.recovery.expiredInterventions > 1
    ? `${app.state.recovery.expiredInterventions} 个旧干预已合并为一个当前入口。`
    : "一个旧干预已失效；现在生成一个当前恢复入口。";
  const lead = variant === "C"
    ? "恢复后发现上次与当前计划可能需要区分。先选择你要进入的路线。"
    : "恢复后有一个需要辨认的执行上下文。";
  return `${lead} ${expiredText}`;
}

function passiveEntry() {
  const state = app.state;
  if (!state.recovery.passiveEntryVisible) return "";
  if (state.recovery.passiveEntryOpened) {
    return `
      <section class="passive-entry">
        <h4>恢复入口已打开（被动）</h4>
        <p>这是用户主动打开的原有操作，不是新的干预或补发通知。</p>
        ${actionButtons({ includeDefer: false })}
      </section>`;
  }
  return `
    <section class="passive-entry">
      <h4>恢复入口（被动）</h4>
      <p>上次执行上下文仍在；主动呈现已经结束。这里不会闪烁、弹出或显示红点。</p>
      <button type="button" data-action="open-passive">查看恢复选项</button>
    </section>`;
}

function outcomePanel() {
  return `
    <section class="mapping-panel">
      <h3>本次模拟结果</h3>
      <p class="quiet-copy">${app.state.outcome}</p>
      <p class="action-caption">${app.state.actionHistory.length ? app.state.actionHistory[app.state.actionHistory.length - 1] : "还没有用户操作。"}</p>
    </section>`;
}

function carrierMapping() {
  const state = app.state;
  const actions = state.availableActions.map(actionLabel).join("、") || "无（已完成这次选择）";
  const trigger = state.recovery.trigger;
  const passive = state.recovery.passiveEntryVisible
    ? "主窗口首页中的静态“恢复入口”"
    : "无；用户已作出本次选择";

  if (!state.recovery.activePresentation) {
    return {
      trigger,
      carrier: "无主动载体（已结束 / 已隐藏）",
      actions,
      deepLink: state.presentation.mainFocus,
      degradation: state.recovery.degradation,
      passive,
    };
  }

  if (app.variant === "A") {
    return {
      trigger,
      carrier: "系统通知：一个“查看恢复选项”入口；主窗口承担选择",
      actions,
      deepLink: "主窗口 → 恢复入口 → 并排的上次 / 当前上下文",
      degradation: "通知关闭或未点：不抢焦点；主窗口保留被动入口；旧干预不补发",
      passive,
    };
  }
  if (app.variant === "B") {
    return {
      trigger,
      carrier: "置顶小窗：有限选择面板；通知只提示可打开",
      actions,
      deepLink: "置顶小窗 → 对应主窗口上下文（需要细节时）",
      degradation: "关闭小窗只隐藏呈现，不改变执行状态；主窗口保留被动入口",
      passive,
    };
  }
  return {
    trigger,
    carrier: "系统通知：直接选择进入上次、上一项或当前计划的路线",
    actions,
    deepLink: "通知操作 → 主窗口的对应路线；小窗仅显示状态",
    degradation: "通知消失后不重发；主窗口保留被动入口。原生动作数量与焦点需 Windows 实测",
    passive,
  };
}

function mappingPanel() {
  const map = carrierMapping();
  const entries = [
    ["触发状态", map.trigger],
    ["主动 / 被动载体", `${map.carrier}\n被动：${map.passive}`],
    ["可用操作", map.actions],
    ["主窗口上下文 / 深链", map.deepLink],
    ["失效或降级", map.degradation],
  ];
  return `
    <section class="mapping-panel">
      <h3>当前方案的载体映射（模拟）</h3>
      <dl class="mapping-grid">
        ${entries.map(([key, value]) => `<div><dt>${key}</dt><dd>${value}</dd></div>`).join("")}
      </dl>
    </section>`;
}

function notificationMock({ variant, actionMode = "launcher" }) {
  const state = app.state;
  if (!state.recovery.activePresentation) {
    return `
      <section class="notice-mock muted">
        <span class="surface-tag">模拟系统通知</span>
        <h3>没有新的主动呈现</h3>
        <p>${state.recovery.degradation}</p>
      </section>`;
  }
  let actions = "";
  if (actionMode === "launcher") {
    actions = '<div class="notice-actions"><button type="button" data-action="open-main">查看恢复选项</button></div>';
  } else if (actionMode === "overlay") {
    actions = '<div class="notice-actions"><button type="button" data-action="open-overlay">打开恢复小窗</button></div>';
  } else {
    actions = `<div class="notice-actions">${actionButtons({ className: "notification-actions" })}</div>`;
  }
  return `
    <section class="notice-mock ${variant === "C" ? "notification-led-notice" : ""}">
      <span class="surface-tag">模拟系统通知</span>
      <h3>恢复后有一个执行入口</h3>
      <p>${activeNoticeBody(variant)}</p>
      ${actions}
      <p class="action-caption">模拟而非原生通知；不证明真实 Windows 动作数量、焦点或呈现顺序。</p>
    </section>`;
}

function mainLedVariant() {
  const state = app.state;
  const mainReady = state.presentation.mainWindowOpen || state.recovery.passiveEntryVisible;
  const recoveryContent = mainReady
    ? `
      <div class="main-led-columns">
        ${contextCard(state.pastContext, "past")}
        ${contextCard(state.currentPlan, "current")}
      </div>
      <section class="main-led-decision">
        <h4>先选择要进入的上下文</h4>
        ${state.recovery.activePresentation || state.recovery.passiveEntryOpened ? actionButtons() : '<div class="empty-action">当前没有等待处理的主动恢复干预。</div>'}
        <p class="action-caption">“处理上一项”只会在没有开始证据时出现；“继续上次执行”只会在有活动执行会话或恢复包时出现。</p>
      </section>
      ${passiveEntry()}
      ${outcomePanel()}`
    : `
      <section class="empty-action">
        此方案刻意不在通知或置顶小窗里摆放决定。点击左侧通知后，主窗口才展示上次与当前的并排对照。
      </section>
      ${contextCard(state.currentPlan, "current")}`;
  return `
    <article class="variant-frame">
      <header class="variant-heading">
        <div>
          <p class="eyebrow">方案 A</p>
          <h2>主窗口主导</h2>
          <p>通知负责发现；主窗口先把两条时间线并排，再给操作。</p>
        </div>
        <span class="surface-tag">通知 → 主窗口</span>
      </header>
      <div class="main-led-stage">
        <aside class="main-led-side">
          ${notificationMock({ variant: "A", actionMode: "launcher" })}
          <section class="overlay-slot">
            <strong>模拟置顶小窗</strong>
            这里只显示“恢复选项在主窗口”。它不抢焦点，也不承载恢复决定。
          </section>
        </aside>
        <section class="surface main-window main-led-window">
          <div class="surface-bar"><span>执行智能体 — 主窗口</span><span class="surface-tag">模拟主窗口</span></div>
          <div class="window-content">
            <div class="main-led-title">
              <div><h3>恢复入口</h3><p>把上次执行上下文与当前计划固定在同一可读区域。</p></div>
              <span class="state-pill ${mainReady ? "current" : "unknown"}">${mainReady ? "已打开" : "等待通知跳转"}</span>
            </div>
            ${recoveryContent}
            ${mappingPanel()}
          </div>
        </section>
      </div>
    </article>`;
}

function overlayLedVariant() {
  const state = app.state;
  const overlay = state.recovery.activePresentation && state.presentation.overlayVisible
    ? `
      <section class="surface overlay-led-panel">
        <div class="surface-bar"><span>恢复选择</span><span class="surface-tag">模拟置顶小窗</span></div>
        <div class="overlay-content">
          <p>只放当前两条上下文和有限操作。完整计划、编辑和核对细节仍在主窗口。</p>
          <div class="overlay-contexts">
            ${contextCard(state.pastContext, "past")}
            ${contextCard(state.currentPlan, "current")}
          </div>
          <section class="overlay-decision">
            <div class="overlay-decision-row">
              <strong>选择一个工作入口</strong>
              <button class="secondary-button small-close" type="button" data-action="close-overlay">关闭小窗（仅隐藏）</button>
            </div>
            ${actionButtons()}
            <p class="action-caption">关闭不等于“暂不决定”：前者只隐藏小窗，后者明确结束主动呈现；二者都不改变上一项事实。</p>
          </section>
        </div>
      </section>`
    : `
      <section class="overlay-slot">
        <strong>模拟置顶小窗未显示</strong>
        ${state.recovery.passiveEntryVisible ? "主动呈现结束；请从主窗口的静态恢复入口重新进入。" : "这次恢复选择已处理。"}
      </section>`;
  return `
    <article class="variant-frame">
      <header class="variant-heading">
        <div>
          <p class="eyebrow">方案 B</p>
          <h2>置顶小窗主导</h2>
          <p>恢复时先给小而明确的选择；主窗口在背后保留完整计划和被动入口。</p>
        </div>
        <span class="surface-tag">通知 → 小窗 → 主窗口</span>
      </header>
      <div class="desktop-stage overlay-led-stage">
        <section class="surface main-window overlay-led-main">
          <div class="surface-bar"><span>执行智能体 — 主窗口（背景）</span><span class="surface-tag">模拟主窗口</span></div>
          <div class="window-content background-window-content">
            <aside class="ghost-list"><strong>当前计划</strong><p>09:00 整理课程大纲</p><p>10:30 阅读岗位 JD</p><p>11:30 整理投递材料</p></aside>
            <section class="background-current">
              <h3>主窗口上下文</h3>
              ${contextCard(state.currentPlan, "current")}
              ${passiveEntry()}
              ${outcomePanel()}
              ${mappingPanel()}
            </section>
          </div>
        </section>
        <div class="overlay-led-notice">${notificationMock({ variant: "B", actionMode: "overlay" })}</div>
        ${overlay}
      </div>
    </article>`;
}

function notificationLedVariant() {
  const state = app.state;
  const routeAction = (id, title, body, tone) => `
    <div class="route-row ${tone}">
      <span class="route-number">${id}</span>
      <div><h4>${title}</h4><p>${body}</p></div>
      <button class="secondary-button" type="button" data-action="open-main">查看</button>
    </div>`;
  return `
    <article class="variant-frame">
      <header class="variant-heading">
        <div>
          <p class="eyebrow">方案 C</p>
          <h2>系统通知主导</h2>
          <p>通知直接让用户选路线；主窗口把对应路线解释清楚，小窗只报告状态。</p>
        </div>
        <span class="surface-tag">通知动作 → 对应路线</span>
      </header>
      <div class="notification-led-stage">
        ${notificationMock({ variant: "C", actionMode: "actions" })}
        <section class="surface main-window notification-led-main">
          <div class="surface-bar"><span>执行智能体 — 主窗口</span><span class="surface-tag">模拟主窗口</span></div>
          <div class="window-content">
            <div class="route-header"><h3>执行入口路线</h3><p>通知动作决定主窗口的初始焦点。这里不补发旧干预，也不把上一项隐藏。</p></div>
            <div class="route-list">
              ${routeAction("1", "上次执行上下文", `${state.pastContext.type}：${state.pastContext.status}`, "is-past")}
              ${routeAction("2", "当前计划", `${state.currentPlan.headline}：${state.currentPlan.status}`, "is-current")}
            </div>
            ${state.presentation.mainWindowOpen ? `<div class="main-led-columns"><div>${contextCard(state.pastContext, "past")}</div><div>${contextCard(state.currentPlan, "current")}</div></div>` : '<p class="quiet-copy">点击“查看”或通知操作后，此处显示更完整的上下文。</p>'}
            ${passiveEntry()}
            ${outcomePanel()}
            ${mappingPanel()}
          </div>
        </section>
        <aside class="surface notification-led-overlay">
          <span class="surface-tag">模拟置顶小窗</span>
          <h3>仅状态</h3>
          <p>不承载恢复选择，不自动抢走输入焦点。</p>
          <p><strong>当前：</strong>${state.presentation.mainFocus}</p>
          <p><strong>主动呈现：</strong>${state.recovery.activePresentation ? "通知" : "已结束"}</p>
        </aside>
      </div>
    </article>`;
}

function renderPrototype() {
  if (app.variant === "A") return mainLedVariant();
  if (app.variant === "B") return overlayLedVariant();
  return notificationLedVariant();
}

function debugState() {
  return {
    prototype: "V-05 throwaway UI only — not formal product state",
    selectedVariant: `${app.variant} — ${variants[app.variant].name}`,
    scenario: app.state.scenarioLabel,
    recoveryIntervention: app.state.recovery,
    pastExecutionContext: app.state.pastContext,
    currentPlanContext: app.state.currentPlan,
    availablePrototypeActions: app.state.availableActions.map(actionLabel),
    presentation: app.state.presentation,
    actionHistory: app.state.actionHistory,
    outcome: app.state.outcome,
    recordedCombinationObservations: app.observations,
    recordedScenarioComparisons: app.comparisons,
  };
}

function observationMarkdown() {
  const combinationRecords = app.observations.length
    ? app.observations
    .map((record, index) => {
      return [
        `### 单项观察 ${index + 1} — ${record.variant} × ${record.scenario}`,
        `- 上下文辨识：${record.clarity}`,
        `- 压力：${record.pressure}`,
        `- 抢焦点风险：${record.focusRisk}`,
        `- 被动入口：${record.discovery}`,
        `- 错误暗示：${record.implication || "无"}`,
        `- 补充：${record.note || "无"}`,
      ].join("\n");
    })
    .join("\n\n")
    : "尚未记录单项观察。";
  const comparisonRecords = app.comparisons.length
    ? app.comparisons
    .map((record, index) => {
      return [
        `### 跨方案比较 ${index + 1} — ${record.scenario}`,
        `- 偏好：${record.preference}`,
        `- 理由：${record.note || "无"}`,
      ].join("\n");
    })
    .join("\n\n")
    : "尚未记录跨方案比较。";
  return `## 当前组合观察\n\n${combinationRecords}\n\n## 同一场景下的跨方案比较\n\n${comparisonRecords}`;
}

function refreshEvidence() {
  document.querySelector("#state-output").textContent = JSON.stringify(debugState(), null, 2);
  document.querySelector("#observation-output").textContent = observationMarkdown();
  document.querySelector("#observation-target").textContent = `本条记录绑定：${app.variant} — ${variants[app.variant].name} × ${app.state.scenarioLabel}`;
  document.querySelector("#comparison-target").textContent = `本条比较绑定：${app.state.scenarioLabel} 下的方案 A / B / C`;
  const recordCount = app.observations.length;
  const comparisonCount = app.comparisons.length;
  document.querySelector("#observation-status").textContent = recordCount || comparisonCount
    ? `已记录 ${recordCount} 条当前组合观察、${comparisonCount} 条跨方案比较；可复制下方完整摘要回传。`
    : "尚未记录观察。";
}

function clearCombinationObservationInputs() {
  ["clarity-select", "pressure-select", "focus-select", "discovery-select"].forEach((id) => {
    const field = document.querySelector(`#${id}`);
    if (field) field.value = "未体验";
  });
  ["implication-note", "freeform-note"].forEach((id) => {
    const field = document.querySelector(`#${id}`);
    if (field) field.value = "";
  });
}

function clearComparisonInputs() {
  const preference = document.querySelector("#preferred-variant-select");
  const note = document.querySelector("#comparison-note");
  if (preference) preference.value = "未形成偏好";
  if (note) note.value = "";
}

function clearAllObservationInputs() {
  clearCombinationObservationInputs();
  clearComparisonInputs();
}

function inputValue(id) {
  return document.querySelector(`#${id}`).value.trim();
}

function recordObservation() {
  app.observations.push({
    variant: `${app.variant} — ${variants[app.variant].name}`,
    scenario: app.state.scenarioLabel,
    clarity: inputValue("clarity-select"),
    pressure: inputValue("pressure-select"),
    focusRisk: inputValue("focus-select"),
    discovery: inputValue("discovery-select"),
    implication: inputValue("implication-note"),
    note: inputValue("freeform-note"),
  });
  app.state.actionHistory.push(`已记录当前组合观察 #${app.observations.length}`);
  clearCombinationObservationInputs();
  refreshEvidence();
}

function recordComparison() {
  app.comparisons.push({
    scenario: app.state.scenarioLabel,
    preference: inputValue("preferred-variant-select"),
    note: inputValue("comparison-note"),
  });
  app.state.actionHistory.push(`已记录跨方案比较 #${app.comparisons.length}`);
  clearComparisonInputs();
  refreshEvidence();
}

async function copyObservations() {
  const text = observationMarkdown();
  const status = document.querySelector("#observation-status");
  try {
    await navigator.clipboard.writeText(text);
    status.textContent = "观察摘要已复制。可直接粘贴回当前任务。";
  } catch {
    status.textContent = "浏览器未授予复制权限；请从下方摘要手动复制。";
  }
}

function applyAction(id) {
  const state = app.state;
  if (!["open-main", "open-overlay", "open-passive", "close-overlay"].includes(id) && !canChoose(id)) {
    state.actionHistory.push(`忽略不可用操作：${id}`);
    render();
    return;
  }

  if (id === "open-main") {
    state.presentation.mainWindowOpen = true;
    state.presentation.mainFocus = "恢复入口 / 上次与当前上下文";
    state.actionHistory.push("打开主窗口的恢复入口");
    state.outcome = "已打开主窗口；尚未对上次或当前计划作出选择。";
  } else if (id === "open-overlay") {
    state.presentation.overlayVisible = true;
    state.presentation.mainFocus = "置顶小窗的恢复选择";
    state.actionHistory.push("打开置顶小窗的恢复选择");
    state.outcome = "已显示小窗；尚未对执行上下文作出选择。";
  } else if (id === "close-overlay") {
    state.presentation.overlayVisible = false;
    state.presentation.mainWindowOpen = true;
    state.presentation.mainFocus = "主窗口首页";
    state.recovery.activePresentation = false;
    state.recovery.passiveEntryVisible = true;
    state.recovery.degradation = "小窗已关闭，仅隐藏呈现；主窗口保留静态被动入口";
    state.actionHistory.push("关闭小窗（未作出恢复决定）");
    state.outcome = "小窗已隐藏；上一项与当前计划都没有被改变。";
  } else if (id === "open-passive") {
    state.presentation.mainWindowOpen = true;
    state.presentation.mainFocus = "主窗口的被动恢复入口";
    state.recovery.passiveEntryOpened = true;
    state.actionHistory.push("用户主动打开被动恢复入口");
    state.outcome = "被动入口已打开；这不是新的通知或干预。";
  } else if (id === "continue-last") {
    state.recovery.activePresentation = false;
    state.recovery.passiveEntryVisible = false;
    state.recovery.decision = "继续上次执行";
    state.recovery.degradation = "用户已明确选择继续上次；不再需要恢复呈现";
    state.presentation.mainWindowOpen = true;
    state.presentation.overlayVisible = false;
    state.presentation.mainFocus = "上次执行上下文";
    state.pastContext.status = state.pastContext.type === "恢复包" ? "已选择重新进入" : "已选择继续执行";
    state.pastContext.result = "用户选择继续上次；并非对当前计划作出否定";
    state.availableActions = [];
    state.actionHistory.push("选择“继续上次执行”");
    state.outcome = "已进入上次执行上下文；当前计划仍保留，未被删除。";
  } else if (id === "handle-previous") {
    state.recovery.activePresentation = false;
    state.recovery.passiveEntryVisible = false;
    state.recovery.decision = "处理上一项";
    state.recovery.degradation = "用户已选择处理上一项；不再需要恢复呈现";
    state.presentation.mainWindowOpen = true;
    state.presentation.overlayVisible = false;
    state.presentation.mainFocus = "上一项的状态核对";
    state.pastContext.status = "已打开状态核对，结果尚未填写";
    state.pastContext.result = "仍未知，等待用户明确报告";
    state.availableActions = [];
    state.actionHistory.push("选择“处理上一项”");
    state.outcome = "已打开上一项的核对路径；没有把沉默写成未开始或失败。";
  } else if (id === "continue-current") {
    state.recovery.activePresentation = false;
    state.recovery.passiveEntryVisible = false;
    state.recovery.decision = "按当前计划继续";
    state.recovery.degradation = "用户已选择当前计划；不再需要恢复呈现";
    state.presentation.mainWindowOpen = true;
    state.presentation.overlayVisible = false;
    state.presentation.mainFocus = "当前计划";
    state.currentPlan.status = "已选为当前执行入口";
    state.currentPlan.facts = ["用户选择按当前计划继续", "上一项结果仍是未知，并未被放弃"];
    state.pastContext.status = "结果仍未知";
    state.pastContext.result = "未知；没有自动推断未开始、失败或放弃";
    state.availableActions = [];
    state.actionHistory.push("选择“按当前计划继续”");
    state.outcome = "当前计划被选为入口；上一项仍明确保留为未知。";
  } else if (id === "defer") {
    state.recovery.activePresentation = false;
    state.recovery.passiveEntryVisible = true;
    state.recovery.passiveEntryOpened = false;
    state.recovery.decision = "暂不决定";
    state.recovery.degradation = "用户明确暂不决定；结束主动呈现并保留静态被动入口";
    state.presentation.mainWindowOpen = true;
    state.presentation.overlayVisible = false;
    state.presentation.mainFocus = "主窗口首页";
    state.actionHistory.push("选择“暂不决定”");
    state.outcome = "主动呈现已结束；恢复入口可在主窗口被动找到。";
  }
  render();
}

function render() {
  document.querySelector("#prototype-root").innerHTML = renderPrototype();
  document.querySelector("#scenario-select").value = app.scenario;
  document.querySelector("#scenario-summary").textContent = scenarioDefinitions[app.scenario].description;
  document.querySelector("#variant-label").textContent = `${app.variant} — ${variants[app.variant].name}`;
  refreshEvidence();
}

function initializeScenarioOptions() {
  const select = document.querySelector("#scenario-select");
  select.innerHTML = Object.entries(scenarioDefinitions)
    .map(([id, definition]) => `<option value="${id}">${definition.label}</option>`)
    .join("");
}

document.addEventListener("click", (event) => {
  const actionButton = event.target.closest("[data-action]");
  if (actionButton) {
    applyAction(actionButton.dataset.action);
    return;
  }
  const stepButton = event.target.closest("[data-variant-step]");
  if (stepButton) nextVariant(stepButton.dataset.variantStep);
});

document.querySelector("#scenario-select").addEventListener("change", (event) => selectScenario(event.target.value));
document.querySelector("#reset-scenario").addEventListener("click", () => selectScenario(app.scenario));
document.querySelector("#record-observation").addEventListener("click", recordObservation);
document.querySelector("#record-comparison").addEventListener("click", recordComparison);
document.querySelector("#copy-observations").addEventListener("click", copyObservations);

window.addEventListener("keydown", (event) => {
  const tag = document.activeElement?.tagName?.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select" || document.activeElement?.isContentEditable) return;
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    nextVariant("previous");
  }
  if (event.key === "ArrowRight") {
    event.preventDefault();
    nextVariant("next");
  }
});

window.addEventListener("popstate", () => {
  app.variant = validVariant(queryValue("variant", "A"));
  selectScenario(validScenario(queryValue("scenario", "active-session")));
});

initializeScenarioOptions();
render();
