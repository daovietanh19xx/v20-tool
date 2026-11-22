chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "save-results") return;
  fetch("http://127.0.0.1:8765/api/extension/ket-qua", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows: message.rows || [] }),
  })
    .then((response) => response.json())
    .then((data) => sendResponse({ ok: true, data }))
    .catch((error) => sendResponse({ ok: false, error: String(error) }));
  return true;
});
