"""
stripe_helpers.py

Small helper utilities used across the Flask app and the webhook orchestration layer.

Key goals:
- Keep Stripe configuration/env lookups in one place
- Provide small, reusable utilities (safe field access, timestamp normalization)
- Keep all inline comments and docstrings in ENGLISH for maintainability
"""

import os
import time
import traceback
from typing import Any, Dict, Optional, Tuple

import stripe
from config_store import load_runtime_config


def safe_get(obj: Any, key: str, default: Any = None) -> Any:
    """
    Safely read a field from either a dict-like object or a StripeObject-like object.
    This avoids a lot of `isinstance(x, dict)` branching across the codebase.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def normalize_report_timestamp(ts: Any) -> int:
    """
    Stripe rejects some timestamps if they are in the future.
    If ts > now, clamp it to (now - 10 seconds).

    Used for all timestamps passed to `payment_records.report_payment(...)` and `payment_records.report_refund(...)`.
    """
    now = int(time.time())
    try:
        v = int(ts)
    except Exception:
        v = now
    if v > now:
        return max(0, now - 10)
    return v


def get_account_env(alias: str) -> Tuple[str, str, str]:
    """
    Returns (account_id, secret_key, publishable_key) for an alias.
    Convention: STRIPE_ACCOUNT_<ALIAS>_*

    Note:
    - ALIAS is normalized to UPPERCASE
    - We deliberately fail fast if something is missing, to avoid silent misrouting.
    """
    a = (alias or "").strip().upper()
    cfg = load_runtime_config()
    accounts = cfg.get("accounts") if isinstance(cfg, dict) else None
    entry = (accounts or {}).get(a) if isinstance(accounts, dict) else None

    # Prefer runtime-config.json; fallback to env for backward compatibility
    account_id = (entry.get("account_id") if isinstance(entry, dict) else None) or ""
    secret_key = (entry.get("secret_key") if isinstance(entry, dict) else None) or ""
    publishable_key = (entry.get("publishable_key") if isinstance(entry, dict) else None) or ""

    if not account_id or not secret_key or not publishable_key:
        key_prefix = f"STRIPE_ACCOUNT_{a}_"
        account_id = account_id or (os.getenv(f"{key_prefix}ACCOUNT_ID", "") or "").strip()
        secret_key = secret_key or (os.getenv(f"{key_prefix}SECRET_KEY", "") or "").strip()
        publishable_key = publishable_key or (os.getenv(f"{key_prefix}PUBLISHABLE_KEY", "") or "").strip()

    missing = []
    if not account_id:
        missing.append(f"{key_prefix}ACCOUNT_ID")
    if not secret_key:
        missing.append(f"{key_prefix}SECRET_KEY")
    if not publishable_key:
        missing.append(f"{key_prefix}PUBLISHABLE_KEY")
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
    return account_id, secret_key, publishable_key


def get_account_country(alias: str) -> Optional[str]:
    """
    Optional UI hint (ISO 2-letter country code) for a given alias.
    Convention: STRIPE_ACCOUNT_<ALIAS>_COUNTRY (e.g. FR, US)
    """
    a = (alias or "").strip().upper()
    cfg = load_runtime_config()
    accounts = cfg.get("accounts") if isinstance(cfg, dict) else None
    entry = (accounts or {}).get(a) if isinstance(accounts, dict) else None
    v = (entry.get("country") if isinstance(entry, dict) else None) or ""
    if not v:
        key = f"STRIPE_ACCOUNT_{a}_COUNTRY"
        v = (os.getenv(key, "") or "").strip().upper()
    return (str(v).strip().upper() or None) if v is not None else None


def get_alias_by_account_id(account_id: str) -> str:
    """
    Best-effort reverse lookup: given a Stripe account id (acct_...), return the configured alias.
    Looks for STRIPE_ACCOUNT_<ALIAS>_ACCOUNT_ID in the environment.

    This is used when the webhook provides an account id (acct_...) and we need the corresponding secret key.
    """
    target = (account_id or "").strip()
    if not target:
        raise ValueError("Missing account_id for alias lookup")

    cfg = load_runtime_config()
    accounts = cfg.get("accounts") if isinstance(cfg, dict) else None
    if isinstance(accounts, dict):
        for alias, entry in accounts.items():
            if not isinstance(entry, dict):
                continue
            if (entry.get("account_id") or "").strip() == target:
                return (alias or "").strip().upper()

    # Fallback: env scan (backward compatible)
    for k, v in os.environ.items():
        if not k.startswith("STRIPE_ACCOUNT_") or not k.endswith("_ACCOUNT_ID"):
            continue
        if (v or "").strip() == target:
            mid = k[len("STRIPE_ACCOUNT_") : -len("_ACCOUNT_ID")]
            return (mid or "").strip().upper()

    raise ValueError(f"Unable to resolve alias for account_id={target} (missing runtime-config.json or STRIPE_ACCOUNT_<ALIAS>_ACCOUNT_ID?)")


def get_master_alias() -> str:
    """
    Master account alias: the account on which we create and maintain the "source-of-truth" objects.
    Default: EU.
    """
    cfg = load_runtime_config()
    v = (cfg.get("master_account_alias") if isinstance(cfg, dict) else None) or ""
    if not v:
        v = (os.getenv("STRIPE_MASTER_ACCOUNT_ALIAS", "EU") or "EU").strip()
    return str(v).strip().upper() or "EU"


def get_webhook_signing_secret(alias: str) -> str:
    """
    Returns the Stripe webhook signing secret for a given account alias.
    Convention: STRIPE_ACCOUNT_<ALIAS>_WEBHOOK_SIGNING_SECRET
    """
    a = (alias or "").strip().upper()
    if not a:
        raise ValueError("Missing webhook alias")

    cfg = load_runtime_config()
    accounts = cfg.get("accounts") if isinstance(cfg, dict) else None
    entry = (accounts or {}).get(a) if isinstance(accounts, dict) else None
    secret = (entry.get("webhook_signing_secret") if isinstance(entry, dict) else None) or ""

    if not secret:
        key = f"STRIPE_ACCOUNT_{a}_WEBHOOK_SIGNING_SECRET"
        secret = (os.getenv(key, "") or "").strip()
    if not secret:
        raise ValueError(f"Missing webhook signing secret for alias={a} (runtime-config.json or {key})")
    return str(secret).strip()


def get_master_custom_payment_method_type(processing_alias: str) -> str:
    """
    Returns the custom payment method type to use on the master account for a given processing account alias.
    Convention: STRIPE_MASTER_ACCOUNT_<PROCESSING_ALIAS>_CPM
    Example: processing_alias=US -> STRIPE_MASTER_ACCOUNT_US_CPM
    """
    a = (processing_alias or "").strip().upper()
    if not a:
        raise ValueError("Missing processing alias for CPM lookup")

    cfg = load_runtime_config()
    mpms = cfg.get("master_custom_payment_methods") if isinstance(cfg, dict) else None
    cpm = (mpms.get(a) if isinstance(mpms, dict) else None) or ""
    if not cpm:
        key = f"STRIPE_MASTER_ACCOUNT_{a}_CPM"
        cpm = (os.getenv(key, "") or "").strip()
    if not cpm:
        raise ValueError(f"Missing master CPM type for alias={a}")
    return str(cpm).strip()


def stripe_client(secret_key: str) -> stripe.StripeClient:
    # Using a per-request client avoids global state when handling multiple accounts.
    return stripe.StripeClient(secret_key)


def debug_dump(obj: Any, enabled_env: str = "WEBHOOK_DEBUG_DUMP_EVENT") -> None:
    """
    Print objects only when explicitly enabled (useful for debugging webhooks without flooding logs).
    Enable with: WEBHOOK_DEBUG_DUMP_EVENT=1
    """
    try:
        if (os.getenv(enabled_env, "0") or "0").strip() == "1":
            print(obj)
    except Exception:
        traceback.print_exc()


def get_runtime_bool(key: str, default: bool = True) -> bool:
    """
    Read a boolean feature flag from runtime-config.json.

    The config UI stores these flags at top-level (e.g. `skip_sync_non_master_invoice`).
    """
    try:
        cfg = load_runtime_config()
        if not isinstance(cfg, dict):
            return bool(default)
        v = cfg.get(key, default)
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        s = str(v).strip().lower()
        if s in ("1", "true", "yes", "y", "on"):
            return True
        if s in ("0", "false", "no", "n", "off", ""):
            return False
        return bool(default)
    except Exception:
        traceback.print_exc()
        return bool(default)


