---
name: trade-deploy
description: |
  Deploy the crypto trading pyramid strategy to production.
  Use ONLY when the user explicitly says "deploy", "trade-deploy", or "trien khai".
  Validates: backtest vs live consistency, 100% test coverage, zero code/config duplication,
  all files compile, docs match code, then triggers GitHub workflow and monitors.

  Key files:
  - scripts/backtest_shared.py        — shared entry_conditions, constants, helpers
  - scripts/combined_backtest.py      — standalone per-coin backtest (calls entry_conditions)
  - scripts/pooled_backtest.py        — pooled shared-capital backtest
  - scripts/crypto_trading.py         — LIVE trading (calls entry_conditions, ~130 lines)
  - scripts/live_pyramid.py           — LIVE signal generator (calls entry_conditions)
  - scripts/crypto_trading_legacy.py  — old 2254-line system (preserved for legacy scripts)
  - scripts/trading_config.py         — coin profiles, SHORT_ALLOWED, constants
  - .github/workflows/crypto-trading.yml — GitHub Actions workflow

  Backtest + live MUST share the same entry_conditions() from backtest_shared.
  NO code segment or constant may be duplicated across files.

  Run `scripts/test/test_all.py` before deploy and expect 0 failures.
  After deploy, monitor the workflow run and fix any errors.
---

# trade-deploy — Pyramid Strategy Deployment

## 1. Pre-deploy Checklist

### 1.1 Consistency Check

Verify the following files all call the SAME `entry_conditions()` from `backtest_shared`:

- [ ] `scripts/combined_backtest.py` — uses `backtest_shared.entry_conditions`
- [ ] `scripts/crypto_trading.py` — uses `backtest_shared.entry_conditions`
- [ ] `scripts/live_pyramid.py` — uses `backtest_shared.entry_conditions`

If any file has its OWN inline entry logic instead of calling the shared function, refactor it first.

Block comparison: the entry block in any file should match `backtest_shared.py` lines 147–173 exactly.

### 1.2 Duplication Check

No constant or code segment may be duplicated across files. The ONLY source:

| Item | Source |
|------|--------|
| `sma()` | `backtest_shared.py` (re-exported, not duplicated) |
| `BASE`, `ENTRY_PCT`, `TRAIL_PCT`, `MA_BUF`, `MA_PERIOD`, `PYRAMID_ROI_DEFAULT`, `TP_SCHEDULE`, `BTC_SHORT_TP`, `MAX_CAP`, `FEE_RATE`, `EXT_BLOCK_PCT` | `backtest_shared.py` |
| `load_data()`, `fetch_paxg()`, `winner_mult()`, `total_asset_value()`, `compute_results()`, `entry_conditions()`, `compute_roi()` | `backtest_shared.py` |
| `SHORT_ALLOWED`, coin profiles | `trading_config.py` |
| Workflow definitions | `.github/workflows/*.yml` |

If any `scripts/*.py` redeclares a constant or function that exists in `backtest_shared`, fail the deploy.

### 1.3 Code Compilation

```bash
for f in scripts/*.py scripts/test/*.py scripts/utils/*.py; do
  python3 -B -c "import ast; ast.parse(open('$f').read())" || echo "FAIL: $f"
done
```

Zero syntax errors required.

### 1.4 Unit Tests

```bash
python3 -B scripts/test/test_all.py
```

Requirement: **0 failures**. If any test fails:
- Fix the code (not the test — tests reflect correct behavior)
- Re-run all tests
- Only proceed when all pass

### 1.5 Test Coverage (100% line, 100% branch)

All logic in `backtest_shared.py` must be covered:

| Function | Lines | Tests in `test_all.py` |
|----------|-------|------------------------|
| `sma()` | 7–21 | period 3 basic, period too large, single value, empty, float input, all same values |
| `winner_mult()` | 40–51 | no entries, >15, 10-15, 5-10, 0-5, -5-0, <-5, short profit, leverage effect |
| `total_asset_value()` | 56–67 | no entries, long profit, short profit, partial rem |
| `compute_results()` | 92–144 | CAGR pos/neg, MD, yearly, final, empty curve |
| `fee_factor()` | 28–30 | lev=1.5, 1.0, 2.0, 0 |
| `entry_conditions()` | 147–173 | long near_ma up, long not near_ma, short bull reg blocked, short bear reg allowed, long ext_block active, short ext_block active |
| `compute_roi()` | 175–180 | long roi pos, short roi pos, long roi neg, short roi neg |
| `load_data()` | — | returns dict, has TRX, has BTC, data has bars, bar has all fields, bar high>=close, bar low<=close, bar volume>=0 |
| Constants | — | BASE, ENTRY_PCT, TRAIL_PCT, TP_SCHEDULE sum/invariants, MAX_CAP, FEE_RATE, EXT_BLOCK_PCT |

If new code is added to `backtest_shared`, corresponding tests MUST be added in `test_all.py` before deploy.

### 1.6 Docs-Code Consistency

- The docstring at the top of each `scripts/*.py` file must accurately describe what the file does
- Method/function names in `backtest_shared.py` must match how they are CALLED in other files
- If a function name changes, ALL callers must be updated
- The `trading_config.py` profile names (keys like `"TRX"`, `"BTC"`, `"ETH"`) must match the symbols used in backtest strategy lists

### 1.7 Resource Consistency

- [ ] Test file imports match actual function signatures
- [ ] Backtest strategy lists match live strategy lists
- [ ] `BTC_SHORT_TP` in `backtest_shared.py` matches `tp` config in all strategy lists
- [ ] All `cfg` keys (`ma`, `buf`, `pyr`, `lev`, `tp`) are spelled the same in all files

## 2. Deploy

### 2.1 Commit and Push

```bash
git add -A
git commit -m "deploy: <short description of changes>"
git push origin master
```

### 2.2 Trigger Workflow

```bash
gh workflow run "Crypto Trading System"
```

### 2.3 Monitor

```bash
gh run list --limit 3 --json headBranch,status,conclusion
sleep 20
gh run view <run-id> --log 2>&1 | grep -i "error\|traceback\|failure\|exit code"
```

- If the workflow fails: read the error, fix the code, and restart from step 2.1
- Only mark deploy as done when the workflow completes with `conclusion: success`

## 3. Post-Deploy

- [ ] Confirm Discord notification was sent (if configured)
- [ ] Verify OKX positions (if configured): `python3 -B -c "import sys; sys.path.insert(0,'scripts'); from utils.okx_utils import okx_get_positions; print(okx_get_positions())"`
- [ ] Log the deployed commit hash for rollback: `git rev-parse HEAD`

## 4. Rollback (if needed)

```bash
git revert HEAD --no-edit
git push origin master
```
