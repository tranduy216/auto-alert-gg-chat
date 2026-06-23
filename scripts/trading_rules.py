"""
Unified Trading Rules — single source of truth for ALL trading logic.
Imported by both backtest_bull_snowball.py (backtest) and crypto_trading.py (production).

All mode detection, entry rule selection, and exit logic lives here.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_config import *

# ═══════════════════════════════════════════════
# MODE DETECTION
# ═══════════════════════════════════════════════

def detect_btc_safe(btc_adx: float) -> bool:
    """BTC trend confidence: ADX < threshold → weak trend → safe mode"""
    return btc_adx < BTC_ADX_SAFE

def detect_bear_short(btc_safe: bool, btc_bull: bool, coin: str) -> bool:
    """Aggressive bear short: only ETH, strong BTC bear (ADX≥22)"""
    return not btc_safe and not btc_bull and coin == "ETH" and BEAR_SHORT_SNOWBALL

def detect_bounce(coin: str, btc_bull: bool) -> bool:
    """All coins: defensive long in BTC bear (2x, fixed TP, peak DD)"""
    return coin in ("ETH", "BNB", "TRX") and not btc_bull

# ═══════════════════════════════════════════════
# ENTRY RULE SELECTION
# ═══════════════════════════════════════════════

def get_entry_rule(
    btc_safe: bool, bear_short: bool, bounce: bool,
    is_bull: bool, is_sh: bool, sc: float,
):
    """
    Returns (mp, lev, sl, bull_mode, safe_flag, bounce_flag, short_flag)
    Matching the backtest's entry priority system.
    Priority order:
    1. Safe mode (btc_safe) → for longs, weak trend, score ≥ 75
    2. Aggressive bear short (bear_short and is_sh)
    3. Bounce (bounce and not is_sh)
    4. Bull (is_bull and not is_sh)
    5. Default (bear mode)
    """
    # Default values
    mp = 0; lev = 3.5; sl = 12
    bull_mode = False; safe_flag = False; bounce_flag = False; short_flag = False

    if btc_safe and not is_sh and not bear_short:
        # Safe mode: 1.5x isolated
        if sc < SAFE_ENTRY_SCORE: mp = 0
        else: mp = SAFE_ENTRY
        lev = SAFE_LEV; sl = SAFE_SL
        safe_flag = True

    elif bear_short and is_sh:
        # Aggressive bear short: 3.5x snowball
        mp = BULL_INITIAL_SIZE; lev = BEAR_SHORT_LEV; sl = BEAR_SHORT_SL
        short_flag = True

    elif bounce and not is_sh:
        # Bounce: defensive long in BTC bear (2x, fixed TP, peak DD)
        mp = 0.10 * 0.70; lev = 2.0; sl = 7
        bounce_flag = True

    elif is_bull and not is_sh:
        # Bull mode: 3.5x snowball
        mp = BULL_INITIAL_SIZE; lev = 3.5; sl = 12
        bull_mode = True

    else:
        # Bear mode / default
        pass  # mp/lev/sl will be set by caller

    return mp, lev, sl, bull_mode, safe_flag, bounce_flag, short_flag


# ═══════════════════════════════════════════════
# EXIT LOGIC
# ═══════════════════════════════════════════════

def process_bull_exit(
    roi: float, pnl_from_entry: float, tstop: float, hi: float, cc: float,
    tp_s: int, rem: float, is_sh: bool,
    max_loss: float, trail_cd_remaining: bool
) -> dict:
    """
    BULL mode exit: staggered TP + trail + regime exit.
    Returns dict with exit_actions, new_rem, removed, new_tp_s, new_tstop.
    """
    result = {'removed': False, 'rem': rem, 'tp': tp_s, 'tstop': tstop,
              'exits': [], 'trail_cd_set': False}

    # 1. Max loss safety
    if roi <= -max_loss * 100:
        result['removed'] = True
        result['exits'].append('MAX_LOSS')
        return result

    # 2. Staggered TP
    if tp_s < len(BULL_TP_SCHEDULE):
        trg, cf_pct = BULL_TP_SCHEDULE[tp_s]
        if roi >= trg:
            cf = cf_pct * rem
            result['rem'] = rem - cf
            result['tp'] = tp_s + 1
            result['exits'].append(f'TP@{trg}%')
            if result['rem'] <= 0.001:
                result['removed'] = True
                return result

    # 3. Trail (only after all staggered TPs)
    if tp_s >= len(BULL_TP_SCHEDULE) and not trail_cd_remaining:
        if pnl_from_entry >= BULL_TRAIL_ACTIVATION:
            nt = max(tstop or cc * (1 - BULL_TRAIL_DISTANCE),
                     hi * (1 - BULL_TRAIL_DISTANCE))
            if cc <= nt if not is_sh else cc >= nt:
                cf = BULL_TRAIL_CLOSE * rem
                result['rem'] = rem - cf
                result['tstop'] = cc * (1 - BULL_TRAIL_DISTANCE)
                result['trail_cd_set'] = True
                result['exits'].append('TRAIL')
                if result['rem'] <= 0.001:
                    result['removed'] = True
                    return result

    return result


def process_safe_exit(
    roi: float, peak_roi: float, rem: float, is_sh: bool,
    tp_s: int, tp_schedule: list, dd_threshold: float, sl: float
) -> dict:
    """
    Safe mode exit: SL + staggered TP + peak DD.
    """
    result = {'removed': False, 'rem': rem, 'tp': tp_s,
              'peak_roi': max(peak_roi, roi), 'exits': []}

    # 1. SL
    if roi <= -sl:
        result['removed'] = True
        result['exits'].append('SL')
        return result

    # 2. Staggered TP
    if tp_s < len(tp_schedule):
        trg, cf_pct = tp_schedule[tp_s]
        if roi >= trg:
            cf = cf_pct * rem
            result['rem'] = rem - cf
            result['tp'] = tp_s + 1
            result['peak_roi'] = roi  # reset peak after TP
            result['exits'].append(f'SAFE_TP@{trg}%')
            if result['rem'] <= 0.001:
                result['removed'] = True
                return result

    # 3. Peak DD (close all if ROI drops dd_threshold from peak)
    if roi <= result['peak_roi'] - dd_threshold:
        result['removed'] = True
        result['exits'].append('PEAK_DD')

    return result


def process_bounce_exit(
    roi: float, peak_roi: float, rem: float, tp_s: int, sl: float,
    tp_schedule: list = None, peak_dd: float = None,
) -> dict:
    """
    Bounce exit: SL + per-coin staggered TP + per-coin peak DD, no trail.
    Uses COIN_BOUNCE_TP / COIN_PEAK_DD per coin if available.
    """
    if tp_schedule is None:
        tp_schedule = BOUNCE_TP
    if peak_dd is None:
        peak_dd = BOUNCE_PEAK_DD

    result = {'removed': False, 'rem': rem, 'tp': tp_s,
              'peak_roi': max(peak_roi, roi), 'exits': []}

    if roi <= -sl:
        result['removed'] = True
        result['exits'].append('SL')
        return result

    # Staggered TP
    if tp_s < len(tp_schedule):
        trg, cf_pct = tp_schedule[tp_s]
        if roi >= trg:
            cf = cf_pct * rem
            result['rem'] = rem - cf
            result['tp'] = tp_s + 1
            result['peak_roi'] = roi
            result['exits'].append(f'BOUNCE_TP@{trg}%')
            if result['rem'] <= 0.001:
                result['removed'] = True
                return result

    # Peak DD: close remaining if roi drops from peak
    if roi <= result['peak_roi'] - peak_dd:
        result['removed'] = True
        result['exits'].append('BOUNCE_PEAK_DD')

    return result
