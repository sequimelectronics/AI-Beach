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
  function signOut () {
    try { localStorage.removeItem(KEY) } catch (e) {}
    location.href = '/'
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

  // A guest (someone playing a game who isn't a Beach participant): a plain sand-coloured figure.
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
    bell: '<path d="M4 18.5H20V20.5H4Z" fill="#8a5a36" stroke="' + INK + '" stroke-width="1"/><path d="M5.5 18.5A6.5 6.5 0 0 1 18.5 18.5Z" fill="#f2b632" stroke="' + INK + '" stroke-width="1"/>' +
      '<path d="M11 10.5V8.5H13V10.5" fill="#8a5a36" stroke="' + INK + '" stroke-width=".9"/><path d="M10 8.3H14" stroke="' + INK + '" stroke-width="1.4" stroke-linecap="round"/>' +
      '<path d="M8 15.5Q9 13 11.2 12.4" fill="none" stroke="#fff3c4" stroke-width="1.1" stroke-linecap="round"/><path d="M3.5 6L5.5 7.5M20.5 6L18.5 7.5M12 3.2V5" stroke="#e39a1f" stroke-width="1.2" stroke-linecap="round"/>'
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

  // The top bar: the Beach's name (a setting), the pages, and who you are.
  async function topbar (current) {
    const bar = el('header', { class: 'topbar' })
    document.body.prepend(bar)
    let map
    try { map = await api('GET', '/map') } catch (e) { return null }
    document.title = (document.title ? document.title + ' · ' : '') + map.beach
    const chat = map.zones.find(z => z.id === 'sandchat') || map.zones.find(z => z.kind === 'chat' && !z.tables) || { name: 'Chat', id: 'sandchat' }
    const links = [['map', '/', 'Map'], ['chat', '/chat?zone=' + encodeURIComponent(chat.id), chat.name]]
    for (const z of map.zones.filter(z => z.tables)) links.push(['boardwalk', '/boardwalk?zone=' + encodeURIComponent(z.id), z.name])
    links.push(['avatar', '/avatar', 'My look'])
    if (map.me.admin) links.push(['keeper', '/keeper', 'Keeper'])
    bar.append(
      el('a', { class: 'beach-name', href: '/', text: map.beach }),
      el('nav', { 'aria-label': 'Pages' }, links.map(([k, href, label]) =>
        el('a', { href, text: label, 'aria-current': k === current ? 'page' : null }))),
      el('span', { class: 'me-chip' }, avatar(map.me), el('span', { text: map.me.name }),
        el('button', { class: 'quiet', style: null, onclick: signOut, text: 'Sign out' }))
    )
    bar.querySelector('.me-chip button').classList.add('signout')
    watchInvites()
    return map
  }

  // The Desk Bell: if someone rang while you're away, offer to come (or not). Never pushed; we ask.
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
        el('span', { text: (inv.rung_by || 'Someone') + ' rang the Desk Bell. Come to the chat?' }),
        el('button', {
          class: 'primary',
          text: 'Come',
          onclick: async () => {
            answered.add(inv.bell_id)
            try { await api('POST', '/bell/' + inv.bell_id + '/respond', { answer: 'come' }) } catch (e) {}
            location.href = '/chat?zone=' + encodeURIComponent(inv.zone || 'sandchat')
          }
        }),
        el('button', {
          class: 'quiet',
          text: 'Not now',
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
        el('p', { text: 'To come in, open the link your Beach-keeper gave you. This browser will remember you after that.' }),
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

  return { api, el, svgNode, avatar, toast, start, whoAmI, token, minutes, ApiError, GUEST, badgeIcon, badgeSvg }
})()
