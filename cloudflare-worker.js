// Cloudflare Worker — trigger trading workflows mỗi 30 phút
const REPO = 'tranduy216/auto-alert-gg-chat'

async function sendDiscord(webhook, msg) {
  if (!webhook) return
  await fetch(webhook, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: msg }),
  })
}

async function triggerWorkflow(pat, webhook, eventType) {
  const resp = await fetch(`https://api.github.com/repos/${REPO}/dispatches`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${pat}`,
      'Content-Type': 'application/json',
      'User-Agent': 'cloudflare-worker',
    },
    body: JSON.stringify({ event_type: eventType }),
  })
  if (resp.status === 204) {
    console.log(`✅ ${eventType} triggered`)
  } else {
    const text = await resp.text()
    await sendDiscord(webhook, `⚠️ ${eventType} fail: HTTP ${resp.status}\n\`\`\`${text.slice(0, 200)}\`\`\``)
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
    await triggerWorkflow(env.GH_PAT, env.DISCORD_WEBHOOK, 'trigger-trading')
    await triggerWorkflow(env.GH_PAT, env.DISCORD_WEBHOOK, 'trigger-daily-trading')
  },

  // HTTP request (để test hoặc trigger thủ công)
  async fetch(request, env, ctx) {
    if (!env.GH_PAT) {
      return new Response('Missing GH_PAT', { status: 500 })
    }
    try {
      await triggerWorkflow(env.GH_PAT, env.DISCORD_WEBHOOK, 'trigger-trading')
      await triggerWorkflow(env.GH_PAT, env.DISCORD_WEBHOOK, 'trigger-daily-trading')
      return new Response('OK', { status: 200 })
    } catch (e) {
      return new Response(e.message, { status: 500 })
    }
  },
}
