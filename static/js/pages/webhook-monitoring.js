import { mountTopbar, toast, countryBadge } from "../components/ui.js";

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmtTime(tsSeconds) {
  const d = new Date(Number(tsSeconds) * 1000);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString();
}

function renderRow(ev) {
  const badge = countryBadge({ alias: ev.alias, country: ev.country });
  const time = fmtTime(ev.received_at);
  const alias = String(ev.alias || "").toUpperCase();
  const type = String(ev.type || "");

  const row = document.createElement("div");
  row.className = "monitor-row";
  row.innerHTML = `
    <div class="monitor-col time mono">${escapeHtml(time)}</div>
    <div class="monitor-col country" title="${escapeHtml(badge.label)}">${badge.emoji}</div>
    <div class="monitor-col alias"><span class="tag mono">${escapeHtml(alias)}</span></div>
    <div class="monitor-col type mono">${escapeHtml(type)}</div>
  `;
  return row;
}

function setStatus(text, tone = "info") {
  const el = document.getElementById("monitorStatus");
  if (!el) return;
  el.textContent = text;
  el.classList.remove("ok", "warn", "err");
  if (tone === "ok") el.classList.add("ok");
  if (tone === "warn") el.classList.add("warn");
  if (tone === "err") el.classList.add("err");
}

function setCount(n) {
  const el = document.getElementById("monitorCount");
  if (!el) return;
  el.textContent = String(n);
}

function main() {
  const app = document.getElementById("app");
  mountTopbar(app, { title: "Webhook monitoring", subtitle: "Live webhooks via Server-Sent Events (no persistence)" });

  const list = document.getElementById("monitorList");
  if (!list) return;

  // Header row
  const header = document.createElement("div");
  header.className = "monitor-row header";
  header.innerHTML = `
    <div class="monitor-col time">Time</div>
    <div class="monitor-col country">Country</div>
    <div class="monitor-col alias">Alias</div>
    <div class="monitor-col type">Event type</div>
  `;
  list.appendChild(header);

  const MAX_ROWS = 250;
  let count = 0;
  setCount(0);
  setStatus("Connecting…", "warn");

  const es = new EventSource("/api/monitor/webhooks/stream");

  es.addEventListener("open", () => {
    setStatus("Connected", "ok");
  });

  es.addEventListener("error", () => {
    // Browser will auto-retry; keep UI informative.
    setStatus("Disconnected (retrying…)", "err");
  });

  es.addEventListener("hello", () => {
    setStatus("Connected", "ok");
  });

  es.addEventListener("webhook", (msg) => {
    try {
      const ev = JSON.parse(msg.data || "{}");
      const row = renderRow(ev);
      // Newest first: insert right after the header row.
      const insertBeforeNode = list.children[1] || null;
      list.insertBefore(row, insertBeforeNode);
      count += 1;
      setCount(count);

      // Trim (keep header + last N events)
      while (list.children.length > MAX_ROWS + 1) {
        // Oldest is now at the bottom.
        list.removeChild(list.lastElementChild);
      }
    } catch (e) {
      toast("error", "Failed to parse webhook event", String(e?.message || e));
    }
  });
}

main();


