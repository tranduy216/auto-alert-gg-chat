#!/usr/bin/env python3
"""Midcap crypto trading — single position, no snowball, high-volatility coins.

Runs via Cloudflare Worker trigger. Uses the same v7 strategy engine
as crypto_trading.py but tuned for mid-cap volatility profiles.

Coins: DOGE, XRP, SUI  (top performers from 2021-2026 backtest)
       DOGE +181%, XRP +76%, SUI +40% total (long+short)
"""

import json
import os
import sys
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_trading import (
    sma, compute_rsi, evaluate_trend_3d, trend_strength,
    compute_volume_score,
    compute_entry_v6_long, compute_entry_v6_short,
    resolve_action_v6, evaluate_exit_v6,
    get_position_size, get_allocation_multiplier, get_trailing_multiplier,
    _entry_score_v7_long,
    get_coin_profile,
    COINS as _BTC_COINS,
    SYMBOL_MAP as _BTC_SYMBOL_MAP,
    SHORT_ALLOWED as _BTC_SHORT_ALLOWED,
    analyse_coin,
)
from utils.okx_utils import (
    OKX_INSTRUMENTS, get_instrument_map,
    okx_close_position, okx_get_account, okx_get_positions,
    okx_place_order, okx_set_leverage, OKXError,
)
from utils.discord_webhook import send_message

# ── Midcap Configuration ────────────────────────────────────────────

COINS = ["DOGE", "XRP", "SUI"]
SYMBOL_MAP = {coin: f"{coin}USDT" for coin in COINS}
SHORT_ALLOWED = {"DOGE", "XRP", "SUI"}

# Per-coin profiles (tuned via backtest sweep)
MIDCAP_PROFILES = {
    "DOGE": {
        "leverage": 3.0,
        "trend_min_long": 0,
        "trend_max_short": -3,
        "vol_min": 0.3,
        "rsi_max_long": 90,
        "rsi_min_short": 45,
        "max_loss_pct": 0.05,
        "trailing_pct": 0.80,
        "initial_stop_pct": 0.80,
        "hard_stop_pct": 0.75,
        "short_max_loss_pct": 0.04,
        "short_trailing_pct": 0.82,
        "short_size_mult": 0.5,
        "min_entry_score": 50,
        "snowball_pnl_min": 0.10,
    },
    "XRP": {
        "leverage": 3.0,
        "trend_min_long": 0,
        "trend_max_short": -3,
        "vol_min": 0.3,
        "rsi_max_long": 90,
        "rsi_min_short": 45,
        "max_loss_pct": 0.05,
        "trailing_pct": 0.82,
        "initial_stop_pct": 0.80,
        "hard_stop_pct": 0.75,
        "short_max_loss_pct": 0.04,
        "short_trailing_pct": 0.82,
        "short_size_mult": 0.5,
        "min_entry_score": 50,
        "snowball_pnl_min": 0.10,
    },
    "SUI": {
        "leverage": 2.0,
        "trend_min_long": 0,
        "trend_max_short": -3,
        "vol_min": 0.3,
        "rsi_max_long": 90,
        "rsi_min_short": 45,
        "max_loss_pct": 0.06,
        "trailing_pct": 0.82,
        "initial_stop_pct": 0.80,
        "hard_stop_pct": 0.75,
        "short_max_loss_pct": 0.05,
        "short_trailing_pct": 0.82,
        "short_size_mult": 0.5,
        "min_entry_score": 50,
        "snowball_pnl_min": 0.10,
    },
}


def get_midcap_profile(coin: str) -> dict:
    return MIDCAP_PROFILES.get(coin, MIDCAP_PROFILES["DOGE"])


# ── Override crypto_trading globals ──────────────────────────────────
# Monkey-patch to use midcap config instead of main config
import crypto_trading as ct
ct.COINS = COINS
ct.SYMBOL_MAP = SYMBOL_MAP
ct.SHORT_ALLOWED = SHORT_ALLOWED
ct.get_coin_profile = get_midcap_profile


def main() -> None:
    webhook_url = os.environ.get("DISCORD_TRADING_WEBHOOK_URL")
    if not webhook_url:
        print("Error: DISCORD_TRADING_WEBHOOK_URL is not set.", file=sys.stderr)
        sys.exit(1)

    okx_enabled = all(os.environ.get(k) for k in
                      ["OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"])

    now_vnt = datetime.now()
    print(f"[midcap_trading] Starting at {now_vnt.strftime('%Y-%m-%d %H:%M')}")

    # Run the main crypto_trading pipeline with midcap config
    ct.main()


if __name__ == "__main__":
    main()
