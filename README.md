### Stripe multi-account demo (Customer + Subscription + Payment Element)
This is a **demo** app (Flask + HTML/CSS/JS) that simulates **multi-account Stripe orchestration**:
- 1 product with multiple prices (EUR / USD / optional others) configured on the backend
- select a price/currency → create a customer (Stripe Address Element)
- create a subscription on the **master account** (EU by default)
- set metadata to indicate the **processing account** associated with the selected price
- optionally collect payment in the frontend (Payment Element) either on master or on processing, depending on the scenario

### Requirements
- Python 3.10+
- Internet access (to load `https://js.stripe.com/v3/`)
- Multiple Stripe accounts (multiple API key sets) + price IDs

### Configuration
- **1) Create your `.env` from the example (admin password only)**

```bash
cp stripe.env.example .env
```

- **2) Configure Stripe accounts + webhooks + CPM in `config/runtime-config.json` (or via `/config`)**
Runtime Stripe configuration is **JSON-backed** (no restart needed):
- `config/runtime-config.json`

You can edit it either:
- manually (JSON file), or
- from the admin UI `GET /config` (recommended)

### Live configuration UI (`/config`)
This project includes an admin configuration UI that lets you edit **accounts/secrets/webhooks/CPM** and the **product catalog** without restarting the app.

- URL: `GET /config`
- Auth: HTTP Basic Auth (browser prompt)
- Credentials:
  - `ADMIN_PASSWORD` (set in `.env`)
  - `ADMIN_USERNAME` (optional, defaults to `admin`)

The runtime configuration is stored in:
- `config/runtime-config.json`

The product catalog is stored in:
- `config/catalog.json`

- **3) Update your Price IDs in `config/catalog.json`**
Replace placeholders / set your real `price_...` IDs and `account_alias` mappings.

### Product & price data (`config/catalog.json`)
This app does **not** store products/prices in a database. Instead, the backend reads a static catalog from:

- `config/catalog.json`

This file drives the whole flow:
- `/api/catalog` returns this catalog to the frontend
- the selected `price_id` determines the **currency** and the **processing account** (via `account_alias`)

#### Structure (high level)
- **products**: list of products (display only)
- **prices**: list of Stripe `price_...` IDs usable in the demo
  - `id`: the Stripe Price ID (`price_...`)
  - `currency`: price currency (e.g. `eur`, `usd`)
  - `account_alias`: which Stripe account alias this price is associated to (e.g. `EU`, `US`)

#### What to change
- Replace placeholder `price_...` IDs with real ones from your Stripe dashboard
- Ensure every `prices[].account_alias` matches an alias configured in `config/runtime-config.json` under `accounts`.

If an alias is missing, the backend will return an error when resolving keys for that price.

### Address autocomplete (Stripe Address Element)
Per Stripe docs, **when you use the Address Element standalone**, you must provide your own Google Maps Places key via `autocomplete.apiKey` to enable address autocomplete.  
Reference: [Stripe Address Element – Autocomplete](https://docs.stripe.com/elements/address-element#autocomplete)

In this demo, you can enable it by setting:
- `GOOGLE_MAPS_PLACES_API_KEY` in `.env` (browser key, restrict by HTTP referrer in Google Cloud Console)

### Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run

```bash
python app.py
```

Open:
- `http://127.0.0.1:5000/`

### Documentation
- [`webhooks.md`](webhooks.md): detailed description of the webhook orchestration scenarios (master vs processing, triggers, actions).
- [`metadata.md`](metadata.md): exhaustive list of all Stripe metadata keys written by this project, per Stripe object.

### Webhook monitoring (real-time)
This project includes a real-time webhook monitoring page (no persistence):
- UI: `GET /webhook-monitoring`
- SSE stream: `GET /api/monitor/webhooks/stream`

Events are streamed to connected browsers only. Refreshing/leaving the page clears the UI history.

### Useful endpoints
- `GET /api/catalog`
- `GET /api/stripe/publishable-key?price_id=...`
- `POST /api/customers`
- `POST /api/subscriptions`
- `POST /api/processing-payment-intents`
- `GET /api/payment-methods/<pm_id>`
- `POST /api/payment-methods/update-processing-metadata`
- `POST /webhook/<ALIAS>`
- `GET /webhook-monitoring`


