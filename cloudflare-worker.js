// Cloudflare Worker — trigger crypto-trading mỗi 30 phút
// 1. Tạo Worker, paste script này
// 2. Settings → Variables → thêm secret GH_PAT
// 3. Triggers → Cron: */30 * * * *

const REPO = 'tranduy216/auto-alert-gg-chat'

export default {
  async scheduled(event, env, ctx) {
    const pat = env.GH_PAT
    if (!pat) {
      console.error('Missing GH_PAT secret')
      return
    }

    // Trigger workflow via repository_dispatch
    const resp = await fetch(`https://api.github.com/repos/${REPO}/dispatches`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${pat}`,
        'Content-Type': 'application/json',
        'User-Agent': 'cloudflare-worker',
      },
      body: JSON.stringify({
        event_type: 'trigger-trading',
      }),
    })

    if (resp.status === 204) {
      console.log('✅ Workflow triggered')
    } else {
      console.error(`❌ Failed: ${resp.status} ${await resp.text()}`)
    }
  },
}
