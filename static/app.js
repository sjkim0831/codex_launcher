const state = {
  bootstrap: null,
  selectedWorkspaceId: "",
  selectedActionId: "",
  selectedJobId: "",
  selectedAccountId: "",
  selectedSessionId: "",
  selectedPlanStep: "",
  selectedPlanStepBySession: {},
  sessionPanelOpen: {
    plan: true,
    tree: true,
    family: true,
    compare: true
  },
  selectedCli: "codex",
  sessions: [],
  currentSession: null,
  referenceRoots: [],
  selectedReferenceRootId: "",
  referenceProjects: [],
  selectedReferenceProject: "",
  referenceTree: null,
  referenceSection: "screen",
  selectedReferenceFolder: "",
  selectedReferencePath: "",
  selectedReferenceMeta: null,
  projectRoots: [],
  selectedProjectRootId: "",
  projectDirectories: [],
  selectedProjectPath: "",
  projectSearch: "",
  projectMenus: null,
  selectedMenuGroup: "home",
  selectedMenuItem: null,
  pollHandle: null,
  browserPollHandle: null,
  lastBrowserCaptureId: ""
};

const UI_STATE_KEY = "carbonet-codex-ui-state";

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

function byId(id) {
  return document.getElementById(id);
}

function loadUiState() {
  try {
    const raw = window.localStorage.getItem(UI_STATE_KEY);
    if (!raw) {
      return;
    }
    const doc = JSON.parse(raw);
    if (doc && typeof doc === "object") {
      if (doc.sessionPanelOpen && typeof doc.sessionPanelOpen === "object") {
        state.sessionPanelOpen = {
          ...state.sessionPanelOpen,
          ...doc.sessionPanelOpen
        };
      }
      if (doc.selectedPlanStepBySession && typeof doc.selectedPlanStepBySession === "object") {
        state.selectedPlanStepBySession = doc.selectedPlanStepBySession;
      }
    }
  } catch (_error) {
    // Ignore invalid local UI state.
  }
}

function persistUiState() {
  try {
    window.localStorage.setItem(UI_STATE_KEY, JSON.stringify({
      sessionPanelOpen: state.sessionPanelOpen,
      selectedPlanStepBySession: state.selectedPlanStepBySession || {}
    }));
  } catch (_error) {
    // Ignore localStorage failures.
  }
}

function syncSessionPanelToggles() {
  const mappings = [
    ["plan", "session-plan-view", "toggle-session-plan"],
    ["tree", "session-tree-view", "toggle-session-tree"],
    ["family", "session-family-view", "toggle-session-family"],
    ["compare", "session-compare-view", "toggle-session-compare"]
  ];
  mappings.forEach(([key, contentId, buttonId]) => {
    const open = Boolean(state.sessionPanelOpen[key]);
    byId(contentId).classList.toggle("is-collapsed", !open);
    byId(buttonId).textContent = open ? "Hide" : "Show";
  });
  persistUiState();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll('"', "&quot;");
}

function normalizeBrowserUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  if (/^https?:\/\//i.test(raw)) {
    return raw;
  }
  return `http://${raw}`;
}

function armBrowserUrl(value) {
  const url = new URL(value);
  url.searchParams.set("codex_bridge", "1");
  return url.toString();
}

function renderWorkspaces() {
  const target = byId("workspace-list");
  const workspaces = state.bootstrap?.workspaces || [];
  target.innerHTML = workspaces.map((workspace) => `
    <button class="workspace-card ${workspace.id === state.selectedWorkspaceId ? "active" : ""}" data-workspace-id="${workspace.id}" type="button">
      <strong>${escapeHtml(workspace.label)}</strong>
      <div class="muted">${escapeHtml(workspace.description || "")}</div>
      <div class="pill">${escapeHtml(workspace.path)}</div>
    </button>
  `).join("");
  target.querySelectorAll("[data-workspace-id]").forEach((element) => {
    element.addEventListener("click", () => {
      state.selectedWorkspaceId = element.getAttribute("data-workspace-id") || "";
      renderWorkspaces();
      renderActions();
      syncWorkspaceCaption();
    });
  });
}

function accountSummaryText(account) {
  const bits = [account.label || account.email || account.name || account.accountId || account.id];
  if (account.email) {
    bits.push(account.email);
  }
  if (account.authMode) {
    bits.push(account.authMode);
  }
  return bits.filter(Boolean).join(" · ");
}

function sessionSummaryText(session) {
  const bits = [session.title || session.id];
  if (session.parentSessionId) {
    bits.push(`branch of ${session.parentSessionId}`);
  }
  if (session.workspaceId) {
    bits.push(session.workspaceId);
  }
  if (session.updatedAt) {
    bits.push(session.updatedAt);
  }
  return bits.filter(Boolean).join(" · ");
}

function formatSessionPlan(plan) {
  const items = Array.isArray(plan) ? plan : [];
  return items.map((item) => `${item.status || "pending"} | ${item.step || ""}`.trim()).join("\n");
}

function parseSessionPlan(text) {
  return String(text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split("|");
      if (parts.length >= 2) {
        return {
          status: parts[0].trim() || "pending",
          step: parts.slice(1).join("|").trim()
        };
      }
      return {
        status: "pending",
        step: line
      };
    })
    .filter((item) => item.step);
}

function renderSessions(sessions, currentSession) {
  state.sessions = sessions || [];
  state.currentSession = currentSession || null;
  state.selectedSessionId = currentSession?.id || sessions?.[0]?.id || "";
  const selectedPlanStepBySession = state.selectedPlanStepBySession || {};
  state.selectedPlanStep = selectedPlanStepBySession[state.selectedSessionId] || state.selectedPlanStep;
  byId("current-session").textContent = state.selectedSessionId
    ? `Active: ${sessionSummaryText(currentSession || {})}`
    : "Active session 없음";
  byId("session-notes").value = currentSession?.notes || "";
  byId("session-plan").value = formatSessionPlan(currentSession?.plan || []);
  renderActivePlanOptions(currentSession?.plan || []);
  renderSessionPlanView(currentSession?.plan || []);
  renderSessionTreeView(state.sessions, state.selectedSessionId);
  renderSessionFamilyView(currentSession || null).catch((error) => {
    byId("session-family-view").innerHTML = `<div class="muted">${escapeHtml(error instanceof Error ? error.message : String(error))}</div>`;
  });
  byId("session-summary").textContent = currentSession?.summary || "세션 요약이 아직 없습니다.";
  renderSessionCompareView(currentSession || null).catch((error) => {
    byId("session-compare-view").innerHTML = `<div class="muted">${escapeHtml(error instanceof Error ? error.message : String(error))}</div>`;
  });
  syncSessionPanelToggles();
  const target = byId("session-list");
  if (!state.sessions.length) {
    target.innerHTML = `<div class="muted">세션이 없습니다.</div>`;
    return;
  }
  target.innerHTML = state.sessions.map((session) => `
    <button class="workspace-card ${session.id === state.selectedSessionId ? "active" : ""}" data-session-id="${session.id}" type="button">
      <strong>${escapeHtml(session.title || session.id)}</strong>
      <div class="muted">${escapeHtml(session.summary || "아직 요약 없음")}</div>
      <div class="account-card-meta">
        <span class="pill">${escapeHtml(session.parentSessionId ? `branch:${session.parentSessionId}` : "root")}</span>
        <span class="pill">${escapeHtml(session.workspaceId || "workspace 없음")}</span>
        <span class="pill">${escapeHtml(session.updatedAt || "")}</span>
      </div>
    </button>
  `).join("");
  target.querySelectorAll("[data-session-id]").forEach((element) => {
    element.addEventListener("click", async () => {
      const sessionId = element.getAttribute("data-session-id") || "";
      await activateSessionById(sessionId);
    });
  });
}

async function activateSessionById(sessionId) {
  const payload = await api(`/api/sessions/${sessionId}/activate`, {
    method: "POST",
    body: "{}"
  });
  renderSessions(payload.items || [], payload.session || null);
  await refreshJobs();
}

function renderActivePlanOptions(plan) {
  const select = byId("active-plan-step");
  const items = Array.isArray(plan) ? plan : [];
  select.innerHTML = [
    `<option value="">자동 선택</option>`,
    ...items.map((item) => {
      const step = String(item.step || "");
      const status = String(item.status || "pending");
      return `<option value="${escapeAttribute(step)}">${escapeHtml(`[${status}] ${step}`)}</option>`;
    })
  ].join("");
  const defaultStep = items.find((item) => item.status === "in_progress")?.step || "";
  state.selectedPlanStep = items.some((item) => item.step === state.selectedPlanStep)
    ? state.selectedPlanStep
    : defaultStep;
  state.selectedPlanStepBySession = {
    ...(state.selectedPlanStepBySession || {}),
    [state.selectedSessionId]: state.selectedPlanStep || ""
  };
  select.value = state.selectedPlanStep || "";
  persistUiState();
}

function renderSessionPlanView(plan) {
  const target = byId("session-plan-view");
  const items = Array.isArray(plan) ? plan : [];
  if (!items.length) {
    target.innerHTML = `<div class="muted">세션 plan이 없습니다.</div>`;
    return;
  }
  target.innerHTML = items.map((item) => `
    <div class="session-plan-item" data-status="${escapeAttribute(item.status || "pending")}">
      <strong>${escapeHtml(item.step || "")}</strong>
      <span class="pill">${escapeHtml(item.status || "pending")}</span>
    </div>
  `).join("");
}

function renderSessionTreeView(sessions, currentSessionId) {
  const target = byId("session-tree-view");
  const items = Array.isArray(sessions) ? sessions : [];
  if (!items.length) {
    target.innerHTML = `<div class="muted">세션 트리가 없습니다.</div>`;
    return;
  }
  const byParent = new Map();
  const roots = [];
  items.forEach((item) => {
    const parentId = item.parentSessionId || "";
    if (!parentId) {
      roots.push(item);
      return;
    }
    const siblings = byParent.get(parentId) || [];
    siblings.push(item);
    byParent.set(parentId, siblings);
  });
  const summarizeNode = (node) => {
    const plan = Array.isArray(node.plan) ? node.plan : [];
    const completed = plan.filter((item) => item.status === "completed").length;
    const total = plan.length;
    const running = plan.find((item) => item.status === "in_progress")?.step || "";
    const recentJobItems = Array.isArray(node.recentJobs) ? node.recentJobs : [];
    const recentJobs = recentJobItems.length;
    const hasFailure = recentJobItems.some((item) => item.status === "failed");
    const status = hasFailure
      ? "failed"
      : running
        ? "in_progress"
        : total > 0 && completed === total
          ? "completed"
          : "idle";
    return {
      status,
      planText: total ? `plan ${completed}/${total}` : "plan 없음",
      runningText: running ? `active ${running}` : "",
      jobsText: recentJobs ? `jobs ${recentJobs}` : "jobs 0"
    };
  };
  const renderNode = (node) => {
    const children = byParent.get(node.id) || [];
    const summary = summarizeNode(node);
    return `
      <div class="session-tree-branch">
        <button class="session-tree-node ${node.id === currentSessionId ? "current" : ""}" data-status="${escapeAttribute(summary.status)}" data-tree-session-id="${escapeAttribute(node.id)}" type="button">
          <strong>${escapeHtml(node.id === currentSessionId ? `Current: ${node.title}` : node.title || node.id)}</strong>
          <div class="session-tree-meta">
            <span class="pill">${escapeHtml(summary.planText)}</span>
            <span class="pill">${escapeHtml(summary.jobsText)}</span>
            ${summary.runningText ? `<span class="pill">${escapeHtml(summary.runningText)}</span>` : ""}
          </div>
        </button>
        ${children.length ? `<div class="session-tree-children">${children.map(renderNode).join("")}</div>` : ""}
      </div>
    `;
  };
  target.innerHTML = `<div class="session-tree-box"><strong>Session Tree</strong>${roots.map(renderNode).join("")}</div>`;
  target.querySelectorAll("[data-tree-session-id]").forEach((element) => {
    element.addEventListener("click", async () => {
      const sessionId = element.getAttribute("data-tree-session-id") || "";
      if (sessionId) {
        await activateSessionById(sessionId);
      }
    });
  });
}

async function focusPlanStep(step) {
  state.selectedPlanStep = step || "";
  state.selectedPlanStepBySession = {
    ...(state.selectedPlanStepBySession || {}),
    [state.selectedSessionId]: state.selectedPlanStep || ""
  };
  byId("active-plan-step").value = state.selectedPlanStep || "";
  persistUiState();
  const recentJobs = Array.isArray(state.currentSession?.recentJobs) ? state.currentSession.recentJobs : [];
  const match = [...recentJobs].reverse().find((item) => (item.planStep || "") === state.selectedPlanStep);
  if (match?.jobId) {
    await loadJob(match.jobId);
  }
  await refreshJobs();
}

async function renderSessionFamilyView(session) {
  const target = byId("session-family-view");
  if (!session?.id) {
    target.innerHTML = `<div class="muted">세션 탐색 정보가 없습니다.</div>`;
    return;
  }
  const payload = await api(`/api/sessions/${session.id}/family`);
  const siblings = payload.siblings || [];
  const lines = [
    `<div class="session-family-box">`,
    `<strong>Branch Navigation</strong>`,
    `<div class="session-family-actions">`
  ];
  if (payload.parent?.id) {
    lines.push(`
      <button class="session-family-link ${payload.parent.isCurrent ? "current" : ""}" data-family-session-id="${escapeAttribute(payload.parent.id)}" type="button">
        ${escapeHtml(payload.parent.isCurrent ? `Current: ${payload.parent.title}` : `Parent: ${payload.parent.title}`)}
      </button>
    `);
  }
  lines.push(...siblings.map((item) => `
    <button class="session-family-link ${item.isCurrent ? "current" : ""}" data-family-session-id="${escapeAttribute(item.id)}" type="button">
      ${escapeHtml(item.isCurrent ? `Current: ${item.title}` : item.title)}
    </button>
  `));
  lines.push(`</div>`, `</div>`);
  target.innerHTML = lines.join("");
  target.querySelectorAll("[data-family-session-id]").forEach((element) => {
    element.addEventListener("click", async () => {
      const sessionId = element.getAttribute("data-family-session-id") || "";
      if (sessionId) {
        await activateSessionById(sessionId);
      }
    });
  });
}

async function renderSessionCompareView(session) {
  const target = byId("session-compare-view");
  if (!session?.id || !session?.parentSessionId) {
    target.innerHTML = `<div class="muted">비교할 부모 세션이 없습니다.</div>`;
    return;
  }
  const payload = await api(`/api/sessions/${session.id}/compare`);
  const changedSteps = payload.changedSteps || [];
  const newJobs = payload.newJobs || [];
  const notesAdded = payload.notesAdded || [];
  const notesRemoved = payload.notesRemoved || [];
  const lines = [
    `<div class="session-compare-box">`,
    `<strong>Compare with ${escapeHtml(payload.parentTitle || payload.parentSessionId || "parent")}</strong>`,
    `<div class="muted">${escapeHtml(payload.notesChanged ? "Notes changed" : "Notes unchanged")}</div>`
  ];
  if (notesAdded.length) {
    lines.push(...notesAdded.map((line) => `<div class="muted">+ ${escapeHtml(line)}</div>`));
  }
  if (notesRemoved.length) {
    lines.push(...notesRemoved.map((line) => `<div class="muted">- ${escapeHtml(line)}</div>`));
  }
  if (changedSteps.length) {
    lines.push(...changedSteps.map((item) => `
      <button class="session-compare-job" data-compare-step="${escapeAttribute(item.step || "")}" type="button">
        <strong>${escapeHtml(item.step)}</strong>
        <div class="muted">${escapeHtml(item.parentStatus || "-")} -> ${escapeHtml(item.sessionStatus || "-")}</div>
      </button>
    `));
  } else {
    lines.push(`<div class="muted">Changed steps 없음</div>`);
  }
  if (newJobs.length) {
    lines.push(`<div class="muted">New jobs</div>`);
    lines.push(...newJobs.map((item) => `
      <button class="session-compare-job" data-compare-job-id="${escapeAttribute(item.jobId || "")}" type="button">
        <strong>${escapeHtml(item.title || item.jobId || "")}</strong>
        <div class="muted">${escapeHtml(item.planStep ? `step: ${item.planStep}` : "step: 자동")}</div>
      </button>
    `));
  } else {
    lines.push(`<div class="muted">새 job 없음</div>`);
  }
  lines.push(`</div>`);
  target.innerHTML = lines.join("");
  target.querySelectorAll("[data-compare-job-id]").forEach((element) => {
    element.addEventListener("click", async () => {
      const jobId = element.getAttribute("data-compare-job-id") || "";
      if (jobId) {
        await loadJob(jobId);
      }
    });
  });
  target.querySelectorAll("[data-compare-step]").forEach((element) => {
    element.addEventListener("click", async () => {
      const step = element.getAttribute("data-compare-step") || "";
      await focusPlanStep(step);
    });
  });
}

async function saveSessionContext() {
  if (!state.selectedSessionId) {
    alert("먼저 세션을 선택하세요.");
    return;
  }
  const payload = await api(`/api/sessions/${state.selectedSessionId}/update`, {
    method: "POST",
    body: JSON.stringify({
      notes: byId("session-notes").value,
      plan: parseSessionPlan(byId("session-plan").value),
      workspaceId: state.selectedWorkspaceId,
      projectPath: state.selectedProjectPath
    })
  });
  renderSessions(payload.items || [], payload.session || null);
}

function renderAccounts(accounts, currentAccountId) {
  state.selectedAccountId = currentAccountId || "";
  byId("current-account").textContent = currentAccountId
    ? `Active: ${accountSummaryText(accounts.find((item) => item.id === currentAccountId) || {})}`
    : "Active: 저장된 슬롯과 현재 로그인이 아직 연결되지 않았습니다.";
  const target = byId("account-list");
  if (!accounts.length) {
    target.innerHTML = `<div class="muted">저장된 로그인 슬롯이 없습니다. 현재 로그인 상태를 저장해 두면 클릭 전환이 가능합니다.</div>`;
    return;
  }
  target.innerHTML = accounts.map((account) => `
    <button class="workspace-card ${account.id === currentAccountId ? "active" : ""}" data-account-id="${account.id}" type="button">
      <strong>${escapeHtml(account.label || account.name || account.email || account.id)}</strong>
      <div class="muted">${escapeHtml(account.email || account.accountId || "")}</div>
      <div class="account-card-meta">
        <span class="pill">${escapeHtml(account.authMode || "unknown")}</span>
        <span class="pill">${escapeHtml(account.updatedAt || account.createdAt || "")}</span>
      </div>
    </button>
  `).join("");
  target.querySelectorAll("[data-account-id]").forEach((element) => {
    element.addEventListener("click", async () => {
      const accountId = element.getAttribute("data-account-id") || "";
      const payload = await api(`/api/accounts/${accountId}/activate`, {
        method: "POST",
        body: "{}"
      });
      byId("login-status").textContent = payload.loginReady ? "ready" : "not ready";
      await refreshAccounts();
      alert("선택한 Codex 로그인 슬롯을 활성화했습니다.");
    });
  });
}

function renderActions() {
  const target = byId("action-grid");
  const actions = state.bootstrap?.actions || [];
  target.innerHTML = actions.map((action) => `
    <button class="action-card ${action.id === state.selectedActionId ? "active" : ""}" data-action-id="${action.id}" type="button">
      <div class="pill">${escapeHtml(action.group || action.kind)}</div>
      <strong>${escapeHtml(action.label)}</strong>
      <div class="muted">${escapeHtml(action.description || "")}</div>
    </button>
  `).join("");
  target.querySelectorAll("[data-action-id]").forEach((element) => {
    element.addEventListener("click", () => {
      const actionId = element.getAttribute("data-action-id") || "";
      const action = actions.find((item) => item.id === actionId);
      state.selectedActionId = actionId;
      byId("selected-action-caption").textContent = action?.description || "버튼을 선택하세요";
      if (action?.kind === "codex") {
        byId("custom-codex-prompt").value = action.promptTemplate || "";
      }
      renderActions();
    });
  });
}

function renderCliOptions() {
  const target = byId("assistant-cli");
  const options = state.bootstrap?.cliOptions || [];
  target.innerHTML = options.map((option) => `
    <option value="${escapeHtml(option.id)}">${escapeHtml(option.label)}</option>
  `).join("");
  target.value = state.selectedCli || "codex";
  target.addEventListener("change", () => {
    state.selectedCli = target.value || "codex";
    syncAssistantNote();
  });
  syncAssistantNote();
}

function syncAssistantNote() {
  const freeagent = state.bootstrap?.freeagent || {};
  if (state.selectedCli === "freeagent") {
    byId("assistant-note").textContent = freeagent.installed
      ? `FreeAgent provider=${freeagent.provider || "unknown"} model=${freeagent.model || "unknown"}`
      : "FreeAgent가 아직 설치되지 않았습니다.";
    return;
  }
  byId("assistant-note").textContent = "Codex는 현재 로그인 세션과 workspace sandbox 설정을 사용합니다.";
}

function formatBrowserCapture(capture) {
  const parts = [
    "[Browser Capture]",
    `URL: ${capture.url || ""}`,
    `Title: ${capture.title || ""}`,
    `Selector: ${capture.selector || ""}`
  ];
  if (capture.html) {
    parts.push("HTML:");
    parts.push(capture.html);
  } else if (capture.text) {
    parts.push("Text:");
    parts.push(capture.text);
  }
  return `${parts.join("\n")}\n\n`;
}

function getReferenceTypeLabel(path) {
  if (path.endsWith(".html")) {
    return "html";
  }
  if (path.endsWith(".png")) {
    return "png";
  }
  return "file";
}

function buildReferencePrompt(meta) {
  const browser = state.bootstrap?.browser || {};
  const capture = browser.lastCapture;
  const parts = [
    "[Reference Screen]",
    `Root: ${state.selectedReferenceRootId}`,
    `Section: ${state.referenceSection}`,
    `Scope: ${getReferenceScopePath()}`,
    `Path: ${meta.path}`,
    `File: ${meta.name}`,
    `Type: ${meta.contentType || ""}`
  ];
  if (browser.currentUrl) {
    parts.push(`Target URL: ${browser.currentUrl}`);
  }
  if (meta.text) {
    parts.push("Reference Source:");
    parts.push(meta.text.slice(0, 12000));
  } else if (meta.downloadUrl) {
    parts.push(`Reference Asset: ${window.location.origin}${meta.downloadUrl}`);
  }
  if (capture) {
    parts.push("");
    parts.push(formatBrowserCapture(capture).trimEnd());
  }
  return `${parts.join("\n")}\n\n`;
}

function buildMigrationPrompt(meta) {
  const browser = state.bootstrap?.browser || {};
  const capture = browser.lastCapture;
  const lines = [
    "선택한 reference 화면을 현재 대상 앱으로 마이그레이션해줘.",
    `reference root id: ${state.selectedReferenceRootId}`,
    `reference section: ${state.referenceSection}`,
    `reference scope path: ${getReferenceScopePath()}`,
    `reference path: ${meta.path}`,
    `reference type: ${meta.contentType || ""}`
  ];
  if (state.selectedProjectPath) {
    lines.push(`target project path: ${state.selectedProjectPath}`);
  }
  if (state.selectedMenuItem?.menu) {
    lines.push(`target menu: ${state.selectedMenuItem.menu.label}`);
    lines.push(`target menu path: ${state.selectedMenuItem.menu.koPath}`);
  }
  if (browser.currentUrl) {
    lines.push(`target url: ${browser.currentUrl}`);
  }
  lines.push("요구사항:");
  lines.push("- 현재 작업공간 기준으로 수정할 실제 파일을 찾을 것");
  lines.push("- 가능하면 React 컴포넌트로 변환할 것");
  lines.push("- 기존 앱 구조와 스타일 체계를 최대한 따를 것");
  lines.push("- 필요한 파일 수정 후 어떤 경로를 바꿨는지 요약할 것");
  if (meta.text) {
    lines.push("reference html:");
    lines.push(meta.text.slice(0, 12000));
  } else if (meta.downloadUrl) {
    lines.push(`reference asset url: ${window.location.origin}${meta.downloadUrl}`);
  }
  if (capture) {
    lines.push("");
    lines.push(formatBrowserCapture(capture).trimEnd());
  }
  return `${lines.join("\n")}\n`;
}

function buildMenuContextPrompt() {
  const item = state.selectedMenuItem?.menu;
  if (!item) {
    return "";
  }
  return [
    "[Project Menu]",
    `Project: ${state.selectedProjectPath || ""}`,
    `Group: ${item.group}`,
    `Label: ${item.label}`,
    `koPath: ${item.koPath}`,
    `enPath: ${item.enPath}`,
    `id: ${item.id}`,
    ""
  ].join("\n");
}

function findReferenceNode(node, targetPath) {
  if (!node) {
    return null;
  }
  if ((node.path || "") === targetPath) {
    return node;
  }
  for (const child of node.children || []) {
    const match = findReferenceNode(child, targetPath);
    if (match) {
      return match;
    }
  }
  return null;
}

function getSelectedProjectName() {
  const raw = String(state.selectedProjectPath || "").trim();
  if (!raw) {
    return "";
  }
  const normalized = raw.replace(/\/+$/, "");
  const bits = normalized.split("/");
  return bits[bits.length - 1] || "";
}

function getReferenceScopePath() {
  const projectName = state.selectedReferenceProject || getSelectedProjectName();
  if (!projectName) {
    return "";
  }
  return `${projectName}/${state.referenceSection}`;
}

function renderReferenceThemeTree() {
  const rootPath = state.referenceRoots.find((item) => item.id === state.selectedReferenceRootId)?.path || "(theme root 없음)";
  const projectName = state.selectedReferenceProject || getSelectedProjectName() || "(theme project 미선택)";
  const section = state.referenceSection || "(section 없음)";
  const folder = state.selectedReferenceFolder || "(theme folder 전체)";
  const lines = [
    rootPath,
    `└── ${projectName}`,
    `    └── ${section}`,
    `        └── ${folder}`
  ];
  byId("reference-theme-tree").textContent = lines.join("\n");
}

function getVisibleReferenceRoot() {
  const scopedRoot = state.referenceTree?.tree;
  if (!scopedRoot) {
    return null;
  }
  if (!state.selectedReferenceFolder) {
    return scopedRoot;
  }
  return findReferenceNode(scopedRoot, state.selectedReferenceFolder) || scopedRoot;
}

function renderReferenceFolderOptions() {
  const select = byId("reference-folder-select");
  const root = state.referenceTree?.tree;
  if (!root) {
    select.innerHTML = `<option value="">전체</option>`;
    renderReferenceThemeTree();
    return;
  }
  const topDirs = (root.children || []).filter((item) => item.type === "directory");
  select.innerHTML = [
    `<option value="">전체</option>`,
    ...topDirs.map((item) => `<option value="${escapeAttribute(item.path || "")}">${escapeHtml(item.name || "")}</option>`)
  ].join("");
  select.value = state.selectedReferenceFolder || "";
  renderReferenceThemeTree();
}

function renderReferenceProjectOptions() {
  const select = byId("reference-project-select");
  const items = state.referenceProjects || [];
  select.innerHTML = items.length
    ? items.map((item) => `<option value="${escapeAttribute(item.name)}">${escapeHtml(item.name)}</option>`).join("")
    : `<option value="">테마 프로젝트 없음</option>`;
  select.value = state.selectedReferenceProject || items[0]?.name || "";
}

function renderRootOptions(kind) {
  const roots = kind === "reference" ? state.referenceRoots : state.projectRoots;
  const selectedId = kind === "reference" ? state.selectedReferenceRootId : state.selectedProjectRootId;
  const select = byId(kind === "reference" ? "reference-root-select" : "project-root-select");
  select.innerHTML = roots.map((item) => `
    <option value="${escapeAttribute(item.id)}">${escapeHtml(item.label)} · ${escapeHtml(item.path)}</option>
  `).join("");
  select.value = selectedId || roots[0]?.id || "";
}

async function refreshRootLists() {
  const [referencePayload, projectPayload] = await Promise.all([
    api("/api/reference/roots"),
    api("/api/project/roots")
  ]);
  state.referenceRoots = referencePayload.items || [];
  state.projectRoots = projectPayload.items || [];
  state.selectedReferenceRootId = state.selectedReferenceRootId || state.referenceRoots[0]?.id || "";
  state.selectedProjectRootId = state.selectedProjectRootId || state.projectRoots[0]?.id || "";
  renderRootOptions("reference");
  renderRootOptions("project");
}

function renderReferenceNode(node) {
  const isDirectory = node.type === "directory";
  const children = isDirectory
    ? `<div class="reference-children">${(node.children || []).map(renderReferenceNode).join("")}</div>`
    : "";
  const badge = isDirectory
    ? `<span class="reference-badge">dir</span>`
    : `<span class="reference-badge">${escapeHtml(getReferenceTypeLabel(node.path || ""))}</span>`;
  return `
    <div class="reference-node">
      <button
        class="reference-item ${isDirectory ? "directory" : "file"} ${node.path === state.selectedReferencePath ? "active" : ""}"
        data-reference-path="${escapeAttribute(node.path || "")}"
        data-reference-type="${escapeAttribute(node.type || "")}"
        type="button"
      >
        ${badge}
        <span>${escapeHtml(node.name || "")}</span>
      </button>
      ${children}
    </div>
  `;
}

function renderMenuNode(node) {
  const isLeaf = node.type === "item";
  const children = node.children?.length
    ? `<div class="reference-children">${node.children.map(renderMenuNode).join("")}</div>`
    : "";
  const label = isLeaf ? (node.menu?.label || node.name) : node.name;
  return `
    <div class="reference-node">
      <button
        class="reference-item ${isLeaf ? "file" : "directory"} ${state.selectedMenuItem?.path === node.path ? "active" : ""}"
        data-menu-path="${escapeAttribute(node.path || "")}"
        type="button"
      >
        <span class="reference-badge">${isLeaf ? "menu" : "dir"}</span>
        <span>${escapeHtml(label || "")}</span>
      </button>
      ${children}
    </div>
  `;
}

function findMenuNode(node, targetPath) {
  if (!node) {
    return null;
  }
  if ((node.path || "") === targetPath) {
    return node;
  }
  for (const child of node.children || []) {
    const match = findMenuNode(child, targetPath);
    if (match) {
      return match;
    }
  }
  return null;
}

function renderProjectMenuTree() {
  const target = byId("project-menu-tree");
  const root = state.projectMenus?.[state.selectedMenuGroup];
  const source = state.selectedMenuGroup === "home"
    ? state.projectMenus?.homeSource
    : state.projectMenus?.adminSource;
  byId("project-menu-source").textContent = source || "메뉴 스캔 전";
  if (!root) {
    target.innerHTML = `<div class="muted">먼저 프로젝트를 선택하고 메뉴를 스캔하세요.</div>`;
    return;
  }
  target.innerHTML = renderMenuNode(root);
  target.querySelectorAll("[data-menu-path]").forEach((element) => {
    element.addEventListener("click", () => {
      const node = findMenuNode(root, element.getAttribute("data-menu-path") || "");
      state.selectedMenuItem = node?.type === "item" ? node : null;
      renderProjectMenuTree();
      syncMenuPreview();
    });
  });
}

function syncMenuPreview() {
  const item = state.selectedMenuItem?.menu;
  byId("project-menu-selected").textContent = item ? `${item.label} · ${item.koPath}` : "선택된 메뉴 없음";
  if (!item) {
    byId("project-menu-preview").textContent = "메뉴를 선택하면 경로와 매핑 정보가 표시됩니다.";
    return;
  }
  const referenceMeta = state.selectedReferenceMeta;
  const lines = [
    `Project: ${state.selectedProjectPath || ""}`,
    `Menu Group: ${item.group}`,
    `Menu: ${item.label}`,
    `koPath: ${item.koPath}`,
    `enPath: ${item.enPath}`,
    `Theme Scope: ${getReferenceScopePath() || ""}`,
    `Reference File: ${referenceMeta?.path || state.selectedReferencePath || "(미선택)"}`,
  ];
  byId("project-menu-preview").textContent = lines.join("\n");
}

function findPreviewCandidate(node) {
  if (!node || node.type !== "directory") {
    return "";
  }
  const children = node.children || [];
  const html = children.find((item) => item.type === "file" && /(^|\/)code\.html$/i.test(item.path || ""));
  if (html?.path) {
    return html.path;
  }
  const png = children.find((item) => item.type === "file" && /(^|\/)screen\.png$/i.test(item.path || ""));
  if (png?.path) {
    return png.path;
  }
  return "";
}

async function selectProjectPath(path) {
  state.selectedProjectPath = path;
  state.projectMenus = null;
  state.selectedMenuItem = null;
  byId("project-menu-source").textContent = "메뉴 스캔 전";
  const selectedName = getSelectedProjectName();
  if (selectedName && state.referenceProjects.some((item) => item.name === selectedName)) {
    state.selectedReferenceProject = selectedName;
    renderReferenceProjectOptions();
  }
  renderProjectList();
  renderProjectSearchResults();
  syncProjectSummary();
  syncReferenceBinding();
  renderProjectMenuTree();
  syncMenuPreview();
  if (state.selectedReferenceRootId) {
    state.selectedReferenceFolder = "";
    state.selectedReferencePath = "";
    state.selectedReferenceMeta = null;
    await loadReferenceTree();
    syncReferencePreview();
  }
}

function renderProjectSearchResults() {
  const target = byId("project-search-results");
  const query = state.projectSearch.trim();
  if (!query) {
    target.innerHTML = "";
    return;
  }
  const lowered = query.toLowerCase();
  const matches = state.projectDirectories
    .filter((item) => `${item.name} ${item.path}`.toLowerCase().includes(lowered))
    .slice(0, 12);
  if (!matches.length) {
    target.innerHTML = `<div class="muted">검색 결과가 없습니다.</div>`;
    return;
  }
  target.innerHTML = matches.map((item) => `
    <button class="project-search-chip" data-project-path="${escapeAttribute(item.path)}" type="button">
      <strong>${escapeHtml(item.name)}</strong>
      <div class="muted">${escapeHtml(item.path)}</div>
    </button>
  `).join("");
  target.querySelectorAll("[data-project-path]").forEach((element) => {
    element.addEventListener("click", async () => {
      await selectProjectPath(element.getAttribute("data-project-path") || "");
    });
  });
}

function syncProjectSummary() {
  byId("project-selected").textContent = state.selectedProjectPath || "선택된 폴더 없음";
  if (!state.selectedProjectPath) {
    byId("project-summary").textContent = "선택한 루트 바로 아래의 프로젝트 폴더를 선택하세요.";
    return;
  }
  byId("project-summary").textContent = "선택 경로를 AI 실행, 빌드, 패키지, 재시작 대상 폴더로 사용합니다.";
}

function renderProjectList() {
  const target = byId("project-list");
  const items = state.projectDirectories;
  if (!items.length) {
    target.innerHTML = `<div class="muted">선택한 루트 바로 아래에 프로젝트 폴더가 없습니다.</div>`;
    return;
  }
  target.innerHTML = items.map((item) => `
    <button class="workspace-card project-item ${item.path === state.selectedProjectPath ? "active selected-target" : ""}" data-project-path="${escapeAttribute(item.path)}" type="button">
      <strong>${escapeHtml(item.name)}</strong>
      <div class="muted">${escapeHtml(item.path)}</div>
      <div class="account-card-meta">
        ${item.hasFrontendPackage ? '<span class="pill">frontend</span>' : ""}
        ${item.hasPom ? '<span class="pill">backend</span>' : ""}
        ${item.hasRestart18000 ? '<span class="pill">restart</span>' : ""}
      </div>
    </button>
  `).join("");
  target.querySelectorAll("[data-project-path]").forEach((element) => {
    element.addEventListener("click", async () => {
      await selectProjectPath(element.getAttribute("data-project-path") || "");
    });
  });
}

async function loadProjectTree() {
  const payload = await api(`/api/projects/tree?rootId=${encodeURIComponent(state.selectedProjectRootId)}`);
  state.projectDirectories = payload.items || [];
  byId("project-root").textContent = payload.root || "";
  byId("project-status").textContent = "선택한 project 루트 바로 아래 폴더 목록입니다.";
  renderProjectList();
  renderProjectSearchResults();
  syncProjectSummary();
}

async function scanProjectMenus() {
  const projectPath = requireProjectPath();
  if (!projectPath) {
    return;
  }
  const payload = await api(`/api/project/menus?projectPath=${encodeURIComponent(projectPath)}`);
  state.projectMenus = payload;
  state.selectedMenuItem = null;
  renderProjectMenuTree();
  syncMenuPreview();
}

function renderReferenceTree() {
  const target = byId("reference-tree");
  const root = getVisibleReferenceRoot();
  renderReferenceThemeTree();
  if (!root) {
    const projectName = getSelectedProjectName();
    const scopePath = getReferenceScopePath();
    target.innerHTML = projectName
      ? `<div class="muted">테마 루트 아래에 <code>${escapeHtml(scopePath)}</code> 경로가 없습니다.</div>`
      : `<div class="muted">먼저 프로젝트를 선택하면 <code>&lt;project&gt;/${escapeHtml(state.referenceSection)}</code>를 자동으로 찾습니다.</div>`;
    return;
  }
  target.innerHTML = renderReferenceNode(root);
  target.querySelectorAll("[data-reference-path]").forEach((element) => {
    element.addEventListener("click", async () => {
      const path = element.getAttribute("data-reference-path") || "";
      const type = element.getAttribute("data-reference-type") || "";
      if (type === "directory") {
        state.selectedReferencePath = path;
        state.selectedReferenceMeta = null;
        const clickedNode = findReferenceNode(root, path);
        const previewPath = findPreviewCandidate(clickedNode);
        renderReferenceTree();
        if (previewPath) {
          await selectReferenceFile(previewPath);
          return;
        }
        syncReferencePreview();
        return;
      }
      await selectReferenceFile(path);
    });
  });
}

function syncReferencePreview() {
  const meta = state.selectedReferenceMeta;
  byId("reference-selected").textContent = meta?.path || state.selectedReferencePath || "선택된 파일 없음";
  byId("reference-html-preview").style.display = "none";
  byId("reference-image-preview").style.display = "none";
  byId("reference-html-preview").srcdoc = "";
  byId("reference-image-preview").removeAttribute("src");
  byId("reference-text-preview").textContent = "선택한 HTML 소스 일부가 여기에 표시됩니다.";
  byId("reference-preview-meta").textContent = meta
    ? `${meta.name} · ${meta.contentType || ""}`
    : "`code.html` 또는 `screen.png`를 선택하세요.";
  if (!meta) {
    return;
  }
  if (meta.contentType?.includes("html")) {
    byId("reference-html-preview").style.display = "block";
    byId("reference-html-preview").srcdoc = meta.text || "";
    byId("reference-text-preview").textContent = meta.text || "";
    return;
  }
  if (meta.contentType?.startsWith("image/")) {
    const image = byId("reference-image-preview");
    image.style.display = "block";
    image.src = meta.downloadUrl;
    byId("reference-text-preview").textContent = `${meta.path}\n${window.location.origin}${meta.downloadUrl}`;
  }
  syncMenuPreview();
}

async function loadReferenceTree() {
  const scopePath = getReferenceScopePath();
  if (!scopePath) {
    state.referenceTree = null;
    syncReferenceBinding();
    renderReferenceFolderOptions();
    renderReferenceTree();
    return;
  }
  const payload = await api(`/api/reference/tree?rootId=${encodeURIComponent(state.selectedReferenceRootId)}&path=${encodeURIComponent(scopePath)}`);
  state.referenceTree = payload;
  renderReferenceFolderOptions();
  byId("reference-root").textContent = payload.root || "";
  syncReferenceBinding();
  renderReferenceTree();
}

async function selectReferenceFile(path) {
  const meta = await api(`/api/reference/meta?rootId=${encodeURIComponent(state.selectedReferenceRootId)}&path=${encodeURIComponent(path)}`);
  state.selectedReferencePath = meta.path || path;
  state.selectedReferenceMeta = meta;
  renderReferenceTree();
  syncReferencePreview();
}

async function addRoot(kind) {
  const labelId = kind === "reference" ? "reference-root-label" : "project-root-label";
  const pathId = kind === "reference" ? "reference-root-path" : "project-root-path";
  const label = byId(labelId).value.trim();
  const path = byId(pathId).value.trim();
  if (!label || !path) {
    alert("루트 라벨과 경로를 입력하세요.");
    return;
  }
  await api(kind === "reference" ? "/api/reference/roots" : "/api/project/roots", {
    method: "POST",
    body: JSON.stringify({ label, path })
  });
  byId(labelId).value = "";
  byId(pathId).value = "";
  await refreshRootLists();
  if (kind === "reference") {
    state.selectedReferenceRootId = state.referenceRoots[state.referenceRoots.length - 1]?.id || state.selectedReferenceRootId;
    state.selectedReferenceFolder = "";
    state.selectedReferencePath = "";
    state.selectedReferenceMeta = null;
    await loadReferenceTree();
    syncReferencePreview();
  } else {
    state.selectedProjectRootId = state.projectRoots[state.projectRoots.length - 1]?.id || state.selectedProjectRootId;
    state.selectedProjectPath = "";
    await loadProjectTree();
    syncProjectSummary();
  }
}

async function deleteSelectedRoot(kind) {
  const rootId = kind === "reference" ? state.selectedReferenceRootId : state.selectedProjectRootId;
  if (!rootId) {
    return;
  }
  await api(`${kind === "reference" ? "/api/reference/roots/" : "/api/project/roots/"}${encodeURIComponent(rootId)}/delete`, {
    method: "POST",
    body: "{}"
  });
  if (kind === "reference") {
    state.selectedReferenceRootId = "";
    state.selectedReferenceFolder = "";
    state.selectedReferencePath = "";
    state.selectedReferenceMeta = null;
  } else {
    state.selectedProjectRootId = "";
    state.selectedProjectPath = "";
  }
  await refreshRootLists();
  if (kind === "reference") {
    await loadReferenceTree();
    syncReferencePreview();
  } else {
    await loadProjectTree();
    syncProjectSummary();
  }
}

async function browseRootPath(kind) {
  const title = kind === "reference" ? "Select theme root folder" : "Select project parent root folder";
  const payload = await api(`/api/system/pick-directory?title=${encodeURIComponent(title)}`);
  const pathId = kind === "reference" ? "reference-root-path" : "project-root-path";
  byId(pathId).value = payload.selectedPath || "";
}

function syncReferenceBinding() {
  const projectName = getSelectedProjectName();
  const scopePath = getReferenceScopePath();
  byId("reference-root").textContent = state.referenceRoots.find((item) => item.id === state.selectedReferenceRootId)?.path || "";
  if (!state.selectedReferenceRootId) {
    byId("reference-status").textContent = "theme root를 먼저 등록하세요.";
    renderReferenceProjectOptions();
    renderReferenceFolderOptions();
    return;
  }
  if (!state.selectedReferenceProject) {
    byId("reference-status").textContent = "Theme Project를 선택하면 <themeProject>/screen 또는 <themeProject>/board를 엽니다.";
    renderReferenceProjectOptions();
    renderReferenceFolderOptions();
    return;
  }
  const scopedRoot = state.referenceTree?.tree;
  byId("reference-status").textContent = scopedRoot
    ? `자동 매핑: ${scopePath}`
    : `자동 매핑 경로 없음: ${scopePath}`;
  renderReferenceProjectOptions();
  renderReferenceFolderOptions();
}

async function loadReferenceProjects() {
  if (!state.selectedReferenceRootId) {
    state.referenceProjects = [];
    state.selectedReferenceProject = "";
    renderReferenceProjectOptions();
    return;
  }
  const payload = await api(`/api/reference/projects?rootId=${encodeURIComponent(state.selectedReferenceRootId)}`);
  state.referenceProjects = payload.items || [];
  if (!state.referenceProjects.some((item) => item.name === state.selectedReferenceProject)) {
    const selectedName = getSelectedProjectName();
    if (selectedName && state.referenceProjects.some((item) => item.name === selectedName)) {
      state.selectedReferenceProject = selectedName;
    } else {
      state.selectedReferenceProject = state.referenceProjects[0]?.name || "";
    }
  }
  renderReferenceProjectOptions();
}

function syncBrowserStatus(browser) {
  if (state.bootstrap) {
    state.bootstrap.browser = browser;
  }
  byId("browser-status").textContent = browser.currentUrl
    ? `${browser.currentTitle || "page"} · ${browser.currentUrl}`
    : "확장 대기 중";
  byId("browser-current-url").textContent = browser.currentUrl
    ? `최근 브라우저 주소: ${browser.currentUrl}`
    : "최근 보고 주소 없음";
  if (browser.lastCapture?.id && browser.lastCapture.id !== state.lastBrowserCaptureId) {
    state.lastBrowserCaptureId = browser.lastCapture.id;
    byId("custom-codex-prompt").value += formatBrowserCapture(browser.lastCapture);
    byId("browser-note").textContent = `최근 캡처가 prompt에 추가됨: ${browser.lastCapture.selector || browser.lastCapture.tagName || "element"}`;
  }
}

function renderJobs(jobs) {
  const target = byId("job-list");
  const filterBar = byId("job-filter-bar");
  const filterText = byId("job-filter-text");
  const items = state.selectedPlanStep
    ? jobs.filter((job) => (job.planStep || "") === state.selectedPlanStep)
    : jobs;
  filterBar.classList.toggle("is-collapsed", !state.selectedPlanStep);
  filterText.textContent = state.selectedPlanStep ? `Filtered by step: ${state.selectedPlanStep}` : "";
  if (!items.length) {
    target.innerHTML = `<div class="muted">${escapeHtml(state.selectedPlanStep ? `선택한 step(${state.selectedPlanStep})에 해당하는 실행 이력이 없습니다.` : "아직 실행 이력이 없습니다.")}</div>`;
    return;
  }
  target.innerHTML = items.map((job) => `
    <button class="job-card ${job.jobId === state.selectedJobId ? "active" : ""}" data-job-id="${job.jobId}" type="button">
      <strong>${escapeHtml(job.title)}</strong>
      <div class="muted">${escapeHtml(job.workspaceLabel || "")}</div>
      <div class="muted">${escapeHtml(job.planStep ? `step: ${job.planStep}` : "step: 자동")}</div>
      <div class="pill ${job.status === "succeeded" ? "success" : job.status === "failed" ? "danger" : ""}">
        ${escapeHtml(job.status)}
      </div>
    </button>
  `).join("");
  target.querySelectorAll("[data-job-id]").forEach((element) => {
    element.addEventListener("click", async () => {
      const jobId = element.getAttribute("data-job-id") || "";
      await loadJob(jobId);
    });
  });
}

function syncWorkspaceCaption() {
  const workspace = (state.bootstrap?.workspaces || []).find((item) => item.id === state.selectedWorkspaceId);
  byId("workspace-caption").textContent = workspace ? `${workspace.label} · ${workspace.path}` : "";
}

function setJobDetail(job) {
  if (!job) {
    return;
  }
  state.selectedJobId = job.jobId;
  byId("job-meta").textContent = `${job.status} · ${job.workspaceLabel || ""} · ${job.startedAt || ""}`;
  byId("job-plan-step").textContent = job.planStep ? `Plan step: ${job.planStep}` : "Plan step: 자동 선택";
  byId("command-preview").textContent = job.commandPreview || "명령 정보가 없습니다.";
  byId("raw-output").textContent = job.output || "출력이 없습니다.";
  byId("final-output").textContent = job.finalMessage || "Codex 최종 응답이 없습니다.";
}

async function refreshJobs() {
  const query = state.selectedSessionId ? `?sessionId=${encodeURIComponent(state.selectedSessionId)}` : "";
  const payload = await api(`/api/jobs${query}`);
  renderJobs(payload.items || []);
}

async function refreshSessions() {
  const payload = await api("/api/sessions");
  renderSessions(payload.items || [], payload.currentSession || null);
}

async function refreshAccounts() {
  const payload = await api("/api/accounts");
  renderAccounts(payload.items || [], payload.currentAccountId || "");
}

async function refreshBrowserState() {
  const browser = await api("/api/browser/state");
  syncBrowserStatus(browser || {});
  return browser;
}

async function loadJob(jobId) {
  if (!jobId) {
    return;
  }
  const job = await api(`/api/jobs/${jobId}`);
  setJobDetail(job);
  const query = state.selectedSessionId ? `?sessionId=${encodeURIComponent(state.selectedSessionId)}` : "";
  renderJobs((await api(`/api/jobs${query}`)).items || []);
  if (job.status === "running") {
    startPolling(jobId);
  }
}

function startPolling(jobId) {
  stopPolling();
  state.pollHandle = window.setInterval(async () => {
    try {
      const job = await api(`/api/jobs/${jobId}`);
      setJobDetail(job);
      await refreshJobs();
      if (job.status !== "running") {
        await refreshSessions();
        stopPolling();
      }
    } catch (error) {
      console.error(error);
      stopPolling();
    }
  }, 1500);
}

function stopPolling() {
  if (state.pollHandle) {
    window.clearInterval(state.pollHandle);
    state.pollHandle = null;
  }
}

async function runAction() {
  if (!state.selectedActionId) {
    alert("먼저 Quick Action을 선택하세요.");
    return;
  }
  const extraInput = byId("extra-input").value;
  const payload = await api("/api/run", {
    method: "POST",
    body: JSON.stringify({
      sessionId: state.selectedSessionId,
      planStep: state.selectedPlanStep,
      workspaceId: state.selectedWorkspaceId,
      projectPath: state.selectedProjectPath,
      actionId: state.selectedActionId,
      extraInput
    })
  });
  setJobDetail(payload);
  await refreshJobs();
  startPolling(payload.jobId);
}

async function runCustomCodex() {
  const prompt = byId("custom-codex-prompt").value.trim();
  if (!prompt) {
    alert("AI Prompt를 입력하세요.");
    return;
  }
  const payload = await api("/api/run", {
    method: "POST",
    body: JSON.stringify({
      sessionId: state.selectedSessionId,
      planStep: state.selectedPlanStep,
      workspaceId: state.selectedWorkspaceId,
      projectPath: state.selectedProjectPath,
      mode: "assistant_custom",
      cli: state.selectedCli,
      prompt
    })
  });
  setJobDetail(payload);
  await refreshJobs();
  startPolling(payload.jobId);
}

async function runCustomShell() {
  const command = byId("custom-shell-command").value.trim();
  if (!command) {
    alert("Shell Command를 입력하세요.");
    return;
  }
  const payload = await api("/api/run", {
    method: "POST",
    body: JSON.stringify({
      sessionId: state.selectedSessionId,
      planStep: state.selectedPlanStep,
      workspaceId: state.selectedWorkspaceId,
      projectPath: state.selectedProjectPath,
      mode: "shell_custom",
      shellCommand: command
    })
  });
  setJobDetail(payload);
  await refreshJobs();
  startPolling(payload.jobId);
}

function requireProjectPath() {
  if (!state.selectedProjectPath) {
    alert("먼저 프로젝트 폴더를 선택하세요.");
    return "";
  }
  return state.selectedProjectPath;
}

async function runProjectShell(projectPath, shellCommand, title) {
  const payload = await api("/api/run", {
    method: "POST",
    body: JSON.stringify({
      sessionId: state.selectedSessionId,
      planStep: state.selectedPlanStep,
      projectPath,
      mode: "shell_custom",
      shellCommand
    })
  });
  setJobDetail(payload);
  byId("job-meta").textContent = `${title} · ${projectPath}`;
  await refreshJobs();
  startPolling(payload.jobId);
}

async function buildSelectedProjectFrontend() {
  const projectPath = requireProjectPath();
  if (!projectPath) {
    return;
  }
  const command = `[ -f frontend/package.json ] && cd frontend && npm run build || { [ -f package.json ] && npm run build; }`;
  await runProjectShell(projectPath, command, "Frontend Build");
}

async function packageSelectedProjectBackend() {
  const projectPath = requireProjectPath();
  if (!projectPath) {
    return;
  }
  const command = `[ -f pom.xml ] && mvn -q -DskipTests package`;
  await runProjectShell(projectPath, command, "Backend Package");
}

async function restartSelectedProject18000() {
  const projectPath = requireProjectPath();
  if (!projectPath) {
    return;
  }
  const command = `[ -x ops/scripts/restart-18000.sh ] && ops/scripts/restart-18000.sh`;
  await runProjectShell(projectPath, command, "Restart 18000");
}

async function oneClickBuildAndRestart() {
  const projectPath = requireProjectPath();
  if (!projectPath) {
    return;
  }
  const command = [
    "if [ -f frontend/package.json ]; then (cd frontend && npm run build);",
    "elif [ -f package.json ]; then npm run build;",
    "fi",
    "&& if [ -f pom.xml ]; then mvn -q -DskipTests package; else true; fi",
    "&& if [ -x ops/scripts/restart-18000.sh ]; then ops/scripts/restart-18000.sh; else true; fi"
  ].join(" ");
  await runProjectShell(projectPath, command, "One Click Build + Restart");
}

async function cancelCurrentJob() {
  if (!state.selectedJobId) {
    return;
  }
  await api(`/api/jobs/${state.selectedJobId}/cancel`, { method: "POST", body: "{}" });
  await loadJob(state.selectedJobId);
}

async function refreshLogin() {
  const payload = await api("/api/login-status", { method: "POST", body: "{}" });
  byId("login-status").textContent = payload.loggedIn ? "ready" : "not ready";
  await refreshAccounts();
}

async function openBrowserPreview(openPopup = false) {
  const url = normalizeBrowserUrl(byId("browser-address").value);
  if (!url) {
    alert("브라우저 주소를 입력하세요.");
    return;
  }
  byId("browser-address").value = url;
  const armedUrl = armBrowserUrl(url);
  if (openPopup) {
    window.open(armedUrl, "codex-real-browser-popup", "width=1440,height=960");
  } else {
    window.open(armedUrl, "_blank");
  }
  byId("browser-note").textContent = "실제 브라우저 페이지를 열었습니다. 이 탭에서는 확장 우클릭 메뉴가 기존 메뉴보다 우선합니다. 기존 메뉴가 필요하면 Shift+우클릭을 쓰세요.";
}

async function useCurrentBrowserAddress() {
  const browser = await refreshBrowserState();
  if (browser?.currentUrl) {
    byId("browser-address").value = browser.currentUrl;
    byId("browser-note").textContent = "최근 브라우저 주소를 입력창으로 가져왔습니다.";
    return;
  }
  alert("아직 브라우저에서 보고된 주소가 없습니다.");
}

function startBrowserPolling() {
  if (state.browserPollHandle) {
    window.clearInterval(state.browserPollHandle);
  }
  state.browserPollHandle = window.setInterval(async () => {
    try {
      await refreshBrowserState();
    } catch (error) {
      console.error(error);
    }
  }, 1500);
}

async function startLogin() {
  const payload = await api("/api/login/start", { method: "POST", body: "{}" });
  const targetUrl = payload.verificationUri || "https://auth.openai.com/codex/device";
  window.open(targetUrl, "_blank", "noopener,noreferrer");
  byId("login-help").textContent = payload.userCode
    ? `브라우저에서 코드를 입력하세요: ${payload.userCode}`
    : "브라우저 창을 열었습니다. 터미널 쪽 device code 출력을 확인하세요.";
}

async function logoutLogin() {
  const payload = await api("/api/logout", { method: "POST", body: "{}" });
  byId("login-status").textContent = payload.loginReady ? "ready" : "not ready";
  byId("login-help").textContent = payload.message || "로그아웃 처리 완료";
  await refreshAccounts();
}

async function saveCurrentAccount() {
  const label = byId("account-label").value.trim();
  if (!label) {
    alert("저장할 계정 라벨을 입력하세요.");
    return;
  }
  const payload = await api("/api/accounts/save-current", {
    method: "POST",
    body: JSON.stringify({ label })
  });
  byId("account-label").value = "";
  byId("login-status").textContent = payload.loginReady ? "ready" : "not ready";
  await refreshAccounts();
}

async function createSession() {
  const title = byId("session-title").value.trim() || "New Session";
  const payload = await api("/api/sessions", {
    method: "POST",
    body: JSON.stringify({
      title,
      workspaceId: state.selectedWorkspaceId,
      projectPath: state.selectedProjectPath
    })
  });
  byId("session-title").value = "";
  renderSessions(payload.items || [], payload.session || null);
  await refreshJobs();
}

async function branchSession() {
  if (!state.selectedSessionId) {
    alert("먼저 세션을 선택하세요.");
    return;
  }
  const title = byId("session-title").value.trim();
  const payload = await api(`/api/sessions/${state.selectedSessionId}/branch`, {
    method: "POST",
    body: JSON.stringify({ title })
  });
  byId("session-title").value = "";
  renderSessions(payload.items || [], payload.session || null);
  await refreshJobs();
}

async function bootstrap() {
  state.bootstrap = await api("/api/bootstrap");
  state.selectedWorkspaceId = state.bootstrap.defaultWorkspaceId || state.bootstrap.workspaces?.[0]?.id || "";
  state.selectedCli = state.bootstrap.cliOptions?.[0]?.id || "codex";
  state.sessions = state.bootstrap.sessions || [];
  state.currentSession = state.bootstrap.currentSession || null;
  state.selectedSessionId = state.bootstrap.currentSessionId || state.sessions[0]?.id || "";
  state.referenceRoots = state.bootstrap.referenceRoots || [];
  state.projectRoots = state.bootstrap.projectRoots || [];
  state.selectedReferenceRootId = state.referenceRoots[0]?.id || "";
  state.selectedProjectRootId = state.projectRoots[0]?.id || "";
  byId("reference-section-select").value = state.referenceSection;
  byId("codex-version").textContent = state.bootstrap.codexVersion || "unknown";
  byId("freeagent-model").textContent = state.bootstrap.freeagent?.installed
    ? `${state.bootstrap.freeagent.provider || "unknown"} · ${state.bootstrap.freeagent.model || "unknown"}`
    : "not installed";
  byId("login-status").textContent = state.bootstrap.loginReady ? "ready" : "not ready";
  byId("runtime-context").textContent = state.bootstrap.runtimeRoot?.startsWith("/mnt/")
    ? `WSL path ${state.bootstrap.runtimeRoot}`
    : `Linux path ${state.bootstrap.runtimeRoot}`;
  byId("browser-address").value = state.bootstrap.browser?.currentUrl || "http://localhost:18000";
  byId("browser-extension-path").textContent = state.bootstrap.browserExtension?.installPath || "";
  byId("browser-extension-link").href = state.bootstrap.browserExtension?.manifestUrl || "/extension/manifest.json";
  byId("browser-note").textContent = state.bootstrap.browserExtension?.installedFiles
    ? "확장 파일이 준비되어 있습니다. 43110에서 연 실제 페이지는 확장 우클릭 메뉴가 우선하고, Shift+우클릭은 원래 메뉴를 유지합니다."
    : "확장 파일이 아직 없습니다. /extension/manifest.json 경로를 먼저 확인하세요.";
  renderRootOptions("reference");
  renderRootOptions("project");
  byId("reference-root").textContent = state.referenceRoots.find((item) => item.id === state.selectedReferenceRootId)?.path || "";
  byId("reference-status").textContent = state.referenceRoots.length
    ? "Theme Project를 선택하면 theme root 아래 <themeProject>/screen를 엽니다."
    : "디폴트 루트가 없습니다. Theme Root에 /opt/reference/theme 를 등록하세요.";
  byId("project-root").textContent = state.projectRoots.find((item) => item.id === state.selectedProjectRootId)?.path || "";
  byId("project-status").textContent = state.projectRoots.length
    ? "등록된 project 루트를 불러오는 중입니다."
    : "디폴트 루트가 없습니다. Project Root에 /opt/projects 를 등록하세요.";
  renderWorkspaces();
  renderSessions(state.sessions, state.currentSession);
  renderActions();
  renderCliOptions();
  syncWorkspaceCaption();
  renderAccounts(state.bootstrap.accounts || [], state.bootstrap.currentAccountId || "");
  syncBrowserStatus(state.bootstrap.browser || {});
  if (state.selectedReferenceRootId) {
    await loadReferenceProjects();
    await loadReferenceTree();
  }
  if (state.selectedProjectRootId) {
    await loadProjectTree();
  }
  await refreshJobs();
  startBrowserPolling();
}

window.addEventListener("DOMContentLoaded", async () => {
  loadUiState();
  byId("run-selected-action").addEventListener("click", runAction);
  byId("run-custom-codex").addEventListener("click", runCustomCodex);
  byId("run-custom-shell").addEventListener("click", runCustomShell);
  byId("cancel-job").addEventListener("click", cancelCurrentJob);
  byId("refresh-jobs").addEventListener("click", refreshJobs);
  byId("clear-job-filter").addEventListener("click", () => {
    focusPlanStep("").catch((error) => {
      byId("raw-output").textContent = error instanceof Error ? error.message : String(error);
    });
  });
  byId("toggle-session-plan").addEventListener("click", () => {
    state.sessionPanelOpen.plan = !state.sessionPanelOpen.plan;
    syncSessionPanelToggles();
  });
  byId("toggle-session-tree").addEventListener("click", () => {
    state.sessionPanelOpen.tree = !state.sessionPanelOpen.tree;
    syncSessionPanelToggles();
  });
  byId("toggle-session-family").addEventListener("click", () => {
    state.sessionPanelOpen.family = !state.sessionPanelOpen.family;
    syncSessionPanelToggles();
  });
  byId("toggle-session-compare").addEventListener("click", () => {
    state.sessionPanelOpen.compare = !state.sessionPanelOpen.compare;
    syncSessionPanelToggles();
  });
  byId("refresh-sessions").addEventListener("click", refreshSessions);
  byId("save-session-context").addEventListener("click", saveSessionContext);
  byId("refresh-login").addEventListener("click", refreshLogin);
  byId("refresh-accounts").addEventListener("click", refreshAccounts);
  byId("create-session").addEventListener("click", createSession);
  byId("branch-session").addEventListener("click", branchSession);
  byId("save-current-account").addEventListener("click", saveCurrentAccount);
  byId("start-login").addEventListener("click", startLogin);
  byId("logout-login").addEventListener("click", logoutLogin);
  byId("open-browser-inline").addEventListener("click", () => openBrowserPreview(false));
  byId("open-browser-popup").addEventListener("click", () => openBrowserPreview(true));
  byId("browser-use-current").addEventListener("click", useCurrentBrowserAddress);
  byId("reference-image-preview").addEventListener("error", () => {
    byId("reference-image-preview").style.display = "none";
    byId("reference-image-preview").removeAttribute("src");
  });
  byId("reference-root-select").addEventListener("change", async () => {
    state.selectedReferenceRootId = byId("reference-root-select").value || "";
    state.selectedReferenceProject = "";
    state.selectedReferenceFolder = "";
    state.selectedReferencePath = "";
    state.selectedReferenceMeta = null;
    await loadReferenceProjects();
    await loadReferenceTree();
    syncReferencePreview();
  });
  byId("reference-project-select").addEventListener("change", async () => {
    state.selectedReferenceProject = byId("reference-project-select").value || "";
    state.selectedReferenceFolder = "";
    state.selectedReferencePath = "";
    state.selectedReferenceMeta = null;
    await loadReferenceTree();
    syncReferencePreview();
  });
  byId("reference-section-select").addEventListener("change", () => {
    state.referenceSection = byId("reference-section-select").value || "screen";
    state.selectedReferenceFolder = "";
    state.selectedReferencePath = "";
    state.selectedReferenceMeta = null;
    loadReferenceTree().catch((error) => {
      byId("raw-output").textContent = error instanceof Error ? error.message : String(error);
    });
    syncReferencePreview();
  });
  byId("project-root-select").addEventListener("change", async () => {
    state.selectedProjectRootId = byId("project-root-select").value || "";
    state.selectedProjectPath = "";
    byId("project-root").textContent = state.projectRoots.find((item) => item.id === state.selectedProjectRootId)?.path || "";
    await loadProjectTree();
    syncProjectSummary();
  });
  byId("reference-root-add").addEventListener("click", async () => {
    await addRoot("reference");
  });
  byId("reference-root-browse").addEventListener("click", async () => {
    await browseRootPath("reference");
  });
  byId("reference-root-delete").addEventListener("click", async () => {
    await deleteSelectedRoot("reference");
  });
  byId("project-root-add").addEventListener("click", async () => {
    await addRoot("project");
  });
  byId("project-root-browse").addEventListener("click", async () => {
    await browseRootPath("project");
  });
  byId("project-root-delete").addEventListener("click", async () => {
    await deleteSelectedRoot("project");
  });
  byId("project-search").addEventListener("input", () => {
    state.projectSearch = byId("project-search").value.trim();
    renderProjectSearchResults();
  });
  byId("project-search").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") {
      return;
    }
    const lowered = state.projectSearch.trim().toLowerCase();
    const matches = state.projectDirectories.filter((item) => `${item.name} ${item.path}`.toLowerCase().includes(lowered));
    if (matches.length) {
      selectProjectPath(matches[0].path).catch((error) => {
        byId("raw-output").textContent = error instanceof Error ? error.message : String(error);
      });
    }
  });
  byId("active-plan-step").addEventListener("change", () => {
    state.selectedPlanStep = byId("active-plan-step").value || "";
    state.selectedPlanStepBySession = {
      ...(state.selectedPlanStepBySession || {}),
      [state.selectedSessionId]: state.selectedPlanStep || ""
    };
    persistUiState();
    refreshJobs().catch((error) => {
      byId("raw-output").textContent = error instanceof Error ? error.message : String(error);
    });
  });
  byId("project-build-frontend").addEventListener("click", buildSelectedProjectFrontend);
  byId("project-package-backend").addEventListener("click", packageSelectedProjectBackend);
  byId("project-restart-18000").addEventListener("click", restartSelectedProject18000);
  byId("project-one-click").addEventListener("click", oneClickBuildAndRestart);
  byId("project-scan-menus").addEventListener("click", () => {
    scanProjectMenus().catch((error) => {
      byId("raw-output").textContent = error instanceof Error ? error.message : String(error);
    });
  });
  byId("project-use-menu-context").addEventListener("click", () => {
    const text = buildMenuContextPrompt();
    if (!text) {
      alert("먼저 메뉴를 선택하세요.");
      return;
    }
    byId("custom-codex-prompt").value += `${text}\n`;
  });
  byId("project-menu-group").addEventListener("change", () => {
    state.selectedMenuGroup = byId("project-menu-group").value || "home";
    state.selectedMenuItem = null;
    renderProjectMenuTree();
    syncMenuPreview();
  });
  byId("reference-folder-select").addEventListener("change", () => {
    state.selectedReferenceFolder = byId("reference-folder-select").value || "";
    state.selectedReferencePath = "";
    state.selectedReferenceMeta = null;
    renderReferenceTree();
    syncReferencePreview();
  });
  byId("insert-reference-context").addEventListener("click", () => {
    const meta = state.selectedReferenceMeta;
    if (!meta) {
      alert("먼저 reference 파일을 선택하세요.");
      return;
    }
    byId("custom-codex-prompt").value += buildReferencePrompt(meta);
  });
  byId("compose-reference-migration").addEventListener("click", () => {
    const meta = state.selectedReferenceMeta;
    if (!meta) {
      alert("먼저 reference 파일을 선택하세요.");
      return;
    }
    byId("custom-codex-prompt").value = buildMigrationPrompt(meta);
  });
  try {
    await bootstrap();
  } catch (error) {
    byId("raw-output").textContent = error instanceof Error ? error.message : String(error);
  }
});
