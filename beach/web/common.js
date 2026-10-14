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
    if (who.id === null || who.id === undefined) box.append(svgNode(GUEST))
    else avatarSvg(who.id, who.v || 0).then(t => box.replaceChildren(svgNode(t)))
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

  return { api, el, svgNode, avatar, toast, start, whoAmI, token, minutes, ApiError, GUEST }
})()
