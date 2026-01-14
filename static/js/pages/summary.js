import { mountTopbar, toast, getQueryParam, countryBadge } from "../components/ui.js";

const STORAGE_KEY = "byop_summary_v1";

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function readStored() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function mergeFromQuery(base) {
  // Stripe may redirect back with payment_intent and related params. We never display client_secret.
  const qPaymentIntent = getQueryParam("payment_intent");
  const qRedirectStatus = getQueryParam("redirect_status");
  const qSetupIntent = getQueryParam("setup_intent");

  const merged = { ...(base || {}) };
  if (qPaymentIntent) merged.redirect_payment_intent_id = qPaymentIntent;
  if (qSetupIntent) merged.redirect_setup_intent_id = qSetupIntent;
  if (qRedirectStatus) merged.redirect_status = qRedirectStatus;
  return merged;
}

function tag(label, value, { emoji, title } = {}) {
  const e = emoji ? `<span title="${escapeHtml(title || "")}">${emoji}</span> ` : "";
  return `<span class="tag">${escapeHtml(label)}: ${e}<span class="mono">${escapeHtml(value || "")}</span></span>`;
}

function render(summaryBlock, data) {
  if (!data) {
    summaryBlock.innerHTML = `<div class="hint">No summary data found. Complete a flow first.</div>`;
    return;
  }

  const masterAlias = data.master_alias || "";
  const processingAlias = data.processing_alias || "";
  const mBadge = countryBadge({ alias: masterAlias, country: data.master_country });
  const pBadge = countryBadge({ alias: processingAlias, country: data.processing_country });

  summaryBlock.innerHTML = `
    <div style="display:grid; gap:14px;">
      <div class="row">
        ${tag("Master account", data.master_account_id, { emoji: mBadge.emoji, title: mBadge.label })}
        ${tag("Processing account", data.processing_account_id, { emoji: pBadge.emoji, title: pBadge.label })}
      </div>

      <div class="row">
        ${tag("Stripe customer", data.stripe_customer_id)}
        ${tag("Stripe subscription", data.stripe_subscription_id)}
        ${tag("Stripe invoice", data.latest_invoice_id)}
      </div>

      <div class="row">
        ${data.master_payment_intent_id ? tag("Master invoice PaymentIntent", data.master_payment_intent_id) : ""}
        ${data.processing_payment_intent_id ? tag("Processing PaymentIntent", data.processing_payment_intent_id) : ""}
      </div>

      ${
        data.hosted_invoice_url
          ? `<div class="hint">Hosted invoice: <a class="mono" href="${escapeHtml(
              data.hosted_invoice_url
            )}" target="_blank" rel="noreferrer">Open</a></div>`
          : ""
      }

      ${
        data.redirect_status || data.redirect_payment_intent_id || data.redirect_setup_intent_id
          ? `<div class="hint">
              Return parameters:
              ${data.redirect_status ? `<span class="mono">redirect_status=${escapeHtml(data.redirect_status)}</span>` : ""}
              ${data.redirect_payment_intent_id ? ` • <span class="mono">payment_intent=${escapeHtml(data.redirect_payment_intent_id)}</span>` : ""}
              ${data.redirect_setup_intent_id ? ` • <span class="mono">setup_intent=${escapeHtml(data.redirect_setup_intent_id)}</span>` : ""}
            </div>`
          : ""
      }
    </div>
  `;
}

function main() {
  const app = document.getElementById("app");
  mountTopbar(app, { title: "Stripe Multi-Account Demo", subtitle: "Summary" });

  const summaryBlock = document.getElementById("summaryBlock");
  const stored = readStored();
  const merged = mergeFromQuery(stored);

  if (!stored) {
    toast("error", "No summary data", "Go back and complete the flow to populate this page.");
  }
  render(summaryBlock, merged);
}

main();


