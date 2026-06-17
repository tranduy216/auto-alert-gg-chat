"""Firebase / Firestore helpers for queuing and deduplication of alerts.

Two Firestore collections are used:
- ``queued_alerts``: alerts held during quiet hours (sent=False until flushed).
- ``sent_alert_hashes``: lightweight deduplication index (TTL ~6 h).
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from .retry_utils import call_with_retry

_db: Optional[Any] = None
_firebase_enabled: Optional[bool] = None


def is_firebase_enabled() -> bool:
    global _firebase_enabled
    if _firebase_enabled is None:
        _firebase_enabled = bool(os.environ.get("FIREBASE_SERVICE_ACCOUNT"))
        if not _firebase_enabled:
            print(
                "Warning: FIREBASE_SERVICE_ACCOUNT not set – Firebase queue disabled.",
                file=sys.stderr,
            )
    return _firebase_enabled


def get_db() -> Any:
    """Return an initialised Firestore client (lazy singleton)."""
    global _db
    if _db is None:
        import firebase_admin
        from firebase_admin import credentials, firestore  # type: ignore

        if not firebase_admin._apps:
            service_account_dict = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])
            cred = credentials.Certificate(service_account_dict)
            firebase_admin.initialize_app(cred)
        _db = firestore.client()
    return _db


# ---------------------------------------------------------------------------
# Alert queue (quiet-hours holding)
# ---------------------------------------------------------------------------

def queue_alert(alert: Dict[str, Any], queued_at_str: str) -> None:
    """Store an alert in Firestore to be sent after quiet hours end."""
    if not is_firebase_enabled():
        return
    db = get_db()
    call_with_retry(
        lambda: db.collection("queued_alerts").add(
            {
                "alert": alert,
                "queued_at_str": queued_at_str,
                "sent": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ),
        resource_name="Firestore queued_alerts.add",
    )


def get_unsent_queued_alerts() -> List[Dict[str, Any]]:
    """Return all unsent queued alerts, ordered by document id (insertion order)."""
    if not is_firebase_enabled():
        return []
    db = get_db()
    docs = call_with_retry(
        lambda: (
            db.collection("queued_alerts")
            .where("sent", "==", False)
            .stream()
        ),
        resource_name="Firestore queued_alerts.stream",
    )
    alerts = []
    for doc in docs:
        data = doc.to_dict()
        data["_doc_id"] = doc.id
        alerts.append(data)
    return alerts


def mark_alert_sent(doc_id: str) -> None:
    """Mark a queued alert document as sent."""
    if not is_firebase_enabled():
        return
    db = get_db()
    call_with_retry(
        lambda: db.collection("queued_alerts").document(doc_id).update({"sent": True}),
        resource_name="Firestore queued_alerts.update",
    )


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _alert_hash(alert: Dict[str, Any]) -> str:
    """Produce a short deterministic hash for an alert dict."""
    canonical = json.dumps(alert, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def was_recently_alerted(alert: Dict[str, Any], within_hours: int = 6) -> bool:
    """Return True if an identical alert was already sent within *within_hours*."""
    if not is_firebase_enabled():
        return False
    db = get_db()
    key = _alert_hash(alert)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)
    docs = call_with_retry(
        lambda: (
            db.collection("sent_alert_hashes")
            .where("hash", "==", key)
            .where("sent_at", ">=", cutoff)
            .limit(1)
            .stream()
        ),
        resource_name="Firestore sent_alert_hashes.stream",
    )
    return any(True for _ in docs)


def record_sent_alert(alert: Dict[str, Any]) -> None:
    """Record that an alert was sent (for deduplication)."""
    if not is_firebase_enabled():
        return
    from firebase_admin import firestore as _fs  # type: ignore

    db = get_db()
    call_with_retry(
        lambda: db.collection("sent_alert_hashes").add(
            {
                "hash": _alert_hash(alert),
                "sent_at": _fs.SERVER_TIMESTAMP,
            }
        ),
        resource_name="Firestore sent_alert_hashes.add",
    )
