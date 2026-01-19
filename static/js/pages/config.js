import { apiGet, apiPut } from "../api.js";
import { el, mountTopbar, setLoading, toast } from "../components/ui.js";

function mask(v) {
  if (!v) return "";
  const s = String(v);
  if (s.length <= 8) return "********";
  return `${s.slice(0, 3)}...${s.slice(-4)}`;
}

function normalizeAlias(a) {
  return String(a || "").trim().toUpperCase();
}

function ensureArray(v) {
  return Array.isArray(v) ? v : [];
}

async function loadAll() {
  const [cfg, catalog] = await Promise.all([apiGet("/api/config"), apiGet("/api/catalog")]);
  return { cfg, catalog };
}

function buildAccountsSection(state, onChange) {
  const accounts = state.cfg?.accounts || {};
  const aliases = Object.keys(accounts).sort();

  const table = el("div", { class: "stack" });

  function renderRow(alias) {
    const a = normalizeAlias(alias);
    const acc = accounts[a] || {};

    const details = el("details", { class: "accordion-item" }, [
      el("summary", { class: "accordion-summary" }, [
        el("div", { class: "row" }, [
          el("div", { class: "tag mono", text: a }),
          el("div", { class: "mono muted", text: acc.account_id ? String(acc.account_id) : "missing account_id" }),
        ]),
      ]),
      el("div", { class: "accordion-content" }, [
        el("div", { class: "row" }, [
          el(
            "button",
            {
              class: "btn danger",
              onClick: () => {
                delete accounts[a];
                onChange();
              },
            },
            ["Delete account"]
          ),
        ]),
        el("div", { class: "grid2" }, [
          field("Account ID", acc.account_id || "", (v) => (acc.account_id = v)),
          field("Country (ISO2)", acc.country || "", (v) => (acc.country = v.toUpperCase())),
          field("Publishable Key", acc.publishable_key || "", (v) => (acc.publishable_key = v)),
          secretField("Secret Key", acc.secret_key || "", (v) => (acc.secret_key = v)),
          secretField("Webhook Signing Secret", acc.webhook_signing_secret || "", (v) => (acc.webhook_signing_secret = v)),
        ]),
      ]),
    ]);

    accounts[a] = acc;
    return details;
  }

  for (const a of aliases) table.appendChild(renderRow(a));

  const addRow = el("div", { class: "row" }, [
    el("input", { class: "input mono", placeholder: "New alias (e.g. EU)", id: "newAlias" }),
    el(
      "button",
      {
        class: "btn",
        onClick: () => {
          const inp = document.getElementById("newAlias");
          const a = normalizeAlias(inp?.value);
          if (!a) return toast("error", "Validation", "Alias is required");
          if (accounts[a]) return toast("error", "Validation", "Alias already exists");
          accounts[a] = { account_id: "", secret_key: "", publishable_key: "", webhook_signing_secret: "", country: "" };
          inp.value = "";
          onChange();
        },
      },
      ["Add account"]
    ),
  ]);

  const root = el("div", { class: "stack" }, [table, addRow]);
  return root;
}

function buildCpmSection(state, onChange) {
  const mpms = state.cfg?.master_custom_payment_methods || {};
  const accountAliases = Object.keys(state.cfg?.accounts || {}).sort();
  const existingAliases = Object.keys(mpms).sort();
  const allAliases = Array.from(new Set([...accountAliases, ...existingAliases])).sort();

  const body = el("div", { class: "stack" });
  for (const a of allAliases) {
    const key = normalizeAlias(a);
    body.appendChild(
      el("details", { class: "accordion-item" }, [
        el("summary", { class: "accordion-summary" }, [
          el("div", { class: "row" }, [
            el("div", { class: "tag mono", text: key }),
            el("div", { class: "mono muted", text: mpms[key] ? String(mpms[key]) : "missing CPM type" }),
          ]),
        ]),
        el("div", { class: "accordion-content" }, [
          el("div", { class: "row" }, [
            el(
              "button",
              {
                class: "btn danger",
                onClick: () => {
                  delete mpms[key];
                  onChange();
                },
              },
              ["Delete mapping"]
            ),
          ]),
          field(`CPM type (cpmt_...)`, mpms[key] || "", (v) => {
            mpms[key] = v;
            onChange();
          }),
        ]),
      ])
    );
  }

  const addRow = el("div", { class: "row" }, [
    el("input", { class: "input mono", placeholder: "Alias (e.g. US)", id: "newCpmAlias" }),
    el("input", { class: "input mono", placeholder: "CPM type (cpmt_...)", id: "newCpmType" }),
    el(
      "button",
      {
        class: "btn",
        onClick: () => {
          const aliasInp = document.getElementById("newCpmAlias");
          const typeInp = document.getElementById("newCpmType");
          const a = normalizeAlias(aliasInp?.value);
          const t = String(typeInp?.value || "").trim();
          if (!a) return toast("error", "Validation", "Alias is required");
          if (!t) return toast("error", "Validation", "CPM type is required");
          mpms[a] = t;
          if (aliasInp) aliasInp.value = "";
          if (typeInp) typeInp.value = "";
          onChange();
        },
      },
      ["Add CPM mapping"]
    ),
  ]);

  state.cfg.master_custom_payment_methods = mpms;
  return el("div", { class: "stack" }, [body, addRow]);
}

function buildMasterAliasSection(state, onChange) {
  const accounts = state.cfg?.accounts || {};
  const aliases = Object.keys(accounts).sort();
  const current = normalizeAlias(state.cfg?.master_account_alias || "EU");

  const select = el(
    "select",
    {
      class: "input mono",
      onChange: (e) => {
        state.cfg.master_account_alias = normalizeAlias(e.target.value);
        onChange();
      },
    },
    []
  );

  // Ensure current selection is visible even if it's not in the accounts list yet.
  if (current && !aliases.includes(current)) {
    select.appendChild(el("option", { value: current, text: `${current} (missing in accounts)` }));
  }

  for (const a of aliases) {
    select.appendChild(el("option", { value: a, text: a }));
  }

  select.value = current;
  return el("div", { class: "stack" }, [select]);
}

function buildCatalogSection(state, onChange) {
  const catalog = state.catalog || {};
  const product = catalog.product || { id: "", name: "", description: "" };
  const prices = ensureArray(catalog.prices);

  const productCard = el("div", { class: "card" }, [
    el("div", { class: "card-header" }, [el("div", { class: "card-title", text: "Product" })]),
    el("div", { class: "grid2" }, [
      field("Product ID", product.id || "", (v) => (product.id = v)),
      field("Name", product.name || "", (v) => (product.name = v)),
      field("Description", product.description || "", (v) => (product.description = v)),
    ]),
  ]);

  const pricesList = el("div", { class: "stack" });
  prices.forEach((p, idx) => {
    const summaryText = `${p.id || "price_..."} • ${normalizeAlias(p.account_alias)} • ${(p.currency || "").toLowerCase()} • ${
      p.amount_cents ?? ""
    }`;
    pricesList.appendChild(
      el("details", { class: "accordion-item" }, [
        el("summary", { class: "accordion-summary" }, [
          el("div", { class: "row" }, [
            el("div", { class: "tag mono", text: `#${idx + 1}` }),
            el("div", { class: "mono muted", text: summaryText }),
          ]),
        ]),
        el("div", { class: "accordion-content" }, [
          el("div", { class: "row" }, [
            el(
              "button",
              {
                class: "btn danger",
                onClick: () => {
                  prices.splice(idx, 1);
                  onChange();
                },
              },
              ["Delete price"]
            ),
          ]),
          el("div", { class: "grid2" }, [
            field("Price ID (price_...)", p.id || "", (v) => (p.id = v)),
            field("Account alias", p.account_alias || "", (v) => (p.account_alias = normalizeAlias(v))),
            field("Currency (eur/usd/gbp)", p.currency || "", (v) => (p.currency = String(v || "").toLowerCase())),
            field("Amount (cents)", p.amount_cents ?? "", (v) => (p.amount_cents = Number(v))),
          ]),
        ]),
      ])
    );
  });

  const addPriceBtn = el(
    "button",
    {
      class: "btn",
      onClick: () => {
        prices.push({ id: "", amount_cents: 0, currency: "eur", account_alias: normalizeAlias(state.cfg?.master_account_alias || "EU") });
        onChange();
      },
    },
    ["Add price"]
  );

  const pricesCard = el("div", { class: "stack" }, [pricesList, addPriceBtn]);

  catalog.product = product;
  catalog.prices = prices;
  state.catalog = catalog;

  return el("div", { class: "stack" }, [productCard, el("div", { class: "card" }, [el("div", { class: "card-header" }, [el("div", { class: "card-title", text: "Prices" })]), pricesCard])]);
}

function field(label, value, onSet) {
  const input = el("input", {
    class: "input",
    value: value ?? "",
    onInput: (e) => onSet(e.target.value),
  });
  return el("div", { class: "field" }, [el("div", { class: "label", text: label }), input]);
}

function secretField(label, value, onSet) {
  const input = el("input", {
    class: "input mono",
    value: value ? mask(value) : "",
    placeholder: value ? "(set)" : "",
    onFocus: (e) => {
      // clear masked value when editing
      if (e.target.value && e.target.value.includes("...")) e.target.value = "";
    },
    onInput: (e) => onSet(e.target.value),
  });
  return el("div", { class: "field" }, [el("div", { class: "label", text: label }), input]);
}

async function saveConfig(state) {
  await apiPut("/api/config", state.cfg);
}

async function saveCatalog(state) {
  await apiPut("/api/catalog", state.catalog);
}

function accordionSection({ title, subtitle, content, open = false }) {
  return el("details", { class: "accordion", open: open ? "open" : null }, [
    el("summary", { class: "accordion-summary" }, [
      el("div", { class: "accordion-title" }, [
        el("div", { class: "card-title", text: title }),
        el("div", { class: "card-subtitle", text: subtitle }),
      ]),
    ]),
    el("div", { class: "accordion-content" }, [content]),
  ]);
}

function render(app, state) {
  app.innerHTML = "";
  mountTopbar(app, { title: "Configuration", subtitle: "Live-edit runtime config and catalog" });

  const actions = el("div", { class: "row" }, [
    el(
      "button",
      {
        class: "btn primary",
        onClick: async () => {
          try {
            await saveConfig(state);
            toast("success", "Saved", "Configuration saved.");
          } catch (e) {
            toast("error", "Save failed", e.message || String(e));
          }
        },
      },
      ["Save configuration"]
    ),
    el(
      "button",
      {
        class: "btn primary",
        onClick: async () => {
          try {
            await saveCatalog(state);
            toast("success", "Saved", "Catalog saved.");
          } catch (e) {
            toast("error", "Save failed", e.message || String(e));
          }
        },
      },
      ["Save catalog"]
    ),
    el(
      "button",
      {
        class: "btn",
        onClick: async () => {
          try {
            setLoading(app, true, "Reloading...");
            const { cfg, catalog } = await loadAll();
            state.cfg = cfg;
            state.catalog = catalog;
            render(app, state);
            toast("success", "Reloaded", "Latest files loaded.");
          } catch (e) {
            toast("error", "Reload failed", e.message || String(e));
          } finally {
            setLoading(app, false);
          }
        },
      },
      ["Reload"]
    ),
  ]);

  const list = el("div", { class: "stack" });
  const rerender = () => render(app, state);

  list.appendChild(
    accordionSection({
      title: "Master account",
      subtitle: "Pick which configured account is used as the master (source of truth).",
      content: buildMasterAliasSection(state, rerender),
      open: true,
    })
  );
  list.appendChild(
    accordionSection({
      title: "Accounts & Webhooks",
      subtitle: "Stripe accounts, API keys, and webhook signing secrets.",
      content: buildAccountsSection(state, rerender),
      open: false,
    })
  );
  list.appendChild(
    accordionSection({
      title: "CPM types",
      subtitle: "Master Custom Payment Method mapping per processing alias (e.g. US → cpmt_...).",
      content: buildCpmSection(state, rerender),
      open: false,
    })
  );
  list.appendChild(
    accordionSection({
      title: "Product catalog",
      subtitle: "Edits config/catalog.json (used by /api/catalog).",
      content: buildCatalogSection(state, rerender),
      open: false,
    })
  );

  app.appendChild(el("div", { class: "spacer" }));
  app.appendChild(actions);
  app.appendChild(el("div", { class: "spacer" }));
  app.appendChild(list);
}

async function main() {
  const app = document.getElementById("app");
  const state = { cfg: null, catalog: null };
  try {
    setLoading(app, true, "Loading configuration...");
    const { cfg, catalog } = await loadAll();
    state.cfg = cfg;
    state.catalog = catalog;
    render(app, state);
  } catch (e) {
    app.innerHTML = "";
    mountTopbar(app, { title: "Configuration", subtitle: "Live-edit runtime config and catalog" });
    toast("error", "Failed to load", e.message || String(e));
    app.appendChild(el("pre", { class: "mono", text: e.stack || String(e) }));
  } finally {
    setLoading(app, false);
  }
}

main();


