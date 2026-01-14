import { apiGet, apiPost } from "../api.js";
import { mountTopbar, toast } from "../components/ui.js";

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderResult(resultBlock, res) {
  resultBlock.innerHTML = `
    <div style="display:grid; gap:10px;">
      <div class="row">
        <span class="tag">Updated PaymentMethod: <span class="mono">${escapeHtml(res.payment_method_id)}</span></span>
        <span class="tag">Master account: <span class="mono">${escapeHtml(res.master_account_id || "")}</span></span>
      </div>
      <div class="hint">
        metadata.PROCESSING_ACCOUNT_PAYMENT_METHOD_ID =
        <span class="mono">${escapeHtml(res.processing_account_payment_method_id || "")}</span>
      </div>
    </div>
  `;
}

function renderLoadedPaymentMethod(resultBlock, data) {
  const pm = data?.payment_method || {};
  const md = pm?.metadata || {};
  const processing = md?.PROCESSING_ACCOUNT_PAYMENT_METHOD_ID || "";
  resultBlock.innerHTML = `
    <div style="display:grid; gap:12px;">
      <div class="row">
        <span class="tag">Loaded PaymentMethod: <span class="mono">${escapeHtml(pm.id || "")}</span></span>
        <span class="tag">Master account: <span class="mono">${escapeHtml(data.master_account_id || "")}</span></span>
        <span class="tag">Type: <span class="mono">${escapeHtml(pm.type || "")}</span></span>
      </div>
      <div class="hint">
        Current metadata.PROCESSING_ACCOUNT_PAYMENT_METHOD_ID =
        <span class="mono">${escapeHtml(processing)}</span>
      </div>
      <div class="stripe-box" style="overflow:auto;">
        <pre class="mono" style="margin:0; white-space:pre-wrap;">${escapeHtml(JSON.stringify(pm, null, 2))}</pre>
      </div>
    </div>
  `;
}

async function main() {
  const app = document.getElementById("app");
  mountTopbar(app, { title: "Stripe Multi-Account Demo", subtitle: "Update payment method metadata" });

  const form = document.getElementById("pmForm");
  const resultBlock = document.getElementById("resultBlock");
  const submitBtn = document.getElementById("submitBtn");
  const masterInput = document.getElementById("masterPaymentMethodId");
  const processingInput = document.getElementById("processingPaymentMethodId");
  const loadBtn = document.getElementById("loadBtn");

  let loadedMasterPmId = "";

  async function loadPaymentMethodIfNeeded({ force = false } = {}) {
    const masterPaymentMethodId = masterInput.value.trim();
    if (!masterPaymentMethodId) return;
    if (!force && masterPaymentMethodId === loadedMasterPmId) return;

    submitBtn.disabled = true;
    submitBtn.textContent = "Update";
    if (loadBtn) {
      loadBtn.disabled = true;
      loadBtn.textContent = "Loading...";
    }
    resultBlock.innerHTML = "";
    try {
      const data = await apiGet(`/api/payment-methods/${encodeURIComponent(masterPaymentMethodId)}`);
      loadedMasterPmId = masterPaymentMethodId;
      renderLoadedPaymentMethod(resultBlock, data);

      const current = data?.payment_method?.metadata?.PROCESSING_ACCOUNT_PAYMENT_METHOD_ID || "";
      if (current && !processingInput.value.trim()) {
        processingInput.value = current;
      }

      toast("success", "PaymentMethod loaded", "Review details before updating metadata.");
      submitBtn.disabled = false;
    } catch (e) {
      loadedMasterPmId = "";
      toast("error", "Load failed", e.message);
      submitBtn.disabled = true;
    } finally {
      if (loadBtn) {
        loadBtn.disabled = false;
        loadBtn.textContent = "Load";
      }
    }
  }

  // Load when the master payment method field loses focus.
  masterInput.addEventListener("blur", () => loadPaymentMethodIfNeeded({ force: false }));
  if (loadBtn) {
    // Allow reloading even if the ID didn't change.
    loadBtn.addEventListener("click", () => loadPaymentMethodIfNeeded({ force: true }));
  }

  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    resultBlock.innerHTML = "";
    submitBtn.disabled = true;
    submitBtn.textContent = "Updating...";
    try {
      const masterPaymentMethodId = document.getElementById("masterPaymentMethodId").value.trim();
      const processingPaymentMethodId = document.getElementById("processingPaymentMethodId").value.trim();

      if (!loadedMasterPmId || loadedMasterPmId !== masterPaymentMethodId) {
        throw new Error("Please load the master PaymentMethod first (click outside the field to trigger loading).");
      }

      const res = await apiPost("/api/payment-methods/update-processing-metadata", {
        master_account_custom_payment_method: masterPaymentMethodId,
        processing_account_payment_method_id: processingPaymentMethodId,
      });

      toast("success", "Updated", "Payment method metadata updated on master account.");
      renderResult(resultBlock, res);
    } catch (e) {
      toast("error", "Update failed", e.message);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Update";
    }
  });
}

main();


