const LAUNCHER_BASES = [
  "http://localhost:43110",
  "http://127.0.0.1:43110"
];

async function postJson(path, payload) {
  let lastError = null;
  for (const base of LAUNCHER_BASES) {
    try {
      const response = await fetch(`${base}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (response.ok) {
        return true;
      }
      lastError = new Error(`${response.status} ${response.statusText}`);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("launcher unavailable");
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message?.type) {
    return false;
  }
  const pathByType = {
    capture: "/api/browser/capture",
    state: "/api/browser/state",
    menuSnapshot: "/api/browser/menu-snapshot"
  };
  const path = pathByType[message.type];
  if (!path) {
    sendResponse({ ok: false, error: "unsupported message type" });
    return false;
  }
  postJson(path, message.payload || {})
    .then(() => sendResponse({ ok: true }))
    .catch((error) => sendResponse({ ok: false, error: String(error) }));
  return true;
});
