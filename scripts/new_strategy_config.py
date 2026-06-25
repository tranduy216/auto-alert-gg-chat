"""New Strategy v3: 1d, ADX/RSI/volume optimized, multi-resistance entries"""

# ── Risk ──
BASE = 10000
MAX_COIN_EQ_PCT = 0.70
MAX_ENTRIES = 20
LEV = 2.0
ENTRY_SIZE = 0.035

# ── Entry MAs ──
MA5 = 5
MA10 = 10
MA15 = 15
MA20 = 20
MA25 = 25
MA100 = 100

# ── Entry filters ──
ADX_MIN = 20        # minimum ADX — avoid ultra-choppy
RSI_MIN = 30        # minimum RSI — not oversold
RSI_MAX = 65        # maximum RSI — was 55, raised to capture bull pullbacks
VOL_MIN_RATIO = 0.8 # minimum volume vs 20d avg (0.8 = 80%)
VOL_MAX_RATIO = 3.0 # max volume ratio (cap to avoid spike noise)

# ── Resistance levels (MA5 to MA25 step 5) ──
# Entry triggers when price crosses any level from below
RESISTANCE_LEVELS = [5, 10, 15, 20, 25]

# ── Exit ──
TP_60 = [(7, 0.15), (15, 0.15), (25, 0.15), (35, 0.15)]
SL = 25
TRAIL_ACT = 50
TRAIL_DIST = 0.09
TRAIL_CLOSE = 1.0
PEAK_DD = 18
