"""
Centralized Trading Configuration
All constants, profiles, and per-coin settings reference this file.

Imported by: crypto_trading.py, backtest_bull_snowball.py, backtest_fast.py
"""

# ── Coins ────────────────────────────────────────────────────────────
COINS = ["ETH", "BNB", "TRX"]
SYMBOL_MAP = {coin: f"{coin}USDT" for coin in COINS}

# ── Risk Management ──────────────────────────────────────────────────
BASE_CAPITAL = 10000
BASE = 10000  # alias
INITIAL = 75  # backtest lookback
MAX_POS_PCT = 0.65
MAX_MARGIN_PER_COIN_PCT = 0.20
FEE_RATE = 0.0005
SF = 2.0  # scale factor 12h → 24h

# ── Entry ────────────────────────────────────────────────────────────
ENTRY_MIN_SCORE = 65
ENTRY_MIN = 65  # alias
ENTRY_COOLDOWN_BARS = {"ETH": 3, "BNB": 1, "TRX": 1}

# Cooldown & Risk
FIB_MIN = 2
FIBONACCI_COOLDOWN_MIN = 2
SL_ROLLING_CAP = 3
SL_ROLLING_LOCK_BARS = 8
SL_ROLLING_FIB = True
SIDEWAY_MAX_SCORE = 2

# ── Take Profit Schedule (BEAR mode) ─────────────────────────────────
TP_SCHEDULE = [(8.0, 0.10), (15.0, 0.15), (25.0, 0.20), (40.0, 0.25)]
TP = TP_SCHEDULE  # alias for backtest

# ── Short Allowed ────────────────────────────────────────────────────
SHORT_ALLOWED = {"ETH", "TRX"}
SHORT_COINS = {"ETH", "TRX"}  # alias

# ── HYBRID Profiles (Bull & Bear per-coin) ───────────────────────────
PROFILES_BULL = {
    "ETH": {
        "lev": 3.5, "sl": 10, "pos_mult": 1.0, "trail": 0.11,
        "initial_exposure": 0.15,
        "snowball_levels": [0.10, 0.20, 0.30],
        "trail_activation": 0.30,
        "no_sl": True, "max_loss": 0.10,
    },
    "BNB": {
        "lev": 3.5, "sl": 40, "pos_mult": 1.2, "trail": 0.11,
        "initial_exposure": 0.22,
        "snowball_levels": [0.10, 0.20, 0.30],
        "trail_activation": 0.50,
        "no_sl": False, "max_loss": 0.40,
    },
    "TRX": {
        "lev": 3.5, "sl": 40, "pos_mult": 1.2, "trail": 0.11,
        "initial_exposure": 0.22,
        "snowball_levels": [0.10, 0.20, 0.30],
        "trail_activation": 0.35,
        "no_sl": False, "max_loss": 0.40,
    },
}

PROFILES_BEAR = {
    "ETH": {
        "lev": 3.0, "sl": 30, "pos_mult": 0.90, "trail": 0.17,
        "initial_exposure": 0.10, "snowball_levels": [], "trail_activation": 0.60,
    },
    "BNB": {
        "lev": 3.0, "sl": 30, "pos_mult": 0.75, "trail": 0.17,
        "initial_exposure": 0.10, "snowball_levels": [], "trail_activation": 0.60,
    },
    "TRX": {
        "lev": 3.0, "sl": 30, "pos_mult": 0.75, "trail": 0.17,
        "initial_exposure": 0.10, "snowball_levels": [], "trail_activation": 0.60,
    },
}

# ── BULL Snowball Strategy ───────────────────────────────────────────
BULL_SNOWBALL_LEVELS = [0.05, 0.10, 0.15, 0.20, 0.25]
BULL_SNOWBALL_SIZES = [0.06, 0.06, 0.06, 0.06, 0.06, 0.06]
BULL_INITIAL_SIZE = 0.08
BULL_TRAIL_DISTANCE = 0.11       # 11% from high
BULL_TRAIL_ACTIVATION = 0.40     # activate at 40% ROI
BULL_TRAIL_CLOSE = 0.40          # close 40% on trail trigger
BULL_TRAIL_COOLDOWN_BARS = 5     # cooldown after trail
BULL_NO_SL = True                # no stop loss for bull longs
BULL_MAX_LOSS = 0.10             # close if ROI drops -10%

# BTC Regime Override — stricter when BTC is bear
BTC_BEAR_OVERRIDE = {
    "adx_min": 20,
    "ma_buffer": 0.025,
    "bull_lev": 3.0,
    "max_loss": 0.25,
}

# ── Per-Coin Strategy Config ─────────────────────────────────────────
# Customize strategy behavior per coin
COIN_CONFIG = {
    "ETH": {
        "bull_mode": True,
        "bear_short": True,
        "adx_min": 12,
        "snowball_min_score": 65,
        "entry_score": 65,
    },
    "BNB": {
        "bull_mode": True,
        "bear_short": False,
        "adx_min": 15,
        "snowball_min_score": 65,
        "entry_score": 65,
        "ma_buffer": 0.01,
    },
    "TRX": {
        "bull_mode": True,
        "bear_short": False,
        "adx_min": 18,
        "snowball_min_score": 65,
        "entry_score": 65,
        "ma_buffer": 0.01,
    },
}

# ── Legacy helpers (used in production) ──────────────────────────────
def _coin_lev(coin: str) -> float:
    return {"ETH": 2.5, "BNB": 3.5, "TRX": 3.5}.get(coin, 3.0)

def _coin_sl_roi(coin: str) -> float:
    return {"ETH": 10, "BNB": 12, "TRX": 12}.get(coin, 12.0)

def _coin_trail(coin: str) -> float:
    return {"ETH": 0.04, "BNB": 0.065, "TRX": 0.065}.get(coin, 0.065)

def _coin_cap(coin: str) -> float:
    return {"ETH": 2.5, "BNB": 2.8, "TRX": 2.5}.get(coin, 2.8)

def get_profile(coin: str, is_bull: bool) -> dict:
    profiles = PROFILES_BULL if is_bull else PROFILES_BEAR
    return profiles.get(coin, profiles.get("ETH"))
