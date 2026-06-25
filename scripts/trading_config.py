"""
Centralized Trading Configuration
All constants, profiles, and per-coin settings reference this file.
"""

COINS = ["ETH", "TRX"]
SYMBOL_MAP = {coin: f"{coin}USDT" for coin in COINS}

BASE = 10000
INITIAL = 75
MAX_POS_PCT = 1.20
MAX_MARGIN_PER_COIN_PCT = 0.20
MAX_ENTRIES_PER_COIN = 5    # max active entries per coin across all modes
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
    "ETH": {"lev": 3.5, "sl": 10, "pos_mult": 1.3, "trail": 0.11, "initial_exposure": 0.08,
            "trail_activation": 0.25, "no_sl": True, "max_loss": 0.10},
    "BNB": {"lev": 3.5, "sl": 20, "pos_mult": 1.3, "trail": 0.11, "initial_exposure": 0.25,
            "trail_activation": 0.30, "no_sl": False, "max_loss": 0.20},
    "TRX": {"lev": 3.5, "sl": 12, "pos_mult": 1.3, "trail": 0.11, "initial_exposure": 0.25,
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

BULL_SNOWBALL_LEVELS = [0.05, 0.10, 0.15]
BULL_SNOWBALL_SIZES = [0.06, 0.06, 0.06, 0.06]
BULL_INITIAL_SIZE = 0.08   # 8% equity per entry
BULL_TRAIL_DISTANCE = 0.11
BULL_TRAIL_ACTIVATION = 0.40
BULL_TRAIL_CLOSE = 0.60
BULL_TRAIL_COOLDOWN_BARS = 5
BULL_NO_SL = True
BULL_MAX_LOSS = 0.10

# Staggered partial TP before trail (ROI%, close_fraction)
BULL_TP_SCHEDULE = [(10, 0.10), (20, 0.10), (30, 0.10)]

# BTC bear override (only for BNB in BTC bear)
BTC_BEAR_OVERRIDE = {"adx_min": 20, "ma_buffer": 0.025, "bull_lev": 3.0, "max_loss": 0.25}

# BNB/TRX bounce: MA confirmation buffer before entering
BNB_BOUNCE_MA_BUF = 0.018   # 1.8%
TRX_BOUNCE_MA_BUF = 0.018   # 1.8%

# Safe isolated: used when BTC trend confidence < 70% (ADX < threshold)
SAFE_LEV        = 1.5
SAFE_SL         = 6.75    # 1.5x × 4.5% price = 6.75% ROI stop
SAFE_ENTRY      = 0.035   # 3.5% equity including margin
SAFE_TP         = [(3, 0.10), (5, 0.20), (8, 0.25), (12, 0.25), (20, 0.20)]  # 80% at 3-12%, max 20%
SAFE_PEAK_DD    = 2.8     # close remaining if ROI drops 2.8% from peak
SAFE_ENTRY_SCORE = 75
SAFE_MA_BUF     = 0.02    # MA50 > MA120 * 1.02 to confirm trend
BTC_ADX_SAFE    = 22      # BTC ADX < 22 → safe mode for all coins

# Aggressive bear short: snowball + trailing like long, in BTC strong bear
BEAR_SHORT_LEV      = 3.5
BEAR_SHORT_SL       = 12
BEAR_SHORT_SNOWBALL = True
BEAR_SHORT_SCORE    = 70      # strong signal required for bear short snowball
BEAR_SHORT_MAX_LOSS = 0.10    # 10% ROI loss limit

# Safe short: isolated 2x for BTC bear
SAFE_SHORT_LEV      = 2.0
SAFE_SHORT_SL       = 9.0    # 2x × 4.5% price = 9% ROI stop
SAFE_SHORT_ENTRY    = 0.035   # 3.5% equity per entry
SAFE_SHORT_SCORE    = 1       # any signal fires
SAFE_SHORT_TP       = [(3, 0.20), (6, 0.30), (9, 0.30), (12, 0.20)]  # 100% at 3-12%
SAFE_SHORT_PEAK_DD  = 2.5     # close remaining if profit drops 2.5% from peak

# Bounce: 3 same-sized entries, 80% TP 4→16%, peak DD 7%, 20% trails at 8% ROI
BOUNCE_ENTRY_SIZE = 0.06   # 6% equity per entry
BOUNCE_MAX_ENTRIES = 3
BOUNCE_SNOWBALL_LEVELS = [0.05, 0.10]
BOUNCE_SNOWBALL_SIZES = [0.09, 0.09, 0.09]
BOUNCE_MIN_SCORE = 85    # really strong signal required

BOUNCE_TP  = [(4, 0.50), (8, 0.30), (12, 0.25), (16, 0.20)]  # ~80% closed by 16% ROI
BOUNCE_SL  = 9.0   # 2.0x × 4.5% price = 9% ROI stop
BOUNCE_PEAK_DD = 7.0
BOUNCE_TRAIL_DISTANCE = 0.032  # 3.2% price trail — at 2.0x = 6.4% ROI
BOUNCE_TRAIL_CLOSE = 1.0
BOUNCE_TRAIL_ACTIVATION = 0

# Per-coin bounce overrides
COIN_BOUNCE_LEV = {}  # default 2.0
COIN_BOUNCE_ENTRY_SIZE = {}
COIN_BOUNCE_TRAIL_ACTIVATION = {"TRX": 10}   # per-coin trail activation ROI% for bounce (0 = after all TPs)
COIN_MAX_MARGIN = {}

# Per-coin bull sizing (default BULL_INITIAL_SIZE / BULL_SNOWBALL_SIZES)
COIN_BULL_INITIAL_SIZE = {}
COIN_BULL_SNOWBALL_SIZES = {}

# Per-coin bull SL and peak DD (% ROI)
COIN_BULL_SL = {}  # stop loss % for bull mode (0 = use BULL_MAX_LOSS)
COIN_BULL_PEAK_DD = {}  # peak DD % for bull mode (0 = disabled)

# Per-coin peak DD (applies to bounce; BOUNCE_PEAK_DD used as fallback)
COIN_PEAK_DD = {"ETH": 3.5, "BNB": 7.0, "TRX": 7.0}

COIN_CONFIG = {
    "ETH": {"bull_mode": True, "bear_short": True, "adx_min": 12, "snowball_min_score": 65, "entry_score": 65},
    "BNB": {"bull_mode": True, "bear_short": False, "adx_min": 15, "snowball_min_score": 65, "entry_score": 65, "ma_buffer": 0.01},
    "TRX": {"bull_mode": True, "bear_short": False, "adx_min": 20, "snowball_min_score": 65, "entry_score": 65, "ma_buffer": 0.01},
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
