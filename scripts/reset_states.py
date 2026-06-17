#!/usr/bin/env python3
"""One-time script to reset all Firestore states (trading + queued alerts)."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.firebase_utils import get_db, is_firebase_enabled

if not is_firebase_enabled():
    print("FIREBASE_SERVICE_ACCOUNT not set.")
    sys.exit(1)

db = get_db()

collections = ["crypto_trading_states", "queued_alerts"]
total = 0
for col in collections:
    docs = db.collection(col).stream()
    count = 0
    for doc in docs:
        doc.reference.delete()
        count += 1
    total += count
    print(f"Deleted {count} docs from {col}")

print(f"Total: {total} documents deleted.")
