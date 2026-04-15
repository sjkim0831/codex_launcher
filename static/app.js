const PARALLEL_LOCAL_MODEL_OPTIONS = [
  "qwen2.5-coder:1.5b",
  "qwen2.5-coder:3b",
  "qwen2.5-coder:7b"
];

function parallelLocalModelControlMap() {
  return {
    "qwen2.5-coder:1.5b": "parallel-local-model-15b",
    "qwen2.5-coder:3b": "parallel-local-model-3b",
    "qwen2.5-coder:7b": "parallel-local-model-7b"
  };
}

const state = {
  instanceId: "default",
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
  selectedFreeAgentMode: "prompt",
  selectedFreeAgentModel: "",
  parallelAccountsEnabled: true,
  modelRoutingOptions: {
    enabled: true,
    memorySafeSingleLocalModel: true,
    escalateHardTasksToCodex: true,
    allowParallelLocalWorkers: true,
    parallelLocalWorkers: 3,
    parallelLocalSelectedModels: [...PARALLEL_LOCAL_MODEL_OPTIONS],
    parallelLocalKeepLoaded: false,
    parallelLocalAllLoadedRequired: false,
    parallelLocalFinalSynthesizer: "codex",
    parallelAccountMax: 14
  },
  localModelStatus: [],
  localModelWarmHandle: null,
  localModelAutoKeepWarm: false,
  localModelKeepAlive: "24h",
  localModelWarmIntervalMs: 30000,
  localModelLastResult: [],
  promptCompactionEnabled: true,
  promptRuntimeOptions: {
    includeSessionContext: true,
    allowSourceAnalysis: true,
    allowDocsRead: true,
    allowSkillsRead: true,
    preferMinimalScan: true,
    preferBriefOutput: true,
    focusScope: "",
    sessionContextLimit: 480
  },
  runtimePreset: "auto",
  selectedSidebarTab: "workspace",
  selectedMainTab: "compose",
  sessionPage: 1,
  jobPage: 1,
  sessionPageSize: 6,
  jobPageSize: 8,
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
  projectRuntimeStatus: null,
  projectAssemblies: { projects: [] },
  selectedProjectAssemblyId: "",
  projectRoots: [],
  selectedProjectRootId: "",
  projectDirectories: [],
  selectedProjectPath: "",
  projectSearch: "",
  projectMenus: null,
  selectedMenuGroup: "home",
  selectedMenuItem: null,
  pollHandle: null,
  outputRefreshHandle: null,
  browserPollHandle: null,
  lastBrowserCaptureId: ""
};

const UI_STATE_KEY_PREFIX = "carbonet-codex-ui-state";
const PASSWORD_ROUTE_PATH = "/mypage/password";

function currentInstanceId() {
  const params = new URLSearchParams(window.location.search);
  const value = (params.get("instance") || "").trim().toLowerCase();
  if (!value || value === "default") {
    return "default";
  }
  return value.replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || "default";
}

function currentRoutePath() {
  return (window.location.pathname || "/").replace(/\/+$/, "") || "/";
}

function isPasswordRoute() {
  return currentRoutePath() === PASSWORD_ROUTE_PATH;
}

function uiStateKey() {
  return `${UI_STATE_KEY_PREFIX}:${state.instanceId || "default"}`;
}

function withInstance(url) {
  const nextUrl = new URL(url, window.location.origin);
  if ((state.instanceId || "default") !== "default") {
    nextUrl.searchParams.set("instance", state.instanceId);
  } else {
    nextUrl.searchParams.delete("instance");
  }
  return `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`;
}

async function api(url, options = {}) {
  const response = await fetch(withInstance(url), {
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

function showPasswordRoute() {
  const routeShell = byId("password-route-shell");
  const launcherShell = document.querySelector(".app-shell");
  if (!routeShell || !launcherShell) {
    return;
  }
  routeShell.hidden = false;
  launcherShell.hidden = true;
}

function initPasswordRoute() {
  showPasswordRoute();
  const form = byId("password-route-form");
  const resetButton = byId("password-route-reset");
  const currentInput = byId("password-current");
  const nextInput = byId("password-next");
  const confirmInput = byId("password-confirm");
  const message = byId("password-route-message");
  if (!form || !resetButton || !currentInput || !nextInput || !confirmInput || !message) {
    return;
  }

  const setMessage = (text, tone = "muted") => {
    message.textContent = text;
    message.classList.remove("success-text", "danger-text");
    if (tone === "success") {
      message.classList.add("success-text");
    } else if (tone === "danger") {
      message.classList.add("danger-text");
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const currentPassword = currentInput.value.trim();
    const nextPassword = nextInput.value.trim();
    const confirmPassword = confirmInput.value.trim();

    if (!currentPassword || !nextPassword || !confirmPassword) {
      setMessage("모든 비밀번호 항목을 입력하세요.", "danger");
      return;
    }
    if (nextPassword.length < 8) {
      setMessage("새 비밀번호는 8자 이상으로 입력하세요.", "danger");
      return;
    }
    if (nextPassword !== confirmPassword) {
      setMessage("새 비밀번호와 확인 값이 일치하지 않습니다.", "danger");
      return;
    }
    setMessage("화면 진입과 입력 검증까지 연결되었습니다. 실제 저장 API만 남아 있습니다.", "success");
  });

  resetButton.addEventListener("click", () => {
    form.reset();
    setMessage("입력값을 초기화했습니다.");
  });
}

async function copyTextToClipboard(text) {
  const value = String(text || "");
  if (!value.trim()) {
    throw new Error("복사할 출력이 없습니다.");
  }
  await navigator.clipboard.writeText(value);
}

async function copyFinalOutput() {
  const button = byId("copy-final-output");
  const originalLabel = button.textContent;
  try {
    await copyTextToClipboard(byId("final-output").textContent);
    button.textContent = "Copied";
  } catch (error) {
    button.textContent = "Copy Failed";
    alert(error instanceof Error ? error.message : String(error));
  } finally {
    window.setTimeout(() => {
      button.textContent = originalLabel;
    }, 1200);
  }
}

async function copyPanelText(elementId, buttonId) {
  const button = byId(buttonId);
  const originalLabel = button.textContent;
  try {
    await copyTextToClipboard(byId(elementId).textContent);
    button.textContent = "Copied";
  } catch (error) {
    button.textContent = "Copy Failed";
    alert(error instanceof Error ? error.message : String(error));
  } finally {
    window.setTimeout(() => {
      button.textContent = originalLabel;
    }, 1200);
  }
}

function loadUiState() {
  try {
    const raw = window.localStorage.getItem(uiStateKey());
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
      if (typeof doc.selectedSidebarTab === "string" && doc.selectedSidebarTab) {
        state.selectedSidebarTab = doc.selectedSidebarTab;
      }
      if (typeof doc.selectedMainTab === "string" && doc.selectedMainTab) {
        state.selectedMainTab = doc.selectedMainTab;
      }
      if (typeof doc.promptCompactionEnabled === "boolean") {
        state.promptCompactionEnabled = doc.promptCompactionEnabled;
      }
      if (doc.promptRuntimeOptions && typeof doc.promptRuntimeOptions === "object") {
        state.promptRuntimeOptions = normalizePromptRuntimeOptions(doc.promptRuntimeOptions);
      }
      if (doc.modelRoutingOptions && typeof doc.modelRoutingOptions === "object") {
        state.modelRoutingOptions = normalizeModelRoutingOptions(doc.modelRoutingOptions);
      }
      if (typeof doc.localModelAutoKeepWarm === "boolean") {
        state.localModelAutoKeepWarm = doc.localModelAutoKeepWarm;
      }
      if (typeof doc.localModelKeepAlive === "string" && doc.localModelKeepAlive) {
        state.localModelKeepAlive = doc.localModelKeepAlive;
      }
      if (Number(doc.localModelWarmIntervalMs) > 0) {
        state.localModelWarmIntervalMs = Number(doc.localModelWarmIntervalMs);
      }
      if (typeof doc.runtimePreset === "string" && doc.runtimePreset) {
        state.runtimePreset = doc.runtimePreset;
      }
    }
  } catch (_error) {
    // Ignore invalid local UI state.
  }
}

function persistUiState() {
  try {
    window.localStorage.setItem(uiStateKey(), JSON.stringify({
      sessionPanelOpen: state.sessionPanelOpen,
      selectedPlanStepBySession: state.selectedPlanStepBySession || {},
      selectedSidebarTab: state.selectedSidebarTab,
      selectedMainTab: state.selectedMainTab,
      promptCompactionEnabled: state.promptCompactionEnabled,
      promptRuntimeOptions: normalizePromptRuntimeOptions(state.promptRuntimeOptions),
      modelRoutingOptions: normalizeModelRoutingOptions(state.modelRoutingOptions),
      localModelAutoKeepWarm: state.localModelAutoKeepWarm,
      localModelKeepAlive: state.localModelKeepAlive,
      localModelWarmIntervalMs: state.localModelWarmIntervalMs,
      runtimePreset: state.runtimePreset || "auto"
    }));
  } catch (_error) {
    // Ignore localStorage failures.
  }
}

function formatDateTime(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) {
    return raw;
  }
  return date.toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "Asia/Seoul"
  }) + " KST";
}

function formatRelativeTime(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const diffMs = date.getTime() - Date.now();
  const absSeconds = Math.round(Math.abs(diffMs) / 1000);
  const minutes = Math.round(absSeconds / 60);
  const hours = Math.round(absSeconds / 3600);
  const days = Math.round(absSeconds / 86400);
  const amount = days >= 1 ? days : hours >= 1 ? hours : Math.max(1, minutes);
  const unit = days >= 1 ? "day" : hours >= 1 ? "hour" : "minute";
  const formatter = new Intl.RelativeTimeFormat("ko-KR", { numeric: "auto" });
  return formatter.format(diffMs >= 0 ? amount : -amount, unit);
}

function compactPromptText(value, limit = 1200) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  const collapsed = raw.replace(/\n{3,}/g, "\n\n");
  if (collapsed.length <= limit) {
    return collapsed;
  }
  return `${collapsed.slice(0, Math.max(0, limit - 48)).trimEnd()}\n...[truncated]`;
}

function appendPromptText(text) {
  const target = byId("custom-codex-prompt");
  const current = target.value || "";
  target.value = current ? `${current}${current.endsWith("\n") ? "" : "\n"}${text}` : text;
}

function setRawOutputText(text) {
  const target = byId("raw-output");
  const nextText = String(text ?? "");
  if (target.textContent === nextText) {
    return;
  }
  const distanceFromBottom = target.scrollHeight - target.scrollTop - target.clientHeight;
  const shouldStickToBottom = distanceFromBottom <= 48;
  target.textContent = nextText;
  if (!shouldStickToBottom) {
    return;
  }
  window.requestAnimationFrame(() => {
    target.scrollTop = target.scrollHeight;
  });
}

function getPromptSourceText(value, limit) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  if (!state.promptCompactionEnabled) {
    return raw;
  }
  return compactPromptText(raw, limit);
}

function syncPromptCompactionToggle() {
  const checkbox = byId("prompt-compaction-toggle");
  if (!checkbox) {
    return;
  }
  checkbox.checked = Boolean(state.promptCompactionEnabled);
  checkbox.setAttribute("aria-checked", checkbox.checked ? "true" : "false");
  persistUiState();
}

function normalizePromptRuntimeOptions(value = {}) {
  const source = value && typeof value === "object" ? value : {};
  return {
    includeBrowserContext: source.includeBrowserContext !== false,
    includeReferenceContext: source.includeReferenceContext !== false,
    includeMenuContext: source.includeMenuContext !== false,
    autoSaverForQuestions: source.autoSaverForQuestions !== false,
    compactPreferencePreamble: source.compactPreferencePreamble === true,
    omitPreferencePreamble: source.omitPreferencePreamble === true,
    compactPromptWhitespace: source.compactPromptWhitespace !== false,
    dedupeConsecutivePromptLines: source.dedupeConsecutivePromptLines !== false,
    stripMarkdownFences: source.stripMarkdownFences === true,
    includeSessionContext: source.includeSessionContext !== false,
    allowSourceAnalysis: source.allowSourceAnalysis !== false,
    allowDocsRead: source.allowDocsRead !== false,
    allowSkillsRead: source.allowSkillsRead !== false,
    preferMinimalScan: source.preferMinimalScan !== false,
    preferBriefOutput: source.preferBriefOutput !== false,
    focusScope: String(source.focusScope || "").trim(),
    sessionContextLimit: Math.max(0, Number(source.sessionContextLimit ?? 480) || 0),
    promptCharsLimit: Math.max(0, Number(source.promptCharsLimit ?? 0) || 0)
  };
}

function normalizeModelRoutingOptions(value = {}) {
  const source = value && typeof value === "object" ? value : {};
  const selectedModels = Array.isArray(source.parallelLocalSelectedModels)
    ? source.parallelLocalSelectedModels.map((item) => String(item || "").trim()).filter((item) => PARALLEL_LOCAL_MODEL_OPTIONS.includes(item))
    : [];
  return {
    enabled: source.enabled !== false,
    memorySafeSingleLocalModel: source.memorySafeSingleLocalModel !== false,
    escalateHardTasksToCodex: source.escalateHardTasksToCodex !== false,
    allowParallelLocalWorkers: source.allowParallelLocalWorkers !== false,
    parallelLocalWorkers: Math.max(1, Math.min(4, Number(source.parallelLocalWorkers ?? 3) || 3)),
    parallelLocalSelectedModels: selectedModels.length ? [...new Set(selectedModels)] : [...PARALLEL_LOCAL_MODEL_OPTIONS],
    parallelLocalKeepLoaded: Boolean(source.parallelLocalKeepLoaded),
    parallelLocalAllLoadedRequired: Boolean(source.parallelLocalAllLoadedRequired),
    parallelLocalFinalSynthesizer: ["off", "ready-first", "local-7b", "codex"].includes(String(source.parallelLocalFinalSynthesizer || ""))
      ? String(source.parallelLocalFinalSynthesizer)
      : "codex",
    parallelAccountMax: Math.max(1, Math.min(14, Number(source.parallelAccountMax ?? 14) || 14))
  };
}

function runtimePresetOptions(preset) {
  if (preset === "saver") {
    return {
      includeBrowserContext: false,
      includeReferenceContext: false,
      includeMenuContext: false,
      autoSaverForQuestions: true,
      compactPreferencePreamble: true,
      omitPreferencePreamble: true,
      compactPromptWhitespace: true,
      dedupeConsecutivePromptLines: true,
      stripMarkdownFences: false,
      includeSessionContext: false,
      allowSourceAnalysis: false,
      allowDocsRead: false,
      allowSkillsRead: false,
      preferMinimalScan: true,
      preferBriefOutput: true,
      focusScope: "",
      sessionContextLimit: 120,
      promptCharsLimit: 800
    };
  }
  if (preset === "question") {
    return {
      includeBrowserContext: false,
      includeReferenceContext: false,
      includeMenuContext: false,
      autoSaverForQuestions: true,
      compactPreferencePreamble: true,
      omitPreferencePreamble: true,
      compactPromptWhitespace: true,
      dedupeConsecutivePromptLines: true,
      stripMarkdownFences: false,
      includeSessionContext: false,
      allowSourceAnalysis: false,
      allowDocsRead: false,
      allowSkillsRead: false,
      preferMinimalScan: true,
      preferBriefOutput: true,
      focusScope: "",
      sessionContextLimit: 80,
      promptCharsLimit: 600
    };
  }
  if (preset === "summary") {
    return {
      includeBrowserContext: false,
      includeReferenceContext: false,
      includeMenuContext: false,
      autoSaverForQuestions: true,
      compactPreferencePreamble: true,
      omitPreferencePreamble: false,
      compactPromptWhitespace: true,
      dedupeConsecutivePromptLines: true,
      stripMarkdownFences: false,
      includeSessionContext: false,
      allowSourceAnalysis: true,
      allowDocsRead: true,
      allowSkillsRead: false,
      preferMinimalScan: true,
      preferBriefOutput: true,
      focusScope: "",
      sessionContextLimit: 180,
      promptCharsLimit: 1200
    };
  }
  if (preset === "migration") {
    return {
      includeBrowserContext: false,
      includeReferenceContext: true,
      includeMenuContext: false,
      autoSaverForQuestions: false,
      compactPreferencePreamble: true,
      omitPreferencePreamble: false,
      compactPromptWhitespace: true,
      dedupeConsecutivePromptLines: true,
      stripMarkdownFences: false,
      includeSessionContext: true,
      allowSourceAnalysis: true,
      allowDocsRead: false,
      allowSkillsRead: false,
      preferMinimalScan: true,
      preferBriefOutput: false,
      focusScope: "",
      sessionContextLimit: 240,
      promptCharsLimit: 2200
    };
  }
  if (preset === "implementation") {
    return {
      includeBrowserContext: true,
      includeReferenceContext: false,
      includeMenuContext: true,
      autoSaverForQuestions: false,
      compactPreferencePreamble: true,
      omitPreferencePreamble: false,
      compactPromptWhitespace: true,
      dedupeConsecutivePromptLines: true,
      stripMarkdownFences: false,
      includeSessionContext: true,
      allowSourceAnalysis: true,
      allowDocsRead: false,
      allowSkillsRead: false,
      preferMinimalScan: true,
      preferBriefOutput: false,
      focusScope: "",
      sessionContextLimit: 320,
      promptCharsLimit: 2400
    };
  }
  if (preset === "review") {
    return {
      includeBrowserContext: false,
      includeReferenceContext: false,
      includeMenuContext: false,
      autoSaverForQuestions: false,
      compactPreferencePreamble: true,
      omitPreferencePreamble: false,
      compactPromptWhitespace: true,
      dedupeConsecutivePromptLines: true,
      stripMarkdownFences: false,
      includeSessionContext: true,
      allowSourceAnalysis: true,
      allowDocsRead: false,
      allowSkillsRead: false,
      preferMinimalScan: true,
      preferBriefOutput: true,
      focusScope: "",
      sessionContextLimit: 320,
      promptCharsLimit: 1800
    };
  }
  if (preset === "debug") {
    return {
      includeBrowserContext: false,
      includeReferenceContext: false,
      includeMenuContext: false,
      autoSaverForQuestions: false,
      compactPreferencePreamble: false,
      omitPreferencePreamble: false,
      compactPromptWhitespace: true,
      dedupeConsecutivePromptLines: true,
      stripMarkdownFences: false,
      includeSessionContext: true,
      allowSourceAnalysis: true,
      allowDocsRead: true,
      allowSkillsRead: false,
      preferMinimalScan: true,
      preferBriefOutput: false,
      focusScope: "",
      sessionContextLimit: 480,
      promptCharsLimit: 2200
    };
  }
  if (preset === "lite") {
    return {
      includeBrowserContext: false,
      includeReferenceContext: false,
      includeMenuContext: false,
      autoSaverForQuestions: true,
      compactPreferencePreamble: true,
      omitPreferencePreamble: false,
      compactPromptWhitespace: true,
      dedupeConsecutivePromptLines: true,
      stripMarkdownFences: false,
      includeSessionContext: false,
      allowSourceAnalysis: false,
      allowDocsRead: false,
      allowSkillsRead: false,
      preferMinimalScan: true,
      preferBriefOutput: true,
      focusScope: "",
      sessionContextLimit: 240,
      promptCharsLimit: 1600
    };
  }
  if (preset === "full") {
    return {
      includeBrowserContext: true,
      includeReferenceContext: true,
      includeMenuContext: true,
      autoSaverForQuestions: false,
      compactPreferencePreamble: false,
      omitPreferencePreamble: false,
      compactPromptWhitespace: false,
      dedupeConsecutivePromptLines: false,
      stripMarkdownFences: false,
      includeSessionContext: true,
      allowSourceAnalysis: true,
      allowDocsRead: true,
      allowSkillsRead: true,
      preferMinimalScan: false,
      preferBriefOutput: false,
      focusScope: "",
      sessionContextLimit: 0,
      promptCharsLimit: 0
    };
  }
  return {
    includeBrowserContext: true,
    includeReferenceContext: true,
    includeMenuContext: true,
    autoSaverForQuestions: true,
    compactPreferencePreamble: false,
    omitPreferencePreamble: false,
    compactPromptWhitespace: true,
    dedupeConsecutivePromptLines: true,
    stripMarkdownFences: false,
    includeSessionContext: true,
    allowSourceAnalysis: true,
    allowDocsRead: true,
    allowSkillsRead: true,
    preferMinimalScan: true,
    preferBriefOutput: true,
    focusScope: "",
    sessionContextLimit: 480,
    promptCharsLimit: 0
  };
}

function detectRuntimePreset(options) {
  const normalized = normalizePromptRuntimeOptions(options);
  for (const preset of ["saver", "question", "summary", "migration", "implementation", "review", "debug", "lite", "balanced", "full"]) {
    const candidate = runtimePresetOptions(preset);
    const matches = Object.keys(candidate).every((key) => candidate[key] === normalized[key]);
    if (matches) {
      return preset;
    }
  }
  return "custom";
}

function syncPromptRuntimeOptionsControls() {
  const options = normalizePromptRuntimeOptions(state.promptRuntimeOptions);
  state.promptRuntimeOptions = options;
  const bindings = [
    ["runtime-browser-context-toggle", "includeBrowserContext"],
    ["runtime-reference-context-toggle", "includeReferenceContext"],
    ["runtime-menu-context-toggle", "includeMenuContext"],
    ["runtime-question-saver-toggle", "autoSaverForQuestions"],
    ["runtime-compact-preamble-toggle", "compactPreferencePreamble"],
    ["runtime-omit-preamble-toggle", "omitPreferencePreamble"],
    ["runtime-whitespace-compact-toggle", "compactPromptWhitespace"],
    ["runtime-dedupe-lines-toggle", "dedupeConsecutivePromptLines"],
    ["runtime-strip-fences-toggle", "stripMarkdownFences"],
    ["runtime-session-context-toggle", "includeSessionContext"],
    ["runtime-source-analysis-toggle", "allowSourceAnalysis"],
    ["runtime-docs-toggle", "allowDocsRead"],
    ["runtime-skills-toggle", "allowSkillsRead"],
    ["runtime-minimal-scan-toggle", "preferMinimalScan"],
    ["runtime-brief-output-toggle", "preferBriefOutput"]
  ];
  bindings.forEach(([id, key]) => {
    const checkbox = byId(id);
    if (!checkbox) {
      return;
    }
    checkbox.checked = Boolean(options[key]);
    checkbox.setAttribute("aria-checked", checkbox.checked ? "true" : "false");
  });
  const preset = detectRuntimePreset(options);
  if (state.runtimePreset !== "auto") {
    state.runtimePreset = preset;
  }
  const presetSelect = byId("runtime-preset-select");
  if (presetSelect) {
    presetSelect.value = state.runtimePreset === "auto" ? "auto" : preset;
  }
  const focusInput = byId("runtime-focus-scope");
  if (focusInput) {
    focusInput.value = options.focusScope || "";
  }
  const limitSelect = byId("runtime-session-context-limit");
  if (limitSelect) {
    limitSelect.value = String(options.sessionContextLimit || 0);
  }
  const promptLimitSelect = byId("runtime-prompt-chars-limit");
  if (promptLimitSelect) {
    promptLimitSelect.value = String(options.promptCharsLimit || 0);
  }
  persistUiState();
}

function readPromptRuntimeOptionsFromControls() {
  state.promptRuntimeOptions = normalizePromptRuntimeOptions({
    includeBrowserContext: byId("runtime-browser-context-toggle").checked,
    includeReferenceContext: byId("runtime-reference-context-toggle").checked,
    includeMenuContext: byId("runtime-menu-context-toggle").checked,
    autoSaverForQuestions: byId("runtime-question-saver-toggle").checked,
    compactPreferencePreamble: byId("runtime-compact-preamble-toggle").checked,
    omitPreferencePreamble: byId("runtime-omit-preamble-toggle").checked,
    compactPromptWhitespace: byId("runtime-whitespace-compact-toggle").checked,
    dedupeConsecutivePromptLines: byId("runtime-dedupe-lines-toggle").checked,
    stripMarkdownFences: byId("runtime-strip-fences-toggle").checked,
    includeSessionContext: byId("runtime-session-context-toggle").checked,
    allowSourceAnalysis: byId("runtime-source-analysis-toggle").checked,
    allowDocsRead: byId("runtime-docs-toggle").checked,
    allowSkillsRead: byId("runtime-skills-toggle").checked,
    preferMinimalScan: byId("runtime-minimal-scan-toggle").checked,
    preferBriefOutput: byId("runtime-brief-output-toggle").checked,
    focusScope: byId("runtime-focus-scope").value.trim(),
    sessionContextLimit: Number(byId("runtime-session-context-limit").value || 0),
    promptCharsLimit: Number(byId("runtime-prompt-chars-limit").value || 0)
  });
  const currentSelection = byId("runtime-preset-select")?.value || state.runtimePreset || "auto";
  const detectedPreset = detectRuntimePreset(state.promptRuntimeOptions);
  state.runtimePreset = currentSelection === "auto" ? "auto" : detectedPreset;
  const presetSelect = byId("runtime-preset-select");
  if (presetSelect) {
    presetSelect.value = state.runtimePreset;
  }
  persistUiState();
  return state.promptRuntimeOptions;
}

function shouldIncludeBrowserContext() {
  return normalizePromptRuntimeOptions(state.promptRuntimeOptions).includeBrowserContext;
}

function shouldIncludeReferenceContext() {
  return normalizePromptRuntimeOptions(state.promptRuntimeOptions).includeReferenceContext;
}

function shouldIncludeMenuContext() {
  return normalizePromptRuntimeOptions(state.promptRuntimeOptions).includeMenuContext;
}

function applyRuntimePreset(preset) {
  state.runtimePreset = preset;
  state.promptRuntimeOptions = normalizePromptRuntimeOptions(runtimePresetOptions(preset));
  syncPromptRuntimeOptionsControls();
}

function syncModelRoutingControls() {
  state.modelRoutingOptions = normalizeModelRoutingOptions(state.modelRoutingOptions);
  const bindings = [
    ["model-routing-enabled-toggle", "enabled"],
    ["single-local-model-toggle", "memorySafeSingleLocalModel"],
    ["hard-task-codex-toggle", "escalateHardTasksToCodex"],
    ["parallel-local-workers-toggle", "allowParallelLocalWorkers"],
    ["parallel-local-keep-loaded-toggle", "parallelLocalKeepLoaded"],
    ["parallel-local-all-loaded-required-toggle", "parallelLocalAllLoadedRequired"]
  ];
  bindings.forEach(([id, key]) => {
    const checkbox = byId(id);
    if (!checkbox) {
      return;
    }
    checkbox.checked = Boolean(state.modelRoutingOptions[key]);
    checkbox.setAttribute("aria-checked", checkbox.checked ? "true" : "false");
  });
  const workerSelect = byId("parallel-local-workers-count");
  if (workerSelect) {
    workerSelect.value = String(state.modelRoutingOptions.parallelLocalWorkers || 1);
  }
  const controlMap = parallelLocalModelControlMap();
  PARALLEL_LOCAL_MODEL_OPTIONS.forEach((model) => {
    const checkbox = byId(controlMap[model]);
    if (checkbox) {
      checkbox.checked = state.modelRoutingOptions.parallelLocalSelectedModels.includes(model);
      checkbox.setAttribute("aria-checked", checkbox.checked ? "true" : "false");
    }
  });
  const synthesizerSelect = byId("parallel-local-final-synthesizer");
  if (synthesizerSelect) {
    synthesizerSelect.value = state.modelRoutingOptions.parallelLocalFinalSynthesizer || "ready-first";
  }
  const accountMaxSelect = byId("parallel-account-max");
  if (accountMaxSelect) {
    accountMaxSelect.value = String(state.modelRoutingOptions.parallelAccountMax || 14);
  }
  const autoKeepWarmToggle = byId("parallel-local-auto-keep-warm-toggle");
  if (autoKeepWarmToggle) {
    autoKeepWarmToggle.checked = Boolean(state.localModelAutoKeepWarm);
  }
  const keepAliveSelect = byId("parallel-local-keepalive-select");
  if (keepAliveSelect) {
    keepAliveSelect.value = state.localModelKeepAlive || "24h";
  }
  const warmIntervalSelect = byId("parallel-local-warm-interval-select");
  if (warmIntervalSelect) {
    warmIntervalSelect.value = String(state.localModelWarmIntervalMs || 30000);
  }
  persistUiState();
}

function readModelRoutingOptionsFromControls() {
  state.modelRoutingOptions = normalizeModelRoutingOptions({
    enabled: byId("model-routing-enabled-toggle")?.checked,
    memorySafeSingleLocalModel: byId("single-local-model-toggle")?.checked,
    escalateHardTasksToCodex: byId("hard-task-codex-toggle")?.checked,
    allowParallelLocalWorkers: byId("parallel-local-workers-toggle")?.checked,
    parallelLocalWorkers: Number(byId("parallel-local-workers-count")?.value || 3),
    parallelLocalSelectedModels: PARALLEL_LOCAL_MODEL_OPTIONS.filter((model) => {
      const checkbox = byId(parallelLocalModelControlMap()[model]);
      return checkbox?.checked;
    }),
    parallelLocalKeepLoaded: byId("parallel-local-keep-loaded-toggle")?.checked,
    parallelLocalAllLoadedRequired: byId("parallel-local-all-loaded-required-toggle")?.checked,
    parallelLocalFinalSynthesizer: byId("parallel-local-final-synthesizer")?.value || "codex",
    parallelAccountMax: Number(byId("parallel-account-max")?.value || 14)
  });
  persistUiState();
  return state.modelRoutingOptions;
}

function selectedParallelLocalModels() {
  return PARALLEL_LOCAL_MODEL_OPTIONS.filter((model) => {
    const checkbox = byId(parallelLocalModelControlMap()[model]);
    return checkbox?.checked;
  });
}

function renderLocalModelLastResult(items = []) {
  const target = byId("parallel-local-last-result");
  if (!target) {
    return;
  }
  const rows = Array.isArray(items) ? items : [];
  target.innerHTML = rows.length
    ? rows.map((item) => {
      const tone = item?.ok ? "success" : "danger";
      const bits = [
        String(item?.name || "unknown"),
        item?.ok ? "ok" : "failed",
        String(item?.reasonLabel || ""),
        String(item?.message || ""),
        item?.loaded ? "loaded" : "not-loaded",
        item?.expiresAt ? `expires ${String(item.expiresAt)}` : ""
      ].filter(Boolean);
      return `<div><span class="pill ${escapeAttribute(tone)}">${escapeHtml(bits[0])}</span> ${escapeHtml(bits.slice(1).join(" · "))}</div>`;
    }).join("")
    : "기록 없음";
}

async function refreshLocalModelStatus() {
  const models = selectedParallelLocalModels();
  const target = byId("parallel-local-loaded-status");
  if (!target) {
    return [];
  }
  if (!models.length) {
    state.localModelStatus = [];
    target.textContent = "선택된 로컬 모델이 없습니다.";
    return [];
  }
  const response = await api(`/api/freeagent/loaded-models?models=${encodeURIComponent(models.join(","))}`);
  state.localModelStatus = Array.isArray(response?.items) ? response.items : [];
  const summary = response?.summary && typeof response.summary === "object" ? response.summary : {};
  const loadedCount = state.localModelStatus.filter((item) => item?.loaded).length;
  const readyCount = state.localModelStatus.filter((item) => item?.ready).length;
  const allLoaded = models.length > 0 && loadedCount === models.length;
  const summaryPills = [
    `<span class="pill ${allLoaded ? "success" : "warning"}">${escapeHtml(allLoaded ? "all loaded" : `loaded ${loadedCount}/${models.length}`)}</span>`,
    `<span class="pill">${escapeHtml(`ready ${readyCount}/${models.length}`)}</span>`
  ];
  if (summary?.selectedTotalBytes) {
    summaryPills.push(`<span class="pill">${escapeHtml(`selected ${formatBytes(Number(summary.selectedTotalBytes) || 0)}`)}</span>`);
  }
  if (summary?.safeBudgetBytes) {
    const overBudget = Number(summary.selectedTotalBytes || 0) > Number(summary.safeBudgetBytes || 0);
    summaryPills.push(`<span class="pill ${overBudget ? "danger" : ""}">${escapeHtml(`safe budget ${formatBytes(Number(summary.safeBudgetBytes) || 0)}`)}</span>`);
  }
  const memoryBits = [];
  if (summary?.memory?.totalBytes) {
    memoryBits.push(`RAM ${formatBytes(Number(summary.memory.totalBytes) || 0)}`);
  }
  if (summary?.memory?.availableBytes) {
    memoryBits.push(`available ${formatBytes(Number(summary.memory.availableBytes) || 0)}`);
  }
  if (summary?.memory?.swapTotalBytes) {
    const swapUsed = Math.max(0, Number(summary.memory.swapTotalBytes || 0) - Number(summary.memory.swapFreeBytes || 0));
    memoryBits.push(`swap used ${formatBytes(swapUsed)}/${formatBytes(Number(summary.memory.swapTotalBytes) || 0)}`);
  }
  const warningBlock = summary?.warning
    ? `<div><span class="pill danger">RAM 경고</span> ${escapeHtml(String(summary.warning || ""))}</div>`
    : "";
  const recommendationBlock = summary?.recommendation
    ? `<div><span class="pill">recommended</span> ${escapeHtml(`추천 조합 ${String(summary.recommendation || "")}`)}</div>`
    : "";
  const memoryBlock = memoryBits.length
    ? `<div class="muted">${escapeHtml(memoryBits.join(" · "))}</div>`
    : "";
  target.innerHTML = `
    <div class="current-account-pills">${summaryPills.join("")}</div>
    ${warningBlock}
    ${recommendationBlock}
    ${memoryBlock}
    ${state.localModelStatus.map((item) => {
      const bits = [
        item?.ready ? "ready" : String(item?.reason || "not ready"),
        item?.loaded ? "loaded" : "not-loaded",
        item?.sizeBytes ? `size ${formatBytes(Number(item.sizeBytes) || 0)}` : "",
        item?.sizeVram ? `vram ${formatBytes(Number(item.sizeVram) || 0)}` : "",
        item?.expiresAt ? `expires ${String(item.expiresAt)}` : ""
      ].filter(Boolean);
      return `<div><strong>${escapeHtml(String(item?.name || "unknown"))}</strong> · ${escapeHtml(bits.join(" · "))}</div>`;
    }).join("") || "상태 없음"}
  `;
  return state.localModelStatus;
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size >= 10 || index === 0 ? Math.round(size) : size.toFixed(1)} ${units[index]}`;
}

async function preloadSelectedLocalModels() {
  const models = selectedParallelLocalModels();
  if (!models.length) {
    return;
  }
  state.localModelKeepAlive = String(byId("parallel-local-keepalive-select")?.value || state.localModelKeepAlive || "24h");
  persistUiState();
  const response = await api("/api/freeagent/preload-models", {
    method: "POST",
    body: JSON.stringify({ models, keepAlive: state.localModelKeepAlive })
  });
  state.localModelLastResult = Array.isArray(response?.items) ? response.items : [];
  renderLocalModelLastResult(state.localModelLastResult);
  await refreshLocalModelStatus();
  setRawOutputText((state.localModelLastResult || []).map((item) => {
    return `${item.name}: ${item.ok ? "ok" : "failed"} · ${item.reasonLabel || ""} · ${item.message} · ${item.loaded ? "loaded" : "not-loaded"}`;
  }).join("\n"));
}

async function retryMissingLocalModels() {
  const items = await refreshLocalModelStatus();
  const missing = items
    .filter((item) => item?.ready && !item?.loaded)
    .map((item) => String(item?.name || "").trim())
    .filter(Boolean);
  if (!missing.length) {
    setRawOutputText("모든 선택 모델이 이미 loaded 상태입니다.");
    return;
  }
  state.localModelKeepAlive = String(byId("parallel-local-keepalive-select")?.value || state.localModelKeepAlive || "24h");
  persistUiState();
  const response = await api("/api/freeagent/preload-models", {
    method: "POST",
    body: JSON.stringify({ models: missing, keepAlive: state.localModelKeepAlive })
  });
  state.localModelLastResult = Array.isArray(response?.items) ? response.items : [];
  renderLocalModelLastResult(state.localModelLastResult);
  await refreshLocalModelStatus();
  setRawOutputText((state.localModelLastResult || []).map((item) => {
    return `${item.name}: ${item.ok ? "ok" : "failed"} · ${item.reasonLabel || ""} · ${item.message} · ${item.loaded ? "loaded" : "not-loaded"}`;
  }).join("\n"));
}

async function unloadSelectedLocalModels() {
  const models = selectedParallelLocalModels();
  if (!models.length) {
    return;
  }
  const response = await api("/api/freeagent/unload-models", {
    method: "POST",
    body: JSON.stringify({ models })
  });
  state.localModelLastResult = Array.isArray(response?.items) ? response.items : [];
  renderLocalModelLastResult(state.localModelLastResult);
  await refreshLocalModelStatus();
  setRawOutputText((state.localModelLastResult || []).map((item) => {
    return `${item.name}: ${item.ok ? "ok" : "failed"} · ${item.reasonLabel || ""} · ${item.message} · ${item.loaded ? "loaded" : "not-loaded"}`;
  }).join("\n"));
}

function syncLocalModelWarmLoop() {
  if (state.localModelWarmHandle) {
    window.clearInterval(state.localModelWarmHandle);
    state.localModelWarmHandle = null;
  }
  if (!state.localModelAutoKeepWarm) {
    return;
  }
  state.localModelWarmIntervalMs = Number(byId("parallel-local-warm-interval-select")?.value || state.localModelWarmIntervalMs || 30000);
  state.localModelKeepAlive = String(byId("parallel-local-keepalive-select")?.value || state.localModelKeepAlive || "24h");
  persistUiState();
  state.localModelWarmHandle = window.setInterval(async () => {
    try {
      const items = await refreshLocalModelStatus();
      const missing = items.filter((item) => item?.ready && !item?.loaded).map((item) => String(item.name || "").trim()).filter(Boolean);
      if (missing.length) {
        const response = await api("/api/freeagent/preload-models", {
          method: "POST",
          body: JSON.stringify({ models: missing, keepAlive: state.localModelKeepAlive })
        });
        state.localModelLastResult = Array.isArray(response?.items) ? response.items : [];
        renderLocalModelLastResult(state.localModelLastResult);
        await refreshLocalModelStatus();
      }
    } catch (error) {
      console.error(error);
    }
  }, state.localModelWarmIntervalMs);
}

function syncComposerDefaultsFromAction(action) {
  if (!action) {
    return;
  }
  if (action.runtimePreset) {
    applyRuntimePreset(action.runtimePreset);
  }
}

function buildPromptPreviewRequest() {
  const action = getSelectedAction();
  const runtimeOptions = readPromptRuntimeOptionsFromControls();
  const runtimePreset = byId("runtime-preset-select")?.value || state.runtimePreset || "auto";
  const base = {
    sessionId: state.selectedSessionId,
    planStep: state.selectedPlanStep,
    workspaceId: state.selectedWorkspaceId,
    projectPath: state.selectedProjectPath,
    modelRouting: readModelRoutingOptionsFromControls(),
    runtimeOptions,
    runtimePreset
  };
  if (action?.kind === "codex" && state.selectedActionId) {
    return {
      ...base,
      actionId: state.selectedActionId,
      extraInput: byId("extra-input").value,
      prompt: (byId("custom-codex-prompt").value || "").trim() || getActionPromptTemplate(action)
    };
  }
  const prompt = byId("custom-codex-prompt").value.trim();
  return {
    ...base,
    mode: "assistant_custom",
    cli: state.selectedCli,
    freeagentMode: state.selectedFreeAgentMode,
    freeagentModel: byId("freeagent-model-input").value.trim(),
    freeagentTargets: byId("freeagent-targets").value.trim(),
    freeagentTestCommand: byId("freeagent-test-command").value.trim(),
    parallelAccounts: byId("parallel-accounts-toggle")?.checked || false,
    prompt
  };
}

async function refreshPromptPreview() {
  const stats = byId("prompt-preview-stats");
  const note = byId("prompt-preview-note");
  const preview = byId("prompt-preview");
  const request = buildPromptPreviewRequest();
  const prompt = String(request.prompt || "").trim();
  if (!prompt) {
    stats.textContent = "prompt 없음";
    note.textContent = "먼저 AI Prompt를 입력하거나 Codex Quick Action을 선택하세요.";
    preview.textContent = "미리볼 prompt가 없습니다.";
    return;
  }
  stats.textContent = "계산 중...";
  try {
    const payload = await api("/api/prompt-preview", {
      method: "POST",
      body: JSON.stringify(request)
    });
    const estimatedTokens = Number(payload.estimatedTokens || 0).toLocaleString("ko-KR");
    stats.textContent = `${payload.promptChars || 0} chars · ${payload.promptLines || 0} lines · ~${estimatedTokens} tokens`;
    const noteBits = [payload.note || "실행 직전 서버 기준 미리보기입니다."];
    if (payload.effectiveCli || payload.effectiveModel) {
      noteBits.push(`effective=${payload.effectiveCli || "unknown"}${payload.effectiveModel ? `:${payload.effectiveModel}` : ""}`);
    }
    if (payload.routeNote) {
      noteBits.push(payload.routeNote);
    }
    if (Array.isArray(payload.localModelInspection) && payload.localModelInspection.length) {
      const notReady = payload.localModelInspection.filter((item) => !item.ready).map((item) => item.name);
      if (notReady.length) {
        noteBits.push(`model-missing=${notReady.join(", ")}`);
      }
    }
    note.textContent = noteBits.filter(Boolean).join(" · ");
    const sections = [];
    if (payload.commandPreview) {
      sections.push("[Command]");
      sections.push(payload.commandPreview);
    }
    if (payload.effectivePrompt) {
      sections.push("");
      sections.push("[Effective Prompt]");
      sections.push(payload.effectivePrompt);
    } else {
      sections.push(payload.message || "Prompt preview unavailable.");
    }
    preview.textContent = sections.join("\n");
  } catch (error) {
    stats.textContent = "preview 실패";
    note.textContent = error instanceof Error ? error.message : String(error);
    preview.textContent = "미리보기를 계산하지 못했습니다.";
  }
}

function getActionPromptTemplate(action) {
  if (!action || action.kind !== "codex") {
    return "";
  }
  if (state.promptCompactionEnabled) {
    return action.promptTemplate || "";
  }
  return action.verbosePromptTemplate || action.promptTemplate || "";
}

function getSelectedAction() {
  return (state.bootstrap?.actions || []).find((item) => item.id === state.selectedActionId) || null;
}

function syncSelectedActionPrompt(force = false) {
  const action = getSelectedAction();
  if (!action || action.kind !== "codex") {
    return;
  }
  const target = byId("custom-codex-prompt");
  const compact = action.promptTemplate || "";
  const verbose = action.verbosePromptTemplate || compact;
  const next = getActionPromptTemplate(action);
  const current = target.value || "";
  const shouldReplace = force || !current || current === compact || current === verbose;
  if (shouldReplace) {
    target.value = next;
  }
  refreshPromptPreview().catch(() => {});
}

function formatScheduleMoment(label, value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return `${label}: 확인 필요`;
  }
  const formatted = formatDateTime(raw) || raw;
  const relative = formatRelativeTime(raw);
  return relative ? `${label}: ${formatted} (${relative})` : `${label}: ${formatted}`;
}

function extractQuotaRetryLabel(text) {
  const raw = String(text || "");
  if (!raw) {
    return "";
  }
  const isoMatch = raw.match(/\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?/);
  if (isoMatch?.[0]) {
    return formatScheduleMoment("재시도", isoMatch[0]);
  }
  const naturalMatch = raw.match(/[A-Z][a-z]{2,8}\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)/);
  if (naturalMatch?.[0]) {
    return `재시도: ${naturalMatch[0]}`;
  }
  return "";
}

function quotaStatusSummary(job) {
  const raw = `${job?.output || ""}\n${job?.finalMessage || ""}`;
  const lowered = raw.toLowerCase();
  if (!lowered || !["quota exceeded", "429 too many requests", "rate limit reached", "usage limit", "try again at"].some((marker) => lowered.includes(marker))) {
    return "";
  }
  const retryLabel = extractQuotaRetryLabel(raw);
  return retryLabel ? `Quota wait 감지 · ${retryLabel}` : "Quota wait 감지";
}

function waitingForFinalStreamSummary(job) {
  const raw = `${job?.output || ""}`;
  if (!raw.includes("mcp startup: no servers") && !raw.includes("bubblewrap")) {
    return "";
  }
  if (raw.includes("[Final Output Stream]")) {
    return "";
  }
  const startedAt = String(job?.startedAt || "").trim();
  const started = startedAt ? new Date(startedAt) : null;
  if (!started || Number.isNaN(started.getTime())) {
    return "startup 완료 후 응답 대기 중";
  }
  const ageMs = Date.now() - started.getTime();
  if (ageMs < 5000) {
    return "";
  }
  return "startup 완료 후 final stream 대기 중";
}

function localModelInspectionSummary(job) {
  const items = Array.isArray(job?.localModelInspection) ? job.localModelInspection : [];
  if (!items.length) {
    return "";
  }
  const ready = items.filter((item) => item?.ready).map((item) => String(item.name || "").trim()).filter(Boolean);
  const loaded = items.filter((item) => item?.loaded).map((item) => String(item.name || "").trim()).filter(Boolean);
  const missing = items.filter((item) => !item?.ready).map((item) => `${String(item.name || "").trim() || "unknown"}:${String(item.reason || "not ready").trim()}`);
  const bits = [];
  if (ready.length) {
    bits.push(`ready ${ready.join(", ")}`);
  }
  if (loaded.length) {
    bits.push(`loaded ${loaded.join(", ")}`);
  }
  if (missing.length) {
    bits.push(`missing ${missing.join(", ")}`);
  }
  return bits.length ? `Local models: ${bits.join(" · ")}` : "";
}

function failoverDetailText(job) {
  const history = Array.isArray(job?.failoverHistory) ? job.failoverHistory : [];
  if (!history.length) {
    return "";
  }
  const lines = ["[Failover History]"];
  history.forEach((entry, index) => {
    lines.push(`${index + 1}. ${entry.at || ""} ${entry.reason || "failover"}: ${entry.fromAccountId || "?"} -> ${entry.toAccountId || "?"}${entry.nextAvailableAt ? ` retryAfter=${entry.nextAvailableAt}` : ""}`.trim());
    if (Array.isArray(entry.probes) && entry.probes.length) {
      entry.probes.forEach((probe) => {
        lines.push(`   probe ${probe.accountLabel || probe.accountId || "?"}: ${probe.beforeStatus || "unknown"} -> ${probe.decision || "checked"}${probe.nextAvailableAt ? ` next=${probe.nextAvailableAt}` : ""}${probe.message ? ` (${probe.message})` : ""}`);
      });
    }
  });
  return lines.join("\n");
}

function localModelInspectionText(job) {
  const items = Array.isArray(job?.localModelInspection) ? job.localModelInspection : [];
  if (!items.length) {
    return "";
  }
  return [
    "[Local Model Inspection]",
    ...items.map((item) => {
      const installed = item?.ready ? "ready" : item?.reason || "not ready";
      const loaded = item?.loaded ? "loaded" : "not-loaded";
      const expires = item?.expiresAt ? ` expires=${item.expiresAt}` : "";
      return `- ${item.name || "unknown"}: ${installed} · ${loaded}${expires}`;
    })
  ].join("\n");
}

function parseParallelResultEvent(line) {
  const cleaned = String(line || "").replace(/^\[Launcher\]\s*/, "").trim();
  const match = cleaned.match(/^(.+?) result \| ([^|]+) \| role=([^|]+) \| (.+)$/i);
  if (!match) {
    return null;
  }
  const detailText = String(match[4] || "").trim();
  const parts = detailText.split("|").map((part) => part.trim()).filter(Boolean);
  const fields = {};
  parts.forEach((part) => {
    const eq = part.indexOf("=");
    if (eq <= 0) {
      return;
    }
    const key = part.slice(0, eq).trim();
    const value = part.slice(eq + 1).trim();
    fields[key] = value;
  });
  return {
    workerType: String(match[1] || "").trim(),
    workerName: String(match[2] || "").trim(),
    role: String(match[3] || "").trim(),
    status: String(fields.status || "").trim(),
    actor: String(fields.actor || "").trim(),
    task: String(fields.task || "").trim(),
    writes: String(fields.writes || "").trim(),
    files: String(fields.files || "").trim(),
    result: String(fields.result || "").trim()
  };
}

function isParallelJob(job) {
  const title = String(job?.title || "").toLowerCase();
  const preview = String(job?.commandPreview || "").toLowerCase();
  const output = String(job?.output || "").toLowerCase();
  return title.includes("[parallel")
    || preview.includes("parallel-local-models")
    || output.includes("[launcher] parallel")
    || (Array.isArray(job?.failoverHistory) && job.failoverHistory.some((entry) => String(entry?.reason || "").includes("parallel")))
    || (Array.isArray(job?.localModelInspection) && job.localModelInspection.length > 1);
}

function launcherEventLines(job) {
  return String(job?.output || "")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("[Launcher]"));
}

function parallelEventKind(text) {
  const lowered = String(text || "").toLowerCase();
  if (lowered.includes("succeeded") || lowered.includes("ready") || lowered.includes("final")) {
    return "success";
  }
  if (lowered.includes("failed") || lowered.includes("quota") || lowered.includes("auth failure") || lowered.includes("timeout")) {
    return "failed";
  }
  return "running";
}

function renderParallelTimeline(job) {
  const events = [];
  launcherEventLines(job).forEach((line) => {
    const parsed = parseParallelResultEvent(line);
    if (parsed) {
      const detailBits = [
        parsed.workerType,
        parsed.status || "unknown",
        parsed.actor ? `actor ${parsed.actor}` : "",
        parsed.task ? `task ${parsed.task}` : "",
        parsed.writes ? `writes ${parsed.writes}` : "",
        parsed.files ? `files ${parsed.files}` : "",
        parsed.result
      ].filter(Boolean);
      events.push({
        title: `${parsed.workerName} · ${parsed.role}`,
        detail: detailBits.join(" · "),
        kind: parallelEventKind(parsed.status || parsed.result)
      });
      return;
    }
    if (/parallel|quota|auth failure|switching account|local model|final synthesizer/i.test(line)) {
      events.push({
        title: line.replace(/^\[Launcher\]\s*/, "").split("\n")[0],
        detail: line.replace(/^\[Launcher\]\s*/, ""),
        kind: parallelEventKind(line)
      });
    }
  });
  (Array.isArray(job?.failoverHistory) ? job.failoverHistory : []).forEach((entry) => {
    events.push({
      title: `failover: ${entry.reason || "switch"}`,
      detail: `${entry.fromAccountId || "?"} -> ${entry.toAccountId || "?"}${entry.nextAvailableAt ? ` · retry ${entry.nextAvailableAt}` : ""}`,
      kind: String(entry.reason || "").includes("quota") || String(entry.reason || "").includes("auth") ? "failed" : "running"
    });
  });
  const target = byId("parallel-timeline");
  if (!target) {
    return;
  }
  target.innerHTML = events.length
    ? events.slice(-24).map((event) => `
        <div class="parallel-event ${escapeAttribute(event.kind)}">
          <strong>${escapeHtml(event.title)}</strong>
          <span>${escapeHtml(event.detail)}</span>
        </div>
      `).join("")
    : "이벤트 없음";
}

function renderParallelWorkers(job) {
  const workers = [];
  const seen = new Set();
  (Array.isArray(job?.localModelInspection) ? job.localModelInspection : []).forEach((item) => {
    const name = String(item?.name || "unknown").trim();
    if (!name || seen.has(`local:${name}`)) {
      return;
    }
    seen.add(`local:${name}`);
    const stateBits = [];
    stateBits.push(item?.ready ? "ready" : String(item?.reason || "not ready"));
    stateBits.push(item?.loaded ? "loaded" : "not-loaded");
    if (item?.expiresAt) {
      stateBits.push(`expires ${String(item.expiresAt)}`);
    }
    workers.push({
      name,
      type: "local model",
      status: item?.ready ? "ready" : "failed",
      detail: stateBits.join(" · ")
    });
  });
  (Array.isArray(job?.failoverHistory) ? job.failoverHistory : []).forEach((entry) => {
    (Array.isArray(entry?.probes) ? entry.probes : []).forEach((probe) => {
      const id = String(probe?.accountId || probe?.accountLabel || "unknown").trim();
      if (!id || seen.has(`account:${id}`)) {
        return;
      }
      seen.add(`account:${id}`);
      const decision = String(probe?.decision || "checked");
      workers.push({
        name: String(probe?.accountLabel || id),
        type: "account",
        status: decision === "ready" ? "ready" : "failed",
        detail: `${probe?.beforeStatus || "unknown"} -> ${decision}${probe?.message ? ` · ${probe.message}` : ""}`
      });
    });
  });
  launcherEventLines(job).forEach((line) => {
    const parsed = parseParallelResultEvent(line);
    if (parsed) {
      const key = `result:${parsed.workerType}:${parsed.workerName}`;
      if (seen.has(key)) {
        return;
      }
      seen.add(key);
      const detailBits = [
        parsed.role,
        parsed.status || "unknown",
        parsed.actor ? `actor ${parsed.actor}` : "",
        parsed.task ? `task ${parsed.task}` : "",
        parsed.writes ? `writes ${parsed.writes}` : "",
        parsed.files ? `files ${parsed.files}` : "",
        parsed.result
      ].filter(Boolean);
      workers.push({
        name: parsed.workerName,
        type: parsed.workerType,
        status: parallelEventKind(parsed.status || parsed.result),
        detail: detailBits.join(" · ")
      });
      return;
    }
    const match = line.match(/parallel (scout|final) ([^:]+):\s*(.+?)\s*\[/i);
    if (!match) {
      return;
    }
    const key = `event:${match[1]}:${match[2]}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    workers.push({
      name: match[3],
      type: `codex ${match[1]} ${match[2]}`,
      status: "running",
      detail: line.replace(/^\[Launcher\]\s*/, "")
    });
  });
  const target = byId("parallel-workers");
  if (!target) {
    return;
  }
  target.innerHTML = workers.length
    ? workers.map((worker) => `
        <div class="parallel-worker ${escapeAttribute(worker.status)}">
          <strong>${escapeHtml(worker.name)}</strong>
          <span>${escapeHtml(worker.type)} · ${escapeHtml(worker.detail)}</span>
        </div>
      `).join("")
    : "워커 없음";
}

function renderParallelFailover(job) {
  const history = Array.isArray(job?.failoverHistory) ? job.failoverHistory : [];
  const target = byId("parallel-failover");
  if (!target) {
    return;
  }
  target.innerHTML = history.length
    ? history.map((entry, index) => `
        <div class="parallel-failover-row">
          <strong>${index + 1}. ${escapeHtml(entry.reason || "failover")}</strong>
          <span>${escapeHtml(entry.fromAccountId || "?")} -> ${escapeHtml(entry.toAccountId || "?")}${entry.nextAvailableAt ? ` · retry ${escapeHtml(entry.nextAvailableAt)}` : ""}${Array.isArray(entry.probes) ? ` · probes ${entry.probes.length}` : ""}</span>
        </div>
      `).join("")
    : "전환 이력 없음";
}

function renderParallelOutputPanel(job) {
  const panel = byId("parallel-output-panel");
  if (!panel) {
    return;
  }
  const visible = isParallelJob(job);
  panel.hidden = !visible;
  if (!visible) {
    return;
  }
  const readyModels = (Array.isArray(job?.localModelInspection) ? job.localModelInspection : []).filter((item) => item?.ready).length;
  const failoverCount = Array.isArray(job?.failoverHistory) ? job.failoverHistory.length : 0;
  const probeCount = (Array.isArray(job?.failoverHistory) ? job.failoverHistory : []).reduce((total, entry) => total + (Array.isArray(entry?.probes) ? entry.probes.length : 0), 0);
  byId("parallel-output-summary").textContent = [
    job.status || "unknown",
    readyModels ? `ready local models ${readyModels}` : "",
    probeCount ? `account probes ${probeCount}` : "",
    failoverCount ? `failover ${failoverCount}` : ""
  ].filter(Boolean).join(" · ");
  renderParallelTimeline(job);
  renderParallelWorkers(job);
  renderParallelFailover(job);
}

function renderLiveLogPanel(job) {
  const panel = byId("live-log-panel");
  const target = byId("live-log");
  const summary = byId("live-log-summary");
  if (!panel || !target || !summary) {
    return;
  }
  const lines = launcherEventLines(job);
  const visible = lines.length > 0;
  panel.hidden = !visible;
  if (!visible) {
    summary.textContent = "실시간 런처 로그 없음";
    target.textContent = "실시간 로그가 여기에 표시됩니다.";
    return;
  }
  summary.textContent = `${lines.length} events`;
  const distanceFromBottom = target.scrollHeight - target.scrollTop - target.clientHeight;
  const shouldStickToBottom = distanceFromBottom <= 40;
  target.innerHTML = lines.map((line) => `
      <div class="live-log-row ${escapeAttribute(parallelEventKind(line))}">${escapeHtml(line.replace(/^\[Launcher\]\s*/, ""))}</div>
    `).join("");
  if (shouldStickToBottom) {
    window.requestAnimationFrame(() => {
      target.scrollTop = target.scrollHeight;
    });
  }
}

function accountSortRank(account) {
  const status = String(account?.statusCode || "").trim().toLowerCase();
  if (status === "ready") {
    return 0;
  }
  if (status === "unknown") {
    return 1;
  }
  if (status === "quota_wait" || status === "open_pending") {
    return 2;
  }
  if (status === "login_expired" || status === "unauthorized" || status === "plan_expired") {
    return 3;
  }
  return 4;
}

function accountNextAvailableSortValue(account) {
  const raw = String(account?.nextAvailableAt || "").trim();
  if (!raw) {
    return Number.POSITIVE_INFINITY;
  }
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) {
    return Number.POSITIVE_INFINITY;
  }
  return parsed.getTime();
}

function formatTimeOnly(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  return parsed.toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Seoul"
  });
}

function formatDateOnly(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) {
    return raw.slice(0, 10);
  }
  return parsed.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  });
}

function isoToLocalDateTimeValue(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  const year = parsed.getFullYear();
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const day = String(parsed.getDate()).padStart(2, "0");
  const hours = String(parsed.getHours()).padStart(2, "0");
  const minutes = String(parsed.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function localDateTimeValueToIso(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  return parsed.toISOString();
}

function extractQuotaRetryText(account) {
  const raw = String(account?.lastQuotaMessage || "").trim();
  if (!raw) {
    return "";
  }
  const match = raw.match(/try again at ([A-Z][a-z]{2,8}\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM))/);
  return match ? String(match[1] || "").trim() : "";
}

function accountScheduleText(account) {
  const manualBlockedUntil = String(account?.manualBlockedUntil || "").trim();
  if ((String(account?.manualStatus || "").trim().toLowerCase() === "open_pending") && manualBlockedUntil) {
    return formatScheduleMoment("오픈 예정", manualBlockedUntil);
  }
  const nextAvailableAt = String(account?.nextAvailableAt || "").trim();
  const statusCode = String(account?.statusCode || "").trim().toLowerCase();
  const availabilitySource = String(account?.nextAvailableAtSource || "").trim().toLowerCase();
  const retryText = extractQuotaRetryText(account);
  if (nextAvailableAt) {
    const label = formatScheduleMoment("재사용 가능 시각", nextAvailableAt);
    return retryText ? `${label} · 원문: ${retryText}` : label;
  }
  if (statusCode === "quota_wait" || availabilitySource === "quota-output") {
    return retryText ? `재사용 가능 시각: quota 감지됨 · 원문: ${retryText}` : "재사용 가능 시각: quota 감지됨, 자동 추출 실패";
  }
  return "";
}

function accountReusableDayText(account) {
  const manualBlockedUntil = String(account?.manualBlockedUntil || "").trim();
  if ((String(account?.manualStatus || "").trim().toLowerCase() === "open_pending") && manualBlockedUntil) {
    const dateOnly = formatDateOnly(manualBlockedUntil);
    return dateOnly ? `재사용 가능일: ${dateOnly}` : "";
  }
  const nextAvailableAt = String(account?.nextAvailableAt || "").trim();
  if (!nextAvailableAt) {
    const statusCode = String(account?.statusCode || "").trim().toLowerCase();
    const availabilitySource = String(account?.nextAvailableAtSource || "").trim().toLowerCase();
    if (statusCode === "quota_wait" || availabilitySource === "quota-output") {
      return "재사용 가능일: 미기록";
    }
    return "";
  }
  const dateOnly = formatDateOnly(nextAvailableAt);
  return dateOnly ? `재사용 가능일: ${dateOnly}` : "";
}

function accountReusableTimeText(account) {
  const manualBlockedUntil = String(account?.manualBlockedUntil || "").trim();
  if ((String(account?.manualStatus || "").trim().toLowerCase() === "open_pending") && manualBlockedUntil) {
    const timeOnly = formatTimeOnly(manualBlockedUntil);
    return timeOnly ? `재사용 가능시간: ${timeOnly}` : "";
  }
  const nextAvailableAt = String(account?.nextAvailableAt || "").trim();
  if (!nextAvailableAt) {
    const statusCode = String(account?.statusCode || "").trim().toLowerCase();
    const availabilitySource = String(account?.nextAvailableAtSource || "").trim().toLowerCase();
    if (statusCode === "quota_wait" || availabilitySource === "quota-output") {
      return "재사용 가능시간: 미기록";
    }
    return "";
  }
  const timeOnly = formatTimeOnly(nextAvailableAt);
  return timeOnly ? `재사용 가능시간: ${timeOnly}` : "";
}

function accountReusableDateTimeText(account) {
  const dayText = accountReusableDayText(account);
  const timeText = accountReusableTimeText(account);
  return [dayText, timeText].filter(Boolean).join(' · ');
}

function accountAuthTokenText(account) {
  const expiresAt = String(account?.authTokenExpiresAt || account?.tokenExpiresAt || "").trim();
  if (!expiresAt) {
    return "인증 토큰 exp: 확인 불가";
  }
  return formatScheduleMoment("인증 토큰 exp", expiresAt);
}

function actionRoutingSummary(action) {
  if (!action) {
    return "";
  }
  const bits = [];
  if (Array.isArray(action.preferredAccountIds) && action.preferredAccountIds.length) {
    bits.push(`체인 ${action.preferredAccountIds.join(" -> ")}`);
  }
  if (action.preferredAccountId) {
    bits.push(`계정 ${action.preferredAccountId}`);
  }
  if (action.runtimePreset) {
    bits.push(`프리셋 ${action.runtimePreset}`);
  }
  return bits.join(" · ");
}

function accountAvailabilitySource(account) {
  const source = String(account?.nextAvailableAtSource || "").trim().toLowerCase();
  if (source) {
    return source;
  }
  if (String(account?.suggestedNextAvailableAt || "").trim()) {
    return "suggested";
  }
  if (String(account?.lastAuthCheckedAt || "").trim()) {
    return "scan-only";
  }
  return "";
}

function accountAvailabilitySourceLabel(account) {
  const source = accountAvailabilitySource(account);
  if (source === "manual") {
    return "재사용: manual";
  }
  if (source === "quota-output") {
    return "재사용: quota";
  }
  if (source === "suggested") {
    return "재사용: suggested";
  }
  if (source === "scan-only") {
    return "재사용: scan";
  }
  return "";
}

function accountAvailabilitySourceTone(account) {
  const source = accountAvailabilitySource(account);
  if (source === "manual") {
    return "success";
  }
  if (source === "quota-output") {
    return "danger";
  }
  if (source === "suggested") {
    return "warning";
  }
  return "";
}

function renderCurrentAccountMarkup(account, hasLinkedSlot = false) {
  const pills = [];
  if (hasLinkedSlot) {
    pills.push(`<span class="pill">${escapeHtml(accountSummaryText(account))}</span>`);
    pills.push(`<span class="pill">${escapeHtml(accountScheduleText(account))}</span>`);
    if (accountReusableDateTimeText(account)) {
      pills.push(`<span class="pill">${escapeHtml(accountReusableDateTimeText(account))}</span>`);
    }
    pills.push(`<span class="pill">${escapeHtml(accountAuthTokenText(account))}</span>`);
    pills.push(`<span class="pill ${escapeAttribute(accountStatusTone(account))}">${escapeHtml(accountStatusText(account))}</span>`);
    if (accountAvailabilitySourceLabel(account)) {
      pills.push(`<span class="pill ${escapeAttribute(accountAvailabilitySourceTone(account))}">${escapeHtml(accountAvailabilitySourceLabel(account))}</span>`);
    }
    if (account.lastAuthCheckedAt) {
      pills.push(`<span class="pill">${escapeHtml(`checked ${formatDateTime(account.lastAuthCheckedAt)}`)}</span>`);
    }
  } else {
    pills.push(`<span class="pill">저장된 슬롯과 현재 로그인이 아직 연결되지 않았습니다.</span>`);
    if (account && Object.keys(account).length) {
      pills.push(`<span class="pill">${escapeHtml(accountScheduleText(account))}</span>`);
      if (accountReusableDayText(account)) {
        pills.push(`<span class="pill">${escapeHtml(accountReusableDayText(account))}</span>`);
      }
      pills.push(`<span class="pill">${escapeHtml(accountAuthTokenText(account))}</span>`);
      if (accountAvailabilitySourceLabel(account)) {
        pills.push(`<span class="pill ${escapeAttribute(accountAvailabilitySourceTone(account))}">${escapeHtml(accountAvailabilitySourceLabel(account))}</span>`);
      }
    }
    pills.push(`<span class="pill">window ${escapeHtml(state.instanceId || "default")}</span>`);
  }
  return `<div class="account-card-meta current-account-pills">${pills.join("")}</div>`;
}

function syncTabs() {
  const sidebarTab = state.selectedSidebarTab || "workspace";
  const mainTab = state.selectedMainTab || "compose";
  document.querySelectorAll("[data-sidebar-tab]").forEach((element) => {
    const active = (element.getAttribute("data-sidebar-tab") || "") === sidebarTab;
    element.classList.toggle("active", active);
    element.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-sidebar-tab-panel]").forEach((element) => {
    const active = (element.getAttribute("data-sidebar-tab-panel") || "") === sidebarTab;
    element.classList.toggle("is-collapsed", !active);
    element.hidden = !active;
    element.setAttribute("aria-hidden", active ? "false" : "true");
  });
  document.querySelectorAll("[data-main-tab]").forEach((element) => {
    const active = (element.getAttribute("data-main-tab") || "") === mainTab;
    element.classList.toggle("active", active);
    element.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-main-tab-panel]").forEach((element) => {
    const active = (element.getAttribute("data-main-tab-panel") || "") === mainTab;
    element.classList.toggle("is-collapsed", !active);
    element.hidden = !active;
    element.setAttribute("aria-hidden", active ? "false" : "true");
  });
  persistUiState();
}

function openMainTab(tabId, focusId = "") {
  state.selectedMainTab = tabId || "compose";
  syncTabs();
  if (state.selectedMainTab === "output") {
    ensureOutputAutoRefresh();
    if (state.selectedJobId) {
      loadJob(state.selectedJobId).catch((error) => {
        console.error(error);
      });
    }
  } else {
    stopOutputAutoRefresh();
  }
  if (!focusId) {
    return;
  }
  window.setTimeout(() => {
    byId(focusId)?.focus();
  }, 0);
}

function switchToOutputTab() {
  openMainTab("output");
}

function switchToComposeTab() {
  openMainTab("compose", "custom-codex-prompt");
}

function startOutputAutoRefresh() {
  stopOutputAutoRefresh();
  state.outputRefreshHandle = window.setInterval(async () => {
    if (state.selectedMainTab !== "output" || !state.selectedJobId) {
      return;
    }
    try {
      const job = await api(`/api/jobs/${state.selectedJobId}`);
      setJobDetail(job);
    } catch (error) {
      console.error(error);
    }
  }, 1200);
}

function stopOutputAutoRefresh() {
  if (state.outputRefreshHandle) {
    window.clearInterval(state.outputRefreshHandle);
    state.outputRefreshHandle = null;
  }
}

function ensureOutputAutoRefresh() {
  if (state.outputRefreshHandle) {
    return;
  }
  startOutputAutoRefresh();
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

function createInstanceId() {
  return `w${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

function openNewInstanceWindow() {
  const target = new URL(window.location.href);
  target.searchParams.set("instance", createInstanceId());
  window.open(target.toString(), "_blank", "noopener,noreferrer");
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

function accountStatusText(account) {
  if (account.openPending || account.statusCode === "open_pending") {
    return "open pending";
  }
  if (account.planExpired || account.statusCode === "plan_expired") {
    return "plan expired";
  }
  if (account.quotaWaiting || account.statusCode === "quota_wait") {
    return "quota wait";
  }
  if (account.lastAuthStatus === "unauthorized" || account.statusCode === "unauthorized") {
    return "Auth";
  }
  if (account.lastAuthStatus === "expired" || account.statusCode === "login_expired") {
    return "Auth";
  }
  if (account.lastAuthStatus === "ready") {
    return "ready";
  }
  return "status unknown";
}

function accountStatusTone(account) {
  const status = accountStatusText(account);
  if (status === "Auth" || status === "plan expired") {
    return "danger";
  }
  if (status === "quota wait" || status === "open pending") {
    return "warning";
  }
  if (status === "ready") {
    return "success";
  }
  return "";
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
  const pagination = byId("session-pagination");
  const paginationText = byId("session-pagination-text");
  if (!state.sessions.length) {
    pagination.classList.add("is-collapsed");
    target.innerHTML = `<div class="muted">세션이 없습니다.</div>`;
    return;
  }
  const totalPages = Math.max(1, Math.ceil(state.sessions.length / state.sessionPageSize));
  state.sessionPage = Math.min(Math.max(1, state.sessionPage), totalPages);
  const start = (state.sessionPage - 1) * state.sessionPageSize;
  const pageItems = state.sessions.slice(start, start + state.sessionPageSize);
  pagination.classList.toggle("is-collapsed", totalPages <= 1);
  paginationText.textContent = `Sessions ${start + 1}-${Math.min(start + pageItems.length, state.sessions.length)} / ${state.sessions.length}`;
  byId("session-page-prev").disabled = state.sessionPage <= 1;
  byId("session-page-next").disabled = state.sessionPage >= totalPages;
  target.innerHTML = pageItems.map((session) => `
    <div class="workspace-card card-with-action ${session.id === state.selectedSessionId ? "active" : ""}" data-session-id="${session.id}" role="button" tabindex="0">
      <button class="card-delete-button" data-delete-session-id="${session.id}" type="button" aria-label="세션 삭제">🗑</button>
      <strong>${escapeHtml(session.title || session.id)}</strong>
      <div class="muted">${escapeHtml(session.summary || "아직 요약 없음")}</div>
      <div class="account-card-meta">
        <span class="pill">${escapeHtml(session.parentSessionId ? `branch:${session.parentSessionId}` : "root")}</span>
        <span class="pill">${escapeHtml(session.workspaceId || "workspace 없음")}</span>
        <span class="pill">${escapeHtml(session.updatedAt || "")}</span>
      </div>
    </div>
  `).join("");
  target.querySelectorAll("[data-session-id]").forEach((element) => {
    element.addEventListener("click", async () => {
      const sessionId = element.getAttribute("data-session-id") || "";
      await activateSessionById(sessionId);
    });
  });
  target.querySelectorAll("[data-delete-session-id]").forEach((element) => {
    element.addEventListener("click", async (event) => {
      event.stopPropagation();
      const sessionId = element.getAttribute("data-delete-session-id") || "";
      if (!sessionId || !window.confirm("이 세션을 삭제할까요?")) {
        return;
      }
      const payload = await api(`/api/sessions/${sessionId}/delete`, { method: "POST", body: "{}" });
      renderSessions(payload.items || [], payload.currentSession || null);
      await refreshJobs();
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
    <button
      class="session-plan-item ${item.step === state.selectedPlanStep ? "active" : ""}"
      data-status="${escapeAttribute(item.status || "pending")}"
      data-plan-step="${escapeAttribute(item.step || "")}"
      type="button"
    >
      <strong>${escapeHtml(item.step || "")}</strong>
      <span class="pill">${escapeHtml(item.status || "pending")}</span>
    </button>
  `).join("");
  target.querySelectorAll("[data-plan-step]").forEach((element) => {
    element.addEventListener("click", async () => {
      const step = element.getAttribute("data-plan-step") || "";
      await focusPlanStep(step === state.selectedPlanStep ? "" : step);
    });
  });
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

function renderAccounts(accounts, currentAccountId, currentAccount = {}) {
  state.bootstrap = state.bootstrap || {};
  state.bootstrap.accounts = accounts;
  state.selectedAccountId = currentAccountId || "";
  const activeAccount = accounts.find((item) => item.id === currentAccountId) || currentAccount || {};
  byId("current-account").innerHTML = renderCurrentAccountMarkup(currentAccountId ? activeAccount : currentAccount, Boolean(currentAccountId));
  const target = byId("account-list");
  if (!accounts.length) {
    target.innerHTML = `<div class="muted">저장된 로그인 슬롯이 없습니다. 현재 로그인 상태를 저장해 두면 창별 전환이 가능합니다.</div>`;
    renderAccountEditor([], {});
    return;
  }
  const sortedAccounts = [...accounts].sort((left, right) => {
    const leftStatus = String(left?.statusCode || "").trim().toLowerCase();
    const rightStatus = String(right?.statusCode || "").trim().toLowerCase();
    const leftReady = leftStatus === "ready" || leftStatus === "unknown";
    const rightReady = rightStatus === "ready" || rightStatus === "unknown";
    if (leftReady !== rightReady) {
      return leftReady ? -1 : 1;
    }
    const leftNext = accountNextAvailableSortValue(left);
    const rightNext = accountNextAvailableSortValue(right);
    const leftHasNext = Number.isFinite(leftNext);
    const rightHasNext = Number.isFinite(rightNext);
    if (!leftReady && !rightReady) {
      if (leftHasNext && rightHasNext && leftNext !== rightNext) {
        return leftNext - rightNext;
      }
      if (leftHasNext !== rightHasNext) {
        return leftHasNext ? -1 : 1;
      }
    }
    const rankDiff = accountSortRank(left) - accountSortRank(right);
    if (rankDiff !== 0) {
      return rankDiff;
    }
    const leftTime = String(left?.updatedAt || left?.lastAuthCheckedAt || left?.createdAt || "");
    const rightTime = String(right?.updatedAt || right?.lastAuthCheckedAt || right?.createdAt || "");
    return rightTime.localeCompare(leftTime);
  });
  target.innerHTML = sortedAccounts.map((account) => {
    const reusableDay = accountReusableDayText(account) || "재사용 가능일: -";
    const reusableTime = accountReusableTimeText(account) || "재사용 가능시간: -";
    const scheduleText = accountScheduleText(account);
    return `
    <div class="workspace-card card-with-action ${account.id === currentAccountId ? "active" : ""}" data-account-id="${account.id}" role="button" tabindex="0">
      <button class="card-delete-button" data-delete-account-id="${account.id}" type="button" aria-label="계정 삭제">🗑</button>
      <strong>${escapeHtml(account.label || account.name || account.email || account.id)}</strong>
      <div class="muted">${escapeHtml(account.email || account.accountId || "")}</div>
      <div class="muted">${escapeHtml(reusableDay)}</div>
      <div class="muted">${escapeHtml(reusableTime)}</div>
      <div class="muted">${escapeHtml(scheduleText || "재사용 가능 시각: 미기록")}</div>
      <div class="account-card-meta">
        <span class="pill">${escapeHtml(account.authMode || "unknown")}</span>
        <span class="pill ${escapeAttribute(accountStatusTone(account))}">${escapeHtml(accountStatusText(account))}</span>
        ${accountAvailabilitySourceLabel(account) ? `<span class="pill ${escapeAttribute(accountAvailabilitySourceTone(account))}">${escapeHtml(accountAvailabilitySourceLabel(account))}</span>` : ""}
        <span class="pill">${escapeHtml(formatDateTime(account.lastAuthCheckedAt || account.updatedAt || account.createdAt || ""))}</span>
      </div>
    </div>
  `;}).join("");
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
  target.querySelectorAll("[data-delete-account-id]").forEach((element) => {
    element.addEventListener("click", async (event) => {
      event.stopPropagation();
      const accountId = element.getAttribute("data-delete-account-id") || "";
      if (!accountId || !window.confirm("이 계정 슬롯을 삭제할까요?")) {
        return;
      }
      const payload = await api(`/api/accounts/${accountId}/delete`, { method: "POST", body: "{}" });
      byId("login-status").textContent = accountStatusText(payload.currentAccount || {});
      renderAccounts(payload.items || [], payload.currentAccountId || "", payload.currentAccount || {});
    });
  });
  renderAccountEditor(accounts, activeAccount);
}

function renderAccountEditor(accounts, activeAccount = {}) {
  const selected = accounts.find((item) => item.id === state.selectedAccountId) || activeAccount || {};
  byId("account-editor-title").textContent = selected.id
    ? `${selected.label || selected.email || selected.id} · ${accountStatusText(selected)}`
    : "선택된 계정 없음";
  byId("account-editor-status").value = String(selected.manualStatus || "").trim().toLowerCase();
  byId("account-editor-next-available").value = isoToLocalDateTimeValue(selected.nextAvailableAt || "");
  byId("account-editor-note").value = String(selected.manualNote || "").trim();
  const suggestionBits = [];
  if (selected.suggestedNextAvailableAt) {
    suggestionBits.push(`추정 재사용 가능: ${formatScheduleMoment("시각", selected.suggestedNextAvailableAt)}`);
  }
  if (selected.suggestedNextAvailableSource) {
    suggestionBits.push(`source=${selected.suggestedNextAvailableSource}`);
  }
  if (selected.nextAvailableAtSource) {
    suggestionBits.push(`저장 source=${selected.nextAvailableAtSource}`);
  }
  if (selected.lastQuotaDetectedAt) {
    suggestionBits.push(`quota 감지 ${formatDateTime(selected.lastQuotaDetectedAt)}`);
  }
  if (!suggestionBits.length && selected.authTokenExpiresAt) {
    suggestionBits.push(`토큰 exp 참고값: ${formatScheduleMoment("시각", selected.authTokenExpiresAt)}`);
  }
  byId("account-editor-suggestion").textContent = suggestionBits.join(" · ") || "주기 스캔은 로그인 상태만 갱신합니다. 재사용 가능 시각은 429/쿼터 문구 또는 수동 입력으로 관리합니다.";
}

function renderActionRoutingEditor() {
  const action = getSelectedAction();
  const accounts = state.bootstrap?.accounts || [];
  const accountSelect = byId("action-routing-account");
  accountSelect.innerHTML = [
    `<option value="">자동</option>`,
    ...accounts.map((account) => `<option value="${escapeHtml(account.id)}">${escapeHtml(account.label || account.email || account.id)}</option>`)
  ].join("");
  byId("action-routing-title").textContent = action ? `${action.label} · ${actionRoutingSummary(action) || "자동"}` : "선택된 액션 없음";
  accountSelect.value = action?.preferredAccountId || "";
  const chain = Array.isArray(action?.preferredAccountIds) ? action.preferredAccountIds : [];
  byId("action-routing-chain").value = chain.join(",");
  byId("action-routing-account-type").value = action?.preferredAccountType || "";
  byId("action-routing-preset").value = action?.runtimePreset || "";
  refreshActionRoutingChainPreview();
}

function refreshActionRoutingChainPreview() {
  const accounts = state.bootstrap?.accounts || [];
  const knownIds = new Set(accounts.map((account) => String(account.id || "").trim()).filter(Boolean));
  const preview = byId("action-routing-chain-preview");
  const chain = parseActionRoutingChain();
  preview.innerHTML = chain.map((id, index) => {
    const known = knownIds.has(String(id).trim());
    return `
      <span class="pill ${known ? "" : "danger"}">
        ${escapeHtml(id)}${known ? "" : " (missing)"}
        <button class="ghost-button" data-chain-move="up" data-chain-index="${index}" type="button">↑</button>
        <button class="ghost-button" data-chain-move="down" data-chain-index="${index}" type="button">↓</button>
        <button class="ghost-button" data-chain-move="remove" data-chain-index="${index}" type="button">×</button>
      </span>
    `;
  }).join("");
  preview.querySelectorAll("[data-chain-move]").forEach((element) => {
    element.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const index = Number(element.getAttribute("data-chain-index") || -1);
      const direction = element.getAttribute("data-chain-move") || "";
      moveActionRoutingChainItem(index, direction);
    });
  });
}

function parseActionRoutingChain() {
  return byId("action-routing-chain").value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function setActionRoutingChain(ids) {
  const unique = [];
  for (const id of ids) {
    const value = String(id || "").trim();
    if (value && !unique.includes(value)) {
      unique.push(value);
    }
  }
  byId("action-routing-chain").value = unique.join(",");
  refreshActionRoutingChainPreview();
}

function appendToActionRoutingChain(id) {
  const value = String(id || "").trim();
  if (!value) {
    return;
  }
  setActionRoutingChain([...parseActionRoutingChain(), value]);
}

function moveActionRoutingChainItem(index, direction) {
  const chain = parseActionRoutingChain();
  if (index < 0 || index >= chain.length) {
    return;
  }
  if (direction === "remove") {
    chain.splice(index, 1);
    setActionRoutingChain(chain);
    return;
  }
  const targetIndex = direction === "up" ? index - 1 : direction === "down" ? index + 1 : index;
  if (targetIndex < 0 || targetIndex >= chain.length || targetIndex === index) {
    return;
  }
  const [item] = chain.splice(index, 1);
  chain.splice(targetIndex, 0, item);
  setActionRoutingChain(chain);
}

function renderActions() {
  const target = byId("action-grid");
  const actions = state.bootstrap?.actions || [];
  target.innerHTML = actions.map((action) => `
    <button class="action-card ${action.id === state.selectedActionId ? "active" : ""}" data-action-id="${action.id}" type="button">
      <div class="pill">${escapeHtml(action.group || action.kind)}</div>
      <strong>${escapeHtml(action.label)}</strong>
      <div class="muted">${escapeHtml(action.description || "")}</div>
      <div class="muted">${escapeHtml(actionRoutingSummary(action) || "자동 라우팅")}</div>
    </button>
  `).join("");
  target.querySelectorAll("[data-action-id]").forEach((element) => {
    element.addEventListener("click", () => {
      const actionId = element.getAttribute("data-action-id") || "";
      const action = actions.find((item) => item.id === actionId);
      state.selectedActionId = actionId;
      byId("selected-action-caption").textContent = action?.description || "버튼을 선택하세요";
      syncComposerDefaultsFromAction(action);
      if (action?.kind === "codex") {
        syncSelectedActionPrompt(true);
      }
      renderActions();
      refreshPromptPreview().catch(() => {});
    });
  });
  renderActionRoutingEditor();
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
    state.selectedFreeAgentModel = defaultFreeAgentModel(state.selectedCli);
    syncFreeAgentModelControl();
    syncAssistantNote();
  });
  const freeagentMode = byId("freeagent-mode");
  freeagentMode.value = state.selectedFreeAgentMode || "prompt";
  freeagentMode.addEventListener("change", () => {
    state.selectedFreeAgentMode = freeagentMode.value || "prompt";
    syncAssistantNote();
  });
  const freeagentModel = byId("freeagent-model-input");
  freeagentModel.addEventListener("change", () => {
    state.selectedFreeAgentModel = freeagentModel.value.trim();
    syncAssistantNote();
  });
  const parallelAccounts = byId("parallel-accounts-toggle");
  parallelAccounts?.addEventListener("change", () => {
    state.parallelAccountsEnabled = parallelAccounts.checked;
    syncAssistantNote();
  });
  syncFreeAgentModelControl();
  syncAssistantNote();
}

function defaultFreeAgentModel(cliId = state.selectedCli) {
  const freeagent = state.bootstrap?.freeagent || {};
  if (cliId === "minimax") {
    return freeagent.minimax?.model || "minimax2.7";
  }
  return freeagent.ollama?.model || freeagent.model || "qwen3.5:cloud";
}

function freeAgentModelSuggestions(cliId = state.selectedCli) {
  const freeagent = state.bootstrap?.freeagent || {};
  if (cliId === "minimax") {
    return [freeagent.minimax?.model || "minimax2.7"].filter(Boolean);
  }
  const items = [
    freeagent.ollama?.model,
    freeagent.model,
    ...(freeagent.availableModels || []).map((item) => item?.name || "")
  ];
  return [...new Set(items.filter(Boolean))];
}

function syncFreeAgentModelControl() {
  const row = byId("freeagent-model-row");
  const input = byId("freeagent-model-input");
  const isFreeAgent = state.selectedCli === "freeagent" || state.selectedCli === "minimax";
  row.hidden = !isFreeAgent;
  if (!isFreeAgent) {
    return;
  }
  const suggestions = freeAgentModelSuggestions(state.selectedCli);
  const next = state.selectedFreeAgentModel || defaultFreeAgentModel(state.selectedCli);
  input.innerHTML = suggestions.map((model) => `
    <option value="${escapeAttribute(model)}">${escapeHtml(model)}</option>
  `).join("");
  if (!suggestions.includes(next) && next) {
    input.innerHTML += `\n<option value="${escapeAttribute(next)}">${escapeHtml(next)}</option>`;
  }
  if (input.value !== next) {
    input.value = next;
  }
}

function syncFreeAgentControls() {
  const isFreeAgent = state.selectedCli === "freeagent" || state.selectedCli === "minimax";
  byId("freeagent-mode-row").hidden = !isFreeAgent;
  byId("freeagent-model-row").hidden = !isFreeAgent;
  byId("freeagent-targets-row").hidden = !isFreeAgent;
  byId("freeagent-test-command-row").hidden = !isFreeAgent || state.selectedFreeAgentMode !== "apply";
}

function syncAssistantNote() {
  const freeagent = state.bootstrap?.freeagent || {};
  const parallelSuffix = state.parallelAccountsEnabled ? " · 계정 병렬 실행 준비" : "";
  const routing = normalizeModelRoutingOptions(state.modelRoutingOptions);
  const localParallelSuffix = routing.allowParallelLocalWorkers && routing.parallelLocalWorkers > 1
    ? ` · local-workers=${routing.parallelLocalWorkers}`
    : "";
  const routingSuffix = routing.enabled
    ? ` · auto-route on · single-local=${routing.memorySafeSingleLocalModel ? "on" : "off"} · hard->codex=${routing.escalateHardTasksToCodex ? "on" : "off"}${localParallelSuffix}`
    : " · auto-route off";
  if (state.selectedCli === "minimax-codex") {
    byId("assistant-note").textContent = `MiniMax Codex Compat는 Codex exec 문법 일부를 MiniMax-backed FreeAgent로 매핑합니다.${parallelSuffix}${routingSuffix}`;
    syncFreeAgentControls();
    return;
  }
  if (state.selectedCli === "freeagent" || state.selectedCli === "minimax") {
    const modeText = state.selectedFreeAgentMode || "prompt";
    const cliLabel = state.selectedCli === "minimax" ? "MiniMax 2.7" : "FreeAgent";
    const providerText = state.selectedCli === "minimax" ? "minimax" : (freeagent.provider || "unknown");
    const modelText = byId("freeagent-model-input").value.trim() || defaultFreeAgentModel(state.selectedCli) || "unknown";
    byId("assistant-note").textContent = freeagent.installed
      ? `${cliLabel} mode=${modeText} provider=${providerText} model=${modelText}${parallelSuffix}${routingSuffix}`
      : `${cliLabel} runtime이 아직 설치되지 않았습니다.${parallelSuffix}${routingSuffix}`;
    syncFreeAgentControls();
    syncFreeAgentModelControl();
    refreshPromptPreview().catch(() => {});
    return;
  }
  byId("assistant-note").textContent = `Codex는 현재 로그인 세션과 workspace sandbox 설정을 사용합니다.${parallelSuffix}${routingSuffix}`;
  syncFreeAgentControls();
  refreshPromptPreview().catch(() => {});
}

function syncFreeAgentStatus() {
  const freeagent = state.bootstrap?.freeagent || {};
  const ollama = freeagent.ollama || {};
  const minimax = freeagent.minimax || {};
  if (!freeagent.installed) {
    byId("freeagent-model").textContent = "not installed";
    byId("minimax-model").textContent = "not installed";
    byId("freeagent-status-note").textContent = "FreeAgent source 또는 runtime이 아직 준비되지 않았습니다.";
    return;
  }
  const runtimeText = freeagent.venvReady ? "runtime ready" : "runtime missing";
  const ollamaAgentText = ollama.running ? "agent on" : ollama.installedOnSystem ? "agent off" : "ollama missing";
  const ollamaModelText = ollama.modelReady ? "model ready" : "model missing";
  const minimaxKeyText = minimax.keyReady ? "api key ready" : "api key missing";
  const minimaxModelText = minimax.model ? "model set" : "model missing";
  byId("freeagent-model").textContent = `${ollama.provider || "ollama"} · ${ollama.model || "unknown"}`;
  byId("minimax-model").textContent = `${minimax.provider || "minimax"} · ${minimax.model || "unknown"}`;
  byId("freeagent-status-note").textContent = `${runtimeText} · FreeAgent: ${ollamaAgentText}, ${ollamaModelText} · MiniMax: ${minimaxKeyText}, ${minimaxModelText}`;
}

function formatBrowserCapture(capture) {
  if (!shouldIncludeBrowserContext()) {
    return "";
  }
  const parts = [
    "[Browser Capture]",
    `URL: ${capture.url || ""}`,
    `Title: ${capture.title || ""}`,
    `Selector: ${capture.selector || ""}`
  ];
  if (capture.html) {
    parts.push("HTML:");
    parts.push(getPromptSourceText(capture.html, 2000));
  } else if (capture.text) {
    parts.push("Text:");
    parts.push(getPromptSourceText(capture.text, 1200));
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
  if (browser.currentUrl && shouldIncludeBrowserContext()) {
    parts.push(`Target URL: ${browser.currentUrl}`);
  }
  if (shouldIncludeReferenceContext() && meta.text) {
    parts.push("Reference Source:");
    parts.push(getPromptSourceText(meta.text, 3000));
  } else if (shouldIncludeReferenceContext() && meta.downloadUrl) {
    parts.push(`Reference Asset: ${window.location.origin}${meta.downloadUrl}`);
  }
  if (capture && shouldIncludeBrowserContext()) {
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
  if (state.selectedMenuItem?.menu && shouldIncludeMenuContext()) {
    lines.push(`target menu: ${state.selectedMenuItem.menu.label}`);
    if (state.promptCompactionEnabled) {
      lines.push(`target menu path: ${state.selectedMenuItem.menu.koPath || state.selectedMenuItem.menu.enPath || ""}`);
    } else {
      lines.push(`target menu koPath: ${state.selectedMenuItem.menu.koPath || ""}`);
      lines.push(`target menu enPath: ${state.selectedMenuItem.menu.enPath || ""}`);
    }
  }
  if (browser.currentUrl && shouldIncludeBrowserContext()) {
    lines.push(`target url: ${browser.currentUrl}`);
  }
  lines.push("requirements:");
  if (state.promptCompactionEnabled) {
    lines.push("- 수정 파일 찾기");
    lines.push("- 가능하면 React로 변환");
    lines.push("- 기존 구조/스타일 유지");
    lines.push("- 변경 파일 요약");
  } else {
    lines.push("- reference 화면의 DOM 구조, 레이아웃, 텍스트, 스타일 의도를 먼저 파악");
    lines.push("- 대상 프로젝트에서 수정할 파일과 진입 경로를 찾기");
    lines.push("- 가능하면 React 컴포넌트 구조로 옮기되 기존 앱 패턴에 맞추기");
    lines.push("- 필요한 스타일, asset, 이벤트 연결을 빠뜨리지 않기");
    lines.push("- 변경 파일과 후속 확인 포인트를 함께 요약");
  }
  if (shouldIncludeReferenceContext() && meta.text) {
    lines.push("reference html:");
    lines.push(getPromptSourceText(meta.text, 4000));
  } else if (shouldIncludeReferenceContext() && meta.downloadUrl) {
    lines.push(`reference asset url: ${window.location.origin}${meta.downloadUrl}`);
  }
  if (capture && shouldIncludeBrowserContext()) {
    lines.push("");
    lines.push(formatBrowserCapture(capture).trimEnd());
  }
  return `${lines.join("\n")}\n`;
}

function buildMenuContextPrompt() {
  if (!shouldIncludeMenuContext()) {
    return "";
  }
  const item = state.selectedMenuItem?.menu;
  if (!item) {
    return "";
  }
  return [
    "[Project Menu]",
    `Project: ${state.selectedProjectPath || ""}`,
    `Group: ${item.group}`,
    `Label: ${item.label}`,
    ...(state.promptCompactionEnabled
      ? [`Path: ${item.koPath || item.enPath || ""}`]
      : [`koPath: ${item.koPath || ""}`, `enPath: ${item.enPath || ""}`]),
    `id: ${item.id}`,
    ""
  ].join("\n");
}

function extractPathnameFromUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  try {
    const url = new URL(raw, window.location.origin);
    return (url.pathname || "").trim();
  } catch (_error) {
    return raw.startsWith("/") ? raw : "";
  }
}

function selectedMenuFocusScope() {
  const item = state.selectedMenuItem?.menu;
  if (!item) {
    return "";
  }
  return String(item.koPath || item.enPath || "").trim();
}

function setRuntimeFocusScope(value) {
  const next = String(value || "").trim();
  byId("runtime-focus-scope").value = next;
  readPromptRuntimeOptionsFromControls();
  refreshPromptPreview().catch(() => {});
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

function getSelectedProjectAssembly() {
  const projects = state.projectAssemblies?.projects || [];
  const byId = projects.find((item) => item.id === state.selectedProjectAssemblyId);
  if (byId) {
    return byId;
  }
  const selectedPath = String(state.selectedProjectPath || "").replace(/\/+$/, "");
  return projects.find((item) => String(item.path || "").replace(/\/+$/, "") === selectedPath) || null;
}

function renderProjectAssemblyPanel() {
  const projects = state.projectAssemblies?.projects || [];
  const select = byId("project-assembly-select");
  if (select) {
    select.innerHTML = projects.length
      ? projects.map((item) => `<option value="${escapeAttribute(item.id)}">${escapeHtml(item.label || item.id)} · ${escapeHtml(item.path || "")}</option>`).join("")
      : `<option value="">등록된 프로젝트 없음</option>`;
    select.value = state.selectedProjectAssemblyId || projects[0]?.id || "";
  }
  const assembly = getSelectedProjectAssembly() || projects[0] || null;
  if (assembly && !state.selectedProjectAssemblyId) {
    state.selectedProjectAssemblyId = assembly.id || "";
  }
  byId("project-assembly-id").value = assembly?.id || getSelectedProjectName() || "";
  byId("project-assembly-label").value = assembly?.label || getSelectedProjectName() || "";
  byId("project-assembly-adapter").value = assembly?.adapterType || "";
  byId("project-assembly-common-adapter").value = assembly?.commonAdapter || "";
  byId("project-assembly-app-module").value = assembly?.appModule || "";
  byId("project-assembly-port").value = assembly?.runtimePort || "";
  const status = byId("project-assembly-status");
  if (status) {
    status.textContent = assembly
      ? `${assembly.label || assembly.id} · ${assembly.exists ? "path ok" : "path missing"}`
      : "등록된 assembly profile이 없습니다.";
  }
  const commonModules = assembly?.commonModules || [];
  const projectModules = assembly?.projectModules || [];
  const lines = assembly
    ? [
        `Project: ${assembly.label || assembly.id}`,
        `Path: ${assembly.path || ""}`,
        `Common adapter: ${assembly.commonAdapter || "(미지정)"}`,
        `Project adapter: ${assembly.adapterType || "(미지정)"}`,
        `App module: ${assembly.appModule || "(미지정)"}`,
        `Runtime port: ${assembly.runtimePort || "(미지정)"}`,
        "",
        `[Common Jars] ${commonModules.length}`,
        ...commonModules.map((item) => `- ${item}`),
        "",
        `[Project Modules] ${projectModules.length}`,
        ...projectModules.map((item) => `- ${item}`),
      ]
    : ["프로젝트 폴더를 선택한 뒤 Register Selected로 assembly profile을 등록하세요."];
  byId("project-assembly-preview").textContent = lines.join("\n");
}

async function refreshProjectAssemblies() {
  state.projectAssemblies = await api("/api/project-assemblies");
  if (!state.selectedProjectAssemblyId) {
    state.selectedProjectAssemblyId = state.projectAssemblies.defaultProjectId || state.projectAssemblies.projects?.[0]?.id || "";
  }
  renderProjectAssemblyPanel();
}

async function registerSelectedProjectAssembly() {
  const projectPath = requireProjectPath();
  if (!projectPath) {
    return;
  }
  const payload = await api("/api/project-assemblies/upsert", {
    method: "POST",
    body: JSON.stringify({
      id: byId("project-assembly-id").value.trim(),
      label: byId("project-assembly-label").value.trim(),
      path: projectPath,
      adapterType: byId("project-assembly-adapter").value.trim(),
      commonAdapter: byId("project-assembly-common-adapter").value.trim(),
      appModule: byId("project-assembly-app-module").value.trim(),
      runtimePort: Number(byId("project-assembly-port").value || 0)
    })
  });
  state.projectAssemblies = payload.projectAssemblies || state.projectAssemblies;
  state.selectedProjectAssemblyId = payload.item?.id || state.selectedProjectAssemblyId;
  renderProjectAssemblyPanel();
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
  const normalizedPath = String(path || "").replace(/\/+$/, "");
  const matchedAssembly = (state.projectAssemblies?.projects || []).find((item) => String(item.path || "").replace(/\/+$/, "") === normalizedPath);
  if (matchedAssembly) {
    state.selectedProjectAssemblyId = matchedAssembly.id || "";
  }
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
  renderProjectAssemblyPanel();
  syncProjectSummary();
  syncReferenceBinding();
  renderProjectMenuTree();
  syncMenuPreview();
  if (state.selectedProjectPath) {
    refreshProjectRuntimeStatus().catch(() => {});
  } else if (byId("project-runtime-status")) {
    byId("project-runtime-status").textContent = "프로젝트를 선택하면 runtime profile과 health를 확인합니다.";
  }
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
    if (byId("project-runtime-status")) {
      byId("project-runtime-status").textContent = "프로젝트를 선택하면 runtime profile과 health를 확인합니다.";
    }
    return;
  }
  const assembly = getSelectedProjectAssembly();
  byId("project-summary").textContent = assembly
    ? `assembly=${assembly.id} · common adapter=${assembly.commonAdapter || "미지정"} · project adapter=${assembly.adapterType || "미지정"}`
    : "선택 경로를 AI 실행, 빌드, 패키지, 재시작 대상 폴더로 사용합니다.";
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
        ${(state.projectAssemblies?.projects || []).some((profile) => String(profile.path || "").replace(/\/+$/, "") === String(item.path || "").replace(/\/+$/, "")) ? '<span class="pill success">assembly</span>' : ""}
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
  renderProjectAssemblyPanel();
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
    const captureText = formatBrowserCapture(browser.lastCapture).trimEnd();
    if (captureText) {
      appendPromptText(captureText);
      byId("browser-note").textContent = `최근 캡처가 prompt에 추가됨: ${browser.lastCapture.selector || browser.lastCapture.tagName || "element"}`;
    } else {
      byId("browser-note").textContent = "최근 캡처를 받았지만 브라우저 문맥 포함 옵션이 꺼져 있어 prompt에는 넣지 않았습니다.";
    }
  }
}

function renderJobs(jobs) {
  const target = byId("job-list");
  const filterBar = byId("job-filter-bar");
  const filterText = byId("job-filter-text");
  const pagination = byId("job-pagination");
  const paginationText = byId("job-pagination-text");
  const items = state.selectedPlanStep
    ? jobs.filter((job) => (job.planStep || "") === state.selectedPlanStep)
    : jobs;
  filterBar.classList.toggle("is-collapsed", !state.selectedPlanStep);
  filterText.textContent = state.selectedPlanStep ? `Filtered by step: ${state.selectedPlanStep}` : "";
  if (!items.length) {
    pagination.classList.add("is-collapsed");
    target.innerHTML = `<div class="muted">${escapeHtml(state.selectedPlanStep ? `선택한 step(${state.selectedPlanStep})에 해당하는 실행 이력이 없습니다.` : "아직 실행 이력이 없습니다.")}</div>`;
    return;
  }
  const totalPages = Math.max(1, Math.ceil(items.length / state.jobPageSize));
  state.jobPage = Math.min(Math.max(1, state.jobPage), totalPages);
  const start = (state.jobPage - 1) * state.jobPageSize;
  const pageItems = items.slice(start, start + state.jobPageSize);
  pagination.classList.toggle("is-collapsed", totalPages <= 1);
  paginationText.textContent = `Jobs ${start + 1}-${Math.min(start + pageItems.length, items.length)} / ${items.length}`;
  byId("job-page-prev").disabled = state.jobPage <= 1;
  byId("job-page-next").disabled = state.jobPage >= totalPages;
  target.innerHTML = pageItems.map((job) => `
    <div class="job-card card-with-action ${job.jobId === state.selectedJobId ? "active" : ""}" data-job-id="${job.jobId}" role="button" tabindex="0">
      <button class="card-delete-button" data-delete-job-id="${job.jobId}" type="button" aria-label="잡 삭제">🗑</button>
      <strong>${escapeHtml(job.title)}</strong>
      <div class="muted">${escapeHtml(job.workspaceLabel || "")}</div>
      <div class="muted">${escapeHtml(job.planStep ? `step: ${job.planStep}` : "step: 자동")}</div>
      <div class="muted">${escapeHtml(Array.isArray(job.accountChain) && job.accountChain.length ? `chain: ${job.accountChain.join(" -> ")}` : "chain: 자동")}</div>
      ${quotaStatusSummary(job) ? `<div class="muted">${escapeHtml(quotaStatusSummary(job))}</div>` : ""}
      ${Array.isArray(job.failoverHistory) && job.failoverHistory.length ? `<div class="muted">${escapeHtml(`failover ${job.failoverHistory.length}회`)}</div>` : ""}
      ${localModelInspectionSummary(job) ? `<div class="muted">${escapeHtml(localModelInspectionSummary(job))}</div>` : ""}
      <div class="pill ${job.status === "succeeded" ? "success" : job.status === "failed" ? "danger" : ""}">
        ${escapeHtml(job.status)}
      </div>
    </div>
  `).join("");
  target.querySelectorAll("[data-job-id]").forEach((element) => {
    element.addEventListener("click", async () => {
      const jobId = element.getAttribute("data-job-id") || "";
      await loadJob(jobId);
    });
  });
  target.querySelectorAll("[data-delete-job-id]").forEach((element) => {
    element.addEventListener("click", async (event) => {
      event.stopPropagation();
      const jobId = element.getAttribute("data-delete-job-id") || "";
      if (!jobId || !window.confirm("이 잡을 삭제할까요?")) {
        return;
      }
      await api(`/api/jobs/${jobId}/delete`, { method: "POST", body: "{}" });
      if (state.selectedJobId === jobId) {
        state.selectedJobId = "";
      }
      await refreshJobs();
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
  if (job.jobId) {
    state.selectedJobId = job.jobId;
  }
  if (state.selectedMainTab === "output") {
    ensureOutputAutoRefresh();
  }
  const metaBits = [job.status, job.workspaceLabel || "", job.startedAt || ""];
  if (job.executionAccountLabel || job.executionAccountId) {
    metaBits.push(`account: ${job.executionAccountLabel || job.executionAccountId}`);
  }
  byId("job-meta").textContent = metaBits.filter(Boolean).join(" · ");
  const detailBits = [job.planStep ? `Plan step: ${job.planStep}` : "Plan step: 자동 선택"];
  if (Array.isArray(job.accountChain) && job.accountChain.length) {
    detailBits.push(`Account chain: ${job.accountChain.join(" -> ")}`);
  }
  if (job.executionAccountLabel || job.executionAccountId) {
    detailBits.push(`Execution account: ${job.executionAccountLabel || job.executionAccountId}`);
  }
  if (Array.isArray(job.failoverHistory) && job.failoverHistory.length) {
    const latest = job.failoverHistory[job.failoverHistory.length - 1];
    detailBits.push(`Failover ${job.failoverHistory.length}회`);
    if (latest?.fromAccountId || latest?.toAccountId) {
      detailBits.push(`${latest.fromAccountId || "?"} -> ${latest.toAccountId || "?"}`);
    }
    if (Array.isArray(latest?.probes) && latest.probes.length) {
      detailBits.push(`probes ${latest.probes.length}`);
    }
  }
  const modelSummary = localModelInspectionSummary(job);
  if (modelSummary) {
    detailBits.push(modelSummary);
  }
  const quotaSummary = quotaStatusSummary(job);
  if (quotaSummary) {
    detailBits.push(quotaSummary);
  }
  const waitingSummary = waitingForFinalStreamSummary(job);
  if (waitingSummary) {
    detailBits.push(waitingSummary);
  }
  byId("job-plan-step").textContent = detailBits.join(" · ");
  byId("command-preview").textContent = job.commandPreview || "명령 정보가 없습니다.";
  renderParallelOutputPanel(job);
  renderLiveLogPanel(job);
  const outputSections = [failoverDetailText(job), localModelInspectionText(job), job.output || "출력이 없습니다."].filter(Boolean);
  setRawOutputText(outputSections.join("\n\n"));
  byId("final-output").textContent = job.finalMessage || "완료 내용이 없습니다.";
}

function resolveJobId(payload) {
  if (!payload || typeof payload !== "object") {
    return "";
  }
  return String(payload.jobId || payload.job_id || payload.id || "").trim();
}

function startPollingFromPayload(payload, sourceLabel = "job") {
  const jobId = resolveJobId(payload);
  if (!jobId) {
    const detail = (() => {
      try {
        return JSON.stringify(payload, null, 2);
      } catch (_error) {
        return String(payload);
      }
    })();
    const message = `${sourceLabel} 응답에 jobId가 없습니다.\n${detail}`;
    console.error(message);
    setRawOutputText(message);
    throw new Error(message);
  }
  startPolling(jobId);
}

async function refreshJobs() {
  const query = state.selectedSessionId ? `?sessionId=${encodeURIComponent(state.selectedSessionId)}` : "";
  const payload = await api(`/api/jobs${query}`);
  renderJobs(payload.items || []);
}

async function recoverJobs() {
  const payload = await api("/api/jobs/recover", { method: "POST", body: "{}" });
  renderSessions(payload.sessions || [], payload.currentSession || null);
  renderJobs(payload.items || []);
  if (payload.currentJob) {
    setJobDetail(payload.currentJob);
  } else {
    setRawOutputText(payload.message || "복구할 job이 없습니다.");
  }
}

async function refreshSessions() {
  const payload = await api("/api/sessions");
  renderSessions(payload.items || [], payload.currentSession || null);
}

async function refreshAccounts() {
  const payload = await api("/api/accounts");
  renderAccounts(payload.items || [], payload.currentAccountId || "", payload.currentAccount || {});
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
      try {
        await refreshAccounts();
      } catch (error) {
        console.error(error);
      }
      try {
        await refreshJobs();
      } catch (error) {
        console.error(error);
      }
      if (job.status !== "running") {
        try {
          const finalJob = await api(`/api/jobs/${jobId}`);
          setJobDetail(finalJob);
        } catch (error) {
          console.error(error);
        }
        try {
          await refreshSessions();
        } catch (error) {
          console.error(error);
        }
        stopPolling();
      }
    } catch (error) {
      console.error(error);
    }
  }, 1500);
}

function stopPolling() {
  if (state.pollHandle) {
    window.clearInterval(state.pollHandle);
    state.pollHandle = null;
  }
  if (state.selectedMainTab !== "output") {
    stopOutputAutoRefresh();
  }
}

async function runAction() {
  if (!state.selectedActionId) {
    alert("먼저 Quick Action을 선택하세요.");
    return;
  }
  const action = getSelectedAction();
  const extraInput = byId("extra-input").value;
  const request = {
    sessionId: state.selectedSessionId,
    planStep: state.selectedPlanStep,
    workspaceId: state.selectedWorkspaceId,
    projectPath: state.selectedProjectPath,
    actionId: state.selectedActionId,
    extraInput,
    classicMode: byId("classic-mode-toggle")?.checked || false,
    parallelAccounts: byId("parallel-accounts-toggle")?.checked || false,
    modelRouting: readModelRoutingOptionsFromControls(),
    runtimeOptions: readPromptRuntimeOptionsFromControls(),
    runtimePreset: byId("runtime-preset-select")?.value || state.runtimePreset || "auto"
  };
  if (action?.kind === "codex") {
    request.prompt = (byId("custom-codex-prompt").value || "").trim() || getActionPromptTemplate(action);
  }
  const payload = await api("/api/run", {
    method: "POST",
    body: JSON.stringify(request)
  });
  setJobDetail(payload);
  switchToOutputTab();
  await refreshAccounts();
  await refreshJobs();
  startPollingFromPayload(payload, "Quick Action");
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
      freeagentMode: state.selectedFreeAgentMode,
      freeagentModel: byId("freeagent-model-input").value.trim(),
      freeagentTargets: byId("freeagent-targets").value.trim(),
      freeagentTestCommand: byId("freeagent-test-command").value.trim(),
      classicMode: byId("classic-mode-toggle")?.checked || false,
      parallelAccounts: byId("parallel-accounts-toggle")?.checked || false,
      modelRouting: readModelRoutingOptionsFromControls(),
      prompt,
      runtimeOptions: readPromptRuntimeOptionsFromControls(),
      runtimePreset: byId("runtime-preset-select")?.value || state.runtimePreset || "auto"
    })
  });
  setJobDetail(payload);
  switchToOutputTab();
  await refreshAccounts();
  await refreshJobs();
  startPollingFromPayload(payload, "Custom Codex");
  refreshPromptPreview().catch(() => {});
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
  switchToOutputTab();
  await refreshAccounts();
  await refreshJobs();
  startPollingFromPayload(payload, "Custom Shell");
}

async function setupFreeAgent() {
  const model = prompt("설치할 FreeAgent 기본 모델", state.bootstrap?.freeagent?.model || "qwen3.5:cloud");
  if (!model) {
    return;
  }
  const sudoPassword = byId("freeagent-sudo-password").value;
  const payload = await api("/api/freeagent/setup", {
    method: "POST",
    body: JSON.stringify({ model, sudoPassword })
  });
  byId("freeagent-sudo-password").value = "";
  state.bootstrap.freeagent = payload.freeagent || state.bootstrap.freeagent;
  syncFreeAgentStatus();
  syncAssistantNote();
  alert(payload.message || "FreeAgent setup completed");
}

async function startFreeAgent() {
  const payload = await api("/api/freeagent/start", {
    method: "POST",
    body: JSON.stringify({})
  });
  state.bootstrap.freeagent = payload.freeagent || state.bootstrap.freeagent;
  syncFreeAgentStatus();
  syncAssistantNote();
  alert(payload.message || "FreeAgent start completed");
}

async function pullFreeAgentModel() {
  if ((state.bootstrap?.freeagent?.provider || "") !== "ollama") {
    alert("현재 provider는 Ollama가 아니라서 model pull이 필요 없습니다.");
    return;
  }
  const model = prompt("다운로드할 Ollama 모델", state.bootstrap?.freeagent?.model || "qwen3.5:cloud");
  if (!model) {
    return;
  }
  const payload = await api("/api/freeagent/pull-model", {
    method: "POST",
    body: JSON.stringify({
      sessionId: state.selectedSessionId,
      planStep: state.selectedPlanStep,
      workspaceId: state.selectedWorkspaceId,
      projectPath: state.selectedProjectPath,
      model
    })
  });
  setJobDetail(payload);
  switchToOutputTab();
  await refreshAccounts();
  await refreshJobs();
  startPollingFromPayload(payload, "FreeAgent Pull Model");
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
  switchToOutputTab();
  await refreshAccounts();
  await refreshJobs();
  startPollingFromPayload(payload, title);
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

async function refreshProjectRuntimeStatus() {
  const projectPath = requireProjectPath();
  if (!projectPath) {
    return;
  }
  const payload = await api(`/api/project-runtime/status?projectPath=${encodeURIComponent(projectPath)}`);
  state.projectRuntimeStatus = payload;
  const target = byId("project-runtime-status");
  if (!target) {
    return;
  }
  if (!payload.matched) {
    target.textContent = payload.message || "runtime profile not matched";
    return;
  }
  const healthText = payload.healthUrl
    ? `${payload.healthOk ? "health ok" : "health fail"} · ${payload.healthUrl}`
    : "health url 없음";
  target.textContent = `${payload.label || payload.projectId} · ${healthText}`;
}

async function runProjectRuntimeAction(actionName, title) {
  const projectPath = requireProjectPath();
  if (!projectPath) {
    return;
  }
  const payload = await api(`/api/project-runtime/${actionName}`, {
    method: "POST",
    body: JSON.stringify({
      sessionId: state.selectedSessionId,
      planStep: state.selectedPlanStep,
      projectPath
    })
  });
  setJobDetail(payload);
  switchToOutputTab();
  await refreshAccounts();
  await refreshJobs();
  startPollingFromPayload(payload, title);
}

async function runProjectAssemblyAction(actionName, title) {
  const projectPath = requireProjectPath();
  if (!projectPath) {
    return;
  }
  const assembly = getSelectedProjectAssembly();
  const payload = await api(`/api/project-assembly/${actionName}`, {
    method: "POST",
    body: JSON.stringify({
      sessionId: state.selectedSessionId,
      planStep: state.selectedPlanStep,
      projectPath,
      projectId: assembly?.id || state.selectedProjectAssemblyId || ""
    })
  });
  setJobDetail(payload);
  switchToOutputTab();
  await refreshAccounts();
  await refreshJobs();
  startPollingFromPayload(payload, title);
}

async function buildSelectedProjectCommon() {
  await runProjectAssemblyAction("buildCommon", "Build Common Jars");
}

async function installSelectedProjectCommon() {
  await runProjectAssemblyAction("installCommon", "Install Common Jars");
}

async function buildSelectedProjectApp() {
  await runProjectAssemblyAction("buildProject", "Build Project App");
}

async function buildSelectedProjectAll() {
  await runProjectAssemblyAction("buildAll", "Build Common + Project");
}

async function startSelectedProjectRuntime() {
  await runProjectRuntimeAction("start", "Project Runtime Start");
}

async function stopSelectedProjectRuntime() {
  await runProjectRuntimeAction("stop", "Project Runtime Stop");
}

async function restartSelectedProjectRuntime() {
  await runProjectRuntimeAction("restart", "Project Runtime Restart");
}

async function verifySelectedProjectRuntime() {
  await runProjectRuntimeAction("verify", "Project Runtime Verify");
}

async function backupSelectedProjectSql() {
  await runProjectAssemblyAction("sqlBackup", "SQL Backup");
}

async function backupSelectedProjectPhysical() {
  await runProjectAssemblyAction("physicalBackup", "Physical Backup");
}

async function checkSelectedProjectBackupStatus() {
  await runProjectAssemblyAction("backupStatus", "Backup Status");
}

async function checkSelectedProjectTrafficStatus() {
  await runProjectAssemblyAction("trafficStatus", "Traffic Status");
}

async function tailSelectedProjectTraffic() {
  await runProjectAssemblyAction("trafficTail", "Traffic Tail");
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
  byId("login-status").textContent = accountStatusText(payload.currentAccount || { lastAuthStatus: payload.loggedIn ? "ready" : "not_ready" });
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
    ? `브라우저에서 코드를 입력하세요: ${payload.userCode} · 현재 창 instance=${state.instanceId || "default"}`
    : `브라우저 창을 열었습니다. 현재 창 instance=${state.instanceId || "default"} 기준으로 로그인합니다.`;
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

async function saveAccountSettings() {
  if (!state.selectedAccountId) {
    alert("먼저 관리할 계정을 선택하세요.");
    return;
  }
  await api(`/api/accounts/${state.selectedAccountId}/update`, {
    method: "POST",
    body: JSON.stringify({
      manualStatus: byId("account-editor-status").value,
      nextAvailableAt: localDateTimeValueToIso(byId("account-editor-next-available").value),
      manualNote: byId("account-editor-note").value.trim()
    })
  });
  await refreshAccounts();
}

function applyAccountSuggestedDate() {
  const accounts = state.bootstrap?.accounts || [];
  const selected = accounts.find((item) => item.id === state.selectedAccountId);
  if (!selected?.suggestedNextAvailableAt) {
    alert("적용할 추정 재사용 가능 시각이 없습니다.");
    return;
  }
  byId("account-editor-next-available").value = isoToLocalDateTimeValue(selected.suggestedNextAvailableAt);
}

function applyAccountTokenExpiryDate() {
  const accounts = state.bootstrap?.accounts || [];
  const selected = accounts.find((item) => item.id === state.selectedAccountId);
  if (!selected?.authTokenExpiresAt) {
    alert("적용할 토큰 exp 정보가 없습니다.");
    return;
  }
  byId("account-editor-next-available").value = isoToLocalDateTimeValue(selected.authTokenExpiresAt);
}

async function clearAccountSettings() {
  if (!state.selectedAccountId) {
    alert("먼저 관리할 계정을 선택하세요.");
    return;
  }
  await api(`/api/accounts/${state.selectedAccountId}/update`, {
    method: "POST",
    body: JSON.stringify({
      manualStatus: "",
      nextAvailableAt: "",
      manualNote: "",
      exhausted: false
    })
  });
  await refreshAccounts();
}

async function saveActionRouting() {
  const action = getSelectedAction();
  if (!action?.id) {
    alert("먼저 Quick Action을 선택하세요.");
    return;
  }
  const payload = await api(`/api/actions/${action.id}/routing`, {
    method: "POST",
    body: JSON.stringify({
      preferredAccountId: byId("action-routing-account").value,
      preferredAccountChain: byId("action-routing-chain").value,
      preferredAccountType: byId("action-routing-account-type").value,
      runtimePreset: byId("action-routing-preset").value
    })
  });
  state.bootstrap = state.bootstrap || {};
  state.bootstrap.actions = payload.actions || [];
  renderActions();
  refreshPromptPreview().catch(() => {});
}

async function clearActionRouting() {
  const action = getSelectedAction();
  if (!action?.id) {
    alert("먼저 Quick Action을 선택하세요.");
    return;
  }
  const payload = await api(`/api/actions/${action.id}/routing`, {
    method: "POST",
    body: JSON.stringify({
      preferredAccountId: "",
      preferredAccountChain: "",
      preferredAccountType: "",
      runtimePreset: ""
    })
  });
  state.bootstrap = state.bootstrap || {};
  state.bootstrap.actions = payload.actions || [];
  renderActions();
  refreshPromptPreview().catch(() => {});
}

function shouldSubmitComposePromptOnEnter(event) {
  if (!event || event.key !== "Enter") {
    return false;
  }
  if (event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) {
    return false;
  }
  if (event.isComposing) {
    return false;
  }
  return true;
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
  state.sessionPage = 1;
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
  state.sessionPage = 1;
  renderSessions(payload.items || [], payload.session || null);
  await refreshJobs();
}

async function deleteSelectedSession() {
  if (!state.selectedSessionId) {
    alert("먼저 세션을 선택하세요.");
    return;
  }
  const current = state.sessions.find((item) => item.id === state.selectedSessionId) || state.currentSession || {};
  const title = String(current.title || state.selectedSessionId).trim();
  const confirmed = window.confirm(`이 세션을 삭제할까요?\n\n${title}\n\n자식 브랜치나 실행 중 job이 있으면 삭제되지 않습니다.`);
  if (!confirmed) {
    return;
  }
  const payload = await api(`/api/sessions/${state.selectedSessionId}/delete`, {
    method: "POST",
    body: "{}"
  });
  state.sessionPage = 1;
  renderSessions(payload.items || [], payload.currentSession || null);
  await refreshJobs();
}

async function bootstrap() {
  state.bootstrap = await api("/api/bootstrap");
  state.instanceId = state.bootstrap.instanceId || state.instanceId || "default";
  state.selectedWorkspaceId = state.bootstrap.defaultWorkspaceId || state.bootstrap.workspaces?.[0]?.id || "";
  state.selectedCli = state.bootstrap.cliOptions?.[0]?.id || "codex";
  state.selectedFreeAgentModel = defaultFreeAgentModel(state.selectedCli);
  state.parallelAccountsEnabled = true;
  state.modelRoutingOptions = normalizeModelRoutingOptions(state.bootstrap.modelRouting || state.modelRoutingOptions);
  state.sessions = state.bootstrap.sessions || [];
  state.currentSession = state.bootstrap.currentSession || null;
  state.selectedSessionId = state.bootstrap.currentSessionId || state.sessions[0]?.id || "";
  state.referenceRoots = state.bootstrap.referenceRoots || [];
  state.projectRoots = state.bootstrap.projectRoots || [];
  state.projectAssemblies = state.bootstrap.projectAssemblies || { projects: [] };
  state.selectedProjectAssemblyId = state.projectAssemblies.defaultProjectId || state.projectAssemblies.projects?.[0]?.id || "";
  state.selectedReferenceRootId = state.referenceRoots[0]?.id || "";
  state.selectedProjectRootId = state.projectRoots[0]?.id || "";
  byId("reference-section-select").value = state.referenceSection;
  byId("codex-version").textContent = state.bootstrap.codexVersion || "unknown";
  if (byId("parallel-accounts-toggle")) {
    byId("parallel-accounts-toggle").checked = state.parallelAccountsEnabled;
  }
  syncModelRoutingControls();
  syncFreeAgentStatus();
  byId("login-status").textContent = state.bootstrap.loginReady ? "ready" : "not ready";
  byId("instance-label").textContent = state.instanceId;
  const runtimeLabel = state.bootstrap.runtimeRoot?.startsWith("/mnt/")
    ? `WSL path ${state.bootstrap.runtimeRoot}`
    : `Linux path ${state.bootstrap.runtimeRoot}`;
  byId("runtime-context").textContent = `${runtimeLabel} · ${state.bootstrap.codexHome || ""}`;
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
  syncTabs();
  syncWorkspaceCaption();
  renderAccounts(state.bootstrap.accounts || [], state.bootstrap.currentAccountId || "", state.bootstrap.currentAccount || {});
  renderProjectAssemblyPanel();
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
  if (isPasswordRoute()) {
    initPasswordRoute();
    return;
  }
  state.instanceId = currentInstanceId();
  loadUiState();
  syncTabs();
  syncPromptCompactionToggle();
  syncPromptRuntimeOptionsControls();
  document.querySelectorAll("[data-sidebar-tab]").forEach((element) => {
    element.addEventListener("click", () => {
      state.selectedSidebarTab = element.getAttribute("data-sidebar-tab") || "workspace";
      syncTabs();
    });
  });
  document.querySelectorAll("[data-main-tab]").forEach((element) => {
    element.addEventListener("click", () => {
      state.selectedMainTab = element.getAttribute("data-main-tab") || "compose";
      syncTabs();
    });
  });
  byId("run-selected-action").addEventListener("click", runAction);
  byId("run-custom-codex").addEventListener("click", runCustomCodex);
  byId("run-custom-shell").addEventListener("click", runCustomShell);
  byId("output-to-compose").addEventListener("click", switchToComposeTab);
  byId("prompt-compaction-toggle").addEventListener("change", () => {
    state.promptCompactionEnabled = byId("prompt-compaction-toggle").checked;
    syncPromptCompactionToggle();
    syncSelectedActionPrompt(false);
    refreshPromptPreview().catch(() => {});
  });
  byId("runtime-preset-select").addEventListener("change", () => {
    const preset = byId("runtime-preset-select").value || "auto";
    if (preset === "auto") {
      state.runtimePreset = "auto";
      persistUiState();
    } else if (preset !== "custom") {
      applyRuntimePreset(preset);
    } else {
      state.runtimePreset = "custom";
      persistUiState();
    }
    refreshPromptPreview().catch(() => {});
  });
  [
    "model-routing-enabled-toggle",
    "single-local-model-toggle",
    "hard-task-codex-toggle",
    "parallel-local-workers-toggle",
    "parallel-local-workers-count",
    "parallel-local-model-15b",
    "parallel-local-model-3b",
    "parallel-local-model-7b",
    "parallel-local-keep-loaded-toggle",
    "parallel-local-all-loaded-required-toggle",
    "parallel-account-max",
    "parallel-local-final-synthesizer",
    "runtime-browser-context-toggle",
    "runtime-reference-context-toggle",
    "runtime-menu-context-toggle",
    "runtime-question-saver-toggle",
    "runtime-compact-preamble-toggle",
    "runtime-omit-preamble-toggle",
    "runtime-whitespace-compact-toggle",
    "runtime-dedupe-lines-toggle",
    "runtime-strip-fences-toggle",
    "runtime-session-context-toggle",
    "runtime-source-analysis-toggle",
    "runtime-docs-toggle",
    "runtime-skills-toggle",
    "runtime-minimal-scan-toggle",
    "runtime-brief-output-toggle"
  ].forEach((id) => {
    byId(id).addEventListener("change", () => {
      readModelRoutingOptionsFromControls();
      readPromptRuntimeOptionsFromControls();
      refreshLocalModelStatus().catch(() => {});
      refreshPromptPreview().catch(() => {});
    });
  });
  byId("parallel-local-preload-now").addEventListener("click", () => {
    preloadSelectedLocalModels().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("parallel-local-retry-missing").addEventListener("click", () => {
    retryMissingLocalModels().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("parallel-local-unload-selected").addEventListener("click", () => {
    unloadSelectedLocalModels().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("parallel-local-refresh-status").addEventListener("click", () => {
    refreshLocalModelStatus().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("parallel-local-auto-keep-warm-toggle").addEventListener("change", () => {
    state.localModelAutoKeepWarm = Boolean(byId("parallel-local-auto-keep-warm-toggle")?.checked);
    persistUiState();
    syncLocalModelWarmLoop();
  });
  byId("parallel-local-keepalive-select").addEventListener("change", () => {
    state.localModelKeepAlive = String(byId("parallel-local-keepalive-select")?.value || "24h");
    persistUiState();
  });
  byId("parallel-local-warm-interval-select").addEventListener("change", () => {
    state.localModelWarmIntervalMs = Number(byId("parallel-local-warm-interval-select")?.value || 30000);
    persistUiState();
    syncLocalModelWarmLoop();
  });
  byId("refresh-prompt-preview").addEventListener("click", () => {
    refreshPromptPreview().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  [
    "custom-codex-prompt",
    "extra-input",
    "freeagent-model-input",
    "freeagent-targets",
    "freeagent-test-command",
    "runtime-focus-scope",
    "runtime-session-context-limit",
    "runtime-prompt-chars-limit",
    "assistant-cli",
    "freeagent-mode",
    "active-plan-step"
  ].forEach((id) => {
    byId(id).addEventListener("input", () => {
      refreshPromptPreview().catch(() => {});
    });
    byId(id).addEventListener("change", () => {
      refreshPromptPreview().catch(() => {});
    });
  });
  byId("custom-codex-prompt").addEventListener("keydown", (event) => {
    if (!shouldSubmitComposePromptOnEnter(event)) {
      return;
    }
    event.preventDefault();
    runCustomCodex().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("freeagent-setup").addEventListener("click", setupFreeAgent);
  byId("freeagent-start").addEventListener("click", startFreeAgent);
  byId("freeagent-pull-model").addEventListener("click", pullFreeAgentModel);
  byId("cancel-job").addEventListener("click", cancelCurrentJob);
  byId("refresh-jobs").addEventListener("click", refreshJobs);
  byId("clear-all-jobs").addEventListener("click", clearAllJobs);
  byId("recover-jobs").addEventListener("click", () => {
    recoverJobs().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("clear-job-filter").addEventListener("click", () => {
    focusPlanStep("").catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("job-page-prev").addEventListener("click", async () => {
    state.jobPage = Math.max(1, state.jobPage - 1);
    await refreshJobs();
  });
  byId("job-page-next").addEventListener("click", async () => {
    state.jobPage += 1;
    await refreshJobs();
  });
  byId("session-page-prev").addEventListener("click", async () => {
    state.sessionPage = Math.max(1, state.sessionPage - 1);
    await refreshSessions();
  });
  byId("session-page-next").addEventListener("click", async () => {
    state.sessionPage += 1;
    await refreshSessions();
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
  byId("delete-session").addEventListener("click", () => {
    deleteSelectedSession().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
      alert(error instanceof Error ? error.message : String(error));
    });
  });
  byId("open-new-instance").addEventListener("click", openNewInstanceWindow);
  byId("project-build-frontend").addEventListener("click", buildSelectedProjectFrontend);
  byId("project-package-backend").addEventListener("click", packageSelectedProjectBackend);
  byId("project-restart-18000").addEventListener("click", restartSelectedProject18000);
  byId("project-build-common").addEventListener("click", buildSelectedProjectCommon);
  byId("project-install-common").addEventListener("click", installSelectedProjectCommon);
  byId("project-build-app").addEventListener("click", buildSelectedProjectApp);
  byId("project-build-all").addEventListener("click", buildSelectedProjectAll);
  byId("project-assembly-register").addEventListener("click", () => {
    registerSelectedProjectAssembly().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("project-assembly-refresh").addEventListener("click", () => {
    refreshProjectAssemblies().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("project-assembly-select").addEventListener("change", async () => {
    state.selectedProjectAssemblyId = byId("project-assembly-select").value || "";
    const assembly = getSelectedProjectAssembly();
    if (assembly?.path) {
      await selectProjectPath(assembly.path);
    } else {
      renderProjectAssemblyPanel();
    }
  });
  byId("project-runtime-status-refresh").addEventListener("click", refreshProjectRuntimeStatus);
  byId("project-runtime-start").addEventListener("click", startSelectedProjectRuntime);
  byId("project-runtime-stop").addEventListener("click", stopSelectedProjectRuntime);
  byId("project-runtime-restart").addEventListener("click", restartSelectedProjectRuntime);
  byId("project-runtime-verify").addEventListener("click", verifySelectedProjectRuntime);
  byId("project-one-click").addEventListener("click", oneClickBuildAndRestart);
  byId("project-backup-sql").addEventListener("click", backupSelectedProjectSql);
  byId("project-backup-physical").addEventListener("click", backupSelectedProjectPhysical);
  byId("project-backup-status").addEventListener("click", checkSelectedProjectBackupStatus);
  byId("project-traffic-status").addEventListener("click", checkSelectedProjectTrafficStatus);
  byId("project-traffic-tail").addEventListener("click", tailSelectedProjectTraffic);
  byId("save-current-account").addEventListener("click", saveCurrentAccount);
  byId("save-account-settings").addEventListener("click", () => {
    saveAccountSettings().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("clear-account-settings").addEventListener("click", () => {
    clearAccountSettings().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("account-editor-apply-suggested").addEventListener("click", applyAccountSuggestedDate);
  byId("account-editor-apply-token-exp").addEventListener("click", applyAccountTokenExpiryDate);
  byId("start-login").addEventListener("click", startLogin);
  byId("logout-login").addEventListener("click", logoutLogin);
  byId("save-action-routing").addEventListener("click", () => {
    saveActionRouting().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("action-routing-chain").addEventListener("input", refreshActionRoutingChainPreview);
  byId("action-routing-chain-add-selected").addEventListener("click", () => {
    appendToActionRoutingChain(state.selectedAccountId);
  });
  byId("action-routing-chain-add-fixed").addEventListener("click", () => {
    appendToActionRoutingChain(byId("action-routing-account").value);
  });
  byId("action-routing-chain-clear").addEventListener("click", () => {
    setActionRoutingChain([]);
  });
  byId("clear-action-routing").addEventListener("click", () => {
    clearActionRouting().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
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
      setRawOutputText(error instanceof Error ? error.message : String(error));
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
        setRawOutputText(error instanceof Error ? error.message : String(error));
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
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("project-build-frontend").addEventListener("click", buildSelectedProjectFrontend);
  byId("project-package-backend").addEventListener("click", packageSelectedProjectBackend);
  byId("project-restart-18000").addEventListener("click", restartSelectedProject18000);
  byId("project-one-click").addEventListener("click", oneClickBuildAndRestart);
  byId("project-scan-menus").addEventListener("click", () => {
    scanProjectMenus().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("project-use-menu-context").addEventListener("click", () => {
    if (!shouldIncludeMenuContext()) {
      alert("메뉴 문맥 포함 옵션이 꺼져 있습니다.");
      return;
    }
    const text = buildMenuContextPrompt();
    if (!text) {
      alert("먼저 메뉴를 선택하세요.");
      return;
    }
    appendPromptText(text);
  });
  byId("runtime-focus-from-browser").addEventListener("click", () => {
    const browserPath = extractPathnameFromUrl(state.bootstrap?.browser?.currentUrl || byId("browser-address").value);
    if (!browserPath) {
      alert("현재 브라우저 경로를 찾지 못했습니다.");
      return;
    }
    setRuntimeFocusScope(browserPath);
  });
  byId("runtime-focus-from-menu").addEventListener("click", () => {
    const menuPath = selectedMenuFocusScope();
    if (!menuPath) {
      alert("먼저 프로젝트 메뉴를 선택하세요.");
      return;
    }
    setRuntimeFocusScope(menuPath);
  });
  byId("runtime-focus-clear").addEventListener("click", () => {
    setRuntimeFocusScope("");
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
    appendPromptText(buildReferencePrompt(meta).trimEnd());
  });
  byId("compose-reference-migration").addEventListener("click", () => {
    const meta = state.selectedReferenceMeta;
    if (!meta) {
      alert("먼저 reference 파일을 선택하세요.");
      return;
    }
    byId("custom-codex-prompt").value = buildMigrationPrompt(meta);
  });
  byId("copy-final-output").addEventListener("click", () => {
    copyFinalOutput().catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("copy-command-preview").addEventListener("click", () => {
    copyPanelText("command-preview", "copy-command-preview").catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  byId("copy-raw-output").addEventListener("click", () => {
    copyPanelText("raw-output", "copy-raw-output").catch((error) => {
      setRawOutputText(error instanceof Error ? error.message : String(error));
    });
  });
  try {
    await bootstrap();
    renderLocalModelLastResult(state.localModelLastResult);
    await refreshLocalModelStatus();
    syncLocalModelWarmLoop();
    await refreshPromptPreview();
  } catch (error) {
    setRawOutputText(error instanceof Error ? error.message : String(error));
  }
});

async function clearAllJobs() {
  if (!window.confirm("잡 목록을 모두 삭제할까요?")) {
    return;
  }
  if (state.selectedJobId) {
    state.selectedJobId = "";
  }
  await api("/api/jobs/clear", { method: "POST", body: "{}" });
  await refreshJobs();
}
