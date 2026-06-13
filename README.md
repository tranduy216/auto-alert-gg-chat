# auto-alert-gg-chat

Automated news alerts delivered to a **Discord** channel via **GitHub Actions**, **OpenAI**, and **Firebase**.

---

## Features

### 1 · Daily RSS Digest (twice a day)

| Schedule | Time (VNT UTC+7) | Time (UTC) |
|---|---|---|
| Morning | 07:30 | 00:30 |
| Evening | 19:30 | 12:30 |

- Reads RSS feeds covering **AI/ML**, **Java/JVM**, **Software Development**, **Finance/Economics**, and **Commodity prices** (oil, gold, rubber, …).
- Token-optimized pipeline:
  - keeps only the **first 5 recent articles per topic**,
  - prefilters with a **topic keyword map** before AI,
  - sends only compact fields (`title`, `url`, `topic`) to OpenAI.
- OpenAI produces a concise, topic-grouped summary from the prefiltered shortlist.
- Summary is sent to Discord with source URLs.

### 2 · Breaking-News Monitor (every 2 hours)

Checks continuously for high-impact events:

- Bitcoin 24-h price change **> ±4 %** (CoinGecko free API)
- Major central-bank or government decisions
- Wars, peace deals, geopolitical escalations
- Large corporate collapses / mergers with global market impact
- Supply-chain shocks or commodity crises

Token optimization for breaking-news:
- limit feed intake (top 5 per feed),
- keyword prefilter before OpenAI,
- only compact article payload (`title` + `url`) is sent to the model.

**Quiet hours (22:00 – 06:00 VNT):** alerts are stored in **Firebase Firestore** and delivered in a batch immediately after 06:00 VNT.

**Deduplication:** the same alert is not re-sent within a 6-hour window.

---

## Repository structure

```
.github/
  workflows/
    daily-rss-digest.yml    # twice-daily RSS digest job
    breaking-news.yml       # every-2-hour breaking news job
scripts/
  rss_digest.py             # daily digest entry point
  breaking_news.py          # breaking news entry point
  utils/
    discord_webhook.py      # Discord webhook helper
    firebase_utils.py       # Firestore queue + deduplication
    openai_utils.py         # OpenAI summarisation & detection
requirements.txt
```

---

## Setup

### 1. Discord – create two incoming webhooks

This bot uses **two separate Discord webhooks** — one per channel:

| Channel purpose | Env var used |
|---|---|
| Daily RSS digest | `DISCORD_DAILY_WEBHOOK_URL` |
| Breaking-news alerts | `DISCORD_BREAKING_WEBHOOK_URL` |

For **each** channel:

1. Open your Discord server → go to the target channel.
2. Click the gear icon (**Edit Channel**) → **Integrations** → **Webhooks** → **New Webhook**.
3. Give it a name (e.g. `Daily Digest Bot` or `Breaking News Bot`), then click **Copy Webhook URL**.

### 2. Firebase – create a Firestore database

1. Go to [Firebase Console](https://console.firebase.google.com/) → create (or open) a project.
2. Enable **Firestore Database** (Native mode).
3. Go to **Project Settings → Service Accounts → Generate new private key**.
4. Download the JSON file.

### 3. Add GitHub Secrets

In your repository go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret name | Value |
|---|---|
| `OPENAI_API_KEY` | Your OpenAI API key |
| `DISCORD_DAILY_WEBHOOK_URL` | Webhook URL for the daily-digest Discord channel (step 1) |
| `DISCORD_BREAKING_WEBHOOK_URL` | Webhook URL for the breaking-news Discord channel (step 1) |
| `FIREBASE_SERVICE_ACCOUNT` | The entire content of the service-account JSON from step 2 |

> `FIREBASE_SERVICE_ACCOUNT` is optional. Without it the monitor still works but
> quiet-hours alerts will not be queued and deduplication is disabled.

### 4. Enable GitHub Actions

Workflows run automatically on the defined schedules once the secrets are set.
You can also trigger them manually via **Actions → workflow name → Run workflow**.

---

## Technology stack

| Component | Role |
|---|---|
| GitHub Actions | Workflow scheduler & runner |
| OpenAI `gpt-4o-mini` | News filtering, summarisation, breaking-news detection |
| Firebase Firestore | Quiet-hours alert queue & deduplication |
| Discord webhook | Notification delivery |
| CoinGecko API | Real-time Bitcoin price (free, no key needed) |
| RSS feeds | News source (AI, Java, Dev, Finance, Commodities) |

---

## Keyword map (daily digest prefilter)

Each topic uses a dedicated keyword list for rule-based filtering before OpenAI.

- **AI/ML**: `gpt`, `gemini`, `claude`, `llama`, `mistral`, `openai`, `anthropic`, `deepmind`, `model`, `ai agent`, `reasoning`, `multimodal`, `fine-tuning`
- **Java/JVM**: `java`, `jvm`, `spring`, `spring boot`, `kotlin`, `gradle`, `maven`, `quarkus`, `micronaut`, `virtual threads`, `jdk`, `openjdk`
- **Developer**: `culture`, `performance`, `framework`, `architecture`, `design`, `scalability`, `reliability`, `observability`, `refactoring`, `clean code`, `engineering`, `developer experience`, `testing`, `devops`, `api`, `platform`, `security`
- **Finance/Economics**: `inflation`, `interest rate`, `federal reserve`, `central bank`, `stocks`, `bonds`, `recession`, `gdp`, `unemployment`, `earnings`, `market`, `tariff`
- **Commodities**: `oil`, `gold`, `gas`, `rubber`, `copper`, `silver`, `crude`, `opec`, `supply`, `demand`, `commodity`
