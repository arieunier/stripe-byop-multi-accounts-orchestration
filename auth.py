"""
auth.py

Very small HTTP Basic Auth helper for admin pages/APIs.

We intentionally keep it dependency-free (no Flask-Login) to keep the demo lightweight.
Credentials are configured via .env (loaded at app startup).
"""

import base64
import os
from functools import wraps
from typing import Callable, TypeVar

from flask import Response, request

F = TypeVar("F", bound=Callable[..., object])


def _unauthorized() -> Response:
    # Basic Auth challenge
    return Response("Unauthorized", 401, {"WWW-Authenticate": 'Basic realm="BYOP Config"'})


def requires_basic_auth(fn: F) -> F:
    """
    Flask decorator enforcing HTTP Basic Auth.

    Env vars:
    - ADMIN_PASSWORD (required)
    - ADMIN_USERNAME (optional, default: "admin")
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):  # type: ignore[misc]
        expected_user = (os.getenv("ADMIN_USERNAME", "admin") or "admin").strip()
        expected_pass = (os.getenv("ADMIN_PASSWORD", "") or "").strip()
        if not expected_pass:
            # Misconfiguration: do not allow access if credentials aren't set.
            return _unauthorized()

        header = request.headers.get("Authorization", "") or ""
        if not header.startswith("Basic "):
            return _unauthorized()

        try:
            raw = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
            user, pwd = raw.split(":", 1)
        except Exception:
            return _unauthorized()

        if user != expected_user or pwd != expected_pass:
            return _unauthorized()

        return fn(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


