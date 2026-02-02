"""
config_store.py

File-backed configuration store for "live edit" environments.

We store:
- runtime Stripe config (accounts, secrets, webhook secrets, CPM types) in `config/runtime-config.json`
- product catalog in `config/catalog.json`

Writes are atomic (write temp file + rename) and protected by an in-process lock.
"""

import json
import os
import threading
from typing import Any, Dict, Optional

_lock = threading.Lock()

ROOT_DIR = os.path.dirname(__file__)
RUNTIME_CONFIG_PATH = os.path.join(ROOT_DIR, "config", "runtime-config.json")
CATALOG_PATH = os.path.join(ROOT_DIR, "config", "catalog.json")

# Simple cache (mtime-based)
_runtime_cache: Optional[Dict[str, Any]] = None
_runtime_mtime: Optional[float] = None


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


def _default_runtime_config() -> Dict[str, Any]:
    # Feature flags are intentionally stored in runtime-config.json so they can be toggled live from /config.
    return {
        "master_account_alias": "EU",
        "accounts": {},
        "master_custom_payment_methods": {},
        # If true, when processing != master we tag Subscription + Master Invoice with metadata.SKIP_NS_INVOICE_SYNC="true".
        "skip_sync_non_master_invoice": True,
        # If true, Scenario #1 propagates master invoice tax details to a processing send_invoice invoice.
        "propagate_tax_to_processing": True,
    }


def _build_runtime_from_env() -> Dict[str, Any]:
    """
    Bootstrap config from .env-style variables if runtime-config.json does not exist yet.
    This keeps backward compatibility for first run, while allowing live edits afterwards.
    """
    master_alias = (os.getenv("STRIPE_MASTER_ACCOUNT_ALIAS", "EU") or "EU").strip().upper()
    cfg: Dict[str, Any] = {
        "master_account_alias": master_alias,
        "accounts": {},
        "master_custom_payment_methods": {},
        "skip_sync_non_master_invoice": True,
        "propagate_tax_to_processing": True,
    }

    # Accounts: scan env for STRIPE_ACCOUNT_<ALIAS>_ACCOUNT_ID
    for k, v in os.environ.items():
        if not k.startswith("STRIPE_ACCOUNT_") or not k.endswith("_ACCOUNT_ID"):
            continue
        alias = k[len("STRIPE_ACCOUNT_") : -len("_ACCOUNT_ID")].strip().upper()
        if not alias:
            continue
        account_id = (v or "").strip()
        secret_key = (os.getenv(f"STRIPE_ACCOUNT_{alias}_SECRET_KEY", "") or "").strip()
        publishable_key = (os.getenv(f"STRIPE_ACCOUNT_{alias}_PUBLISHABLE_KEY", "") or "").strip()
        webhook_secret = (os.getenv(f"STRIPE_ACCOUNT_{alias}_WEBHOOK_SIGNING_SECRET", "") or "").strip()
        country = (os.getenv(f"STRIPE_ACCOUNT_{alias}_COUNTRY", "") or "").strip().upper() or None

        cfg["accounts"][alias] = {
            "account_id": account_id,
            "secret_key": secret_key,
            "publishable_key": publishable_key,
            "webhook_signing_secret": webhook_secret,
            "country": country,
        }

    # CPM mapping: STRIPE_MASTER_ACCOUNT_<ALIAS>_CPM
    for k, v in os.environ.items():
        if not k.startswith("STRIPE_MASTER_ACCOUNT_") or not k.endswith("_CPM"):
            continue
        # STRIPE_MASTER_ACCOUNT_<ALIAS>_CPM
        alias = k[len("STRIPE_MASTER_ACCOUNT_") : -len("_CPM")].strip().upper()
        if alias:
            cfg["master_custom_payment_methods"][alias] = (v or "").strip()

    return cfg


def load_runtime_config(force_reload: bool = False) -> Dict[str, Any]:
    """
    Load runtime Stripe configuration.
    - If runtime-config.json exists: load it (with mtime-based caching)
    - Else: build from env vars (backward compatible)
    """
    global _runtime_cache, _runtime_mtime

    with _lock:
        if os.path.exists(RUNTIME_CONFIG_PATH):
            mtime = os.path.getmtime(RUNTIME_CONFIG_PATH)
            if not force_reload and _runtime_cache is not None and _runtime_mtime == mtime:
                return _runtime_cache
            with open(RUNTIME_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            # Ensure new keys exist with sane defaults (do not force a write).
            defaults = _default_runtime_config()
            if isinstance(data, dict):
                for k, v in defaults.items():
                    if k not in data:
                        data[k] = v
            _runtime_cache = data
            _runtime_mtime = mtime
            return data

        # No runtime file yet: fallback to env
        data = _build_runtime_from_env()
        defaults = _default_runtime_config()
        if isinstance(data, dict):
            for k, v in defaults.items():
                if k not in data:
                    data[k] = v
        _runtime_cache = data
        _runtime_mtime = None
        return data


def save_runtime_config(data: Dict[str, Any]) -> None:
    """
    Persist runtime config to runtime-config.json.
    This also refreshes the in-process cache.
    """
    global _runtime_cache, _runtime_mtime
    with _lock:
        os.makedirs(os.path.dirname(RUNTIME_CONFIG_PATH), exist_ok=True)
        _atomic_write_json(RUNTIME_CONFIG_PATH, data)
        _runtime_cache = data
        _runtime_mtime = os.path.getmtime(RUNTIME_CONFIG_PATH)


def load_catalog() -> Dict[str, Any]:
    """Load the product catalog JSON (config/catalog.json)."""
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f) or {}


def save_catalog(data: Dict[str, Any]) -> None:
    """Persist the catalog JSON (config/catalog.json)."""
    with _lock:
        os.makedirs(os.path.dirname(CATALOG_PATH), exist_ok=True)
        _atomic_write_json(CATALOG_PATH, data)


