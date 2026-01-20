export function el(tag, attrs = {}, children = []) {
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

function iso2ToFlagEmoji(code) {
  const c = String(code || "").trim().toUpperCase();
  // Common non-ISO but frequently used codes:
  if (c === "UK") return "🇬🇧";
  if (c === "EU") return "🇪🇺";
  // ISO 3166-1 alpha-2 flags are represented by "regional indicator symbols":
  // 🇦 = 0x1F1E6 ... 🇿 = 0x1F1FF
  if (!/^[A-Z]{2}$/.test(c)) return "🏳️";
  const A = "A".charCodeAt(0);
  const base = 0x1f1e6; // regional indicator A
  const cp1 = base + (c.charCodeAt(0) - A);
  const cp2 = base + (c.charCodeAt(1) - A);
  return String.fromCodePoint(cp1, cp2);
}

export function countryBadgeForAlias(alias) {
  const a = String(alias || "").trim().toUpperCase();
  if (a === "EU") return { emoji: "🇪🇺", label: "European Union", alias: "EU" };
  if (a === "US") return { emoji: "🇺🇸", label: "United States", alias: "US" };
  if (a === "UK" || a === "GB") return { emoji: "🇬🇧", label: "United Kingdom", alias: a };
  if (/^[A-Z]{2}$/.test(a)) return { emoji: iso2ToFlagEmoji(a), label: a, alias: a };
  return { emoji: "🏳️", label: "Unknown", alias: a || "?" };
}

export function countryBadge({ alias, country } = {}) {
  const c = String(country || "").trim().toUpperCase();
  const a = String(alias || "").trim().toUpperCase() || "?";

  // If we have a country ISO2, use the generic ISO2 flag rendering.
  if (c) {
    const cc = c === "UK" ? "GB" : c;
    const emoji = iso2ToFlagEmoji(cc);
    const label =
      cc === "US"
        ? "United States"
        : cc === "FR"
          ? "France"
          : cc === "GB"
            ? "United Kingdom"
            : cc === "EU"
              ? "European Union"
              : cc;
    return { emoji, label, alias: a };
  }

  // Fallback to alias mapping if country isn't provided.
  return countryBadgeForAlias(alias);
}

export function getQueryParam(name) {
  const url = new URL(window.location.href);
  return url.searchParams.get(name);
}


