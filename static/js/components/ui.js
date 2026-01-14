function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
    else node.setAttribute(k, String(v));
  }
  for (const c of children) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

export function mountTopbar(container, { title, subtitle }) {
  const bar = el("div", { class: "topbar" }, [
    el("div", { class: "brand" }, [
      el("div", { class: "brand-title", text: title }),
      el("div", { class: "brand-subtitle", text: subtitle }),
    ]),
    el("div", { class: "tag mono", id: "envTag", text: "Stripe multi-account demo" }),
  ]);
  container.appendChild(bar);
}

let toastRoot = null;
function ensureToastRoot() {
  if (toastRoot) return toastRoot;
  toastRoot = el("div", { class: "toast", id: "toastRoot" });
  document.body.appendChild(toastRoot);
  return toastRoot;
}

export function toast(type, title, body, timeoutMs = 5000) {
  const root = ensureToastRoot();
  const item = el("div", { class: `toast-item ${type}` }, [
    el("p", { class: "toast-title", text: title }),
    el("p", { class: "toast-body", text: body }),
  ]);
  root.appendChild(item);
  window.setTimeout(() => item.remove(), timeoutMs);
}

export function setLoading(container, isLoading, text = "Loading...") {
  const existing = container.querySelector("[data-loading]");
  if (isLoading) {
    if (existing) return;
    container.appendChild(
      el("div", { class: "loading", "data-loading": "1" }, [el("div", { class: "spinner" }), el("div", { text })])
    );
  } else if (existing) {
    existing.remove();
  }
}

export function formatMoney(amountCents, currency) {
  try {
    const amount = amountCents / 100;
    return new Intl.NumberFormat(undefined, { style: "currency", currency: currency.toUpperCase() }).format(amount);
  } catch {
    return `${amountCents} ${currency}`.toUpperCase();
  }
}

export function countryBadgeForAlias(alias) {
  const a = String(alias || "").trim().toUpperCase();
  if (a === "EU") return { emoji: "🇫🇷", label: "France", alias: "EU" };
  if (a === "US") return { emoji: "🇺🇸", label: "United States", alias: "US" };
  if (a === "UK" || a === "GB") return { emoji: "🇬🇧", label: "United Kingdom", alias: a };
  return { emoji: "🏳️", label: "Unknown", alias: a || "?" };
}

export function countryBadge({ alias, country } = {}) {
  const c = String(country || "").trim().toUpperCase();
  if (c === "FR") return { emoji: "🇫🇷", label: "France", alias: String(alias || "").trim().toUpperCase() || "?" };
  if (c === "US") return { emoji: "🇺🇸", label: "United States", alias: String(alias || "").trim().toUpperCase() || "?" };
  // ISO2 is "GB", but many people use "UK" informally - accept both.
  if (c === "GB" || c === "UK")
    return { emoji: "🇬🇧", label: "United Kingdom", alias: String(alias || "").trim().toUpperCase() || "?" };
  // Fallback to alias mapping (EU/US) if country isn't provided.
  return countryBadgeForAlias(alias);
}

export function getQueryParam(name) {
  const url = new URL(window.location.href);
  return url.searchParams.get(name);
}


