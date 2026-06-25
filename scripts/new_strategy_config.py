"""New Strategy v2: 1d, limit entry near MA5-MA25 zone, 2x lev"""

# ── Risk ──
BASE = 10000
MAX_COIN_EQ_PCT = 0.70   # max 70% equity deployed per coin
MAX_ENTRIES = 20         # max concurrent entries
LEV = 2.0
ENTRY_SIZE = 0.035       # 3.5% original capital per entry (20 entries × 3.5% = 70%)

# ── Entry MAs ──
MA5 = 5
MA25 = 25
MA100 = 100

# ── Entry conditions ──
# Buy when: price > MA5 (short-term up) AND price < MA25 (pullback)
# At strong resistance: the MA25 acts as resistance, buying below it

# ── Exit ──
# 60% of position: staged TP from 7% to 50% ROI
TP_60 = [(7, 0.15), (15, 0.15), (25, 0.15), (35, 0.15)]  # 60% total
# 40% of position: trailing after all TPs
SL = 25        # 25% ROI stop loss
TRAIL_ACT = 50  # trail activates at 50% ROI (after TPs finish)
TRAIL_DIST = 0.09  # 9% price trail = 18% ROI at 2x
TRAIL_CLOSE = 1.0  # close all remaining on trail hit
PEAK_DD = 18   # 18% ROI peak drawdown — close remaining if profit drops 18% from peak
