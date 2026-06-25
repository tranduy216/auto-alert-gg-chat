"""New Strategy v4: 1.5x lev, Fibonacci MAs, pullback entries"""

# ── Risk ──
BASE = 10000
MAX_COIN_EQ_PCT = 0.70
MAX_ENTRIES = 20
LEV = 1.5
ENTRY_SIZE = 0.035       # 3.5% per entry (3.5% × 1.5x = 5.25% position)

# ── Entry MAs ──
MA5 = 5
MA8 = 8
MA13 = 13
MA21 = 21
MA50 = 50
MA100 = 100

# ── Entry filters ──
ADX_MIN = 20
RSI_MIN = 30
RSI_MAX = 65
VOL_MIN_RATIO = 0.8
VOL_MAX_RATIO = 3.0

# ── Resistance levels (Fibonacci MAs) ──
RESISTANCE_LEVELS = [5, 8, 13, 21]

# ── Resistance-based SL ──
# Each entry level maps to the next lower MA for SL placement
NEXT_LOWER_MA = {5: None, 8: 5, 13: 8, 21: 13, 50: 21, 100: 50}
SL_MA_BUF = 0.97  # SL at 97% of the next lower MA (3% buffer below it)
SL_FIXED_FALLBACK = 15  # fallback SL % if no lower MA (for MA5 entries)

# ── Exit ──
TP_60 = [(7, 0.15), (15, 0.15), (25, 0.15), (35, 0.15)]
SL = 25        # 25% ROI at 1.5x = 16.7% price move
TRAIL_ACT = 50
TRAIL_DIST = 0.09
TRAIL_CLOSE = 1.0
PEAK_DD = 18
