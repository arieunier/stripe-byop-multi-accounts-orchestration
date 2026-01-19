"""
webhook_monitor.py

In-memory webhook event broadcaster for the "Webhook monitoring" page.

Requirements:
- No persistence (no DB, no filesystem): events are pushed only to currently connected clients.
- Browser refresh / page leave should lose history: the frontend keeps the list in memory.
- Server-Sent Events (SSE): Flask streams JSON events to clients.
"""

from __future__ import annotations

import json
import queue
import threading
from typing import Any, Dict, Iterable, Optional


class WebhookEventHub:
    """
    Thread-safe fan-out hub.

    Each SSE client gets its own Queue (bounded). Publishing tries to push to all queues without blocking.
    If a client is slow and its queue is full, events are dropped for that client (best-effort monitoring).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: set[queue.Queue[str]] = set()

    def subscribe(self, max_queue_size: int = 200) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue(maxsize=max_queue_size)
        with self._lock:
            self._clients.add(q)
        return q

    def unsubscribe(self, q: queue.Queue[str]) -> None:
        with self._lock:
            self._clients.discard(q)

    def publish(self, payload: Dict[str, Any]) -> None:
        msg = json.dumps(payload, separators=(",", ":"))
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(msg)
            except Exception:
                # If queue is full or client is misbehaving, drop silently.
                # Monitoring is best-effort and must never block webhook handling.
                continue


