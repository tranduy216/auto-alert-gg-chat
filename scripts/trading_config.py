"""
Centralized Trading Configuration
All constants, profiles, and per-coin settings reference this file.
"""

COINS = ["ETH", "BNB", "TRX"]
SYMBOL_MAP = {coin: f"{coin}USDT" for coin in COINS}

BASE = 10000
INITIAL = 75
MAX_POS_PCT = 1.20
MAX_MARGIN_PER_COIN_PCT = 0.20
FEE_RATE = 0.0005
SF = 2.0

ENTRY_MIN_SCORE = 65
ENTRY_COOLDOWN_BARS = {"ETH": 3, "BNB": 1, "TRX": 1}

FIB_MIN = 2
FIBONACCI_COOLDOWN_MIN = 2
SL_ROLLING_CAP = 3
SL_ROLLING_LOCK_BARS = 8
SL_ROLLING_FIB = True
SIDEWAY_MAX_SCORE = 2

TP_SCHEDULE = [(8.0, 0.10), (15.0, 0.15), (25.0, 0.20), (40.0, 0.25)]

SHORT_ALLOWED = {"ETH", "TRX"}

PROFILES_BULL = {
    "ETH": {"lev": 3.5, "sl": 10, "pos_mult": 0.8, "trail": 0.11, "initial_exposure": 0.08,
            "trail_activation": 0.30, "no_sl": True, "max_loss": 0.05},
    "BNB": {"lev": 3.5, "sl": 20, "pos_mult": 1.2, "trail": 0.11, "initial_exposure": 0.25,
            "trail_activation": 0.30, "no_sl": False, "max_loss": 0.20},
    "TRX": {"lev": 3.5, "sl": 12, "pos_mult": 1.2, "trail": 0.11, "initial_exposure": 0.25,
            "trail_activation": 0.30, "no_sl": False, "max_loss": 0.12},
}

PROFILES_BEAR = {
    "ETH": {"lev": 3.0, "sl": 30, "pos_mult": 0.90, "trail": 0.17, "initial_exposure": 0.10,
            "trail_activation": 0.60},
    "BNB": {"lev": 3.0, "sl": 30, "pos_mult": 0.75, "trail": 0.17, "initial_exposure": 0.10,
            "trail_activation": 0.60},
    "TRX": {"lev": 3.0, "sl": 30, "pos_mult": 0.75, "trail": 0.17, "initial_exposure": 0.10,
            "trail_activation": 0.60},
}

BULL_SNOWBALL_LEVELS = [0.05, 0.10, 0.15, 0.20]
BULL_SNOWBALL_SIZES = [0.07, 0.07, 0.07, 0.07, 0.07]
BULL_INITIAL_SIZE = 0.10
BULL_TRAIL_DISTANCE = 0.11
BULL_TRAIL_ACTIVATION = 0.40
BULL_TRAIL_CLOSE = 0.50
BULL_TRAIL_COOLDOWN_BARS = 5
BULL_NO_SL = True
BULL_MAX_LOSS = 0.10

# BTC bear override (only for BNB in BTC bear)
BTC_BEAR_OVERRIDE = {"adx_min": 20, "ma_buffer": 0.025, "bull_lev": 3.0, "max_loss": 0.25}

# Counter-trend (BNB only): long in BTC bear
CT_LEVERAGE = 2.0
CT_STOP_LOSS = 9
CT_TP_SCHEDULE = [(7, 0.10), (15, 0.15), (25, 0.20), (40, 0.25)]  # staggered TP 70%
CT_TRAIL = 0.07
CT_ENTRY_SCORE = 75

COIN_CONFIG = {
    "ETH": {"bull_mode": True, "bear_short": True, "adx_min": 12, "snowball_min_score": 60, "entry_score": 65},
    "BNB": {"bull_mode": True, "bear_short": False, "adx_min": 15, "snowball_min_score": 65, "entry_score": 65, "ma_buffer": 0.01},
    "TRX": {"bull_mode": True, "bear_short": False, "adx_min": 18, "snowball_min_score": 65, "entry_score": 65, "ma_buffer": 0.01},
}

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
