"""Validate all 3rd-party integrations + run backtest."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
errs = []

# 1. OKX read APIs
print('=== OKX smoke test ===')
try:
    from utils.okx_utils import okx_get_account, okx_get_positions
    a = okx_get_account()
    print(f'  Account OK (${float(a["data"][0]["totalEq"]):,.2f})')
    p = okx_get_positions()
    print(f'  Positions OK ({len(p)} open)')
except Exception as e:
    errs.append(f'OKX: {e}'); print(f'  FAIL: {e}')

# 2. Firestore
print('=== Firestore smoke test ===')
try:
    from crypto_trading import load_state
    s = load_state('BTC')
    print(f'  BTC state: {s.get("position_state","?")}')
    print(f'  Firestore OK')
except Exception as e:
    errs.append(f'Firestore: {e}'); print(f'  FAIL: {e}')

# 3. Discord
print('=== Discord smoke test ===')
try:
    from utils.discord_webhook import send_message
    send_message(os.environ['DISCORD_TRADING_WEBHOOK_URL'],
                 '**Validation Test**\nOKX ✅ Firestore ✅')
    print('  Discord OK')
except Exception as e:
    errs.append(f'Discord: {e}'); print(f'  FAIL: {e}')

# 4. Backtest
print('=== Backtest ===')
try:
    from backtest_crypto import main as bt_main
    bt_main()
    print('  Backtest OK')
except Exception as e:
    errs.append(f'Backtest: {e}'); print(f'  FAIL: {e}')

# 5. Signal analysis (BTC_SYMBOL, not in COINS)
print('=== Signal analysis smoke test ===')
try:
    from crypto_trading import BTC_SYMBOL, fetch_klines, analyse_coin, COINS, SYMBOL_MAP
    btc = fetch_klines(BTC_SYMBOL, '1d', 250)
    print(f'  BTC candles: {len(btc)}')
    eth = fetch_klines(SYMBOL_MAP['ETH'], '3d', 100)
    print(f'  ETH candles (3d): {len(eth)}')
except Exception as e:
    errs.append(f'Analysis: {e}'); print(f'  FAIL: {e}')

if errs:
    print(f'\nFAILURES: {" | ".join(errs)}')
    sys.exit(1)
else:
    print('\nAll checks passed')
