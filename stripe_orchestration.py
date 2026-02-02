"""
stripe_orchestration.py

Stripe webhook orchestration logic (multi-account).

This module intentionally contains the "business" part of the webhook processing, separate from Flask routing:
- `app.py` validates the webhook signature and delegates here
- this module decides which scenario to execute based on (alias, event.type)

Conventions used by this project:
- Master account alias is STRIPE_MASTER_ACCOUNT_ALIAS (default: EU)
- All metadata keys written by this project are UPPERCASE (dev-mode breaking change)
- Timestamps passed to PaymentRecord APIs are normalized to avoid future-timestamp rejections by Stripe
"""

import json
import traceback
from typing import Any, Dict, Optional

from stripe_helpers import (
    get_account_env,
    get_alias_by_account_id,
    get_master_alias,
    get_master_custom_payment_method_type,
    get_runtime_bool,
    normalize_report_timestamp,
    safe_get,
    stripe_client,
)


def _require(value: Any, message: str) -> Any:
    """Fail fast if a required field is missing/empty."""
    if value is None:
        raise ValueError(message)
    if isinstance(value, str) and not value.strip():
        raise ValueError(message)
    return value


def _get_upper(md: Any, key: str) -> Optional[str]:
    """Read a metadata value and normalize it to a stripped string (or None)."""
    if md is None:
        return None
    if hasattr(md, "get"):
        v = md.get(key)
    else:
        v = safe_get(md, key)
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _extract_master_links_from_payment_intent(pi: Any) -> Dict[str, str]:
    """
    Some flows have an invoice expanded on the PaymentIntent; some don't (e.g. initial payment).
    Prefer invoice.metadata when present, otherwise fallback to payment_intent.metadata.

    This is used by refund/dispute scenarios to locate the corresponding master objects.
    """
    pi_md = safe_get(pi, "metadata") or {}
    inv = safe_get(pi, "invoice")
    inv_md = (safe_get(inv, "metadata") or {}) if inv else {}
    source = inv_md if inv_md else pi_md

    return {
        "MASTER_ACCOUNT_CUSTOMER_ID": _get_upper(source, "MASTER_ACCOUNT_CUSTOMER_ID") or "",
        "MASTER_ACCOUNT_ID": _get_upper(source, "MASTER_ACCOUNT_ID") or "",
        "MASTER_ACCOUNT_INVOICE_ID": _get_upper(source, "MASTER_ACCOUNT_INVOICE_ID") or "",
        "MASTER_ACCOUNT_SUBSCRIPTION_ID": _get_upper(source, "MASTER_ACCOUNT_SUBSCRIPTION_ID") or "",
    }


def _get_master_payment_record_id(master_client, master_invoice_id: str) -> str:
    """Retrieve the master invoice and return metadata.MASTER_ACCOUNT_PAYMENT_RECORD_ID."""
    inv = master_client.v1.invoices.retrieve(str(master_invoice_id))
    md = safe_get(inv, "metadata") or {}
    rid = _get_upper(md, "MASTER_ACCOUNT_PAYMENT_RECORD_ID")
    return _require(rid, "Missing master invoice metadata: MASTER_ACCOUNT_PAYMENT_RECORD_ID")


def _update_master_invoice_payment_record_id(master_client, master_invoice_id: str, payment_record_id: str) -> None:
    """Persist metadata.MASTER_ACCOUNT_PAYMENT_RECORD_ID on the master invoice."""
    master_client.v1.invoices.update(
        str(master_invoice_id), {"metadata": {"MASTER_ACCOUNT_PAYMENT_RECORD_ID": str(payment_record_id)}}
    )


def _get_first_master_invoice_line_item_id(master_client, master_invoice_id: str) -> str:
    """Return the first invoice line item id on a master invoice (used for credit notes)."""
    inv = master_client.v1.invoices.retrieve(str(master_invoice_id))
    lines = inv["lines"]["data"] if isinstance(inv, dict) else safe_get(safe_get(inv, "lines"), "data")
    if not isinstance(lines, list) or not lines:
        raise ValueError("Unable to find invoice line items on master invoice")
    return str(lines[0]["id"])


def _create_master_credit_note(master_client, master_invoice_id: str, amount: int, metadata: Dict[str, str]) -> None:
    """Create an out-of-band credit note on the master invoice."""
    invoice_line_item = _get_first_master_invoice_line_item_id(master_client, master_invoice_id)
    master_client.v1.credit_notes.create(
        {
            "invoice": str(master_invoice_id),
            "lines": [{"invoice_line_item": str(invoice_line_item), "quantity": 1, "type": "invoice_line_item"}],
            "out_of_band_amount": int(amount),
            "metadata": metadata,
        }
    )


def handle_orchestration_event(normalized_alias: str, event: Any, resolved_account_id: str) -> None:
    """
    Execute orchestration scenarios based on (alias, event.type).
    This function raises on errors; caller (Flask route) handles HTTP response.
    """
    master_alias = get_master_alias()
    event_type = safe_get(event, "type") or (event.get("type") if isinstance(event, dict) else None)
    
    # Scenario 1: payment_intent.succeeded on processing account with INITIAL_PAYMENT=true
    if normalized_alias != master_alias and event_type == "payment_intent.succeeded":
        pi = safe_get(safe_get(event, "data"), "object")
        pi_md = safe_get(pi, "metadata") or {}
        initial_payment = _get_upper(pi_md, "INITIAL_PAYMENT")
        if (initial_payment or "").lower() == "true":
            processing_payment_intent_id = safe_get(pi, "id")
            processing_payment_method_id = safe_get(pi, "payment_method")
            processing_customer_id = safe_get(pi, "customer")

            master_invoice_id = _get_upper(pi_md, "MASTER_ACCOUNT_INVOICE_ID")
            master_subscription_id = _get_upper(pi_md, "MASTER_ACCOUNT_SUBSCRIPTION_ID")
            _require(master_invoice_id, "Missing required payment intent metadata: MASTER_ACCOUNT_INVOICE_ID")
            _require(master_subscription_id, "Missing required payment intent metadata: MASTER_ACCOUNT_SUBSCRIPTION_ID")

            cpm_type = get_master_custom_payment_method_type(normalized_alias)

            _master_account_id, master_secret_key, _ = get_account_env(master_alias)
            master_client = stripe_client(master_secret_key)

            invoice = master_client.v1.invoices.retrieve(str(master_invoice_id))
            customer_id = safe_get(invoice, "customer")
            _require(customer_id, "Unable to resolve customer from master invoice")

            pm_master = master_client.v1.payment_methods.create(
                {
                    "type": "custom",
                    "custom": {"type": cpm_type},
                    "metadata": {
                        "PROCESSING_ACCOUNT_PAYMENT_METHOD_ID": str(processing_payment_method_id),
                        "MASTER_ACCOUNT_CUSTOMER_ID": str(customer_id),
                        "PROCESSING_ACCOUNT_CUSTOMER_ID": str(processing_customer_id),
                    },
                }
            )
            pm_master_id = safe_get(pm_master, "id")
            _require(pm_master_id, "Failed to create master custom payment method")

            master_client.v1.payment_methods.attach(str(pm_master_id), {"customer": str(customer_id)})

            pi_currency = safe_get(pi, "currency")
            pi_amount = safe_get(pi, "amount_received") or safe_get(pi, "amount")
            pi_created = safe_get(pi, "created")
            _require(pi_currency, "Missing required fields on payment intent: currency")
            _require(pi_amount, "Missing required fields on payment intent: amount")
            _require(pi_created, "Missing required fields on payment intent: created")

            report_ts = normalize_report_timestamp(pi_created)
            payment_record = master_client.v1.payment_records.report_payment(
                {
                    "amount_requested": {"currency": str(pi_currency), "value": int(pi_amount)},
                    "initiated_at": report_ts,
                    "customer_details": {"customer": str(customer_id)},
                    "outcome": "guaranteed",
                    "guaranteed": {"guaranteed_at": report_ts},
                    "metadata": {
                        "PROCESSING_ACCOUNT_PAYMENT_INTENT_ID": str(processing_payment_intent_id),
                        "MASTER_ACCOUNT_INVOICE_ID": str(master_invoice_id),
                        "MASTER_ACCOUNT_SUBSCRIPTION_ID": str(master_subscription_id),
                    },
                    "payment_method_details": {"payment_method": str(pm_master_id)},
                    "processor_details": {"type": "custom", "custom": {"payment_reference": str(processing_payment_intent_id)}},
                }
            )
            payment_record_id = safe_get(payment_record, "id")
            _require(payment_record_id, "Failed to create payment record on master account")

            master_client.v1.invoices.attach_payment(str(master_invoice_id), {"payment_record": str(payment_record_id)})
            _update_master_invoice_payment_record_id(master_client, str(master_invoice_id), str(payment_record_id))
            master_client.v1.subscriptions.update(str(master_subscription_id), {"default_payment_method": str(pm_master_id)})

            # --- NEW: Build a "send_invoice" invoice on the processing account mirroring the master invoice lines,
            # including tax details as structured data. This is used for downstream systems (e.g. invoicing sync)
            # when processing != master.
            try:
                if not get_runtime_bool("propagate_tax_to_processing", True):
                    raise StopIteration("propagate_tax_to_processing disabled")
                # 1) Build tax_amounts structures from master invoice lines.
                master_invoice_lines = safe_get(safe_get(invoice, "lines"), "data") or []
                if not isinstance(master_invoice_lines, list):
                    master_invoice_lines = []

                master_invoice_number = safe_get(invoice, "number")
                if master_invoice_number is None:
                    # Fallback: retrieve invoice again (some shapes may omit number)
                    inv2 = master_client.v1.invoices.retrieve(str(master_invoice_id))
                    master_invoice_number = safe_get(inv2, "number")

                # Processing client (same alias as the PaymentIntent)
                _processing_account_id, processing_secret_key, _ = get_account_env(normalized_alias)
                processing_client = stripe_client(processing_secret_key)

                # Use PI.customer as processing customer id (in org sharing setups it matches the master customer id).
                proc_customer_id = processing_customer_id or customer_id
                _require(proc_customer_id, "Missing processing customer id for invoice creation")

                for master_invoice_item in master_invoice_lines:
                    taxes = safe_get(master_invoice_item, "taxes") or []
                    taxes_data = []
                    if isinstance(taxes, list):
                        for t in taxes:
                            trd = safe_get(t, "tax_rate_details") or {}
                            tax_rate_id = safe_get(trd, "tax_rate")
                            if not tax_rate_id:
                                continue

                            tax_master = master_client.v1.tax_rates.retrieve(str(tax_rate_id))
                            display_name = safe_get(tax_master, "display_name") or ""
                            jurisdiction = safe_get(tax_master, "jurisdiction") or ""
                            tax_display_name = f"{display_name}-{jurisdiction}".strip("-")

                            tax_behavior = str(safe_get(t, "tax_behavior") or "").lower()
                            inclusive = tax_behavior == "inclusive"
                            percentage = safe_get(tax_master, "effective_percentage")

                            taxes_data.append(
                                {
                                    "amount": int(safe_get(t, "amount") or 0),
                                    "taxable_amount": int(safe_get(t, "taxable_amount") or 0),
                                    "tax_rate_data": {
                                        "inclusive": bool(inclusive),
                                        "display_name": str(tax_display_name),
                                        "percentage": percentage,
                                    },
                                }
                            )

                    # Create invoice item on processing with taxes encoded as JSON in metadata (Stripe metadata values are strings).
                    item_currency = safe_get(master_invoice_item, "currency") or pi_currency
                    item_amount = safe_get(master_invoice_item, "amount") or safe_get(master_invoice_item, "subtotal")
                    item_desc = safe_get(master_invoice_item, "description") or ""
                    _require(item_currency, "Missing currency on master invoice line item")
                    _require(item_amount, "Missing amount on master invoice line item")

                    processing_client.v1.invoice_items.create(
                        {
                            "customer": str(proc_customer_id),
                            "currency": str(item_currency),
                            "amount": int(item_amount),
                            "description": str(item_desc),
                            "metadata": {"TAXES": json.dumps(taxes_data, separators=(",", ":"))},
                        }
                    )

                # 2) Create processing invoice (send_invoice) and propagate invoice number.
                processing_invoice = processing_client.v1.invoices.create(
                    {
                        "customer": str(proc_customer_id),
                        "pending_invoice_items_behavior": "include",
                        "collection_method": "send_invoice",
                        "days_until_due": 1,
                        "number": str(master_invoice_number) if master_invoice_number else None,
                        "expand": ["lines"],
                        "metadata": {
                            "MASTER_ACCOUNT_INVOICE_ID": str(master_invoice_id),
                            "MASTER_ACCOUNT_SUBSCRIPTION_ID": str(master_subscription_id),
                            "MASTER_ACCOUNT_ID": str(resolved_account_id),
                        },
                    }
                )
                processing_invoice_id = safe_get(processing_invoice, "id")
                _require(processing_invoice_id, "Failed to create processing send_invoice invoice")

                # 3) For each processing invoice line, read metadata.TAXES and set invoice line tax_amounts accordingly.
                processing_lines = safe_get(safe_get(processing_invoice, "lines"), "data") or []
                if isinstance(processing_lines, list):
                    for pl in processing_lines:
                        line_id = safe_get(pl, "id")
                        if not line_id:
                            continue
                        md = safe_get(pl, "metadata") or {}
                        raw = safe_get(md, "TAXES")
                        if not raw:
                            continue
                        try:
                            line_taxes = json.loads(raw) if isinstance(raw, str) else raw
                        except Exception:
                            line_taxes = None
                        if not line_taxes:
                            continue

                        # StripeClient provides invoices.update_lines(invoice, {lines:[{id, tax_amounts:[...]}]})
                        processing_client.v1.invoices.line_items.update(
                            str(processing_invoice_id), 
                            str(line_id),
                            {"tax_amounts": line_taxes},
                        )

                # 4) Finalize invoice on processing
                processing_client.v1.invoices.finalize_invoice(str(processing_invoice_id))

                # 5) Attach the original processing PaymentIntent for traceability.
                # Stripe does not always support attaching an existing PaymentIntent to a "send_invoice" invoice.
                # We persist it in metadata and best-effort attempt an invoice.pay(...) with payment_intent if supported.
                try:
                    processing_client.v1.invoices.update(
                        str(processing_invoice_id),
                        {"metadata": {
                            "PROCESSING_ACCOUNT_PAYMENT_INTENT_ID": str(processing_payment_intent_id),
                            "IS_INITIAL_PAYMENT": "true",
                        },
                        },
                    )
                except Exception:
                    traceback.print_exc()
                try:
                    processing_client.v1.invoices.attach_payment(
                        str(processing_invoice_id),
                        {"payment_intent": str(processing_payment_intent_id)},
                    )
                except Exception:
                    # Best-effort only; keep orchestration successful even if Stripe rejects this operation.
                    traceback.print_exc()

            except StopIteration:
                # Feature disabled: skip silently.
                pass
            except Exception:
                traceback.print_exc()

            print(
                "[stripe-webhook-orch] scenario=initial_payment "
                f"processing_alias={normalized_alias} master_alias={master_alias} "
                f"pi={processing_payment_intent_id} master_invoice_id={master_invoice_id} "
                f"pm_master_id={pm_master_id} payment_record_id={payment_record_id}"
            )
        return

    # Scenario 7: customer.updated on processing account (invoice_settings.default_payment_method changed)
    elif normalized_alias != master_alias and event_type == "customer.updated":
        # Stripe event shape: previous_attributes is inside event.data.previous_attributes
        data = safe_get(event, "data") or (event.get("data") if isinstance(event, dict) else None) or {}
        prev = safe_get(data, "previous_attributes") or (
            data.get("previous_attributes") if isinstance(data, dict) else None
        ) or {}
        
        prev_invoice_settings = safe_get(prev, "invoice_settings") or (
            prev.get("invoice_settings") if isinstance(prev, dict) else None
        )

        # Only act when Stripe indicates the default_payment_method changed.
        default_pm_changed = isinstance(prev_invoice_settings, dict) and "default_payment_method" in prev_invoice_settings
        if not default_pm_changed:
            return

        cust = safe_get(safe_get(event, "data"), "object")
        PROCESSING_ACCOUNT_CUSTOMER_ID = _require(safe_get(cust, "id"), "Missing customer id in event: data.object.id")
        invoice_settings = safe_get(cust, "invoice_settings") or {}
        PROCESSING_ACCOUNT_PAYMENT_METHOD_ID = _require(
            safe_get(invoice_settings, "default_payment_method"),
            "Missing customer invoice_settings.default_payment_method in event",
        )

        # Processing account id (acct_...) from env for this alias
        PROCESSING_ACCOUNT_ID, _processing_secret_key, _ = get_account_env(normalized_alias)

        # Master: list customer's custom payment methods and update metadata key
        _master_account_id, master_secret_key, _ = get_account_env(master_alias)
        master_client = stripe_client(master_secret_key)

        payment_methods = master_client.v1.customers.payment_methods.list(
            str(PROCESSING_ACCOUNT_CUSTOMER_ID),
            {"type": "custom"},
        )
        # Optional debug: can be verbose, keep it during dev iterations.
        print(f"payment_methods: {payment_methods}")
        pm_data = safe_get(payment_methods, "data") or []
        updated = 0
        for pm in pm_data:
            pm_id = safe_get(pm, "id")
            if not pm_id:
                continue
            # Keep master custom PM aligned with the new processing default payment method.
            master_client.v1.payment_methods.update(
                str(pm_id),
                {"metadata": {"PROCESSING_ACCOUNT_PAYMENT_METHOD_ID": str(PROCESSING_ACCOUNT_PAYMENT_METHOD_ID)}},
            )
            updated += 1

        print(
            "[stripe-webhook-orch] scenario=customer_updated_processing_default_pm_changed "
            f"processing_alias={normalized_alias} processing_account_id={PROCESSING_ACCOUNT_ID} "
            f"processing_customer_id={PROCESSING_ACCOUNT_CUSTOMER_ID} processing_payment_method_id={PROCESSING_ACCOUNT_PAYMENT_METHOD_ID} "
            f"updated_master_custom_pms={updated}"
        )
        return

    # Scenario 3: invoice.paid on processing account
    elif normalized_alias != master_alias and event_type == "invoice.paid":
        # Some webhook deliveries omit fields like payment_intent.
        # To make this robust, we re-fetch the invoice from the processing account using the invoice id from the event.
        inv_stub = safe_get(safe_get(event, "data"), "object")
        processing_invoice_id = _require(safe_get(inv_stub, "id"), "Missing processing invoice field: data.object.id")
        print(f"processing_invoice_id: {processing_invoice_id}")
        processing_pi= None
        processing_pm = None
        paid_at = None
        
        while processing_pi is None or processing_pi == "":
            _processing_account_id, processing_secret_key, _ = get_account_env(normalized_alias)
            processing_client = stripe_client(processing_secret_key)
            inv = processing_client.v1.invoices.retrieve(str(processing_invoice_id),options={"stripe_version": "2020-08-27"})
            # gets all metadata from the invoice
            md = safe_get(inv, "metadata") or {}
            is_initial_payment = safe_get(md, "IS_INITIAL_PAYMENT")
            if is_initial_payment is not None and is_initial_payment == "true":
                print("initial payment already processed, skipping")
                return
            processing_pm = safe_get(inv, "default_payment_method")
            processing_pi = safe_get(inv, "payment_intent")
            paid_at = safe_get(safe_get(inv, "status_transitions"), "paid_at")
            print(f"processing_pi: {processing_pi}")
            print(f"processing_pm: {processing_pm}")
            print(f"paid_at: {paid_at}")
            import time
            if (processing_pi is not None and processing_pi != "" and processing_pm is not None and processing_pm != "" and paid_at is not None and paid_at != ""):
                break
            else:
                print("waiting for processing_pi, processing_pm, and paid_at to be set")
                time.sleep(1)

        _require(processing_pm, "Missing processing invoice field: data.object.default_payment_method")
        _require(processing_pi, "Missing processing invoice field: data.object.payment_intent")
        _require(paid_at, "Missing processing invoice field: data.object.status_transitions.paid_at")

        md = safe_get(inv, "metadata") or {}
        master_customer_id = _require(_get_upper(md, "MASTER_ACCOUNT_CUSTOMER_ID"), "Missing processing invoice metadata: MASTER_ACCOUNT_CUSTOMER_ID")
        master_invoice_id = _require(_get_upper(md, "MASTER_ACCOUNT_INVOICE_ID"), "Missing processing invoice metadata: MASTER_ACCOUNT_INVOICE_ID")
        master_subscription_id = _require(_get_upper(md, "MASTER_ACCOUNT_SUBSCRIPTION_ID"), "Missing processing invoice metadata: MASTER_ACCOUNT_SUBSCRIPTION_ID")
        master_account_id = _require(_get_upper(md, "MASTER_ACCOUNT_ID"), "Missing processing invoice metadata: MASTER_ACCOUNT_ID")

        inv_currency = safe_get(inv, "currency")
        inv_amount = safe_get(inv, "amount_paid") or safe_get(inv, "amount_due") or safe_get(inv, "total")
        _require(inv_currency, "Missing processing invoice fields: currency")
        _require(inv_amount, "Missing processing invoice fields: amount")

        _master_account_id, master_secret_key, _ = get_account_env(master_alias)
        master_client = stripe_client(master_secret_key)
        sub = master_client.v1.subscriptions.retrieve(str(master_subscription_id), {"expand": ["default_payment_method"]})
        default_pm = safe_get(sub, "default_payment_method")
        master_custom_pm_id = safe_get(default_pm, "id")
        _require(master_custom_pm_id, "Missing master subscription default_payment_method.id")

        report_ts = normalize_report_timestamp(paid_at)
        payment_record = master_client.v1.payment_records.report_payment(
            {
                "amount_requested": {"currency": str(inv_currency), "value": int(inv_amount)},
                "initiated_at": report_ts,
                "customer_details": {"customer": str(master_customer_id)},
                "outcome": "guaranteed",
                "guaranteed": {"guaranteed_at": report_ts},
                "metadata": {
                    "PROCESSING_ACCOUNT_PAYMENT_INTENT_ID": str(processing_pi),
                    "PROCESSING_ACCOUNT_PAYMENT_METHOD_ID": str(processing_pm),
                    "MASTER_ACCOUNT_ID": str(master_account_id),
                    "MASTER_ACCOUNT_INVOICE_ID": str(master_invoice_id),
                    "MASTER_ACCOUNT_SUBSCRIPTION_ID": str(master_subscription_id),
                },
                "payment_method_details": {"payment_method": str(master_custom_pm_id)},
                "processor_details": {"type": "custom", "custom": {"payment_reference": str(processing_pi)}},
            }
        )
        payment_record_id = safe_get(payment_record, "id")
        _require(payment_record_id, "Failed to create payment record on master account (scenario #3)")

        master_client.v1.invoices.attach_payment(str(master_invoice_id), {"payment_record": str(payment_record_id)})
        _update_master_invoice_payment_record_id(master_client, str(master_invoice_id), str(payment_record_id))

        print(
            "[stripe-webhook-orch] scenario=processing_invoice_paid "
            f"processing_alias={normalized_alias} master_alias={master_alias} "
            f"processing_pi={processing_pi} master_invoice_id={master_invoice_id} payment_record_id={payment_record_id}"
        )
        return

    # Scenario 4: invoice.payment_failed on processing account
    elif normalized_alias != master_alias and event_type == "invoice.payment_failed":
        inv_stub = safe_get(safe_get(event, "data"), "object")
        processing_invoice_id = _require(safe_get(inv_stub, "id"), "Missing processing invoice field: data.object.id")
        print(f"processing_invoice_id: {processing_invoice_id}")
        processing_pi= None
        processing_pm = None
        ts = None
        st = None
        inv = None
        # breaking change since api version 2020-08-27, the payment_intent is not always present in the invoice
        while ts is None or ts == "":
             _processing_account_id, processing_secret_key, _ = get_account_env(normalized_alias)
             processing_client = stripe_client(processing_secret_key)
             inv = processing_client.v1.invoices.retrieve(str(processing_invoice_id),options={"stripe_version": "2020-08-27"})

             processing_pm = safe_get(inv, "default_payment_method")
             processing_pi = safe_get(inv, "payment_intent")
             paid_at = safe_get(safe_get(inv, "status_transitions"), "paid_at")
             print(f"processing_pi: {processing_pi}")
             print(f"processing_pm: {processing_pm}")
             print(f"paid_at: {paid_at}")
             st = safe_get(inv, "status_transitions")
             ts = (
                safe_get(st, "paid_at")
                or safe_get(st, "finalized_at")
                or safe_get(st, "marked_uncollectible_at")
                or safe_get(st, "voided_at")
                or safe_get(inv, "created")
             )
             print(f"ts: {ts}")
             print(f"st: {st}")
             import time
             if (processing_pi is not None and processing_pi != "" and processing_pm is not None and processing_pm != "" and paid_at is not None and paid_at != ""):
                break
             else:
                print("waiting for processing_pi, processing_pm, and paid_at to be set")
                time.sleep(1)
       
        _require(processing_pm, "Missing processing invoice field: data.object.default_payment_method")
        _require(processing_pi, "Missing processing invoice field: data.object.payment_intent")
        _require(ts, "Missing processing invoice field: data.object.status_transitions.* timestamp")

        md = safe_get(inv, "metadata") or {}
        master_customer_id = _require(_get_upper(md, "MASTER_ACCOUNT_CUSTOMER_ID"), "Missing processing invoice metadata: MASTER_ACCOUNT_CUSTOMER_ID")
        master_invoice_id = _require(_get_upper(md, "MASTER_ACCOUNT_INVOICE_ID"), "Missing processing invoice metadata: MASTER_ACCOUNT_INVOICE_ID")
        master_subscription_id = _require(_get_upper(md, "MASTER_ACCOUNT_SUBSCRIPTION_ID"), "Missing processing invoice metadata: MASTER_ACCOUNT_SUBSCRIPTION_ID")
        master_account_id = _require(_get_upper(md, "MASTER_ACCOUNT_ID"), "Missing processing invoice metadata: MASTER_ACCOUNT_ID")

        inv_currency = safe_get(inv, "currency")
        inv_amount = safe_get(inv, "amount_due") or safe_get(inv, "total")
        _require(inv_currency, "Missing processing invoice fields: currency")
        _require(inv_amount, "Missing processing invoice fields: amount")

        _master_account_id, master_secret_key, _ = get_account_env(master_alias)
        master_client = stripe_client(master_secret_key)
        sub = master_client.v1.subscriptions.retrieve(str(master_subscription_id), {"expand": ["default_payment_method"]})
        default_pm = safe_get(sub, "default_payment_method")
        master_custom_pm_id = safe_get(default_pm, "id")
        _require(master_custom_pm_id, "Missing master subscription default_payment_method.id")

        report_ts = normalize_report_timestamp(ts)
        payment_record = master_client.v1.payment_records.report_payment(
            {
                "amount_requested": {"currency": str(inv_currency), "value": int(inv_amount)},
                "initiated_at": report_ts,
                "customer_details": {"customer": str(master_customer_id)},
                "outcome": "failed",
                "failed": {"failed_at": report_ts},
                "metadata": {
                    "PROCESSING_ACCOUNT_PAYMENT_INTENT_ID": str(processing_pi),
                    "PROCESSING_ACCOUNT_PAYMENT_METHOD_ID": str(processing_pm),
                    "MASTER_ACCOUNT_ID": str(master_account_id),
                    "MASTER_ACCOUNT_INVOICE_ID": str(master_invoice_id),
                    "MASTER_ACCOUNT_SUBSCRIPTION_ID": str(master_subscription_id),
                },
                "payment_method_details": {"payment_method": str(master_custom_pm_id)},
                "processor_details": {"type": "custom", "custom": {"payment_reference": str(processing_pi)}},
            }
        )
        payment_record_id = safe_get(payment_record, "id")
        _require(payment_record_id, "Failed to create failed payment record on master account (scenario #4)")

        master_client.v1.invoices.attach_payment(str(master_invoice_id), {"payment_record": str(payment_record_id)})
        print(
            "[stripe-webhook-orch] scenario=processing_invoice_payment_failed "
            f"processing_alias={normalized_alias} master_alias={master_alias} "
            f"processing_pi={processing_pi} master_invoice_id={master_invoice_id} payment_record_id={payment_record_id}"
        )
        return

    # Scenario 5: refund.created on processing account
    elif normalized_alias != master_alias and event_type == "refund.created":
        refund_obj = safe_get(safe_get(event, "data"), "object")
        processing_pi = _require(safe_get(refund_obj, "payment_intent"), "Missing refund field: data.object.payment_intent")
        refund_id = _require(safe_get(refund_obj, "id"), "Missing refund field: data.object.id")
        amount = _require(safe_get(refund_obj, "amount"), "Missing refund field: data.object.amount")
        currency = _require(safe_get(refund_obj, "currency"), "Missing refund field: data.object.currency")
        created = _require(safe_get(refund_obj, "created"), "Missing refund field: data.object.created")

        _processing_account_id, processing_secret_key, _ = get_account_env(normalized_alias)
        processing_client = stripe_client(processing_secret_key)
        pi = processing_client.v1.payment_intents.retrieve(
            str(processing_pi), {"expand": ["invoice"]}, options={"stripe_version": "2020-08-27"}
        )
        links = _extract_master_links_from_payment_intent(pi)
        master_invoice_id = _require(links["MASTER_ACCOUNT_INVOICE_ID"], "Missing metadata: MASTER_ACCOUNT_INVOICE_ID")

        _master_account_id, master_secret_key, _ = get_account_env(master_alias)
        master_client = stripe_client(master_secret_key)
        master_payment_record_id = _get_master_payment_record_id(master_client, master_invoice_id)

        refund_ts = normalize_report_timestamp(created)
        payment_record = master_client.v1.payment_records.report_refund(
            str(master_payment_record_id),
            {
                "processor_details": {"type": "custom", "custom": {"refund_reference": str(refund_id)}},
                "outcome": "refunded",
                "refunded": {"refunded_at": refund_ts},
                "amount": {"currency": str(currency), "value": int(amount)},
                "initiated_at": refund_ts,
                "metadata": {"PROCESSING_ACCOUNT_REFUND_ID": str(refund_id)},
            },
        )

        # Create a credit note on master invoice (out-of-band)
        try:
            _create_master_credit_note(master_client, str(master_invoice_id), int(amount), {"PROCESSING_ACCOUNT_REFUND_ID": str(refund_id)})
        except Exception:
            traceback.print_exc()

        print(
            "[stripe-webhook-orch] scenario=processing_refund_created "
            f"processing_alias={normalized_alias} master_alias={master_alias} "
            f"processing_pi={processing_pi} refund_id={refund_id} master_invoice_id={master_invoice_id} "
            f"master_payment_record_id={master_payment_record_id} refund_record_id={safe_get(payment_record,'id')}"
        )
        return

    # Scenario 6: charge.dispute.closed (status=lost) on processing account
    elif normalized_alias != master_alias and event_type == "charge.dispute.closed":
        dispute_obj = safe_get(safe_get(event, "data"), "object")
        status = str(safe_get(dispute_obj, "status") or "").strip().lower()
        if status != "lost":
            return

        processing_pi = _require(safe_get(dispute_obj, "payment_intent"), "Missing dispute field: data.object.payment_intent")
        dispute_id = _require(safe_get(dispute_obj, "id"), "Missing dispute field: data.object.id")
        amount = _require(safe_get(dispute_obj, "amount"), "Missing dispute field: data.object.amount")
        currency = _require(safe_get(dispute_obj, "currency"), "Missing dispute field: data.object.currency")
        created = _require(safe_get(dispute_obj, "created"), "Missing dispute field: data.object.created")

        _processing_account_id, processing_secret_key, _ = get_account_env(normalized_alias)
        processing_client = stripe_client(processing_secret_key)
        pi = processing_client.v1.payment_intents.retrieve(
            str(processing_pi), {"expand": ["invoice"]}, options={"stripe_version": "2020-08-27"}
        )
        links = _extract_master_links_from_payment_intent(pi)
        master_invoice_id = _require(links["MASTER_ACCOUNT_INVOICE_ID"], "Missing metadata: MASTER_ACCOUNT_INVOICE_ID (dispute)")

        _master_account_id, master_secret_key, _ = get_account_env(master_alias)
        master_client = stripe_client(master_secret_key)
        master_payment_record_id = _get_master_payment_record_id(master_client, master_invoice_id)

        dispute_ts = normalize_report_timestamp(created)
        payment_record = master_client.v1.payment_records.report_refund(
            str(master_payment_record_id),
            {
                "processor_details": {"type": "custom", "custom": {"refund_reference": str(dispute_id)}},
                "outcome": "refunded",
                "refunded": {"refunded_at": dispute_ts},
                "amount": {"currency": str(currency), "value": int(amount)},
                "initiated_at": dispute_ts,
                "metadata": {"PROCESSING_ACCOUNT_DISPUTE_ID": str(dispute_id)},
            },
        )

        try:
            _create_master_credit_note(
                master_client, str(master_invoice_id), int(amount), {"PROCESSING_ACCOUNT_DISPUTE_ID": str(dispute_id)}
            )
        except Exception:
            traceback.print_exc()

        print(
            "[stripe-webhook-orch] scenario=processing_dispute_closed_lost "
            f"processing_alias={normalized_alias} master_alias={master_alias} "
            f"processing_pi={processing_pi} dispute_id={dispute_id} master_invoice_id={master_invoice_id} "
            f"master_payment_record_id={master_payment_record_id} dispute_record_id={safe_get(payment_record,'id')}"
        )
        return

    # Scenario 2: invoice.payment_attempt_required on master account
    elif normalized_alias == master_alias and event_type == "invoice.payment_attempt_required":
        inv = safe_get(safe_get(event, "data"), "object")
        
        master_invoice_id = _require(safe_get(inv, "id"), "Missing invoice id in webhook: data.object.id")
        currency = _require(safe_get(inv, "currency"), "Missing invoice currency in webhook: data.object.currency")
        amount = safe_get(inv, "amount_due")
        if amount is None:
            raise ValueError("Missing invoice amount_due in webhook: data.object.amount_due")
        master_customer_id = _require(safe_get(inv, "customer"), "Missing invoice customer in webhook: data.object.customer")
        period_start = _require(safe_get(inv, "period_start"), "Missing invoice period_start in webhook: data.object.period_start")
        period_end = _require(safe_get(inv, "period_end"), "Missing invoice period_end in webhook: data.object.period_end")

        lines = safe_get(inv, "lines")
        lines_data = safe_get(lines, "data") or []
        first_line = lines_data[0] if isinstance(lines_data, list) and len(lines_data) > 0 else None
        description = safe_get(first_line, "description") or ""

        parent = safe_get(inv, "parent")
        subscription_details = safe_get(parent, "subscription_details")
        sd_md = safe_get(subscription_details, "metadata") or {}
        # Optional flag propagated from subscription metadata (used by some clients to skip invoice sync in downstream systems).
        skip_ns_invoice_sync = safe_get(sd_md, "SKIP_NS_INVOICE_SYNC")
        master_subscription_id = _require(
            safe_get(subscription_details, "subscription"),
            "Missing subscription id in webhook: data.object.parent.subscription_details.subscription",
        )
        processing_account_id = _require(
            _get_upper(sd_md, "PROCESSING_ACCOUNT_ID"),
            "Missing processing account id in webhook: data.object.parent.subscription_details.metadata.PROCESSING_ACCOUNT_ID",
        )

        _master_account_id, master_secret_key, _ = get_account_env(master_alias)
        master_client = stripe_client(master_secret_key)

        # If enabled, and the webhook carries SKIP_NS_INVOICE_SYNC in subscription_details.metadata,
        # persist it on the master invoice.
        if get_runtime_bool("skip_sync_non_master_invoice", True) and skip_ns_invoice_sync is not None and str(skip_ns_invoice_sync).strip() != "":
            try:
                v = str(skip_ns_invoice_sync).strip()
                if isinstance(skip_ns_invoice_sync, bool):
                    v = "true" if skip_ns_invoice_sync else "false"
                master_client.v1.invoices.update(str(master_invoice_id), {"metadata": {"SKIP_NS_INVOICE_SYNC": v}})
            except Exception:
                traceback.print_exc()

        sub = master_client.v1.subscriptions.retrieve(str(master_subscription_id), {"expand": ["default_payment_method"]})
        default_pm = safe_get(sub, "default_payment_method")
        master_custom_pm_id = _require(safe_get(default_pm, "id"), "Missing master default_payment_method.id on subscription")
        pm_md = safe_get(default_pm, "metadata") or {}
        processing_payment_method_id = _require(
            _get_upper(pm_md, "PROCESSING_ACCOUNT_PAYMENT_METHOD_ID"),
            "Missing default_payment_method.metadata.PROCESSING_ACCOUNT_PAYMENT_METHOD_ID on subscription",
        )
        processing_customer_id = _require(
            _get_upper(pm_md, "PROCESSING_ACCOUNT_CUSTOMER_ID"),
            "Missing default_payment_method.metadata.PROCESSING_ACCOUNT_CUSTOMER_ID on subscription",
        )
        # get invoice from the master account, in order to save the invoice number field
        invoice = master_client.v1.invoices.retrieve(str(master_invoice_id))
        invoice_number = safe_get(invoice, "number")



        processing_alias = get_alias_by_account_id(str(processing_account_id))
        _processing_account_id, processing_secret_key, _ = get_account_env(processing_alias)
        processing_client = stripe_client(processing_secret_key)

        query = f"metadata['MASTER_ACCOUNT_INVOICE_ID']:'{str(master_invoice_id)}'"
        search_res = processing_client.v1.invoices.search({"query": query, "limit": 1})
        existing = safe_get(search_res, "data") or []
        if isinstance(existing, list) and len(existing) > 0:
            print(
                "[stripe-webhook-orch] scenario=invoice_payment_attempt_required existing_processing_invoice=true "
                f"master_invoice_id={master_invoice_id} processing_alias={processing_alias}"
            )
            return

        processing_client.v1.invoice_items.create(
            {
                "customer": str(processing_customer_id),
                "currency": str(currency),
                "amount": int(amount),
                "description": str(description),
                "period": {"start": int(period_start), "end": int(period_end)},

            }
        )

        processing_invoice = processing_client.v1.invoices.create(
            {
                "customer": str(processing_customer_id),
                "currency": str(currency),
                "collection_method": "charge_automatically",
                "auto_advance": True,
                "pending_invoice_items_behavior": "include",
                "default_payment_method": str(processing_payment_method_id),
                "number": str(invoice_number), #make sure we propagate the invoice number to the processing invoice, to be able to track the invoice number on the processing invoice
                "metadata": {
                    "MASTER_ACCOUNT_INVOICE_ID": str(master_invoice_id),
                    "MASTER_ACCOUNT_CUSTOMER_ID": str(master_customer_id),
                    "MASTER_ACCOUNT_SUBSCRIPTION_ID": str(master_subscription_id),
                    "MASTER_ACCOUNT_ID": str(resolved_account_id),
                },
            }
        )
        processing_invoice_id = safe_get(processing_invoice, "id")
        _require(processing_invoice_id, "Failed to create processing invoice")

        try:
            processing_client.v1.invoices.pay(str(processing_invoice_id), {"off_session": True})
        except Exception as e:
            print(f"Failed to pay processing invoice: {e}")
            traceback.print_exc()

        print(
            "[stripe-webhook-orch] scenario=invoice_payment_attempt_required created_processing_invoice=true "
            f"master_invoice_id={master_invoice_id} processing_alias={processing_alias} processing_invoice_id={processing_invoice_id}"
        )
        return


