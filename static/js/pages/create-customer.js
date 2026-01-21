import { apiGet, apiPost } from "../api.js";
import { mountTopbar, setLoading, toast, getQueryParam, formatMoney, countryBadge } from "../components/ui.js";

const SUMMARY_STORAGE_KEY = "byop_summary_v1";

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderSelection(selectionBlock, data) {
  const price = data.price || {};
  const master = data.master_account || {};
  const processingAlias = price.account_alias || "";
  const masterAlias = master.alias || "";
  const pBadge = countryBadge({ alias: processingAlias, country: data?.processing_account?.country });
  const mBadge = countryBadge({ alias: masterAlias, country: master?.country });
  selectionBlock.innerHTML = `
    <div style="display:grid; gap:10px;">
      <div class="row">
        <span class="tag">Price: <span class="mono">${escapeHtml(price.id || "")}</span></span>
        <span class="tag">Currency: <span class="mono">${escapeHtml(price.currency || "")}</span></span>
        <span class="tag">Amount: <span class="mono">${escapeHtml(formatMoney(price.amount_cents, price.currency))}</span></span>
      </div>
      <div class="row">
        <span class="tag">Account alias: <span class="mono">${escapeHtml(price.account_alias || "")}</span> <span title="${escapeHtml(
          pBadge.label
        )}">${pBadge.emoji}</span></span>
        <span class="tag">Processing account: <span title="${escapeHtml(pBadge.label)}">${pBadge.emoji}</span> <span class="mono">${escapeHtml(
          data.processing_account_id || ""
        )}</span></span>
      </div>
      <div class="row">
        <span class="tag">Master account: <span class="mono">${escapeHtml(master.alias || "")}</span> <span title="${escapeHtml(
          mBadge.label
        )}">${mBadge.emoji}</span></span>
        <span class="tag">Created on: <span title="${escapeHtml(mBadge.label)}">${mBadge.emoji}</span> <span class="mono">${escapeHtml(
          master.account_id || ""
        )}</span></span>
      </div>
      <div class="hint">
        Backend endpoint: <span class="mono">/api/stripe/publishable-key</span>
      </div>
    </div>
  `;
}

function renderResult(resultBlock, result, { masterAlias, processingAlias }) {
  const pBadge = countryBadge({ alias: processingAlias, country: result?.processing_country });
  const mBadge = countryBadge({ alias: masterAlias, country: result?.master_country });
  resultBlock.innerHTML = `
    <div style="display:grid; gap:10px;">
      <div class="row">
        <span class="tag">Stripe customer id: <span class="mono">${escapeHtml(result.stripe_customer_id)}</span></span>
      </div>
      <div class="hint">
        Customer was created on <span title="${escapeHtml(mBadge.label)}">${mBadge.emoji}</span> <span class="mono">${escapeHtml(
          result.created_on_account_id
        )}</span> (master), processing on <span title="${escapeHtml(pBadge.label)}">${pBadge.emoji}</span> <span class="mono">${escapeHtml(
          result.processing_account_id
        )}</span>.
      </div>
    </div>
  `;
}

function renderSubscription(resultBlock, sub, { masterAlias, processingAlias }) {
  const pBadge = countryBadge({ alias: processingAlias, country: sub?.processing_country });
  const mBadge = countryBadge({ alias: masterAlias, country: sub?.master_country });
  const ccy = sub?.invoice_currency || "";
  const totalIncl = sub?.invoice_total != null ? formatMoney(Number(sub.invoice_total), ccy) : null;
  const totalExcl = sub?.invoice_total_excluding_tax != null ? formatMoney(Number(sub.invoice_total_excluding_tax), ccy) : null;
  const wrap = document.createElement("div");
  wrap.style.display = "grid";
  wrap.style.gap = "10px";
  wrap.style.marginTop = "12px";
  wrap.innerHTML = `
    <div class="divider"></div>
    <div class="row">
      <span class="tag">Stripe subscription id: <span class="mono">${escapeHtml(sub.stripe_subscription_id)}</span></span>
      ${sub.latest_invoice_id ? `<span class="tag">Latest invoice id: <span class="mono">${escapeHtml(sub.latest_invoice_id)}</span></span>` : ""}
    </div>
    ${
      totalIncl || totalExcl
        ? `<div class="row">
            ${totalIncl ? `<span class="tag">Total: <span class="mono">${escapeHtml(totalIncl)}</span></span>` : ""}
            ${totalExcl ? `<span class="tag">Total excl. tax: <span class="mono">${escapeHtml(totalExcl)}</span></span>` : ""}
          </div>`
        : ""
    }
    ${sub.hosted_invoice_url ? `<div class="hint">Invoice: <a class="mono" href="${escapeHtml(sub.hosted_invoice_url)}" target="_blank" rel="noreferrer">Open hosted invoice</a></div>` : ""}
    <div class="hint">
      Subscription status: <span class="mono">${escapeHtml(sub.status || "")}</span> — created on <span title="${escapeHtml(
        mBadge.label
      )}">${mBadge.emoji}</span> <span class="mono">${escapeHtml(sub.created_on_account_id)}</span>, processing on <span title="${escapeHtml(
        pBadge.label
      )}">${pBadge.emoji}</span> <span class="mono">${escapeHtml(sub.processing_account_id)}</span>.
    </div>
  `;
  resultBlock.appendChild(wrap);
  return wrap;
}

async function mountPaymentElement({
  container,
  stripe,
  clientSecret,
  appearance,
  processingAccountId,
  createdOnAccountId,
  paymentIntentId,
  processingAlias,
  masterAlias,
  summaryData,
}) {
  container.innerHTML = "";
  const paymentBox = document.createElement("div");
  paymentBox.style.display = "grid";
  paymentBox.style.gap = "12px";

  const title = document.createElement("div");
  const pBadge = countryBadge({ alias: processingAlias, country: summaryData?.processing_country });
  const mBadge = countryBadge({ alias: masterAlias, country: summaryData?.master_country });
  const sameAccount = processingAccountId && createdOnAccountId && processingAccountId === createdOnAccountId;
  title.innerHTML = `
    <div class="row" style="margin-bottom:8px;">
      <span class="tag">Processing account: <span title="${escapeHtml(pBadge.label)}">${pBadge.emoji}</span> <span class="mono">${escapeHtml(
        processingAccountId || ""
      )}</span></span>
      ${createdOnAccountId ? `<span class="tag">Master account: <span title="${escapeHtml(mBadge.label)}">${mBadge.emoji}</span> <span class="mono">${escapeHtml(
        createdOnAccountId
      )}</span></span>` : ""}
      ${paymentIntentId ? `<span class="tag">PaymentIntent: <span class="mono">${escapeHtml(paymentIntentId)}</span></span>` : ""}
    </div>
    <div class="hint">
      ${sameAccount ? "Payment is processed on the same account as the subscription (master)." : "Payment is processed on a different account than the subscription (master)."}
      Enter a payment method to confirm the invoice PaymentIntent.
    </div>
  `;

  const elementMount = document.createElement("div");
  elementMount.className = "stripe-box";
  elementMount.id = "paymentElement";

  const actions = document.createElement("div");
  actions.className = "row";

  const confirmBtn = document.createElement("button");
  confirmBtn.className = "btn btn-primary";
  confirmBtn.type = "button";
  confirmBtn.textContent = "Confirm payment";

  actions.appendChild(confirmBtn);

  paymentBox.appendChild(title);
  paymentBox.appendChild(elementMount);
  paymentBox.appendChild(actions);
  container.appendChild(paymentBox);

  const elements = stripe.elements({ clientSecret, appearance });
  const paymentElement = elements.create("payment");
  paymentElement.mount("#paymentElement");

  confirmBtn.addEventListener("click", async () => {
    confirmBtn.disabled = true;
    confirmBtn.textContent = "Confirming...";
    try {
      if (summaryData) {
        try {
          sessionStorage.setItem(SUMMARY_STORAGE_KEY, JSON.stringify(summaryData));
        } catch {
          // ignore storage errors
        }
      }
      const returnUrl = `${window.location.origin}/summary`;
      const { error, paymentIntent } = await stripe.confirmPayment({
        elements,
        confirmParams: { return_url: returnUrl },
        redirect: "if_required",
      });
      if (error) throw new Error(error.message || "Payment confirmation failed");
      const status = paymentIntent?.status || "unknown";
      // If no redirect is required, navigate to summary immediately on success-like statuses.
      if (["succeeded", "processing", "requires_capture"].includes(status)) {
        window.location.href = "/summary";
        return;
      }
      toast("success", "Payment submitted", `PaymentIntent status: ${status}`);
    } catch (e) {
      toast("error", "Payment failed", e.message);
    } finally {
      confirmBtn.disabled = false;
      confirmBtn.textContent = "Confirm payment";
    }
  });
}

async function main() {
  const app = document.getElementById("app");
  mountTopbar(app, { title: "Stripe Multi-Account Demo", subtitle: "Create customer" });

  const priceId = (getQueryParam("price_id") || "").trim();
  if (!priceId) {
    toast("error", "Missing price_id", "Go back and select a price first.");
    return;
  }

  const selectionBlock = document.getElementById("selectionBlock");
  const resultBlock = document.getElementById("resultBlock");
  const submitBtn = document.getElementById("submitBtn");

  setLoading(selectionBlock, true, "Loading Stripe publishable key...");
  let masterPublishableKey = "";
  let processingPublishableKey = "";
  let processingAccountId = "";
  let processingAlias = "";
  let masterAlias = "";
  let processingCountry = "";
  let masterCountry = "";
  let stripeInstance = null;
  let addressElement = null;
  let appearance = null;

  try {
    const data = await apiGet(`/api/stripe/publishable-key?price_id=${encodeURIComponent(priceId)}`);
    masterPublishableKey = data.publishable_key;
    processingPublishableKey = data.processing_publishable_key || "";
    processingAccountId = data.processing_account_id;
    processingAlias = data?.price?.account_alias || "";
    masterAlias = data?.master_account?.alias || "";
    processingCountry = data?.processing_account?.country || "";
    masterCountry = data?.master_account?.country || "";
    renderSelection(selectionBlock, data);

    if (!window.Stripe) {
      throw new Error("Stripe.js failed to load. Check network access.");
    }
    stripeInstance = window.Stripe(masterPublishableKey);

    appearance = {
      theme: "night",
      variables: {
        colorPrimary: "#2f6fed",
        colorText: "#e8eefc",
        colorBackground: "#0f182a",
        colorDanger: "#e5484d",
        fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial",
        borderRadius: "12px",
      },
    };
    const elements = stripeInstance.elements({ appearance });
    const googleApiKey = data?.address_autocomplete?.google_maps_places_api_key || "";
    const addressOptions = {
      mode: "billing",
      // Stripe docs: when Address Element is used standalone, you must provide your own Places API key:
      // https://docs.stripe.com/elements/address-element#autocomplete
      ...(googleApiKey ? { autocomplete: { apiKey: googleApiKey } } : {}),
    };
    addressElement = elements.create("address", addressOptions);
    addressElement.mount("#addressElement");
  } catch (e) {
    toast("error", "Initialization failed", e.message);
  } finally {
    setLoading(selectionBlock, false);
  }

  const form = document.getElementById("customerForm");
  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    resultBlock.innerHTML = "";
    const paymentCard = document.getElementById("paymentCard");
    const paymentBlock = document.getElementById("paymentBlock");
    if (paymentCard) paymentCard.style.display = "none";
    if (paymentBlock) paymentBlock.innerHTML = "";

    if (!addressElement) {
      toast("error", "Not ready", "Stripe Address Element is not initialized.");
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Creating...";

    try {
      const firstName = document.getElementById("firstName").value.trim();
      const lastName = document.getElementById("lastName").value.trim();
      const email = document.getElementById("email").value.trim();

      const av = await addressElement.getValue();
      if (!av?.complete) {
        throw new Error("Please complete the address fields.");
      }

      const addr = av?.value?.address || {};
      const payload = {
        price_id: priceId,
        first_name: firstName,
        last_name: lastName,
        email,
        address: {
          line1: addr.line1 || "",
          line2: addr.line2 || "",
          city: addr.city || "",
          state: addr.state || "",
          postal_code: addr.postal_code || "",
          country: addr.country || "",
        },
      };

      const result = await apiPost("/api/customers", payload);
      toast("success", "Customer created", `Stripe customer: ${result.stripe_customer_id}`);
      renderResult(resultBlock, { ...result, master_country: masterCountry, processing_country: processingCountry }, { masterAlias, processingAlias });

      // Chain: create subscription on master account with the selected price (qty=1).
      const sub = await apiPost("/api/subscriptions", {
        price_id: priceId,
        stripe_customer_id: result.stripe_customer_id,
      });
      toast("success", "Subscription created", `Stripe subscription: ${sub.stripe_subscription_id}`);
      const subWrap = renderSubscription(
        resultBlock,
        { ...sub, master_country: masterCountry, processing_country: processingCountry },
        { masterAlias, processingAlias }
      );

      const summaryBase = {
        master_alias: masterAlias,
        processing_alias: processingAlias,
        master_country: masterCountry,
        processing_country: processingCountry,
        master_account_id: sub.created_on_account_id,
        processing_account_id: sub.processing_account_id,
        stripe_customer_id: result.stripe_customer_id,
        stripe_subscription_id: sub.stripe_subscription_id,
        latest_invoice_id: sub.latest_invoice_id,
        hosted_invoice_url: sub.hosted_invoice_url,
        master_payment_intent_id: sub.payment_intent_id,
        invoice_currency: sub.invoice_currency,
        invoice_total: sub.invoice_total,
        invoice_total_excluding_tax: sub.invoice_total_excluding_tax,
      };

      // If processing == master, allow payment on the frontend using Payment Element + PaymentIntent client_secret.
      const canPayHere =
        sub.processing_account_id && sub.created_on_account_id && sub.processing_account_id === sub.created_on_account_id;

      if (canPayHere && sub.payment_intent_client_secret && stripeInstance && appearance) {
        if (paymentCard) paymentCard.style.display = "block";
        await mountPaymentElement({
          container: paymentBlock || subWrap,
          stripe: stripeInstance,
          clientSecret: sub.payment_intent_client_secret,
          appearance,
          processingAccountId: sub.processing_account_id,
          createdOnAccountId: sub.created_on_account_id,
          paymentIntentId: sub.payment_intent_id,
          processingAlias,
          masterAlias,
          summaryData: summaryBase,
        });
      } else if (!canPayHere) {
        // processing != master: create a dedicated PaymentIntent on the processing account with same amount/currency.
        const pi = await apiPost("/api/processing-payment-intents", {
          price_id: priceId,
          stripe_customer_id: result.stripe_customer_id,
          original_invoice_id: sub.latest_invoice_id,
          original_subscription_id: sub.stripe_subscription_id,
        });

        const summaryProcessing = {
          ...summaryBase,
          processing_payment_intent_id: pi.payment_intent_id,
        };

        const pk = pi.processing_publishable_key || processingPublishableKey;
        if (!pk) {
          throw new Error("Missing processing publishable key. Check server response / env configuration.");
        }
        const processingStripe = window.Stripe(pk);

        if (paymentCard) paymentCard.style.display = "block";
        await mountPaymentElement({
          container: paymentBlock || subWrap,
          stripe: processingStripe,
          clientSecret: pi.payment_intent_client_secret,
          appearance,
          processingAccountId: pi.processing_account_id,
          createdOnAccountId: sub.created_on_account_id,
          paymentIntentId: pi.payment_intent_id,
          processingAlias,
          masterAlias,
          summaryData: summaryProcessing,
        });
      } else if (!sub.payment_intent_client_secret) {
        const note = document.createElement("div");
        note.className = "hint";
        note.style.marginTop = "10px";
        note.textContent =
          "No PaymentIntent client_secret was returned. Check subscription/invoice settings or expansion.";
        subWrap.appendChild(note);
      }
    } catch (e) {
      toast("error", "Failed to create customer", e.message);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Create Stripe Customer";
    }
  });
}

main();


