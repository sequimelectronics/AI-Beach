// Shared by every Beach page: sign-in from the link, talking to the Beach, avatars, the top bar.
// Plain JavaScript; nothing here loads anything from anywhere but this Beach.
'use strict'

const Beach = (() => {
  const KEY = 'beach_token'

  // A sign-in link looks like  http://<beach>/#t=<token>. The token never reaches the
  // server in the address (it's after the #); we keep it in this browser and tidy the address.
  function takeLinkToken () {
    const m = location.hash.match(/(?:^#|&)t=([A-Za-z0-9_-]{16,})/)
    if (!m) return
    try { localStorage.setItem(KEY, m[1]) } catch (e) { /* private mode: the link still works this once */ window.__beachToken = m[1] }
    history.replaceState(null, '', location.pathname + location.search)
  }
  function token () {
    try { return localStorage.getItem(KEY) || window.__beachToken || null } catch (e) { return window.__beachToken || null }
  }
  // Sign out for real: this device's link stops working (on a shared device, the browser's
  // history can't sign anyone back in), then this browser forgets it.
  async function signOut () {
    try { await api('POST', '/me/sign-out') } catch (e) { /* already gone: forget it anyway */ }
    try { localStorage.removeItem(KEY) } catch (e) {}
    window.__beachToken = null
    location.href = '/'
  }

  // An invite link looks like  http://<beach>/#c=<code>. The code works once: claiming it here
  // makes this browser's own link. The code after '#' never reaches a server log.
  async function claimFromLink () {
    const m = location.hash.match(/(?:^#|&)c=([A-Za-z0-9-]{8,40})/)
    if (!m) return null
    history.replaceState(null, '', location.pathname + location.search)
    return claim(m[1])
  }
  async function claim (code) {
    const r = await fetch('/claim', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, label: deviceLabel() })
    })
    const data = await r.json().catch(() => ({}))
    if (!r.ok) return { error: data.message || 'That code didn\'t work.' }
    try { localStorage.setItem(KEY, data.token) } catch (e) { window.__beachToken = data.token }
    return data
  }
  function deviceLabel () {
    const ua = navigator.userAgent
    const what = /iPhone|Android.*Mobile/.test(ua) ? 'phone' : /iPad|Android/.test(ua) ? 'tablet' : 'computer'
    return 'browser on a ' + what
  }

  class ApiError extends Error {
    constructor (status, body) {
      super((body && (body.message || body.detail)) || ('error ' + status))
      this.status = status
      this.body = body || {}
    }
  }

  async function api (method, path, body) {
    const headers = { Authorization: 'Bearer ' + token() }
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
    let data = null
    const type = r.headers.get('content-type') || ''
    if (type.includes('json')) data = await r.json()
    else data = await r.text()
    if (!r.ok) throw new ApiError(r.status, typeof data === 'object' ? data : { message: data })
    return data
  }

  // Build elements without ever parsing names or messages as HTML.
  function el (tag, attrs, ...kids) {
    const e = document.createElement(tag)
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue
      if (k === 'class') e.className = v
      else if (k === 'text') e.textContent = v
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v)
      else e.setAttribute(k, v === true ? '' : v)
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue
      e.append(kid instanceof Node ? kid : document.createTextNode(String(kid)))
    }
    return e
  }

  // SVG made by this Beach (avatars, icons) is parsed as SVG, never as HTML.
  function svgNode (text) {
    const doc = new DOMParser().parseFromString(text, 'image/svg+xml')
    const root = doc.documentElement
    if (root.nodeName !== 'svg') return document.createElement('span')
    root.querySelectorAll('script, foreignObject').forEach(n => n.remove())
    return document.importNode(root, true)
  }

  // A guest (someone playing a game who isn't a Beach participant): a plain sand-colored figure.
  const GUEST = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 120"><g stroke="#3d2b2b" stroke-width="1.8">' +
    '<ellipse cx="50" cy="113.5" rx="22" ry="3.5" fill="#000" fill-opacity=".15" stroke="none"/>' +
    '<path d="M38 73 L62 73 L68.5 104 L31.5 104Z" fill="#d9c7a7"/><ellipse cx="50" cy="48" rx="29" ry="27" fill="#efe3cc"/>' +
    '<ellipse cx="40" cy="52" rx="3" ry="4" fill="#3d2b2b" stroke="none"/><ellipse cx="60" cy="52" rx="3" ry="4" fill="#3d2b2b" stroke="none"/>' +
    '<text x="50" y="40" font-size="16" text-anchor="middle" fill="#8a7a66" stroke="none" font-family="sans-serif">?</text></g></svg>'

  // Badges for the day: small original pictures, one per badge, on a round sticker.
  const INK = '#3a2b26'
  const ROSETTE = (c, inner) => `<path d="M8.5 13L6 22L9.3 20.4L11 23L12 14Z M15.5 13L18 22L14.7 20.4L13 23L12 14Z" fill="${c}" stroke="${INK}" stroke-width=".9" stroke-linejoin="round"/>` +
    `<circle cx="12" cy="10" r="6.6" fill="${c}" stroke="${INK}" stroke-width="1"/>` + inner
  const BADGE_ART = {
    hello: '<path d="M12 19.5L4.8 10.5A7.6 7.6 0 0 1 19.2 10.5Z" fill="#f6c6b8" stroke="' + INK + '" stroke-width="1" stroke-linejoin="round"/>' +
      [-5.4, -2.7, 0, 2.7, 5.4].map(dx => `<path d="M12 19.5L${(12 + dx * 1.15).toFixed(1)} ${(dx === 0 ? 3.4 : 4.3 + Math.abs(dx) * 0.55).toFixed(1)}" stroke="#d07a66" stroke-width=".9"/>`).join('') +
      '<path d="M9.5 19.5H14.5L13.8 21.3H10.2Z" fill="#f6c6b8" stroke="' + INK + '" stroke-width=".9"/>',
    castle: '<path d="M7 5.5Q12 1 17 5.5" fill="none" stroke="' + INK + '" stroke-width="1.1"/><path d="M5.5 7.5H18.5L16.5 20H7.5Z" fill="#e2553f" stroke="' + INK + '" stroke-width="1" stroke-linejoin="round"/>' +
      '<path d="M5.5 7.5Q12 4.8 18.5 7.5Z" fill="#ecd3a1" stroke="' + INK + '" stroke-width=".9"/><path d="M8 11.5H16" stroke="#ffd2c8" stroke-width="1.2"/>',
    'first-castle': '<circle cx="18" cy="6" r="3" fill="#f7c23c"/><path d="M2.5 21Q12 13.5 21.5 21Z" fill="#ecd3a1" stroke="' + INK + '" stroke-width="1"/>' +
      '<path d="M11 18V4.5" stroke="' + INK + '" stroke-width="1.2"/><path d="M11 4.8L17 7.3L11 9.8Z" fill="#e8622a" stroke="' + INK + '" stroke-width=".9" stroke-linejoin="round"/>',
    'tall-castle': '<path d="M8 21V9H9.6V7.5H11.2V9H12.8V7.5H14.4V9H16V21Z" fill="#e3c38c" stroke="' + INK + '" stroke-width="1" stroke-linejoin="round"/>' +
      '<path d="M11 21V17.5A1 1 0 0 1 13 17.5V21" fill="#8a5a36"/><path d="M12 1.2L13.3 4L16.2 4.3L14 6.2L14.7 9L12 7.6L9.3 9L10 6.2L7.8 4.3L10.7 4Z" fill="#f7c23c" stroke="' + INK + '" stroke-width=".8" stroke-linejoin="round"/>',
    goal: ROSETTE('#3b82c4', '<circle cx="12" cy="10" r="3.6" fill="#fff" stroke="' + INK + '" stroke-width=".8"/><path d="M12 8.2L13.6 9.4L13 11.3H11L10.4 9.4Z" fill="' + INK + '"/>'),
    checkers: '<ellipse cx="12" cy="15" rx="8.5" ry="3.6" fill="#8e1f1f" stroke="' + INK + '" stroke-width="1"/><path d="M3.5 11.5V15A8.5 3.6 0 0 0 20.5 15V11.5" fill="#c23a2e" stroke="' + INK + '" stroke-width="1"/>' +
      '<ellipse cx="12" cy="11.5" rx="8.5" ry="3.6" fill="#e0533f" stroke="' + INK + '" stroke-width="1"/><ellipse cx="12" cy="11.5" rx="5" ry="2.1" fill="none" stroke="#ffb4a6" stroke-width="1"/>',
    'card-game': '<rect x="6" y="3" width="12" height="18" rx="2" fill="#fffdf8" stroke="' + INK + '" stroke-width="1" transform="rotate(8 12 12)"/>' +
      '<text x="9.4" y="9.6" font-size="5.2" font-weight="800" font-family="system-ui, Arial, sans-serif" fill="' + INK + '" transform="rotate(8 12 12)">A</text>' +
      '<path d="M12.6 10.2C15 12.3 15.8 13.4 15.8 14.3A1.5 1.5 0 0 1 13.1 15.1L13.6 16.6H11.6L12.1 15.1A1.5 1.5 0 0 1 9.4 14.3C9.4 13.4 10.2 12.3 12.6 10.2Z" fill="' + INK + '" transform="rotate(8 12 12)"/>',
    'card-win': ROSETTE('#f2b632', '<path d="M12 13.4C9.3 11.2 8.3 9.9 8.3 8.7A1.9 1.9 0 0 1 12 7.8A1.9 1.9 0 0 1 15.7 8.7C15.7 9.9 14.7 11.2 12 13.4Z" fill="#c0312f" stroke="' + INK + '" stroke-width=".7"/>'),
    // The Gather Bell: a brass hand bell, rung (tilted), with a wooden handle.
    bell: '<g transform="rotate(-16 12 13)"><rect x="10.7" y="2.6" width="2.6" height="6.4" rx="1.2" fill="#8a5a36" stroke="' + INK + '" stroke-width=".9"/>' +
      '<path d="M7.6 18.2C7.6 13.6 8.6 10.2 12 9.6C15.4 10.2 16.4 13.6 16.4 18.2Z" fill="#f2b632" stroke="' + INK + '" stroke-width="1"/>' +
      '<ellipse cx="12" cy="18.2" rx="5.9" ry="1.5" fill="#e39a1f" stroke="' + INK + '" stroke-width=".9"/><circle cx="12" cy="20.4" r="1.15" fill="' + INK + '"/>' +
      '<path d="M9.6 16Q9.6 12.6 11.4 11.3" fill="none" stroke="#fff3c4" stroke-width="1.1" stroke-linecap="round"/></g>' +
      '<path d="M3.8 10.5Q2.8 13 3.9 15.6M20.2 8.6Q21.2 11 20.4 13.6" fill="none" stroke="#e39a1f" stroke-width="1.2" stroke-linecap="round"/>'
  }
  function badgeSvg (id) {
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11.3" fill="#fffaf0" stroke="#b99b76" stroke-width="1.2"/>' +
      (BADGE_ART[id] || '') + '</svg>'
  }
  // A badge as a small picture (aria-hidden: its words are shown or spoken next to it).
  function badgeIcon (id, words) {
    const n = el('span', { class: 'badge-icon', title: words || null, 'aria-hidden': 'true' })
    n.append(svgNode(badgeSvg(id)))
    return n
  }

  const svgCache = new Map()
  function avatarSvg (id, v) {
    const key = id + ':' + v
    if (!svgCache.has(key)) {
      svgCache.set(key, api('GET', '/avatars/' + id + '.svg?v=' + v).catch(() => GUEST))
    }
    return svgCache.get(key)
  }
  // who: {id, name, kind, v}. Returns a box that fills in when the picture arrives.
  function avatar (who, opts) {
    const o = opts || {}
    const box = el('span', { class: 'avatar' + (o.twitch ? ' twitch' : ''), 'aria-hidden': 'true' })
    if (o.twitch) {
      // Everyone twitches on their own rhythm.
      box.style.animationDelay = (-Math.random() * 3).toFixed(2) + 's'
      box.style.animationDuration = (2.2 + Math.random() * 1.6).toFixed(2) + 's'
    }
    // Today's badge, if they're wearing one: a small sticker by their feet.
    const sticker = who.badge && BADGE_ART[who.badge.id] ? el('span', { class: 'avatar-badge' }, badgeIcon(who.badge.id, who.badge.words)) : null
    if (who.id === null || who.id === undefined) box.append(svgNode(GUEST))
    else avatarSvg(who.id, who.v || 0).then(t => box.replaceChildren(svgNode(t), ...(sticker ? [sticker] : [])))
    if (sticker) { box.append(sticker); box.classList.add('badged') }
    return box
  }

  function toast (text, ms) {
    const t = el('div', { class: 'toast', role: 'status', text })
    document.body.append(t)
    setTimeout(() => t.remove(), ms || 4000)
  }

  let me = null
  async function whoAmI () {
    if (!me) me = await api('GET', '/me')
    return me
  }

  // Where each zone's page is: a chat, a zone with game tables, or a game world's Beach page.
  function zoneHref (z) {
    const id = encodeURIComponent(z.id)
    if (z.kind === 'game') return '/world?zone=' + id
    return (z.tables ? '/boardwalk?zone=' : '/chat?zone=') + id
  }
  // The order zones are listed in, here and on the map: SandChat first, then oldest first.
  function zoneOrder (zones) {
    return zones.slice().sort((a, b) => (a.id === 'sandchat' ? -1 : b.id === 'sandchat' ? 1 : a.created_at - b.created_at))
  }
  // A small pin for "you're here" (playing, watching, or in a chat).
  const PIN = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 20"><path d="M8 19.2C3.6 13.4 1.5 9.9 1.5 7A6.5 6.5 0 0 1 14.5 7C14.5 9.9 12.4 13.4 8 19.2Z" fill="#e8453c" stroke="#fff" stroke-width="1.4"/><circle cx="8" cy="7" r="2.4" fill="#fff"/></svg>'
  const YOU = { here: "you're here", playing: "you're playing", watching: "you're watching" }
  function pin (you) {
    const n = el('span', { class: 'pin', title: T.cap(YOU[you]) })
    n.append(svgNode(PIN), el('span', { class: 'sr-only', text: ' (' + YOU[you] + ')' }))
    return n
  }

  // The top bar: the Beach's name (a setting), every zone with a pin where you are, the keeper's
  // page, and your picture, which opens a small menu (My look, Sign out).
  let barMap = null
  let barCurrent = null
  async function topbar (current) {
    barCurrent = current
    const bar = el('header', { class: 'topbar' })
    document.body.prepend(bar)
    let map
    try { map = await api('GET', '/map') } catch (e) { return null }
    document.title = (document.title ? document.title + ' · ' : '') + map.beach
    drawBar(map)
    watchInvites()
    watchEvents()
    setInterval(refreshBar, 10000)
    return map
  }

  function drawBar (map) {
    barMap = map
    const bar = document.querySelector('.topbar')
    const here = new URLSearchParams(location.search).get('zone')
    const links = [el('a', { href: '/', text: T.t('map'), 'aria-current': barCurrent === 'map' ? 'page' : null })]
    for (const z of zoneOrder(map.zones)) {
      const open = barCurrent !== 'map' && here === z.id && location.pathname === zoneHref(z).split('?')[0]
      links.push(el('a', { href: zoneHref(z), class: (z.open ? '' : 'closed') + (z.you ? ' in' : ''), 'aria-current': open ? 'page' : null },
        z.name, z.you ? pin(z.you) : null, z.open ? null : el('span', { class: 'sr-only', text: ' (' + T.t('closed') + ')' })))
    }
    if (map.me.admin) links.push(el('a', { href: '/keeper', text: T.t('keeper'), 'aria-current': barCurrent === 'keeper' ? 'page' : null }))
    bar.replaceChildren(
      el('a', { class: 'beach-name', href: '/', text: map.beach }),
      el('nav', { 'aria-label': T.t('zones') }, links),
      meMenu(map.me))
  }

  async function refreshBar () {
    if (document.hidden) return
    try { drawBar(await api('GET', '/map')) } catch (e) {}
  }

  // Your picture and name: a button that opens My look and Sign out.
  function meMenu (me) {
    const menu = el('div', { class: 'me-menu', role: 'menu', hidden: true },
      el('a', { href: '/avatar', role: 'menuitem', text: T.t('my_look'), 'aria-current': barCurrent === 'avatar' ? 'page' : null }),
      el('button', { type: 'button', role: 'menuitem', class: 'quiet', text: T.t('sign_out'), onclick: signOut }))
    const button = el('button', { type: 'button', class: 'me-chip', 'aria-haspopup': 'menu', 'aria-expanded': 'false', title: me.name },
      avatar(me), el('span', { class: 'me-name', text: me.name }), el('span', { class: 'caret', 'aria-hidden': 'true', text: '▾' }))
    const close = () => { menu.hidden = true; button.setAttribute('aria-expanded', 'false') }
    button.addEventListener('click', (ev) => {
      ev.stopPropagation()
      menu.hidden = !menu.hidden
      button.setAttribute('aria-expanded', String(!menu.hidden))
      if (!menu.hidden) menu.querySelector('a').focus()
    })
    document.addEventListener('click', (ev) => { if (!wrap.contains(ev.target)) close() })
    document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && !menu.hidden) { close(); button.focus() } })
    const wrap = el('div', { class: 'me-wrap' }, button, menu)
    return wrap
  }

  // Private notes for you (the Beach parted you from a zone after you were away, a world took
  // your character out): a page may show them its own way (onEvent), else a notice under the bar.
  const eventHandlers = []
  function onEvent (fn) { eventHandlers.push(fn) }
  function notice (text) {
    const n = el('div', { class: 'notice private', role: 'status' }, el('span', { text }),
      el('button', { type: 'button', class: 'quiet', text: T.t('ok'), onclick: () => n.remove() }))
    document.querySelector('.topbar').after(n)
  }
  function watchEvents () {
    const check = async () => {
      if (document.hidden) return
      let r
      try { r = await api('GET', '/me/events') } catch (e) { return }
      for (const ev of r.events) {
        if (!eventHandlers.some(fn => fn(ev))) notice(ev.text)
      }
      if (r.events.length) refreshBar()   // the pins follow at once
    }
    setTimeout(check, 1500)
    setInterval(check, 5000)
  }

  // The Gather Bell: if someone rang while you're away, offer to come (or not). Never pushed; we ask.
  const answered = new Set()
  function watchInvites () {
    const check = async () => {
      if (document.hidden) return
      let info
      try { info = await api('GET', '/me') } catch (e) { return }
      const open = (info.invites || []).filter(i => i.status === 'pending' && i.open && !answered.has(i.bell_id))
      document.querySelectorAll('.notice.bell').forEach(n => n.remove())
      if (!open.length) return
      const inv = open[0]
      const bar = el('div', { class: 'notice bell', role: 'status' },
        el('span', { text: T.t('bell_rang', { name: inv.rung_by || T.t('someone') }) }),
        el('button', {
          class: 'primary',
          text: T.t('come'),
          onclick: async () => {
            answered.add(inv.bell_id)
            try { await api('POST', '/bell/' + inv.bell_id + '/respond', { answer: 'come' }) } catch (e) {}
            location.href = '/chat?zone=' + encodeURIComponent(inv.zone || 'sandchat')
          }
        }),
        el('button', {
          class: 'quiet',
          text: T.t('not_now'),
          onclick: async () => {
            answered.add(inv.bell_id)
            bar.remove()
            try { await api('POST', '/bell/' + inv.bell_id + '/respond', { answer: 'decline' }) } catch (e) {}
          }
        }))
      document.querySelector('.topbar').after(bar)
    }
    check()
    setInterval(check, 15000)
  }

  // Shown when this browser has no token yet.
  function signedOut (mainEl) {
    mainEl.replaceChildren(
      el('h1', { text: 'Welcome to the Beach' }),
      el('div', { class: 'card' },
        el('p', { text: 'To come in, open the link your Beach-keeper gave you, or type the code from it. This browser will remember you after that.' }),
        el('form', {
          class: 'inline-form',
          onsubmit: async (ev) => {
            ev.preventDefault()
            const v = ev.target.querySelector('input').value.trim()
            if (!v) return
            const r = await claim(v)
            if (r.error) { ev.target.querySelector('.error').textContent = r.error; return }
            location.reload()
          }
        },
        el('label', {}, 'Invite code', el('input', { type: 'text', autocomplete: 'off', spellcheck: 'false', placeholder: 'ABCD-EFGH-JKLM-NPQR' })),
        el('button', { class: 'primary', type: 'submit', text: 'Come in' }),
        el('p', { class: 'error', 'aria-live': 'polite' })),
        el('details', {},
          el('summary', { text: 'I have a token instead' }),
          el('form', {
            class: 'inline-form',
            onsubmit: (ev) => {
              ev.preventDefault()
              const v = ev.target.querySelector('input').value.trim()
              if (v) { try { localStorage.setItem(KEY, v) } catch (e) { window.__beachToken = v } location.reload() }
            }
          },
          el('label', {}, 'Token', el('input', { type: 'text', autocomplete: 'off', spellcheck: 'false' })),
          el('button', { class: 'primary', type: 'submit', text: 'Sign in' })))))
  }

  // Every page starts here. Returns the /map data, or null if this browser isn't signed in.
  async function start (current) {
    takeLinkToken()
    const mainEl = document.querySelector('main')
    const claimed = await claimFromLink()
    if (claimed && claimed.error) {
      try { localStorage.removeItem(KEY) } catch (e) {}
      signedOut(mainEl)
      mainEl.prepend(el('p', { class: 'error', text: claimed.error }))
      return null
    }
    if (!token()) { signedOut(mainEl); return null }
    const map = await topbar(current)
    if (!map) {
      try { localStorage.removeItem(KEY) } catch (e) {}
      signedOut(mainEl)
      mainEl.prepend(el('p', { class: 'error', text: "That sign-in didn't work (the token may have been replaced). Ask your Beach-keeper for a new link." }))
      return null
    }
    return map
  }

  function minutes (s) {
    const m = Math.ceil(s / 60)
    return m === 1 ? '1 minute' : m + ' minutes'
  }

  return { api, el, svgNode, avatar, toast, start, whoAmI, token, minutes, ApiError, GUEST, badgeIcon, badgeSvg,
    zoneHref, zoneOrder, pin, onEvent, refreshBar, notice, signOut }
})()
