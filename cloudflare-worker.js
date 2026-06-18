// Cloudflare Worker — trigger crypto-trading mỗi 30 phút + báo Discord
const REPO = 'tranduy216/auto-alert-gg-chat'

async function sendDiscord(webhook, msg) {
  if (!webhook) return
  await fetch(webhook, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: msg }),
  })
}

async function trigger(pat, webhook) {
  const resp = await fetch(`https://api.github.com/repos/${REPO}/dispatches`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${pat}`,
      'Content-Type': 'application/json',
      'User-Agent': 'cloudflare-worker',
    },
    body: JSON.stringify({ event_type: 'trigger-trading' }),
  })
  if (resp.status === 204) {
    await sendDiscord(webhook, '✅ Trading workflow triggered')
  } else {
    const text = await resp.text()
    await sendDiscord(webhook, `⚠️ Trigger fail: HTTP ${resp.status}\n\`\`\`${text.slice(0, 200)}\`\`\``)
    throw new Error(`HTTP ${resp.status}: ${text}`)
  }
}

export default {
  // Cron: mỗi 30 phút
  async scheduled(event, env, ctx) {
    if (!env.GH_PAT) {
      await sendDiscord(env.DISCORD_WEBHOOK, '❌ Worker: thiếu GH_PAT')
      return
    }
    await trigger(env.GH_PAT, env.DISCORD_WEBHOOK)
  },

  // HTTP request (để test hoặc trigger thủ công)
  async fetch(request, env, ctx) {
    if (!env.GH_PAT) {
      return new Response('Missing GH_PAT', { status: 500 })
    }
    try {
      await trigger(env.GH_PAT, env.DISCORD_WEBHOOK)
      return new Response('OK', { status: 200 })
    } catch (e) {
      return new Response(e.message, { status: 500 })
    }
  },
}
