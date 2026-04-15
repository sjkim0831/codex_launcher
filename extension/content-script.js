(function () {
  const bridgeEnabled = new URLSearchParams(location.search).get("codex_bridge") === "1";

  function send(type, payload) {
    chrome.runtime.sendMessage({ type, payload }, () => {
      void chrome.runtime.lastError;
    });
  }

  let menuSnapshotTimer = 0;
  let lastMenuSnapshotKey = "";
  let selectedElement = null;
  let captureMenu = null;
  let captureBadge = null;

  function ensureCaptureMenu() {
    if (!bridgeEnabled || captureMenu) {
      return;
    }
    captureMenu = document.createElement("div");
    captureMenu.style.position = "fixed";
    captureMenu.style.zIndex = "2147483647";
    captureMenu.style.display = "none";
    captureMenu.style.minWidth = "220px";
    captureMenu.style.background = "#fffaf1";
    captureMenu.style.color = "#24190f";
    captureMenu.style.border = "1px solid #c8b79a";
    captureMenu.style.borderRadius = "12px";
    captureMenu.style.boxShadow = "0 16px 36px rgba(30, 20, 10, 0.18)";
    captureMenu.style.overflow = "hidden";
    captureMenu.style.font = "13px/1.4 sans-serif";
    captureMenu.innerHTML = [
      '<button type="button" data-kind="html" style="width:100%;border:0;background:transparent;text-align:left;padding:10px 12px;cursor:pointer;">Codex Prompt에 element HTML 넣기</button>',
      '<button type="button" data-kind="text" style="width:100%;border:0;background:transparent;text-align:left;padding:10px 12px;cursor:pointer;">Codex Prompt에 element text 넣기</button>',
      '<button type="button" data-kind="selector" style="width:100%;border:0;background:transparent;text-align:left;padding:10px 12px;cursor:pointer;">Codex Prompt에 selector만 넣기</button>'
    ].join("");
    document.documentElement.appendChild(captureMenu);
    captureBadge = document.createElement("div");
    captureBadge.textContent = "Codex Browser Capture";
    captureBadge.style.position = "fixed";
    captureBadge.style.right = "12px";
    captureBadge.style.bottom = "12px";
    captureBadge.style.zIndex = "2147483647";
    captureBadge.style.padding = "8px 10px";
    captureBadge.style.borderRadius = "999px";
    captureBadge.style.background = "rgba(36,25,15,0.9)";
    captureBadge.style.color = "#fff";
    captureBadge.style.font = "12px/1 sans-serif";
    captureBadge.style.pointerEvents = "none";
    document.documentElement.appendChild(captureBadge);
    captureMenu.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-kind]");
      if (!button || !selectedElement) {
        return;
      }
      const payload = {
        url: location.href,
        title: document.title || "",
        selector: buildSelector(selectedElement),
        tagName: selectedElement.tagName || "",
        text: (selectedElement.innerText || selectedElement.textContent || "").trim().slice(0, 4000),
        html: (selectedElement.outerHTML || "").slice(0, 12000)
      };
      if (button.dataset.kind === "selector") {
        payload.html = "";
        payload.text = "";
      } else if (button.dataset.kind === "text") {
        payload.html = "";
      }
      send("capture", payload);
      hideCaptureMenu();
    });
    document.addEventListener("click", hideCaptureMenu, true);
    window.addEventListener("blur", hideCaptureMenu, true);
  }

  function hideCaptureMenu() {
    if (captureMenu) {
      captureMenu.style.display = "none";
    }
  }

  function buildSelector(node) {
    if (!(node instanceof Element)) {
      return "";
    }
    const parts = [];
    let current = node;
    while (current && current.nodeType === 1 && parts.length < 6) {
      let part = current.tagName.toLowerCase();
      if (current.id) {
        part += `#${current.id}`;
        parts.unshift(part);
        break;
      }
      const className = (current.className || "")
        .toString()
        .trim()
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .join(".");
      if (className) {
        part += `.${className}`;
      }
      const parent = current.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((child) => child.tagName === current.tagName);
        if (siblings.length > 1) {
          part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
        }
      }
      parts.unshift(part);
      current = current.parentElement;
    }
    return parts.join(" > ");
  }

  function handleContextMenu(event) {
    if (!bridgeEnabled || event.shiftKey) {
      return;
    }
    ensureCaptureMenu();
    selectedElement = event.target instanceof Element ? event.target : null;
    if (!selectedElement || !captureMenu) {
      return;
    }
    event.preventDefault();
    captureMenu.style.left = `${event.clientX}px`;
    captureMenu.style.top = `${event.clientY}px`;
    captureMenu.style.display = "block";
  }

  function reportState() {
    send("state", {
      currentUrl: location.href,
      currentTitle: document.title
    });
    scheduleMenuSnapshot();
  }

  async function fetchJson(url) {
    try {
      const response = await fetch(url, {
        method: "GET",
        credentials: "include",
        headers: {
          Accept: "application/json"
        },
        cache: "no-store"
      });
      const contentType = response.headers.get("content-type") || "";
      if (!response.ok || !contentType.includes("application/json")) {
        return null;
      }
      return await response.json();
    } catch (_error) {
      return null;
    }
  }

  async function captureMenuSnapshot() {
    const origin = location.origin;
    const [home, admin] = await Promise.all([
      fetchJson(`${origin}/api/sitemap`),
      fetchJson(`${origin}/admin/api/admin/content/sitemap`)
    ]);
    const payload = {};
    if (home && (Array.isArray(home.homeMenu) || Array.isArray(home.siteMapSections))) {
      payload.home = home;
    }
    if (admin && Array.isArray(admin.siteMapSections)) {
      payload.admin = admin;
    }
    const snapshotKey = JSON.stringify(payload);
    if (!snapshotKey || snapshotKey === "{}" || snapshotKey === lastMenuSnapshotKey) {
      return;
    }
    lastMenuSnapshotKey = snapshotKey;
    send("menuSnapshot", payload);
  }

  function scheduleMenuSnapshot() {
    window.clearTimeout(menuSnapshotTimer);
    menuSnapshotTimer = window.setTimeout(() => {
      captureMenuSnapshot().catch(() => {});
    }, 250);
  }

  const originalPushState = history.pushState.bind(history);
  const originalReplaceState = history.replaceState.bind(history);
  history.pushState = function (...args) {
    const result = originalPushState(...args);
    window.setTimeout(reportState, 0);
    return result;
  };
  history.replaceState = function (...args) {
    const result = originalReplaceState(...args);
    window.setTimeout(reportState, 0);
    return result;
  };

  window.addEventListener("popstate", reportState, true);
  window.addEventListener("hashchange", reportState, true);
  window.addEventListener("focus", scheduleMenuSnapshot, true);
  document.addEventListener("contextmenu", handleContextMenu, true);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      scheduleMenuSnapshot();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", reportState, { once: true });
  } else {
    reportState();
  }
})();
