# Stripe Metadata Map (all keys written by this project)

This document lists **all Stripe `metadata` keys written by this codebase** (current implementation split across `app.py` APIs and `stripe_orchestration.py` webhook scenarios).

Note: runtime configuration and catalog are stored as local JSON files (typically gitignored):
- `config/runtime-config.json` (sample: `config/runtime-config-sample.json`)
- `config/catalog.json` (sample: `config/catalog-sample.json`)

## Global rules

- **All metadata keys are UPPERCASE** (breaking-change dev mode).
- Metadata is used to:
  - link objects across accounts (master ↔ processing)
  - make webhooks idempotent / traceable
  - retrieve the right “peer” objects later (invoice ↔ payment record ↔ refund/dispute)

---

## 1) Customer (Master account)

**Where written**
- `POST /api/customers` → `client.v1.customers.create({ ..., metadata: {...} })`

**Keys written**
- `PROCESSING_ACCOUNT_ID`
- `MASTER_ACCOUNT_ID`
- `SELECTED_PRICE_ID`
- `SELECTED_CURRENCY`

---

## 2) Subscription (Master account)

**Where written**
- `POST /api/subscriptions` → `client.v1.subscriptions.create({ ..., metadata: {...} })`

**Keys written**
- `PROCESSING_ACCOUNT_ID`
- `MASTER_ACCOUNT_ID`
- `SELECTED_PRICE_ID`
- `SELECTED_CURRENCY`

---

## 3) PaymentIntent (Processing account)

**Where written**
- `POST /api/processing-payment-intents` → `processing_client.v1.payment_intents.create({ ..., metadata: {...} })`

**Keys written**
- `INITIAL_PAYMENT` (string `"true"`)
- `MASTER_ACCOUNT_ID`
- `MASTER_ACCOUNT_INVOICE_ID`
- `MASTER_ACCOUNT_SUBSCRIPTION_ID`

---

## 4) PaymentMethod (Master account) — Custom Payment Method (CPM)

**Where written**
- Webhook scenario #1 (`payment_intent.succeeded` on processing, `INITIAL_PAYMENT="true"`)  
  → `master_client.v1.payment_methods.create({ type: "custom", ..., metadata: {...} })`

**Keys written**
- `PROCESSING_ACCOUNT_PAYMENT_METHOD_ID`
- `MASTER_ACCOUNT_CUSTOMER_ID`
- `PROCESSING_ACCOUNT_CUSTOMER_ID`

### Scenario #7 (sync processing default PM change to master PM metadata)

**Where written**
- Webhook scenario #7 (`customer.updated` on processing, when `data.previous_attributes.invoice_settings.default_payment_method` is present)  
  → for each custom PM: `master_client.v1.payment_methods.update(pm_id, { metadata: {...} })`

**Keys written/overwritten**
- `PROCESSING_ACCOUNT_PAYMENT_METHOD_ID` (overwritten to reflect the latest processing default payment method)

### PaymentMethod metadata update endpoint

**Where written**
- `POST /api/payment-methods/update-processing-metadata`  
  → `client.v1.payment_methods.update(payment_method_id, { metadata: {...} })`

**Keys written/overwritten**
- `PROCESSING_ACCOUNT_PAYMENT_METHOD_ID` (only)

---

## 5) Invoice (Processing account) — “Mirror” invoice created from master invoice

**Where written**
- Webhook scenario #2 (`invoice.payment_attempt_required` on master)  
  → `processing_client.v1.invoices.create({ ..., metadata: {...} })`

**Keys written**
- `MASTER_ACCOUNT_INVOICE_ID`
- `MASTER_ACCOUNT_CUSTOMER_ID`
- `MASTER_ACCOUNT_SUBSCRIPTION_ID`
- `MASTER_ACCOUNT_ID`

---

## 6) Invoice (Master account) — PaymentRecord linkage

**Where written**
- Webhook scenario #3 (`invoice.paid` on processing)  
  → `master_client.v1.invoices.update(master_invoice_id, { metadata: {...} })`

**Keys written**
- `MASTER_ACCOUNT_PAYMENT_RECORD_ID`

---

## 7) PaymentRecord (Master account) — `payment_records.report_payment(...)`

### Scenario #1 (initial payment on processing account)

**Where written**
- Webhook scenario #1 (`payment_intent.succeeded` on processing, `INITIAL_PAYMENT="true"`)  
  → `master_client.v1.payment_records.report_payment({ ..., metadata: {...} })`

**Keys written**
- `PROCESSING_ACCOUNT_PAYMENT_INTENT_ID`
- `MASTER_ACCOUNT_INVOICE_ID`
- `MASTER_ACCOUNT_SUBSCRIPTION_ID`

### Scenario #3 (invoice paid on processing account)

**Where written**
- Webhook scenario #3 (`invoice.paid` on processing)  
  → `master_client.v1.payment_records.report_payment({ ..., metadata: {...} })`

**Keys written**
- `PROCESSING_ACCOUNT_PAYMENT_INTENT_ID`
- `PROCESSING_ACCOUNT_PAYMENT_METHOD_ID`
- `MASTER_ACCOUNT_ID`
- `MASTER_ACCOUNT_INVOICE_ID`
- `MASTER_ACCOUNT_SUBSCRIPTION_ID`

### Scenario #4 (invoice payment failed on processing account)

**Where written**
- Webhook scenario #4 (`invoice.payment_failed` on processing)  
  → `master_client.v1.payment_records.report_payment({ ..., metadata: {...} })`

**Keys written**
- `PROCESSING_ACCOUNT_PAYMENT_INTENT_ID`
- `PROCESSING_ACCOUNT_PAYMENT_METHOD_ID`
- `MASTER_ACCOUNT_ID`
- `MASTER_ACCOUNT_INVOICE_ID`
- `MASTER_ACCOUNT_SUBSCRIPTION_ID`

---

## 8) PaymentRecord (Master account) — `payment_records.report_refund(...)`

### Scenario #5 (refund on processing account)

**Where written**
- Webhook scenario #5 (`refund.created` on processing)  
  → `master_client.v1.payment_records.report_refund(master_payment_record_id, { ..., metadata: {...} })`

**Keys written**
- `PROCESSING_ACCOUNT_REFUND_ID`

### Scenario #6 (lost dispute on processing account)

**Where written**
- Webhook scenario #6 (`charge.dispute.closed` on processing, `status="lost"`)  
  → `master_client.v1.payment_records.report_refund(master_payment_record_id, { ..., metadata: {...} })`

**Keys written**
- `PROCESSING_ACCOUNT_DISPUTE_ID`


