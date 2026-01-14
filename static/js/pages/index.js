import { apiGet } from "../api.js";
import { mountTopbar, setLoading, toast, formatMoney, countryBadge } from "../components/ui.js";

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function sortPrices(prices) {
  const order = { eur: 1, usd: 2, gbp: 3 };
  return [...prices].sort((a, b) => {
    const ca = String(a.currency || "").toLowerCase();
    const cb = String(b.currency || "").toLowerCase();
    const oa = order[ca] || 99;
    const ob = order[cb] || 99;
    if (oa !== ob) return oa - ob;
    return ca.localeCompare(cb);
  });
}

function optionLabel(p) {
  const money = formatMoney(p.amount_cents, p.currency);
  const ccy = String(p.currency || "").toUpperCase();
  return `${ccy} — ${money}`;
}

function renderProduct(productBlock, catalog) {
  const product = catalog.product || {};
  const prices = sortPrices(catalog.prices || []);

  productBlock.innerHTML = "";

  const title = document.createElement("div");
  title.style.display = "grid";
  title.style.gap = "6px";
  title.innerHTML = `
    <div style="font-weight:700; font-size:16px;">${escapeHtml(product.name || "Product")}</div>
    <div class="hint">${escapeHtml(product.description || "")}</div>
  `;

  const picker = document.createElement("div");
  picker.style.display = "grid";
  picker.style.gap = "12px";
  picker.style.marginTop = "14px";

  const selectRow = document.createElement("div");
  selectRow.className = "row";
  selectRow.style.alignItems = "center";

  const selectWrap = document.createElement("div");
  selectWrap.style.flex = "1";
  selectWrap.style.minWidth = "260px";
  selectWrap.style.display = "grid";
  selectWrap.style.gap = "6px";

  const label = document.createElement("div");
  label.className = "label";
  label.textContent = "Currency";

  const select = document.createElement("select");
  select.className = "input mono";
  select.id = "priceSelect";

  for (const p of prices) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = optionLabel(p);
    select.appendChild(opt);
  }

  const helper = document.createElement("div");
  helper.className = "hint";
  helper.textContent = "Pick a currency to see which master and processing accounts will be used.";

  selectWrap.appendChild(label);
  selectWrap.appendChild(select);
  selectWrap.appendChild(helper);

  const continueBtn = document.createElement("button");
  continueBtn.className = "btn btn-primary";
  continueBtn.type = "button";
  continueBtn.textContent = "Continue";

  selectRow.appendChild(selectWrap);
  selectRow.appendChild(continueBtn);
  picker.appendChild(selectRow);

  const info = document.createElement("div");
  info.id = "selectionInfo";
  info.className = "stripe-box";
  info.innerHTML = `<div class="hint">Select a currency to load account routing information…</div>`;
  picker.appendChild(info);

  const meta = document.createElement("div");
  meta.style.marginTop = "14px";
  meta.innerHTML = `
    <div class="row">
      ${prices
        .map(
          (p) => {
            const b = countryBadge({ alias: p.account_alias, country: p.account_country });
            return `<span class="tag"><span class="mono">${escapeHtml(p.currency)}</span> → <span class="mono">${escapeHtml(
              p.account_alias
            )}</span> <span title="${escapeHtml(b.label)}">${b.emoji}</span></span>`;
          }
        )
        .join("")}
    </div>
    <div class="hint" style="margin-top:10px;">
      Price IDs are read from <span class="mono">config/catalog.json</span>.
    </div>
  `;

  async function refreshRouting() {
    const priceId = select.value;
    if (!priceId) return;
    setLoading(info, true, "Loading routing...");
    try {
      const data = await apiGet(`/api/stripe/publishable-key?price_id=${encodeURIComponent(priceId)}`);
      const price = data.price || {};
      const processing = data.processing_account || {};
      const master = data.master_account || {};

      const pBadge = countryBadge({ alias: processing.alias || price.account_alias, country: processing.country });
      const mBadge = countryBadge({ alias: master.alias, country: master.country });

      info.innerHTML = `
        <div style="display:grid; gap:10px;">
          <div class="row">
            <span class="tag">Selected price: <span class="mono">${escapeHtml(price.id || "")}</span></span>
            <span class="tag">Currency: <span class="mono">${escapeHtml(price.currency || "")}</span></span>
          </div>
          <div class="hint">
            Objects will be created on the <b>master account</b> and processed on the <b>processing account</b>.
          </div>
          <div class="row">
            <span class="tag">Master: <span title="${escapeHtml(mBadge.label)}">${mBadge.emoji}</span> <span class="mono">${escapeHtml(
              master.account_id || ""
            )}</span></span>
            <span class="tag">Processing: <span title="${escapeHtml(pBadge.label)}">${pBadge.emoji}</span> <span class="mono">${escapeHtml(
              processing.account_id || data.processing_account_id || ""
            )}</span></span>
          </div>
        </div>
      `;
      continueBtn.disabled = false;
    } catch (e) {
      info.innerHTML = `<div class="hint">Failed to load routing: <span class="mono">${escapeHtml(e.message)}</span></div>`;
      continueBtn.disabled = true;
    } finally {
      setLoading(info, false);
    }
  }

  select.addEventListener("change", refreshRouting);
  continueBtn.addEventListener("click", () => {
    const priceId = select.value;
    if (!priceId) return;
    window.location.href = `/create-customer?price_id=${encodeURIComponent(priceId)}`;
  });
  continueBtn.disabled = true;

  // initial
  if (prices.length > 0) {
    select.value = prices[0].id;
    refreshRouting();
  }

  productBlock.appendChild(title);
  productBlock.appendChild(picker);
  productBlock.appendChild(meta);
}

async function main() {
  const app = document.getElementById("app");
  mountTopbar(app, { title: "Stripe Multi-Account Demo", subtitle: "Select price → Create customer" });

  const productBlock = document.getElementById("productBlock");
  setLoading(productBlock, true, "Loading catalog...");
  try {
    const catalog = await apiGet("/api/catalog");
    renderProduct(productBlock, catalog);
  } catch (e) {
    productBlock.innerHTML = "";
    toast("error", "Failed to load catalog", e.message);
  } finally {
    setLoading(productBlock, false);
  }
}

main();


