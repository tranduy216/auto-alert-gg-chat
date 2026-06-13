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
- OpenAI filters only relevant articles and produces a concise, topic-grouped summary.
- Summary is sent to Discord with source URLs.

### 2 · Breaking-News Monitor (every 2 hours)

Checks continuously for high-impact events:

- Bitcoin 24-h price change **> ±4 %** (CoinGecko free API)
- Major central-bank or government decisions
- Wars, peace deals, geopolitical escalations
- Large corporate collapses / mergers with global market impact
- Supply-chain shocks or commodity crises

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

### 1. Discord – create an incoming webhook

1. Open your Discord server → go to the channel that should receive alerts.
2. Click the gear icon (**Edit Channel**) → **Integrations** → **Webhooks** → **New Webhook**.
3. Give it a name, then click **Copy Webhook URL**.

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
| `DISCORD_WEBHOOK_URL` | The webhook URL from step 1 |
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
