# auto-alert-gg-chat

Automated **crypto trading bot** on OKX + news alerts delivered to Discord via GitHub Actions.

---

## 1 · Crypto Trading System (every 1 hour)

Real automated trading on **OKX** with limit orders, risk management, and Discord notifications.

### Coins traded

| Coin | Symbol (OKX) |
|------|-------------|
| ETH  | ETH-USDT-SWAP |
| BNB  | BNB-USDT-SWAP |
| LINK | LINK-USDT-SWAP |
| ADA  | ADA-USDT-SWAP |
| MATIC| MATIC-USDT-SWAP |

### Strategy

**Two-layer engine:**

| Layer | Timeframe | Purpose |
|-------|-----------|---------|
| Trend Engine | 3D candles (MA7/MA10/MA20) | Trend classification (BULLISH/BEARISH/SIDEWAY, score ±3) |
| Execution Engine | 1D candles (MA3/MA5/MA7/ATR/Volume) | Entry signals + stage probabilities |

**3-stage scaling entries** using **limit orders** at optimal support/resistance levels:
- Entry 1: 10% capital (triggered when TrendScore ≥ threshold + volume confirmation)
- Entry 2: additional 10% (when P_Entry2 ≥ 0.80)
- Entry 3: additional 10% (when P_Entry3 ≥ 0.85)

Total: 30% equity per coin (2.5x → 75% exposure, capped by 75% capital usage limit).

**Adaptive thresholds:** entry ±2 when 3D trend_score ≥ 2 (strong trend), ±3 otherwise. When >55% of capital deployed, all entries use strict ±3.

### Order execution

- **Limit orders** for all entries (at `optimal_entry` price from entry zone)
- **Market orders** for exits / take-profit / over-extension reduces
- All positions on **cross-margin** at **2.5x leverage**
- **Hard stop loss: -5.5%**
- Exit priority: Stop Loss → Emergency Exit (MA cross + score) → Trend Exit (MA3<MA10) → Score Exit → Take Profit (+15%/+25%) → Over-Extension

### Risk management

| Rule | Detail |
|------|--------|
| Max concurrent positions | 4 |
| Capital per position | 10% (equal for all 3 entries) |
| Total capital cap | 75% of equity |
| Tight entry threshold | >55% deployed → force ±3 |
| BTC regime filter | Bear (MA50<MA200) → block LONG entries |
| Correlation filter | ETH↔MATIC: skip if correlated coin has position |
| Time filter | No new entries during economic events (FOMC, NFP, ECB) |
| Loss streak breaker | 3 consecutive losses → 50% size reduction |
| Volatility filter | ATR > 2× ATR_MA20 → skip entry |
| Kill switch | BTC flash crash >5% or -3% with 5× vol spike → close all |

### Backtest results (recent 400 days, 5 coins)

| Metric | Value |
|--------|-------|
| Raw PnL (price %) | +169% |
| ROI (2.5x × 75% deployment) | ~318% |
| Risk per trade (position) | 13.8% (2.5x × 5.5%) |
| Win rate | varies by coin/market regime |

### Notifications

- **Order executed:** OPEN / ADD / EXIT / REDUCE with size and price
- **Errors:** sent to Discord immediately (bypasses silent hours)
- **Portfolio summary:** 06:00, 13:00, 20:00 VNT — total equity + position details (PnL, leverage, margin)
- **Silent hours (22:30–05:30 VNT):** notifications queued in Firestore, flushed at 06:00

### Environment variables

| Secret | Purpose |
|--------|---------|
| `OKX_API_KEY` | OKX API key (trade permission) |
| `OKX_API_SECRET` | OKX API secret |
| `OKX_API_PASSPHRASE` | OKX API passphrase |
| `DISCORD_TRADING_WEBHOOK_URL` | Discord channel for trading notifications |
| `FIREBASE_SERVICE_ACCOUNT` | Firestore for state persistence & silent queue |

---

## 2 · Daily RSS Digest (twice a day)

| Schedule | Time (VNT) |
|----------|------------|
| Morning | 07:30 |
| Evening | 19:30 |

AI-curated news summary across topics: AI/ML, Java, Developer, Big Tech, Finance, Commodities.

---

## 3 · Breaking-News Monitor (every 2 hours)

Detects high-impact events via RSS + OpenRouter AI:
- Bitcoin 24h change >±4%
- Central bank decisions, military conflicts, market-moving events

Quiet hours (22:00–06:00 VNT): queued in Firestore → delivered at 06:00.
Deduplication: same alert not re-sent within 6h.

---

## Repository structure

```
.github/workflows/
  crypto-trading.yml       # every hour
  daily-rss-digest.yml     # twice daily
  breaking-news.yml        # every 2 hours
scripts/
  crypto_trading.py        # main trading system
  rss_digest.py            # RSS digest
  breaking_news.py         # breaking news monitor
  utils/
    okx_utils.py           # OKX API v5 client
    gemini_utils.py        # OpenRouter/Gemini AI helpers
    discord_webhook.py     # Discord webhook + silent hours
    firebase_utils.py      # Firestore queue & dedup
```

---

## Setup

1. Create **OKX API key** (Trade permission) → save key + secret + passphrase
2. Create **Discord webhooks** for trading / news channels
3. (Optional) Create **Firebase Firestore** for state & queue
4. Add **GitHub Secrets** as listed above
5. Workflows run on schedule — or trigger manually via **Actions → Run workflow**
