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
- **1) Create your `.env` from the example**

```bash
cp stripe.env.example .env
```

- **2) Fill in Stripe keys per alias in `.env`**
For each alias (e.g. `EU`, `US`, `GB`), define:
- `STRIPE_ACCOUNT_<ALIAS>_ACCOUNT_ID`
- `STRIPE_ACCOUNT_<ALIAS>_SECRET_KEY`
- `STRIPE_ACCOUNT_<ALIAS>_PUBLISHABLE_KEY`
- optional UI hint: `STRIPE_ACCOUNT_<ALIAS>_COUNTRY` (ISO2, e.g. `FR`, `US`, `GB`)

Also define the master account alias (resource creation account):
- `STRIPE_MASTER_ACCOUNT_ALIAS` (default: `EU`)

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
- Ensure every `prices[].account_alias` matches an alias configured in `.env`:
  - `STRIPE_ACCOUNT_<ALIAS>_ACCOUNT_ID`
  - `STRIPE_ACCOUNT_<ALIAS>_SECRET_KEY`
  - `STRIPE_ACCOUNT_<ALIAS>_PUBLISHABLE_KEY`

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

### Useful endpoints
- `GET /api/catalog`
- `GET /api/stripe/publishable-key?price_id=...`
- `POST /api/customers`
- `POST /api/subscriptions`
- `POST /api/processing-payment-intents`
- `GET /api/payment-methods/<pm_id>`
- `POST /api/payment-methods/update-processing-metadata`


