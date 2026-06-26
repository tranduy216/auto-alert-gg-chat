"""
Live Pyramid Strategy — sử dụng CHUNG logic entry với backtest.
Import entry_conditions từ backtest_shared → behavior 100% giống backtest.
"""
import sys, datetime, requests, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from crypto_trading import sma
from backtest_shared import (
    MA_BUF, MA_PERIOD, PYRAMID_ROI_DEFAULT, BTC_SHORT_TP, EXT_BLOCK_PCT,
    fetch_paxg, entry_conditions,
)


def fetch_binance(symbol, days=600):
    url = 'https://api.binance.com/api/v3/klines'
    start_ms = int((datetime.datetime.now() - datetime.timedelta(days=days)).timestamp() * 1000)
    candles = []
    while True:
        params = {'symbol': symbol, 'interval': '12h', 'startTime': start_ms, 'limit': 1000}
        resp = requests.get(url, params=params, timeout=30)
        raw = resp.json()
        if not raw or isinstance(raw, dict): break
        candles.extend(raw)
        start_ms = raw[-1][6] + 1
        if len(raw) < 1000: break
        time.sleep(0.3)
    daily = []
    for i in range(1, len(candles), 2):
        b2 = candles[i-1:i+1]
        daily.append({
            'close': float(b2[-1][4]), 'high': max(float(x[2]) for x in b2),
            'low': min(float(x[3]) for x in b2), 'volume': sum(float(x[5]) for x in b2),
            'time': b2[0][0],
        })
    return daily


def check_signal(coin_da, btc_da, is_short, cfg):
    """
    Kiểm tra entry tại bar cuối cùng, dùng CHUNG entry_conditions với backtest.
    """
    if not coin_da or len(coin_da) < 60:
        return None

    lev_coin = cfg.get('lev', 1.8)
    ma_buf = cfg.get('buf', MA_BUF)
    ext_block = cfg.get('ext_block', EXT_BLOCK_PCT)
    ma_period = cfg.get('ma', MA_PERIOD)
    pyr_roi = cfg.get('pyr', PYRAMID_ROI_DEFAULT)

    closes = [c['close'] for c in coin_da]
    vols = [c['volume'] for c in coin_da]
    ma_short = sma(closes, ma_period)
    vol_ma20 = sma(vols, 20)

    btc_closes = [c['close'] for c in btc_da] if btc_da else None
    btc_ma200 = sma(btc_closes, 200) if btc_closes else None

    idx = len(closes) - 1
    if idx < 200: return None

    cc = closes[idx]
    m_ma = ma_short[idx]; vavg = vol_ma20[idx]
    if m_ma is None or vavg is None or vavg == 0:
        return None

    # BTC regime
    btc_bull = False
    if btc_ma200 and btc_closes:
        btc_i = min(idx, len(btc_closes) - 1)
        if btc_i >= 200 and btc_ma200[btc_i]:
            btc_bull = btc_closes[btc_i] > btc_ma200[btc_i]

    # Dùng CHUNG entry_conditions với backtest
    should_enter, mult = entry_conditions(
        [], cc, idx, vols, vavg, m_ma, ma_buf, is_short,
        btc_bull, ext_block, lev_coin, -999,
    )

    if not should_enter:
        return None

    direction = 'BUY' if not is_short else 'SELL'
    return {
        'signal': direction,
        'price': cc,
        'ma': m_ma,
        'reason': f'near_ma ok, vol ok',
    }


def main():
    print("Fetching market data...", file=sys.stderr)
    btc_da = fetch_binance('BTCUSDT', 600)
    trx_da = fetch_binance('TRXUSDT', 600)
    paxg_da = fetch_paxg()

    strategies = [
        ('TRX',  trx_da,  False, {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8}),
        ('PAXG', paxg_da, False, {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8}),
        ('BTC',  btc_da,  True,  {'ma': 5,  'buf': 0.05, 'pyr': 3, 'lev': 1.6, 'tp': BTC_SHORT_TP}),
    ]

    now = datetime.datetime.now()
    print("=" * 60)
    print(f"LIVE PYRAMID SIGNALS — {now:%Y-%m-%d %H:%M}")
    print("=" * 60)

    signals = []
    for name, da, is_short, cfg in strategies:
        sig = check_signal(da, btc_da, is_short, cfg)
        if sig:
            print(f"  {name:<6} {sig['signal']:<5} @ ${sig['price']:<10,.4f}  ({sig['reason']})")
            signals.append(sig)
        else:
            if da and len(da) >= 0:
                print(f"  {name:<6} HOLD   @ ${da[-1]['close']:<10,.4f}  (no entry condition met)")
            else:
                print(f"  {name:<6} HOLD   (no data)")

    print("=" * 60)
    print(f"Total signals: {len(signals)}")
    if len(signals) > 0:
        print(f"\n::notice::New signals detected: {' | '.join(s['signal'] for s in signals)}")


if __name__ == '__main__':
    main()
