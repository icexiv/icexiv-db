// Path-based Medama v0.6.2 adapter for the domestic database.
(() => {
  if (location.origin !== 'https://db.icexiv.top'
    || navigator.doNotTrack === '1' || navigator.globalPrivacyControl === true
    || window.__icexivAnalytics) return
  window.__icexivAnalytics = true

  const api = '/_analytics/api/event/'
  const options = { credentials: 'omit', referrerPolicy: 'no-referrer' }
  const routes = new Set(['/items/index.html', '/docs/index.html', '/docs/game-data-rules.html', '/docs/item-categories.html'])
  let disabled = false
  let claimedVisitor = false
  let current
  let queue = Promise.resolve()

  function route() {
    const path = (location.pathname.replace(/\/+$/, '') || '/')
    if (path === '/' || path === '/index.html') return '/'
    if (path === '/items') return '/items/index.html'
    if (path === '/docs') return '/docs/index.html'
    if (/^\/items\/\d+\.html$/.test(path)) return '/items/detail'
    if (/^\/items\/page\/\d+\.html$/.test(path)) return '/items/page'
    // Only known pages are sent; never send arbitrary paths or query strings.
    return routes.has(path) ? path : '/other'
  }

  function referrer() {
    try {
      const url = new URL(document.referrer)
      return /^https?:$/.test(url.protocol) ? url.origin + '/' : ''
    } catch { return '' }
  }

  async function ping(suffix = '') {
    const response = await fetch(api + 'ping' + suffix, {
      ...options, signal: AbortSignal.timeout(3000),
    })
    if (!response.ok) throw new Error('collector unavailable')
    return (await response.text()).trim() === '0'
  }

  // Start once per document; Medama uses the HTTP cache to estimate daily visitors.
  const visitor = ping().catch(() => { disabled = true; return false })

  function pause(view) {
    if (view?.visibleSince != null) {
      view.duration += performance.now() - view.visibleSince
      view.visibleSince = null
    }
  }

  function duration(view) {
    const ms = Math.min(2147483647, Math.round(view.duration))
    if (!view.loaded || ms <= view.sentDuration || ms < 1) return
    const body = JSON.stringify({ b: view.id, e: 'unload', m: ms })
    try {
      void fetch(api + 'hit', {
        ...options, method: 'POST', body, keepalive: true,
        signal: AbortSignal.timeout(3000),
      }).catch(() => {})
      view.sentDuration = ms
    } catch { /* Analytics must never affect the site. */ }
  }

  function navigate() {
    const path = route()
    const previous = current
    pause(previous)
    if (previous) duration(previous)
    const view = {
      path, id: crypto.randomUUID(), url: location.origin + path,
      referrer: previous?.url || referrer(),
      duration: 0, visibleSince: document.hidden ? null : performance.now(),
      loaded: false, sentDuration: 0,
    }
    current = view
    queue = queue.then(async () => {
      const unique = await visitor
      if (disabled) return
      const first = await ping('?u=' + encodeURIComponent(location.hostname + view.path))
      const response = await fetch(api + 'hit', {
        ...options, method: 'POST', keepalive: true, signal: AbortSignal.timeout(3000),
        body: JSON.stringify({
          b: view.id, e: 'load', u: view.url, r: view.referrer,
          p: unique && !claimedVisitor, q: first,
          t: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }),
      })
      if (!response.ok) throw new Error('collector unavailable')
      claimedVisitor = true
      view.loaded = true
      if (view.visibleSince == null) duration(view)
    }).catch(() => { disabled = true })
  }

  document.addEventListener('visibilitychange', () => {
    if (!current) return
    if (document.hidden) {
      pause(current)
      duration(current)
    } else if (current.visibleSince == null) {
      current.visibleSince = performance.now()
    }
  })
  addEventListener('pagehide', () => { pause(current); if (current) duration(current) })
  addEventListener('pageshow', (event) => { if (event.persisted) navigate() })
  navigate()
})()
