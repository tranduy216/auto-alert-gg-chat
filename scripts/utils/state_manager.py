"""Per-coin trading state — Firebase Firestore primary, local JSON fallback.

Collection: trading_state
Document:  {coin}  →  { last_entry_date, last_entry_price, entries_count, ... }
"""
import json, os, sys, datetime
from pathlib import Path
from typing import Any, Dict, Optional

LOCAL_FALLBACK = Path(__file__).parent.parent / '_trading_state.json'


def _get_db():
    """Return Firestore client or None."""
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        if not firebase_admin._apps:
            if not os.environ.get('FIREBASE_SERVICE_ACCOUNT'):
                return None
            svc = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
            firebase_admin.initialize_app(credentials.Certificate(svc))
        return firestore.client()
    except Exception:
        return None


def get_state(coin: str) -> Dict[str, Any]:
    """Return state dict for a coin, or empty dict."""
    db = _get_db()
    if db:
        try:
            doc = db.collection('trading_state').document(coin).get()
            if doc.exists:
                return doc.to_dict() or {}
        except Exception as e:
            print(f"[state_manager] Firestore get_state failed: {e}", file=sys.stderr)
    # Local fallback
    if LOCAL_FALLBACK.exists():
        try:
            all_state = json.loads(LOCAL_FALLBACK.read_text())
            return all_state.get(coin, {})
        except Exception:
            pass
    return {}


def set_state(coin: str, data: dict) -> None:
    """Set/update state fields for a coin."""
    db = _get_db()
    if db:
        try:
            db.collection('trading_state').document(coin).set(data, merge=True)
        except Exception as e:
            print(f"[state_manager] Firestore set_state failed: {e}", file=sys.stderr)
    # Local fallback
    try:
        all_state = {}
        if LOCAL_FALLBACK.exists():
            all_state = json.loads(LOCAL_FALLBACK.read_text())
        all_state[coin] = {**(all_state.get(coin, {})), **data}
        LOCAL_FALLBACK.write_text(json.dumps(all_state, indent=2, default=str))
    except Exception as e:
        print(f"[state_manager] local set_state failed: {e}", file=sys.stderr)


def has_entered_today(coin: str) -> bool:
    """Check if an entry was already executed for this coin today."""
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    state = get_state(coin)
    return state.get('last_entry_date') == today


def record_entry(coin: str, price: float) -> None:
    """Record a successful entry for today."""
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    set_state(coin, {
        'last_entry_date': today,
        'last_entry_price': price,
    })


def get_entries(coin: str) -> list:
    """Return list of open entry dicts: [{'ep': float, 'is_short': bool}, ...]"""
    state = get_state(coin)
    return state.get('entries', [])


def add_entry(coin: str, ep: float, is_short: bool) -> None:
    """Append a new entry to the coin's open entries list."""
    entries = get_entries(coin)
    entries.append({'ep': ep, 'is_short': is_short})
    set_state(coin, {'entries': entries})


def clear_entries(coin: str) -> None:
    """Clear all open entries for a coin (position fully closed)."""
    set_state(coin, {'entries': []})
