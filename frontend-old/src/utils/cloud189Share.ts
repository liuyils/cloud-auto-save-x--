export type Cloud189ShareParseResult = {
  url: string
  pwd: string
  shareCode: string
}

function safeDecodeURIComponent(value: string) {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

function extractPwdFromText(raw: string) {
  let text = raw
  let pwd = ''
  const patterns = [
    /[（(](?:访问码|提取码|密码)[：:]\s*([a-zA-Z0-9]{4,8})[)）]/,
    /(?:访问码|提取码|密码)[：:]\s*([a-zA-Z0-9]{4,8})/,
    /[（(]([a-zA-Z0-9]{4,8})[)）]/,
  ]
  for (const pattern of patterns) {
    const match = text.match(pattern)
    if (!match) continue
    pwd = match[1]
    text = text.replace(match[0], '')
    break
  }
  return { text, pwd }
}

function extractCloud189Url(text: string) {
  const patterns = [
    /(https?:\/\/cloud\.189\.cn\/web\/share\?[^\s]+)/,
    /(https?:\/\/cloud\.189\.cn\/t\/[a-zA-Z0-9]+[^\s]*)/,
    /(https?:\/\/h5\.cloud\.189\.cn\/share\.html#\/t\/[a-zA-Z0-9]+[^\s]*)/,
    /(https?:\/\/[^/]+\/web\/share\?[^\s]+)/,
    /(https?:\/\/[^/]+\/t\/[a-zA-Z0-9]+[^\s]*)/,
    /(https?:\/\/[^/]+\/share\.html[^\s]*)/,
    /(https?:\/\/content\.21cn\.com[^\s]+)/,
  ]
  for (const pattern of patterns) {
    const m = text.match(pattern)
    if (m?.[1]) return m[1]
  }
  const any = text.match(/(https?:\/\/[^\s]+)/)
  return any?.[1] || ''
}

function setPwdOnUrl(shareUrl: URL, pwd: string) {
  if (!pwd) return
  if (shareUrl.searchParams.get('pwd') || shareUrl.searchParams.get('passcode') || shareUrl.searchParams.get('accessCode')) return
  shareUrl.searchParams.set('pwd', pwd)
}

function setPwdOnCloud139ShareUrl(shareUrl: URL, pwd: string) {
  if (!pwd) return
  const rawHash = String(shareUrl.hash || '')
  if (!rawHash || !rawHash.includes('?')) {
    shareUrl.hash = rawHash ? `${rawHash}?pwd=${encodeURIComponent(pwd)}` : `#?pwd=${encodeURIComponent(pwd)}`
    return
  }
  const idx = rawHash.indexOf('?')
  const prefix = rawHash.slice(0, idx)
  const q = rawHash.slice(idx + 1)
  const params = new URLSearchParams(q)
  if (!params.get('pwd') && !params.get('passwd') && !params.get('passcode')) {
    params.set('pwd', pwd)
  }
  shareUrl.hash = `${prefix}?${params.toString()}`
}

function parseShareCode(shareLink: string) {
  let shareCode = ''
  let shareUrl: URL
  try {
    shareUrl = new URL(shareLink)
  } catch {
    return ''
  }

  if ((shareUrl.origin || '').includes('content.21cn.com')) {
    try {
      const hash = shareUrl.hash || ''
      const q = hash.includes('?') ? hash.split('?')[1] : ''
      const params = new URLSearchParams(q)
      shareCode = params.get('shareCode') || ''
    } catch {
      shareCode = ''
    }
  } else if (shareUrl.pathname === '/web/share') {
    shareCode = shareUrl.searchParams.get('code') || ''
  } else if (shareUrl.pathname.startsWith('/t/')) {
    const parts = shareUrl.pathname.split('/')
    shareCode = parts[parts.length - 1] || ''
  } else if (shareUrl.hash && shareUrl.hash.includes('/t/')) {
    const parts = shareUrl.hash.split('/')
    shareCode = parts[parts.length - 1] || ''
  } else if (shareUrl.pathname.includes('share.html')) {
    const parts = (shareUrl.hash || '').split('/')
    shareCode = parts[parts.length - 1] || ''
  }
  return shareCode
}

export function normalizeCloud189ShareUrl(input: string): Cloud189ShareParseResult | null {
  const raw = String(input || '').trim()
  if (!raw) return null

  let compact = raw.replace(/\s/g, '').replace(/？/g, '?').replace(/＆/g, '&')
  compact = safeDecodeURIComponent(compact)

  const { text: removed, pwd: textPwd } = extractPwdFromText(compact)
  const extractedUrl = extractCloud189Url(removed) || extractCloud189Url(compact) || ''
  if (!extractedUrl) return null

  let shareUrl: URL
  try {
    shareUrl = new URL(extractedUrl.replace(/？/g, '?').replace(/＆/g, '&'))
  } catch {
    return null
  }

  const shareCode = parseShareCode(shareUrl.toString()) || ''
  const existingPwd = shareUrl.searchParams.get('pwd') || shareUrl.searchParams.get('passcode') || shareUrl.searchParams.get('accessCode') || ''
  const pwd = textPwd || existingPwd || ''

  const host = String(shareUrl.host || '').toLowerCase()
  if (pwd) {
    if (host.includes('yun.139.com') || host.includes('caiyun.139.com')) {
      setPwdOnCloud139ShareUrl(shareUrl, pwd)
    } else {
      setPwdOnUrl(shareUrl, pwd)
    }
  }
  if (!shareCode) return { url: shareUrl.toString(), pwd, shareCode: '' }

  const hash = String(shareUrl.hash || '')
  const out = new URL(`https://cloud.189.cn/t/${shareCode}`)
  out.searchParams.set('code', shareCode)
  if (pwd) out.searchParams.set('pwd', pwd)
  if (hash) out.hash = hash
  return { url: out.toString(), pwd, shareCode }
}
