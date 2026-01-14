import os
import time
import traceback
from typing import Any, Dict, Optional, Tuple

import stripe


def safe_get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def normalize_report_timestamp(ts: Any) -> int:
    """
    Stripe rejects some timestamps if they are in the future.
    If ts > now, clamp it to (now - 10 seconds).
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
    """
    a = (alias or "").strip().upper()
    key_prefix = f"STRIPE_ACCOUNT_{a}_"
    account_id = (os.getenv(f"{key_prefix}ACCOUNT_ID", "") or "").strip()
    secret_key = (os.getenv(f"{key_prefix}SECRET_KEY", "") or "").strip()
    publishable_key = (os.getenv(f"{key_prefix}PUBLISHABLE_KEY", "") or "").strip()

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
    key = f"STRIPE_ACCOUNT_{a}_COUNTRY"
    v = (os.getenv(key, "") or "").strip().upper()
    return v or None


def get_alias_by_account_id(account_id: str) -> str:
    """
    Best-effort reverse lookup: given a Stripe account id (acct_...), return the configured alias.
    Looks for STRIPE_ACCOUNT_<ALIAS>_ACCOUNT_ID in the environment.
    """
    target = (account_id or "").strip()
    if not target:
        raise ValueError("Missing account_id for alias lookup")
    for k, v in os.environ.items():
        if not k.startswith("STRIPE_ACCOUNT_") or not k.endswith("_ACCOUNT_ID"):
            continue
        if (v or "").strip() == target:
            # STRIPE_ACCOUNT_<ALIAS>_ACCOUNT_ID
            mid = k[len("STRIPE_ACCOUNT_") : -len("_ACCOUNT_ID")]
            return (mid or "").strip().upper()
    raise ValueError(f"Unable to resolve alias for account_id={target} (missing STRIPE_ACCOUNT_<ALIAS>_ACCOUNT_ID?)")


def get_master_alias() -> str:
    return (os.getenv("STRIPE_MASTER_ACCOUNT_ALIAS", "EU") or "EU").strip().upper()


def get_webhook_signing_secret(alias: str) -> str:
    """
    Returns the Stripe webhook signing secret for a given account alias.
    Convention: STRIPE_ACCOUNT_<ALIAS>_WEBHOOK_SIGNING_SECRET
    """
    a = (alias or "").strip().upper()
    if not a:
        raise ValueError("Missing webhook alias")
    key = f"STRIPE_ACCOUNT_{a}_WEBHOOK_SIGNING_SECRET"
    secret = (os.getenv(key, "") or "").strip()
    if not secret:
        raise ValueError(f"Missing environment variable: {key}")
    return secret


def get_master_custom_payment_method_type(processing_alias: str) -> str:
    """
    Returns the custom payment method type to use on the master account for a given processing account alias.
    Convention: STRIPE_MASTER_ACCOUNT_<PROCESSING_ALIAS>_CPM
    Example: processing_alias=US -> STRIPE_MASTER_ACCOUNT_US_CPM
    """
    a = (processing_alias or "").strip().upper()
    if not a:
        raise ValueError("Missing processing alias for CPM lookup")
    key = f"STRIPE_MASTER_ACCOUNT_{a}_CPM"
    cpm = (os.getenv(key, "") or "").strip()
    if not cpm:
        raise ValueError(f"Missing environment variable: {key}")
    return cpm


def stripe_client(secret_key: str) -> stripe.StripeClient:
    # Using a per-request client avoids global state when handling multiple accounts.
    return stripe.StripeClient(secret_key)


def debug_dump(obj: Any, enabled_env: str = "WEBHOOK_DEBUG_DUMP_EVENT") -> None:
    try:
        if (os.getenv(enabled_env, "0") or "0").strip() == "1":
            print(obj)
    except Exception:
        traceback.print_exc()


