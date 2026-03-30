(function () {
  function send(type, payload) {
    chrome.runtime.sendMessage({ type, payload }, () => {
      void chrome.runtime.lastError;
    });
  }

  let menuSnapshotTimer = 0;
  let lastMenuSnapshotKey = "";

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
