// Cloudflare Worker — trigger crypto-trading mỗi 30 phút + báo Discord
// Secrets cần set:
//   GH_PAT            — GitHub token (quyền actions:write)
//   DISCORD_WEBHOOK   — Discord webhook URL để nhận thông báo

const REPO = 'tranduy216/auto-alert-gg-chat'

async function sendDiscord(webhook, message) {
  if (!webhook) return
  await fetch(webhook, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: message }),
  })
}

export default {
  async scheduled(event, env, ctx) {
    const pat = env.GH_PAT
    const webhook = env.DISCORD_WEBHOOK

    if (!pat) {
      await sendDiscord(webhook, '❌ Cloudflare Worker: thiếu GH_PAT secret')
      return
    }

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
      console.log('✅ Triggered')
      // Không spam, chỉ log — im lặng = OK
    } else {
      const text = await resp.text()
      console.error(`❌ ${resp.status}: ${text}`)
      await sendDiscord(webhook, `⚠️ Cloudflare Worker trigger thất bại\nHTTP ${resp.status}\n\`\`\`${text.slice(0, 200)}\`\`\``)
    }
  },
}
