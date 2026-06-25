"""New Strategy: 1d trend-following with isolated entries, 2x lev"""

# ── Risk ──
BASE = 10000
MAX_COIN_EQ_PCT = 0.70   # max 70% equity per coin
MAX_ENTRIES = 10         # max concurrent entries per coin
LEV = 2.0
ENTRY_SIZE = 0.07        # 7% equity per entry (10 entries = 70% cap)

# ── Trend MAs (1d) ──
MA10 = 10
MA30 = 30
MA100 = 100
MA180 = 180

# ── Entry scores ──
BOUNCE_SCORE = 50   # bear bounce min score (0-100)
PULLBACK_SCORE = 60 # bull pullback min score

# ── Exit (isolated: each entry manages itself) ──
# Bull pullback TP schedule: close partial at each level
BULL_TP = [(5, 0.25), (10, 0.25), (15, 0.25), (20, 0.25)]  # 25% each at 5/10/15/20% ROI
BULL_SL = 8   # 8% ROI stop loss
BULL_TRAIL_ACT = 15  # trail activates at 15% ROI profit
BULL_TRAIL_DIST = 0.06  # 6% price trail distance
BULL_TRAIL_CLOSE = 0.50  # close 50% of remaining on trail

# Bear bounce TP: tighter targets (quick scalps)
BEAR_TP = [(3, 0.25), (6, 0.25), (9, 0.25), (12, 0.25)]
BEAR_SL = 5    # 5% ROI stop loss
BEAR_TRAIL_ACT = 10
BEAR_TRAIL_DIST = 0.04
BEAR_TRAIL_CLOSE = 0.50

# ── Score function params ──
# Bull pullback score: near MA support + RSI cooling + volume confirmation
# Bear bounce score: oversold + bullish rejection + volume spike

# ── Custom score thresholds (0-100 scale) ──
BOUNCE_SCORE_MIN = 30
PULLBACK_SCORE_MIN = 35
ENTRY_COOLDOWN_DAYS = 3

# ── Custom score thresholds (0-100 scale) ──
BOUNCE_SCORE_MIN = 30
PULLBACK_SCORE_MIN = 35
ENTRY_COOLDOWN_DAYS = 3
