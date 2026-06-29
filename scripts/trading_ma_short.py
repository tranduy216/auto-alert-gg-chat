"""
Live Trading — 12h/1D Hybrid Trend + Pullback
- Trend: 1D MA3>MA5>MA7 (long) | MA3<MA5<MA7 (short)
- Entry: 12h — price near MA3 (1%), MA3 near MA7 (1%)
- TP 6%, SL 3%, 1% equity/entry, 1x leverage
- BNB, SOL, ETH
"""
import os, sys, time, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from backtest_shared import sma
from utils.discord_webhook import send_message
from utils.okx_utils import (
    okx_get_account, okx_get_positions, okx_place_order, okx_place_algo,
    okx_close_position, okx_get_candles, okx_get_instruments, OKX_INSTRUMENTS,
)
from utils.state_manager import get_state, set_state, has_entered_today, record_entry

DISCORD_WEBHOOK = os.environ.get("DISCORD_TRADING_WEBHOOK_URL", "")
COINS = ['BNB', 'SOL', 'ETH']
ENTRY_PCT = 0.01
TP_PCT = 0.06
SL_PCT = 0.03
LEV = 1.0
MA_NEAR_BUF = 0.01
PRICE_NEAR_BUF = 0.01


def check_signal(h12_da, daily_da):
    """Check entry signal: daily trend + 12h pullback.
    Returns (direction: 'LONG'|'SHORT'|None, price).
    """
    if not daily_da or len(daily_da) < 10 or not h12_da or len(h12_da) < 10:
        return None, None

    # Daily trend
    dclose = [c['close'] for c in daily_da]
    dma3 = sma(dclose, 3)
    dma5 = sma(dclose, 5)
    dma7 = sma(dclose, 7)
    di = len(dclose) - 1
    d3, d5, d7 = dma3[di], dma5[di], dma7[di]
    if d3 is None or d5 is None or d7 is None:
        return None, None

    uptrend = d3 > d5 > d7
    downtrend = d3 < d5 < d7
    if not uptrend and not downtrend:
        return None, None

    # 12h entry
    h12c = [c['close'] for c in h12_da]
    h12m3 = sma(h12c, 3)
    h12m7 = sma(h12c, 7)
    ri = len(h12c) - 1
    cc = h12c[ri]
    m3 = h12m3[ri]
    m7 = h12m7[ri]
    if m3 is None or m7 is None:
        return None, None

    ma_near = abs(m3 - m7) / m7 <= MA_NEAR_BUF
    price_near = abs(cc - m3) / m3 <= PRICE_NEAR_BUF

    if not ma_near or not price_near:
        return None, None

    direction = 'LONG' if uptrend else 'SHORT'
    return direction, cc


def main():
    now = datetime.datetime.now()
    def log(msg): print(f"[{now:%H:%M}] {msg}")

    log("12h/1D Hybrid Trader — Fetching data...")

    # Fetch 12h data for entry signal
    h12_map = {}
    for coin in COINS:
        da = okx_get_candles(OKX_INSTRUMENTS[coin], bar='12H', limit=30)
        if not da or len(da) < 10:
            log(f"  {coin}: insufficient 12h data")
            continue
        h12_map[coin] = da

    # Fetch daily data for trend detection
    daily_map = {}
    for coin in COINS:
        da = okx_get_candles(OKX_INSTRUMENTS[coin], bar='1D', limit=30)
        if not da or len(da) < 10:
            log(f"  {coin}: insufficient daily data, trying fetch_candles")
            from backtest_shared import fetch_candles
            da = fetch_candles(f'{coin}USDT', 30)
            if not da or len(da) < 10:
                log(f"  {coin}: still no data")
                continue
        daily_map[coin] = da

    if not daily_map or not h12_map:
        log("No data available, exiting")
        return

    # Account
    eq = 0
    has_okx = bool(os.environ.get("OKX_API_KEY"))
    if has_okx:
        try:
            acct = okx_get_account()
            for d in acct.get('data', []):
                if isinstance(d, dict):
                    eq = float(d.get('totalEq', 0) or d.get('eq', 0) or 0)
                    if eq > 0: break
            if eq <= 0: eq = float(acct.get('totalEq', 0))
            log(f"Equity: ${eq:,.0f}")
        except Exception as e:
            log(f"Account fetch failed: {e}")
            eq = 10000

    positions = []
    pos_map = {}
    if has_okx:
        try:
            positions = okx_get_positions()
            pos_map = {p['instId']: p for p in positions if float(p.get('pos', 0)) != 0}
        except Exception as e:
            log(f"Positions fetch failed: {e}")

    inst_map = {}
    if has_okx:
        try:
            insts = okx_get_instruments('SWAP')
            inst_map = {inst['instId']: inst for inst in insts}
        except Exception as e:
            log(f"Instruments fetch failed: {e}")

    today = datetime.datetime.now().strftime('%Y-%m-%d')

    # ── Exit check ──
    if has_okx:
        for coin in COINS:
            da = daily_map.get(coin)
            if not da: continue
            inst_id = OKX_INSTRUMENTS.get(coin)
            if not inst_id: continue
            state = get_state(coin)
            ep = state.get('last_entry_price')
            if not ep: continue
            cc = da[-1]['close']
            is_short = state.get('is_short', False)

            if is_short:
                if cc >= ep * (1 + SL_PCT):
                    log(f"  {coin}: SL hit ({cc:.4f} >= {ep*(1+SL_PCT):.4f}), closing")
                    try:
                        okx_close_position(inst_id)
                        set_state(coin, {'last_entry_date': '', 'last_entry_price': 0, 'is_short': False})
                        if DISCORD_WEBHOOK:
                            send_message(DISCORD_WEBHOOK, f"SL: {coin} short @ ${cc:.2f} (loss {SL_PCT*100:.0f}%)")
                    except Exception as e:
                        log(f"  {coin}: close FAILED: {e}")
                elif cc <= ep * (1 - TP_PCT):
                    log(f"  {coin}: TP hit ({cc:.4f} <= {ep*(1-TP_PCT):.4f}), closing")
                    try:
                        okx_close_position(inst_id)
                        set_state(coin, {'last_entry_date': '', 'last_entry_price': 0, 'is_short': False})
                        if DISCORD_WEBHOOK:
                            send_message(DISCORD_WEBHOOK, f"TP: {coin} short @ ${cc:.2f} (profit {TP_PCT*100:.0f}%)")
                    except Exception as e:
                        log(f"  {coin}: close FAILED: {e}")
            else:
                if cc <= ep * (1 - SL_PCT):
                    log(f"  {coin}: SL hit ({cc:.4f} <= {ep*(1-SL_PCT):.4f}), closing")
                    try:
                        okx_close_position(inst_id)
                        set_state(coin, {'last_entry_date': '', 'last_entry_price': 0, 'is_short': False})
                        if DISCORD_WEBHOOK:
                            send_message(DISCORD_WEBHOOK, f"SL: {coin} long @ ${cc:.2f} (loss {SL_PCT*100:.0f}%)")
                    except Exception as e:
                        log(f"  {coin}: close FAILED: {e}")
                elif cc >= ep * (1 + TP_PCT):
                    log(f"  {coin}: TP hit ({cc:.4f} >= {ep*(1+TP_PCT):.4f}), closing")
                    try:
                        okx_close_position(inst_id)
                        set_state(coin, {'last_entry_date': '', 'last_entry_price': 0, 'is_short': False})
                        if DISCORD_WEBHOOK:
                            send_message(DISCORD_WEBHOOK, f"TP: {coin} long @ ${cc:.2f} (profit {TP_PCT*100:.0f}%)")
                    except Exception as e:
                        log(f"  {coin}: close FAILED: {e}")

    # ── Entry check ──
    signals = []
    for coin in COINS:
        h12 = h12_map.get(coin)
        daily = daily_map.get(coin)
        if not h12 or not daily: continue
        direction, price = check_signal(h12, daily)
        if direction:
            signals.append((coin, direction, price))
            log(f"  {coin}: {direction} @ ${price:.4f}")

    # ── Execute ──
    traded = []
    if has_okx and eq > 0:
        for coin, direction, price in signals:
            inst_id = OKX_INSTRUMENTS.get(coin)
            if not inst_id: continue
            if has_entered_today(coin):
                log(f"  {coin}: already entered today, skip")
                continue
            if inst_id in pos_map:
                log(f"  {coin}: existing position, skip")
                continue

            usd_val = eq * LEV * ENTRY_PCT
            if inst_id in inst_map:
                ct_val = float(inst_map[inst_id].get('ctVal', '0.01'))
                sz = max(1, int(usd_val / (price * ct_val)))
            else:
                sz = max(1, int(usd_val / price))

            is_buy = direction == 'LONG'
            side = 'buy' if is_buy else 'sell'
            tp_px = f"{price * (1 + TP_PCT):.4f}" if is_buy else f"{price * (1 - TP_PCT):.4f}"
            sl_px = f"{price * (1 - SL_PCT):.4f}" if is_buy else f"{price * (1 + SL_PCT):.4f}"

            log(f"  TRADE {coin}: {direction} {sz}ct @ ${price:.2f} (${usd_val:.0f}) TP={tp_px} SL={sl_px}")
            try:
                r = okx_place_order(inst_id=inst_id, td_mode='cross', side=side, sz=str(sz))
                log(f"  Order OK: {r.get('data', [{}])[0].get('ordId', '?')}")
                time.sleep(1)

                # SL algo
                try:
                    okx_place_algo(inst_id=inst_id, td_mode='cross',
                                   side='buy' if not is_buy else 'sell',
                                   sz=str(sz), ord_type='conditional',
                                   sl_trigger_px=sl_px)
                    log(f"  SL placed @ {sl_px}")
                except Exception as e:
                    log(f"  SL failed: {e}")

                # TP algo
                try:
                    okx_place_algo(inst_id=inst_id, td_mode='cross',
                                   side='buy' if not is_buy else 'sell',
                                   sz=str(sz), ord_type='conditional',
                                   tp_trigger_px=tp_px)
                    log(f"  TP placed @ {tp_px}")
                except Exception as e:
                    log(f"  TP failed: {e}")

                record_entry(coin, price)
                set_state(coin, {'is_short': not is_buy})
                traded.append((coin, direction, price))
                if DISCORD_WEBHOOK:
                    send_message(DISCORD_WEBHOOK,
                        f"{direction} {coin} {sz}ct @ ${price:.2f} | TP {tp_px} SL {sl_px}")
            except Exception as e:
                log(f"  Order FAILED: {e}")
                if DISCORD_WEBHOOK:
                    send_message(DISCORD_WEBHOOK, f"FAILED: {direction} {coin} — {e}")

    # ── Summary ──
    print(f"\n{'='*55}")
    print(f"12h/1D Hybrid Trader — {now:%Y-%m-%d %H:%M}")
    print(f"{'='*55}")
    for coin in COINS:
        h12 = h12_map.get(coin)
        daily = daily_map.get(coin)
        if not h12 or not daily:
            print(f"  {coin}: no data")
            continue
        direction, price = check_signal(h12, daily)
        status = direction or "HOLD"
        pos = get_state(coin)
        has_pos = pos.get('last_entry_price', 0) != 0
        ep = pos.get('last_entry_price', 0)
        dir_label = 'LONG' if not pos.get('is_short') else 'SHORT'
        print(f"  {coin:<5} {status:<6} @ ${h12[-1]['close']:<10.2f} {'POS: '+dir_label+' @ $'+f'{ep:.2f}' if has_pos else ''}")
    print(f"  Signals: {len(signals)}, Traded: {len(traded)}")
    print(f"{'='*55}")


if __name__ == '__main__':
    main()
