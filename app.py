"""
app.py

Flask entrypoint for the BYOP Orchestration demo.

This file intentionally focuses on:
- Flask routing (pages + JSON APIs)
- Minimal webhook plumbing (signature verification + delegating to the orchestration layer)

All Stripe orchestration logic (multi-account webhook scenarios) lives in `stripe_orchestration.py`.
Small shared utilities (env lookup, StripeClient, timestamp normalization) live in `stripe_helpers.py`.
"""

import os
import json
import traceback
import time
import queue
from typing import Any, Dict, Optional

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context
from dotenv import load_dotenv

import stripe

from stripe_helpers import (
    debug_dump,
    get_account_env,
    get_account_country,
    get_master_alias,
    get_webhook_signing_secret,
    stripe_client,
)
from stripe_orchestration import handle_orchestration_event
from auth import requires_basic_auth
from config_store import load_runtime_config, save_runtime_config, load_catalog, save_catalog
from webhook_monitor import WebhookEventHub


def create_app() -> Flask:
    load_dotenv()

    app = Flask(__name__, static_folder="static", static_url_path="/static")
    webhook_hub = WebhookEventHub()

    @app.get("/")
    def index_page():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/create-customer")
    def create_customer_page():
        return send_from_directory(app.static_folder, "create-customer.html")

    @app.get("/summary")
    def summary_page():
        return send_from_directory(app.static_folder, "summary.html")

    @app.get("/update-custom-payment-method")
    def update_custom_payment_method_page():
        return send_from_directory(app.static_folder, "update-custom-payment-method.html")

    @app.get("/config")
    @requires_basic_auth
    def config_page():
        return send_from_directory(app.static_folder, "config.html")

    @app.get("/webhook-monitoring")
    def webhook_monitoring_page():
        return send_from_directory(app.static_folder, "webhook-monitoring.html")

    @app.get("/api/monitor/webhooks/stream")
    def api_webhook_stream():
        """
        Server-Sent Events stream for webhook monitoring.

        No persistence: events are only sent to currently connected clients.
        """

        client_q: queue.Queue[str] = webhook_hub.subscribe(max_queue_size=200)

        @stream_with_context
        def generate():
            try:
                # Initial hello to confirm connection and allow the UI to flip to "connected".
                yield "event: hello\ndata: {}\n\n"
                while True:
                    try:
                        msg = client_q.get(timeout=15)
                        yield f"event: webhook\ndata: {msg}\n\n"
                    except Exception:
                        # Keep-alive comment to prevent idle timeouts in some proxies.
                        yield ": keepalive\n\n"
            finally:
                webhook_hub.unsubscribe(client_q)

        headers = {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
        return Response(generate(), headers=headers, mimetype="text/event-stream")

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    # Catalog is file-backed and can be edited live from /config.
    def load_catalog_local() -> Dict[str, Any]:
        return load_catalog()

    def get_price_by_id(catalog: Dict[str, Any], price_id: str) -> Optional[Dict[str, Any]]:
        for p in catalog.get("prices", []):
            if p.get("id") == price_id:
                return p
        return None

    @app.post("/webhook/<alias>")
    def stripe_webhook(alias: str):
        """
        Stripe webhook endpoint for a specific account alias.
        URL: /webhook/<ALIAS> (e.g. /webhook/EU, /webhook/US)

    Notes:
    - We use the URL alias to pick the correct webhook signing secret.
    - After verification, we delegate processing to `handle_orchestration_event(...)`.
        """
        try:
            normalized_alias = (alias or "").strip().upper()
            if not normalized_alias:
                return jsonify({"error": "Missing required path param: alias"}), 400

            sig_header = (request.headers.get("Stripe-Signature", "") or "").strip()
            if not sig_header:
                return jsonify({"error": "Missing required header: Stripe-Signature"}), 400

            signing_secret = get_webhook_signing_secret(normalized_alias)
            payload = request.get_data(as_text=True)  # raw JSON body as string

            try:
                event = stripe.Webhook.construct_event(payload=payload, sig_header=sig_header, secret=signing_secret)
            except Exception as e:
                import traceback
                traceback.print_exc()
                return jsonify({"error": "Webhook signature verification failed", "detail": str(e)}), 400
            # debug the event received (can be very verbose)
            debug_dump(event)
            event_type = getattr(event, "type", None)
            if event_type is None and isinstance(event, dict):
                event_type = event.get("type")
            # Use alias to resolve the expected Stripe account id from env (more reliable than event.account).
            resolved_account_id, _resolved_secret_key, _resolved_publishable_key = get_account_env(normalized_alias)
            resolved_country = get_account_country(normalized_alias)

            # Keep the raw event "account" as optional debug signal (may be missing depending on event source).
            event_account_id = getattr(event, "account", None)
            if event_account_id is None and isinstance(event, dict):
                event_account_id = event.get("account")

            # Broadcast monitoring event (best-effort, in-memory only).
            webhook_hub.publish(
                {
                    "received_at": int(time.time()),
                    "alias": normalized_alias,
                    "account_id": resolved_account_id,
                    "country": resolved_country,
                    "type": event_type,
                }
            )
            print(
                f"[stripe-webhook] alias={normalized_alias} account_id={resolved_account_id} "
                f"type={event_type} event_account_id={event_account_id}"
            )
            # Delegate orchestration logic (scenarios 1-6)
            handle_orchestration_event(normalized_alias, event, resolved_account_id)
            
            return "ok", 200
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": "Webhook handler failed", "detail": str(e)}), 500

    @app.get("/api/catalog")
    def api_catalog():
        try:
            catalog = load_catalog_local()
            return jsonify(catalog)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": "Failed to load catalog", "detail": str(e)}), 500

    @app.get("/card_failed")
    def card_failed_page():
        #print everything received in the request, both headers, body, params, etc
        print(f"headers: {request.headers}")
        print(f"body: {request.get_data(as_text=True)}")
        print(f"params: {request.args}")
        print(f"form: {request.form}")
        print(f"json: {request.get_json(silent=True)}")
        print(f"files: {request.files}")
        print(f"cookies: {request.cookies}")
        print(f"url: {request.url}")
        print(f"path: {request.path}")
        print(f"full_path: {request.full_path}")
        print(f"base_url: {request.base_url}")
        print(f"host: {request.host}")
        print(f"remote_addr: {request.remote_addr}")
        print(f"user_agent: {request.user_agent}")
        # just return OK
        return "OK", 200

    @app.put("/api/catalog")
    @requires_basic_auth
    def api_update_catalog():
        """
        Update the product catalog (config/catalog.json).
        Protected by Basic Auth because it mutates server-side configuration.
        """
        try:
            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                return jsonify({"error": "Invalid payload: expected JSON object"}), 400
            save_catalog(payload)
            return jsonify({"status": "ok"})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": "Failed to update catalog", "detail": str(e)}), 500

    @app.get("/api/config")
    @requires_basic_auth
    def api_get_config():
        """
        Return runtime config from config/runtime-config.json.
        Protected by Basic Auth because it contains sensitive fields.
        """
        try:
            cfg = load_runtime_config()
            return jsonify(cfg)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": "Failed to load config", "detail": str(e)}), 500

    @app.put("/api/config")
    @requires_basic_auth
    def api_update_config():
        """
        Update runtime config (config/runtime-config.json).
        Protected by Basic Auth because it contains secrets (Stripe keys / webhook signing secrets).
        """
        try:
            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                return jsonify({"error": "Invalid payload: expected JSON object"}), 400
            save_runtime_config(payload)
            return jsonify({"status": "ok"})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": "Failed to update config", "detail": str(e)}), 500

    @app.get("/api/stripe/publishable-key")
    def api_publishable_key():
        try:
            price_id = request.args.get("price_id", "").strip()
            if not price_id:
                return jsonify({"error": "Missing required query param: price_id"}), 400

            catalog = load_catalog_local()
            # NOTE: catalog is file-backed (config/catalog.json) and can be edited live from /config.
            price = get_price_by_id(catalog, price_id)
            if not price:
                return jsonify({"error": "Unknown price_id"}), 404

            alias = price.get("account_alias", "").strip()
            if not alias:
                return jsonify({"error": "Catalog price is missing account_alias"}), 500

            # "Processing" account is associated to the selected price (EUR/USD), but we always create resources
            # (like Customers) on the master account (typically EU) using Stripe Organization Resource Sharing.
            processing_account_id, _processing_secret_key, processing_publishable_key = get_account_env(alias)
            processing_country = get_account_country(alias)

            master_alias = get_master_alias()
            master_account_id, _master_secret_key, master_publishable_key = get_account_env(master_alias)
            master_country = get_account_country(master_alias)
            google_places_api_key = os.getenv("GOOGLE_MAPS_PLACES_API_KEY", "").strip() or None
            return jsonify(
                {
                    # Use master publishable key to initialize Stripe.js for this flow.
                    "publishable_key": master_publishable_key,
                    "master_account": {
                        "alias": master_alias,
                        "account_id": master_account_id,
                        "country": master_country,
                    },
                    "processing_account_id": processing_account_id,
                    "processing_publishable_key": processing_publishable_key,
                    "processing_account": {
                        "alias": alias,
                        "account_id": processing_account_id,
                        "country": processing_country,
                    },
                    "price": price,
                    "address_autocomplete": {
                        # Stripe docs: Address Element used standalone requires your own Places API key:
                        # https://docs.stripe.com/elements/address-element#autocomplete
                        "google_maps_places_api_key": google_places_api_key
                    },
                }
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": "Failed to resolve publishable key", "detail": str(e)}), 500

    @app.post("/api/customers")
    def api_create_customer():
        try:
            payload = request.get_json(silent=True) or {}

            price_id = str(payload.get("price_id", "")).strip()
            first_name = str(payload.get("first_name", "")).strip()
            last_name = str(payload.get("last_name", "")).strip()
            email = str(payload.get("email", "")).strip()
            address = payload.get("address") or {}

            if not price_id:
                return jsonify({"error": "Missing required field: price_id"}), 400
            if not first_name:
                return jsonify({"error": "Missing required field: first_name"}), 400
            if not last_name:
                return jsonify({"error": "Missing required field: last_name"}), 400
            if not email:
                return jsonify({"error": "Missing required field: email"}), 400

            catalog = load_catalog_local()
            price = get_price_by_id(catalog, price_id)
            if not price:
                return jsonify({"error": "Unknown price_id"}), 404

            alias = price.get("account_alias", "").strip()
            if not alias:
                return jsonify({"error": "Catalog price is missing account_alias"}), 500

            # Always create Customer on the master account (EU by default).
            master_alias = get_master_alias()
            master_account_id, master_secret_key, _master_publishable_key = get_account_env(master_alias)
            client = stripe_client(master_secret_key)

            # Processing account is associated to the selected price.
            processing_account_id, _processing_secret_key, _processing_publishable_key = get_account_env(alias)

            # Address Element returns a structured object; we normalize to Stripe Customer address.
            normalized_address = {
                "line1": (address.get("line1") or "").strip() or None,
                "line2": (address.get("line2") or "").strip() or None,
                "city": (address.get("city") or "").strip() or None,
                "state": (address.get("state") or "").strip() or None,
                "postal_code": (address.get("postal_code") or "").strip() or None,
                "country": (address.get("country") or "").strip() or None,
            }
            normalized_address = {k: v for k, v in normalized_address.items() if v is not None}

            params: Dict[str, Any] = {
                "name": f"{first_name} {last_name}".strip(),
                "email": email,
                "metadata": {
                    "PROCESSING_ACCOUNT_ID": processing_account_id,
                    "MASTER_ACCOUNT_ID": master_account_id,
                    "SELECTED_PRICE_ID": price_id,
                    "SELECTED_CURRENCY": price.get("currency"),
                },
            }
            if normalized_address:
                params["address"] = normalized_address

            customer = client.v1.customers.create(params)

            return jsonify(
                {
                    "stripe_customer_id": customer.id,
                    "created_on_account_id": master_account_id,
                    "processing_account_id": processing_account_id,
                }
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": "Failed to create customer", "detail": str(e)}), 500

    @app.post("/api/subscriptions")
    def api_create_subscription():
        try:
            payload = request.get_json(silent=True) or {}

            price_id = str(payload.get("price_id", "")).strip()
            stripe_customer_id = str(payload.get("stripe_customer_id", "")).strip()

            if not price_id:
                return jsonify({"error": "Missing required field: price_id"}), 400
            if not stripe_customer_id:
                return jsonify({"error": "Missing required field: stripe_customer_id"}), 400

            catalog = load_catalog_local()
            price = get_price_by_id(catalog, price_id)
            if not price:
                return jsonify({"error": "Unknown price_id"}), 404

            alias = price.get("account_alias", "").strip()
            if not alias:
                return jsonify({"error": "Catalog price is missing account_alias"}), 500

            # Always create Subscription on the master account (EU by default).
            master_alias = get_master_alias()
            master_account_id, master_secret_key, _master_publishable_key = get_account_env(master_alias)
            client = stripe_client(master_secret_key)

            # Processing account is associated to the selected price.
            processing_account_id, _processing_secret_key, _processing_publishable_key = get_account_env(alias)

            # If the subscription is created on master but processed on a different account,
            # we can mark it to skip certain downstream invoice sync behaviors (custom orchestration flag).
            cfg = load_runtime_config()
            tag_skip_sync = bool(cfg.get("skip_sync_non_master_invoice", True)) if isinstance(cfg, dict) else True
            skip_ns_invoice_sync = (processing_account_id != master_account_id) and tag_skip_sync

            subscription = client.v1.subscriptions.create(
                {
                    "customer": stripe_customer_id,
                    "items": [{"price": price_id, "quantity": 1}],
                    "collection_method": "charge_automatically",
                    "payment_behavior": "default_incomplete",
                    "payment_settings": {"save_default_payment_method": "on_subscription"},
                    "automatic_tax": {"enabled": True},
                    "metadata": {
                        "PROCESSING_ACCOUNT_ID": processing_account_id,
                        "MASTER_ACCOUNT_ID": master_account_id,
                        "SELECTED_PRICE_ID": price_id,
                        "SELECTED_CURRENCY": price.get("currency"),
                        **({"SKIP_NS_INVOICE_SYNC": "true"} if skip_ns_invoice_sync else {}),
                    },
                    "expand": ["latest_invoice", "latest_invoice.payment_intent", "pending_setup_intent",
                    "latest_invoice.confirmation_secret"],
                }
            )
            latest_invoice = subscription.latest_invoice if hasattr(subscription, "latest_invoice") else None
            latest_invoice_id = None
            hosted_invoice_url = None
            invoice_currency = None
            invoice_total = None
            invoice_total_excluding_tax = None
            invoice_taxable_amount = None
            invoice_amount_due = None
            payment_intent_id = None
            payment_intent_client_secret = None
            payment_confirmation_type = None
            pending_setup_intent_id = None
            pending_setup_intent_client_secret = None
            try:
                # With expand=['latest_invoice'], this is usually an object.
                latest_invoice_id = getattr(latest_invoice, "id", None) or (latest_invoice.get("id") if latest_invoice else None)
                hosted_invoice_url = getattr(latest_invoice, "hosted_invoice_url", None) or (
                    latest_invoice.get("hosted_invoice_url") if latest_invoice else None
                )
                invoice_currency = getattr(latest_invoice, "currency", None) or (latest_invoice.get("currency") if latest_invoice else None)
                invoice_total = getattr(latest_invoice, "total", None) or (latest_invoice.get("total") if latest_invoice else None)
                invoice_total_excluding_tax = getattr(latest_invoice, "total_excluding_tax", None) or (
                    latest_invoice.get("total_excluding_tax") if latest_invoice else None
                )
                invoice_amount_due = getattr(latest_invoice, "amount_due", None) or (
                    latest_invoice.get("amount_due") if latest_invoice else None
                )

                # taxable_amount is exposed per tax breakdown entry in invoice.total_taxes[].
                # We return a single number by summing them (in the invoice currency minor unit).
                try:
                    total_taxes = getattr(latest_invoice, "total_taxes", None) or (
                        latest_invoice.get("total_taxes") if latest_invoice else None
                    )
                    taxable_sum = 0
                    if total_taxes:
                        for t in total_taxes:
                            ta = getattr(t, "taxable_amount", None) if hasattr(t, "taxable_amount") else None
                            if ta is None and isinstance(t, dict):
                                ta = t.get("taxable_amount")
                            if ta is None:
                                continue
                            try:
                                taxable_sum += int(ta)
                            except Exception:
                                continue
                    invoice_taxable_amount = taxable_sum if taxable_sum else None
                except Exception:
                    invoice_taxable_amount = None

                pi = getattr(latest_invoice, "payment_intent", None) or (latest_invoice.get("payment_intent") if latest_invoice else None)
                payment_intent_id = (getattr(pi, "id", None) or (pi.get("id") if pi else None)) if pi else None
                payment_intent_client_secret = (
                    (getattr(pi, "client_secret", None) or (pi.get("client_secret") if pi else None)) if pi else None
                )

                # Newer API versions can expose a confirmation_secret on the Invoice instead of expanding payment_intent.
                # Example: latest_invoice.confirmation_secret.client_secret + type=payment_intent
                if not payment_intent_client_secret:
                    cs = getattr(latest_invoice, "confirmation_secret", None) or (
                        latest_invoice.get("confirmation_secret") if latest_invoice else None
                    )
                    payment_confirmation_type = getattr(cs, "type", None) or (cs.get("type") if cs else None)
                    cs_client_secret = getattr(cs, "client_secret", None) or (cs.get("client_secret") if cs else None)
                    if cs_client_secret:
                        payment_intent_client_secret = cs_client_secret
                        try:
                            payment_intent_id = cs_client_secret.split("_secret_", 1)[0]
                        except Exception:
                            pass
            except Exception:
                latest_invoice_id = None

            # Propagate the same "SKIP_NS_INVOICE_SYNC" marker to the master invoice created by the subscription.
            # Note: Stripe metadata values are strings.
            if skip_ns_invoice_sync and latest_invoice_id:
                try:
                    client.v1.invoices.update(str(latest_invoice_id), {"metadata": {"SKIP_NS_INVOICE_SYNC": "true"}})
                except Exception:
                    traceback.print_exc()

            try:
                psi = getattr(subscription, "pending_setup_intent", None) or (
                    subscription.get("pending_setup_intent") if isinstance(subscription, dict) else None
                )
                pending_setup_intent_id = getattr(psi, "id", None) or (psi.get("id") if psi else None)
                pending_setup_intent_client_secret = getattr(psi, "client_secret", None) or (
                    psi.get("client_secret") if psi else None
                )
            except Exception:
                pending_setup_intent_id = None

            return jsonify(
                {
                    "stripe_subscription_id": subscription.id,
                    "status": getattr(subscription, "status", None),
                    "latest_invoice_id": latest_invoice_id,
                    "hosted_invoice_url": hosted_invoice_url,
                    "invoice_currency": invoice_currency,
                    "invoice_total": invoice_total,
                    "invoice_total_excluding_tax": invoice_total_excluding_tax,
                    "invoice_taxable_amount": invoice_taxable_amount,
                    "invoice_amount_due": invoice_amount_due,
                    "payment_intent_id": payment_intent_id,
                    "payment_intent_client_secret": payment_intent_client_secret,
                    "payment_confirmation_type": payment_confirmation_type,
                    "pending_setup_intent_id": pending_setup_intent_id,
                    "pending_setup_intent_client_secret": pending_setup_intent_client_secret,
                    "created_on_account_id": master_account_id,
                    "processing_account_id": processing_account_id,
                }
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": "Failed to create subscription", "detail": str(e)}), 500

    @app.post("/api/processing-payment-intents")
    def api_create_processing_payment_intent():
        """
        Create a PaymentIntent on the processing account, matching the amount/currency of the original master invoice.
        This is used when processing_account != master_account.
        """
        try:
            payload = request.get_json(silent=True) or {}

            price_id = str(payload.get("price_id", "")).strip()
            stripe_customer_id = str(payload.get("stripe_customer_id", "")).strip()
            # Optional debug override (avoid hardcoding test ids in code):
            # FORCE_STRIPE_CUSTOMER_ID=cus_... python app.py
            forced_customer_id = os.getenv("FORCE_STRIPE_CUSTOMER_ID", "").strip()
            if forced_customer_id:
                stripe_customer_id = forced_customer_id
            original_invoice_id = str(payload.get("original_invoice_id", "")).strip()
            original_subscription_id = str(payload.get("original_subscription_id", "")).strip()

            if not price_id:
                return jsonify({"error": "Missing required field: price_id"}), 400
            if not stripe_customer_id:
                return jsonify({"error": "Missing required field: stripe_customer_id"}), 400
            if not original_invoice_id:
                return jsonify({"error": "Missing required field: original_invoice_id"}), 400
            if not original_subscription_id:
                return jsonify({"error": "Missing required field: original_subscription_id"}), 400

            catalog = load_catalog_local()
            price = get_price_by_id(catalog, price_id)
            if not price:
                return jsonify({"error": "Unknown price_id"}), 404

            processing_alias = price.get("account_alias", "").strip()
            if not processing_alias:
                return jsonify({"error": "Catalog price is missing account_alias"}), 500

            # Master account: fetch the invoice to compute amount/currency source of truth.
            master_alias = get_master_alias()
            master_account_id, master_secret_key, _master_publishable_key = get_account_env(master_alias)
            master_client = stripe_client(master_secret_key)
            invoice = master_client.v1.invoices.retrieve(original_invoice_id)

            amount = getattr(invoice, "amount_due", None) or getattr(invoice, "total", None)
            currency = getattr(invoice, "currency", None)
            if amount is None or currency is None:
                return jsonify({"error": "Unable to resolve invoice amount/currency from master invoice"}), 500

            # Processing account: create a matching PaymentIntent.
            processing_account_id, processing_secret_key, processing_publishable_key = get_account_env(processing_alias)
            processing_client = stripe_client(processing_secret_key)

            # org resources sharing can take a few minute to kick things so we might need to loop a few times to make sure the resources are ready  
            isSynced = False
            while not isSynced:
                # try to retrieve the customer on the processing account    
                try:
                    customer = processing_client.v1.customers.retrieve(stripe_customer_id)
                    isSynced = True
                except Exception as e:
                    print(f"Failed to retrieve customer on processing account: {e}")
                    time.sleep(1)

            pi = processing_client.v1.payment_intents.create(
                {
                    "amount": int(amount),
                    "currency": str(currency),
                    "customer": stripe_customer_id,
                    "setup_future_usage": "off_session",
                    "automatic_payment_methods": {"enabled": True},
                    "metadata": {
                        "INITIAL_PAYMENT": "true",
                        "MASTER_ACCOUNT_ID": master_account_id,
                        "MASTER_ACCOUNT_INVOICE_ID": original_invoice_id,
                        "MASTER_ACCOUNT_SUBSCRIPTION_ID": original_subscription_id,
                        "MASTER_ACCOUNT_CUSTOMER_ID": customer.id,
                    },
                }
            )

            return jsonify(
                {
                    "processing_account_id": processing_account_id,
                    "processing_publishable_key": processing_publishable_key,
                    "payment_intent_id": pi.id,
                    "payment_intent_client_secret": getattr(pi, "client_secret", None),
                    "amount": int(amount),
                    "currency": str(currency),
                }
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": "Failed to create processing PaymentIntent", "detail": str(e)}), 500

    @app.post("/api/payment-methods/update-processing-metadata")
    def api_update_payment_method_processing_metadata():
        """
        Update a PaymentMethod on the master account by modifying ONLY:
        metadata.PROCESSING_ACCOUNT_PAYMENT_METHOD_ID
        """
        try:
            payload = request.get_json(silent=True) or {}

            master_payment_method_id = str(payload.get("master_account_custom_payment_method", "")).strip()
            processing_payment_method_id = str(payload.get("processing_account_payment_method_id", "")).strip()
            
            if not master_payment_method_id:
                return jsonify({"error": "Missing required field: master_account_custom_payment_method"}), 400
            if not processing_payment_method_id:
                return jsonify({"error": "Missing required field: processing_account_payment_method_id"}), 400
            master_alias = get_master_alias()
            master_account_id, master_secret_key, _master_publishable_key = get_account_env(master_alias)
            client = stripe_client(master_secret_key)

            pm = client.v1.payment_methods.update(
                master_payment_method_id,
                {
                    "metadata": {
                        "PROCESSING_ACCOUNT_PAYMENT_METHOD_ID": processing_payment_method_id,
                    }
                },
            )

            updated_value = None
            try:
                md = getattr(pm, "metadata", None) or (pm.get("metadata") if isinstance(pm, dict) else None) or {}
                updated_value = md.get("PROCESSING_ACCOUNT_PAYMENT_METHOD_ID")
            except Exception:
                updated_value = None

            return jsonify(
                {
                    "payment_method_id": pm.id,
                    "master_account_id": master_account_id,
                    "processing_account_payment_method_id": updated_value,
                }
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": "Failed to update payment method metadata", "detail": str(e)}), 500

    @app.get("/api/payment-methods/<payment_method_id>")
    def api_get_payment_method(payment_method_id: str):
        """
        Retrieve a PaymentMethod from the master account.
        Used to display current data/metadata before updating.
        """
        try:
            pm_id = (payment_method_id or "").strip()
            if not pm_id:
                return jsonify({"error": "Missing payment_method_id"}), 400

            master_alias = get_master_alias()
            master_account_id, master_secret_key, _master_publishable_key = get_account_env(master_alias)
            client = stripe_client(master_secret_key)

            pm = client.v1.payment_methods.retrieve(pm_id)

            if hasattr(pm, "to_dict_recursive"):
                pm_dict = pm.to_dict_recursive()
            elif isinstance(pm, dict):
                pm_dict = pm
            else:
                pm_dict = {"id": getattr(pm, "id", None)}

            # Return a curated subset for safety/readability.
            billing = (pm_dict.get("billing_details") or {}) if isinstance(pm_dict, dict) else {}
            card = (pm_dict.get("card") or {}) if isinstance(pm_dict, dict) else {}

            return jsonify(
                {
                    "master_account_id": master_account_id,
                    "payment_method": {
                        "id": pm_dict.get("id"),
                        "type": pm_dict.get("type"),
                        "customer": pm_dict.get("customer"),
                        "livemode": pm_dict.get("livemode"),
                        "created": pm_dict.get("created"),
                        "metadata": pm_dict.get("metadata") or {},
                        "billing_details": {
                            "name": billing.get("name"),
                            "email": billing.get("email"),
                            "phone": billing.get("phone"),
                            "address": billing.get("address"),
                        },
                        "card": {
                            "brand": card.get("brand"),
                            "last4": card.get("last4"),
                            "exp_month": card.get("exp_month"),
                            "exp_year": card.get("exp_year"),
                            "funding": card.get("funding"),
                            "country": card.get("country"),
                            "wallet": card.get("wallet"),
                        }
                        if pm_dict.get("type") == "card"
                        else None,
                    },
                }
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": "Failed to retrieve payment method", "detail": str(e)}), 500

    return app


if __name__ == "__main__":
    app = create_app()
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)


