"""
Daily Trading — BNB & ETH (pyramiding)
- Trend: 1D MA3>MA5>MA7 (long) | MA3<MA5<MA7 (short)
- Entry: 12h — price near MA3 (1%), MA3 near MA7 (1%)
- Multiple entries allowed (pyramiding)
- TP/SL calculated on avg entry price of all open entries
- 2% origin cap (10k) per entry, 2x leverage → $400/entry
- TP/SL set on entry via OKX algo orders
"""
import os, sys, time, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from backtest_shared import sma
from utils.discord_webhook import send_message
from utils.okx_utils import (
    okx_get_account, okx_get_positions, okx_place_order, okx_place_algo,
    okx_close_position, okx_get_candles, okx_get_instruments,
)
from utils.state_manager import get_entries, add_entry, clear_entries, set_state, get_state

CAPITAL_BASE = 10000
ENTRY_MARGIN_PCT = 0.02
LEV = 2.0
NOTIONAL = CAPITAL_BASE * ENTRY_MARGIN_PCT * LEV
TP_PCT = 0.06
SL_PCT = 0.03
MA_NEAR_BUF = 0.01
PRICE_NEAR_BUF = 0.01

COINS = ['BNB']
OKX_SYMBOLS = {'BNB': 'BNB-USDT-SWAP'}
DISCORD_WEBHOOK = os.environ.get("DISCORD_TRADING_WEBHOOK_URL", "")


def log(msg):
    t = datetime.datetime.now()
    print(f"[{t:%Y-%m-%d %H:%M:%S}] {msg}")


def avg_ep(entries):
    if not entries:
        return None
    total_w = sum(e.get('mp', 1) for e in entries)
    weighted = sum(e['ep'] * e.get('mp', 1) for e in entries)
    return weighted / total_w


def check_signal(h12_da, daily_da):
    if not daily_da or len(daily_da) < 10 or not h12_da or len(h12_da) < 10:
        return None, None

    dclose = [c['close'] for c in daily_da]
    dma3, dma5, dma7 = sma(dclose, 3), sma(dclose, 5), sma(dclose, 7)
    di = len(dclose) - 1
    d3, d5, d7 = dma3[di], dma5[di], dma7[di]
    if d3 is None or d5 is None or d7 is None:
        return None, None

    uptrend = d3 > d5 > d7
    downtrend = d3 < d5 < d7
    if not uptrend and not downtrend:
        return None, None

    h12c = [c['close'] for c in h12_da]
    h12m3, h12m7 = sma(h12c, 3), sma(h12c, 7)
    ri = len(h12c) - 1
    cc, m3, m7 = h12c[ri], h12m3[ri], h12m7[ri]
    if m3 is None or m7 is None:
        return None, None

    if not (abs(m3 - m7) / m7 <= MA_NEAR_BUF and abs(cc - m3) / m3 <= PRICE_NEAR_BUF):
        return None, None

    return ('LONG' if uptrend else 'SHORT'), cc


def avg_roi(entries, cc, lev):
    if not entries:
        return 0
    aep = avg_ep(entries)
    is_short = entries[0].get('short', False)
    if is_short:
        return (aep - cc) / aep * 100 * lev
    return (cc - aep) / aep * 100 * lev


def main():
    # ── Fetch data ──
    h12_map, daily_map = {}, {}
    for coin in COINS:
        inst = OKX_SYMBOLS[coin]
        da = okx_get_candles(inst, bar='12H', limit=30)
        if da and len(da) >= 10:
            h12_map[coin] = da
        else:
            log(f"{coin}: no 12h data")
        da = okx_get_candles(inst, bar='1D', limit=30)
        if da and len(da) >= 10:
            daily_map[coin] = da
        else:
            log(f"{coin}: no daily data")

    if not h12_map or not daily_map:
        log("Insufficient data, exiting")
        return

    # ── Account ──
    eq = CAPITAL_BASE
    has_okx = bool(os.environ.get("OKX_API_KEY"))
    if has_okx:
        try:
            acct = okx_get_account()
            for d in acct.get('data', []):
                if isinstance(d, dict):
                    eq = float(d.get('totalEq', 0) or d.get('eq', 0) or 0)
                    if eq > 0: break
            if eq <= 0: eq = float(acct.get('totalEq', 0))
        except Exception as e:
            log(f"Account fetch failed: {e}")

    log(f"Equity: ${eq:,.0f}  |  Position size: ${NOTIONAL:,.0f}/entry (2% × $10k @ 2x)")

    # ── Positions ──
    pos_map = {}
    if has_okx:
        try:
            for p in okx_get_positions():
                if float(p.get('pos', 0)) != 0:
                    pos_map[p['instId']] = p
        except Exception as e:
            log(f"Positions fetch failed: {e}")

    # ── Exit check (avg entry price → ROI) ──
    if has_okx:
        for coin in COINS:
            da = daily_map.get(coin)
            if not da: continue
            inst = OKX_SYMBOLS[coin]
            stored = get_entries(coin)
            if not stored:
                continue
            cc = da[-1]['close']
            roi = avg_roi(stored, cc, LEV)

            if roi <= -SL_PCT * 100:
                log(f"{coin}: SL hit (ROI {roi:.1f}%), closing all")
                try:
                    okx_close_position(inst)
                    clear_entries(coin)
                    set_state(coin, {'ep': 0, 'side': ''})
                    if DISCORD_WEBHOOK:
                        send_message(DISCORD_WEBHOOK,
                                     f"SL: {coin} {stored[0].get('short','?')} @ ${cc:.2f} (ROI {roi:.1f}%)")
                except Exception as e:
                    log(f"  close FAILED: {e}")
            elif roi >= TP_PCT * 100:
                log(f"{coin}: TP hit (ROI {roi:.1f}%), closing all")
                try:
                    okx_close_position(inst)
                    clear_entries(coin)
                    set_state(coin, {'ep': 0, 'side': ''})
                    if DISCORD_WEBHOOK:
                        send_message(DISCORD_WEBHOOK,
                                     f"TP: {coin} {stored[0].get('short','?')} @ ${cc:.2f} (ROI {roi:.1f}%)")
                except Exception as e:
                    log(f"  close FAILED: {e}")

    # ── Entry ──
    signals = []
    for coin in COINS:
        h12, daily = h12_map.get(coin), daily_map.get(coin)
        if not h12 or not daily: continue

        inst = OKX_SYMBOLS[coin]
        if inst in pos_map:
            log(f"{coin}: OKX position exists, skip new entry")
            continue

        direction, price = check_signal(h12, daily)
        if direction:
            signals.append((coin, direction, price))
            log(f"{coin}: {direction} signal @ ${price:.4f}")

    if has_okx and eq > 0:
        insts = {}
        try:
            insts = {i['instId']: i for i in okx_get_instruments('SWAP')}
        except Exception:
            pass

        for coin, direction, price in signals:
            inst = OKX_SYMBOLS[coin]
            inst_info = insts.get(inst, {})
            ct_val = float(inst_info.get('ctVal', '0.01'))

            sz = max(1, int(NOTIONAL / (price * ct_val)))
            is_buy = direction == 'LONG'
            side = 'buy' if is_buy else 'sell'
            tp_px = f"{price * (1 + TP_PCT):.2f}" if is_buy else f"{price * (1 - TP_PCT):.2f}"
            sl_px = f"{price * (1 - SL_PCT):.2f}" if is_buy else f"{price * (1 + SL_PCT):.2f}"

            log(f"ENTRY {coin} {direction} {sz}ct @ ${price:.2f} | TP {tp_px} SL {sl_px}")
            try:
                r = okx_place_order(inst_id=inst, td_mode='cross', side=side, sz=str(sz))
                oid = r.get('data', [{}])[0].get('ordId', '?')
                log(f"  Order placed: {oid}")
                time.sleep(1)

                # SL algo order
                try:
                    okx_place_algo(inst_id=inst, td_mode='cross',
                                   side='buy' if not is_buy else 'sell',
                                   sz=str(sz), ord_type='conditional',
                                   sl_trigger_px=sl_px)
                    log(f"  SL @ {sl_px}")
                except Exception as e:
                    log(f"  SL failed: {e}")

                # TP algo order
                try:
                    okx_place_algo(inst_id=inst, td_mode='cross',
                                   side='buy' if not is_buy else 'sell',
                                   sz=str(sz), ord_type='conditional',
                                   tp_trigger_px=tp_px)
                    log(f"  TP @ {tp_px}")
                except Exception as e:
                    log(f"  TP failed: {e}")

                add_entry(coin, price, not is_buy)
                set_state(coin, {'ep': price, 'side': direction})
                if DISCORD_WEBHOOK:
                    send_message(DISCORD_WEBHOOK,
                                 f"{direction} {coin} {sz}ct @ ${price:.2f} | TP {tp_px} SL {sl_px}")
            except Exception as e:
                log(f"  Order FAILED: {e}")
                if DISCORD_WEBHOOK:
                    send_message(DISCORD_WEBHOOK, f"FAILED {direction} {coin}: {e}")

    # ── Summary ──
    print(f"\n{'='*55}")
    now = datetime.datetime.now()
    print(f"Daily Trading (pyramiding) — {now:%Y-%m-%d %H:%M}")
    print(f"{'='*55}")
    for coin in COINS:
        stored = get_entries(coin)
        if stored:
            aep = avg_ep(stored)
            print(f"  {coin:<5} POS {len(stored)}x @ avg ${aep:<10.2f}")
        else:
            h12, daily = h12_map.get(coin), daily_map.get(coin)
            if h12 and daily:
                dir, pr = check_signal(h12, daily)
                print(f"  {coin:<5} {dir or 'HOLD':<5} @ ${(h12[-1]['close'] if h12 else 0):<10.2f}")
            else:
                print(f"  {coin:<5} NODATA")
    print(f"  Signals: {len(signals)}")
    print(f"{'='*55}")


if __name__ == '__main__':
    main()
