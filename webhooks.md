# Stripe Webhooks — Multi-account Orchestration (7 scenarios)

This document describes the **7 orchestration scenarios** implemented in `stripe_orchestration.py`, through the endpoint:

- `POST /webhook/<ALIAS>` (e.g. `/webhook/EU`, `/webhook/US`)

Each webhook is received **on an account identified by the alias** (derived from the URL), and its signature is verified using the alias configuration stored in:
- `config/runtime-config.json` (`accounts[ALIAS].webhook_signing_secret`)

## Key conventions

- **Accounts**
  - **Master account**: `config/runtime-config.json: master_account_alias` (default: `EU`)
  - **Processing account**: any alias different from the master

- **Metadata**
  - **Breaking change / Dev mode**: all `metadata` keys are **UPPERCASE** (no fallback).

- **Stripe timestamps**
  - To prevent Stripe from rejecting timestamps that are **in the future**, timestamps used in `payment_records.*` are normalized:
    - if \(ts > now\) ⇒ we use `now - 10s`

## Required runtime configuration (reminder)

Stored in `config/runtime-config.json` (editable live from `GET /config`):

- **Master alias**:
  - `master_account_alias`
- **Per account (by alias)**:
  - `accounts[ALIAS].account_id`
  - `accounts[ALIAS].secret_key`
  - `accounts[ALIAS].publishable_key`
  - `accounts[ALIAS].webhook_signing_secret`
  - optional UI hint: `accounts[ALIAS].country` (ISO2, e.g. `FR`, `US`, `GB`)
- **CPM mapping** (per processing alias):
  - `master_custom_payment_methods[ALIAS] = "cpmt_..."`

---

## Scenario 1 — Initial payment on processing account (create custom PM on master + report_payment)

- **Account**: Processing account (alias ≠ master)
- **Event**: `payment_intent.succeeded`
- **Condition**: `payment_intent.metadata.INITIAL_PAYMENT == "true"`
- **Expected PaymentIntent metadata (processing)**:
  - `INITIAL_PAYMENT="true"`
  - `MASTER_ACCOUNT_ID`
  - `MASTER_ACCOUNT_INVOICE_ID`
  - `MASTER_ACCOUNT_SUBSCRIPTION_ID`

### Triggered actions

- **Master**:
  - Retrieves the master invoice via `MASTER_ACCOUNT_INVOICE_ID` (to get the `customer`)
  - Creates a **custom PaymentMethod** (CPM type) on the master
    - Metadata written on the master PM:
      - `PROCESSING_ACCOUNT_PAYMENT_METHOD_ID`
      - `MASTER_ACCOUNT_CUSTOMER_ID`
      - `PROCESSING_ACCOUNT_CUSTOMER_ID`
  - Attaches the PaymentMethod to the master customer
  - Creates a `payment_records.report_payment` (outcome **guaranteed**) with:
    - normalized `initiated_at` / `guaranteed_at`
    - Metadata written on the PaymentRecord:
      - `PROCESSING_ACCOUNT_PAYMENT_INTENT_ID`
      - `MASTER_ACCOUNT_INVOICE_ID`
      - `MASTER_ACCOUNT_SUBSCRIPTION_ID`
  - Attaches the payment record to the master invoice via `invoices.attach_payment`
  - Updates the master subscription to set `default_payment_method` = the master custom PM

---

## Scenario 2 — Payment attempt required on master (create+pay a “mirror” invoice on processing)

- **Account**: Master account (alias == master)
- **Event**: `invoice.payment_attempt_required`

### Data extracted from the master invoice (event)

- Invoice:
  - `MASTER_ACCOUNT_INVOICE_ID = data.object.id`
  - `MASTER_ACCOUNT_CURRENCY = data.object.currency`
  - `MASTER_ACCOUNT_AMOUNT = data.object.amount_due`
  - `MASTER_ACCOUNT_CUSTOMER_ID = data.object.customer`
  - `MASTER_ACCOUNT_PERIOD_START = data.object.period_start`
  - `MASTER_ACCOUNT_PERIOD_END = data.object.period_end`
  - `MASTER_ACCOUNT_INVOICE_DESCRIPTION = data.object.lines.data[0].description`
- Parent / subscription_details:
  - `MASTER_ACCOUNT_SUBSCRIPTION_ID = data.object.parent.subscription_details.subscription`
  - `PROCESSING_ACCOUNT_ID = data.object.parent.subscription_details.metadata.PROCESSING_ACCOUNT_ID`

### Triggered actions

- **Master**:
  - Retrieves the master subscription `MASTER_ACCOUNT_SUBSCRIPTION_ID` with `expand=["default_payment_method"]`
  - Extracts from the master custom PM:
    - `MASTER_ACCOUNT_CUSTOM_PAYMENT_METHOD = default_payment_method.id`
    - `PROCESSING_ACCOUNT_PAYMENT_METHOD = default_payment_method.metadata.PROCESSING_ACCOUNT_PAYMENT_METHOD_ID`
    - `PROCESSING_ACCOUNT_CUSTOMER_ID = default_payment_method.metadata.PROCESSING_ACCOUNT_CUSTOMER_ID`

- **Processing**:
  - Searches for an existing invoice with `metadata["MASTER_ACCOUNT_INVOICE_ID"] == MASTER_ACCOUNT_INVOICE_ID`
    - If **found**: do nothing
    - Otherwise:
      - Creates an `invoice_item` (customer/currency/amount/description + `period`)
      - Creates an invoice with:
        - `collection_method="charge_automatically"`
        - `pending_invoice_items_behavior="include"`
        - `default_payment_method=PROCESSING_ACCOUNT_PAYMENT_METHOD`
        - Metadata written:
          - `MASTER_ACCOUNT_INVOICE_ID`
          - `MASTER_ACCOUNT_CUSTOMER_ID`
          - `MASTER_ACCOUNT_SUBSCRIPTION_ID`
          - `MASTER_ACCOUNT_ID`
      - Attempts `invoices.pay(..., off_session=True)`
        - On failure (insufficient funds, etc.), the exception is logged and Stripe can apply retries (“smart retry”)

---

## Scenario 3 — Invoice paid on processing account (report_payment on master + attach + update invoice metadata)

- **Account**: Processing account (alias ≠ master)
- **Event**: `invoice.paid`

### Data extracted from the processing invoice (event)

- `PROCESSING_ACCOUNT_PAYMENT_METHOD = data.object.default_payment_method`
- `PROCESSING_ACCOUNT_PAYMENT_ID = data.object.payment_intent`
- `PROCESSING_ACCOUNT_PAID_AT = data.object.status_transitions.paid_at`
- Metadata (on the processing invoice):
  - `MASTER_ACCOUNT_CUSTOMER_ID`
  - `MASTER_ACCOUNT_ID`
  - `MASTER_ACCOUNT_INVOICE_ID`
  - `MASTER_ACCOUNT_SUBSCRIPTION_ID`

### Triggered actions

- **Master**:
  - Retrieves the master subscription (expand default PM) ⇒ `MASTER_ACCOUNT_CUSTOM_PAYMENT_METHOD`
  - Creates `payment_records.report_payment` (outcome **guaranteed**) with normalized timestamps
  - Attaches to the master invoice via `invoices.attach_payment`
  - Updates the master invoice by adding:
    - `metadata.MASTER_ACCOUNT_PAYMENT_RECORD_ID = <payment_record_id>`

---

## Scenario 4 — Invoice payment failed on processing account (report_payment outcome=failed on master + attach)

- **Account**: Processing account (alias ≠ master)
- **Event**: `invoice.payment_failed`

### Data extracted from the processing invoice (event)

- `PROCESSING_ACCOUNT_PAYMENT_METHOD = data.object.default_payment_method`
- `PROCESSING_ACCOUNT_PAYMENT_ID = data.object.payment_intent`
- Failure timestamp:
  - `PROCESSING_ACCOUNT_PAID_AT = data.object.status_transitions.(paid_at|finalized_at|marked_uncollectible_at|voided_at) or data.object.created`
- Metadata (on the processing invoice):
  - `MASTER_ACCOUNT_CUSTOMER_ID`
  - `MASTER_ACCOUNT_ID`
  - `MASTER_ACCOUNT_INVOICE_ID`
  - `MASTER_ACCOUNT_SUBSCRIPTION_ID`

### Triggered actions

- **Master**:
  - Retrieves the master subscription (expand default PM) ⇒ `MASTER_ACCOUNT_CUSTOM_PAYMENT_METHOD`
  - Creates `payment_records.report_payment` with:
    - `outcome="failed"`
    - `failed={"failed_at": <normalized ts>}`
  - Attaches to the master invoice via `invoices.attach_payment`

---

## Scenario 5 — Refund on processing account (report_refund on master)

- **Account**: Processing account (alias ≠ master)
- **Event**: `refund.created`

### Data extracted from the refund (event.data.object)

- `PROCESSING_ACCOUNT_PAYMENT_INTENT = object.payment_intent`
- `PROCESSING_ACCOUNT_REFUND_ID = object.id`
- `PROCESSING_ACCOUNT_REFUNDED_AMOUNT = object.amount`
- `PROCESSING_ACCOUNT_REFUNDED_CURRENCY = object.currency`
- `PROCESSING_ACCOUNT_REFUNDED_TIMESTAMP = object.created`

### Triggered actions

- **Processing**:
  - Retrieves the PaymentIntent with `expand=["invoice"]` (and a specific `stripe_version`)
  - Reads from `payment_intent.invoice.metadata`:
    - `MASTER_ACCOUNT_CUSTOMER_ID`
    - `MASTER_ACCOUNT_ID`
    - `MASTER_ACCOUNT_INVOICE_ID`
    - `MASTER_ACCOUNT_SUBSCRIPTION_ID`

- **Master**:
  - Retrieves the master invoice (`MASTER_ACCOUNT_INVOICE_ID`)
  - Reads `MASTER_ACCOUNT_PAYMENT_RECORD_ID` from `invoice.metadata`
  - Creates `payment_records.report_refund(MASTER_ACCOUNT_PAYMENT_RECORD_ID, ...)` with:
    - normalized `initiated_at` / `refunded.refunded_at`
    - `amount={currency,value}`
    - `processor_details.custom.refund_reference = PROCESSING_ACCOUNT_REFUND_ID`
    - Metadata added to the record:
      - `PROCESSING_ACCOUNT_REFUND_ID`

---

## Scenario 6 — Lost dispute on processing account (charge.dispute.closed status=lost → report_refund on master)

- **Account**: Processing account (alias ≠ master)
- **Event**: `charge.dispute.closed`
- **Condition**: `data.object.status == "lost"`

### Data extracted from the dispute (event.data.object)

- `PROCESSING_ACCOUNT_PAYMENT_INTENT = object.payment_intent`
- `PROCESSING_ACCOUNT_DISPUTE_ID = object.id`
- `PROCESSING_ACCOUNT_DISPUTED_AMOUNT = object.amount`
- `PROCESSING_ACCOUNT_DISPUTED_CURRENCY = object.currency`
- `PROCESSING_ACCOUNT_DISPUTED_TIMESTAMP = object.created`

### Triggered actions

Same flow as **Scenario 5**, with one change:

- **Master**:
  - Calls `payment_records.report_refund(MASTER_ACCOUNT_PAYMENT_RECORD_ID, ...)`
  - Adds to the record metadata:
    - `PROCESSING_ACCOUNT_DISPUTE_ID` (instead of `PROCESSING_ACCOUNT_REFUND_ID`)

---

## Scenario 7 — Customer default payment method changed on processing account (sync to master custom PM metadata)

- **Account**: Processing account (alias ≠ master)
- **Event**: `customer.updated`
- **Condition**: `data.previous_attributes.invoice_settings.default_payment_method` is present  
  (Stripe indicates the customer’s `invoice_settings.default_payment_method` changed on the processing account)

### Data extracted from the event

- `PROCESSING_ACCOUNT_ID` (resolved from env via the processing alias)
- `PROCESSING_ACCOUNT_CUSTOMER_ID = data.object.id`
- `PROCESSING_ACCOUNT_PAYMENT_METHOD_ID = data.object.invoice_settings.default_payment_method`

### Triggered actions

- **Master**:
  - Lists the customer’s custom payment methods on the master account:
    - `payment_methods = master_client.v1.customers.payment_methods.list(PROCESSING_ACCOUNT_CUSTOMER_ID, {"type": "custom"})`
  - For **each** returned custom PaymentMethod:
    - Updates metadata:
      - `metadata.PROCESSING_ACCOUNT_PAYMENT_METHOD_ID = PROCESSING_ACCOUNT_PAYMENT_METHOD_ID`


