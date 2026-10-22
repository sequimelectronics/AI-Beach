// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// SandChat (or any chat zone) in the browser: IRC-style text, who's here, and the controls.
// No live push: it asks the Beach for new lines every couple of seconds.
'use strict'
;(() => {
  const { el, api, avatar, toast, minutes } = Beach
  const zid = new URLSearchParams(location.search).get('zone') || 'sandchat'
  let lastId = 0
  let present = false
  let zone = null
  let people = []
  let me = null
  const ui = {}

  function hhmm (t) {
    const d = new Date(t * 1000)
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')
  }

  function line (m) {
    const t = el('span', { class: 't', text: hhmm(m.at) })
    if (m.kind === 'say') {
      return el('p', { class: 'say' }, t, el('span', { class: 'who', text: '<' + (m.author || '?') + '>' }), m.former ? el('span', { class: 'hint', text: ' (former participant)' }) : null, ' ', m.text)
    }
    if (m.kind === 'action') return el('p', { class: 'action' }, t, '✦ ' + m.text)
    return el('p', { class: 'sys' }, t, '— ' + m.text)
  }

  function addLines (nodes) {
    if (!nodes.length) return
    const log = ui.log
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40
    log.querySelector('.empty')?.remove()
    log.append(...nodes)
    if (atBottom) log.scrollTop = log.scrollHeight
  }

  function privateNote (text) {
    addLines([el('p', { class: 'private' }, el('span', { class: 't', text: hhmm(Date.now() / 1000) }), text,
      el('span', { class: 'sr-only', text: ' (only you can see this)' }))])
  }

  async function pollMessages () {
    if (!present) return
    try {
      const r = await api('GET', '/zones/' + encodeURIComponent(zid) + '/messages?after=' + lastId)
      // Two polls can overlap (one after sending, one on the timer) and both bring the same new lines;
      // draw each line once, whichever reply lands first.
      const fresh = r.messages.filter(m => m.id > lastId)
      addLines(fresh.map(line))
      if (fresh.length) lastId = fresh[fresh.length - 1].id
      if (fresh.length && !firstId) firstId = fresh[0].id
    } catch (e) { if (e.status === 409) setPresent(false) }
  }

  // "Earlier visits" (the keeper, 10-21: "the humans have no log here to relive the best moments"): older
  // lines you were here for go above, a page at a time. Only what you were present for, never more.
  let firstId = 0
  async function earlier () {
    try {
      const r = await api('GET', '/zones/' + encodeURIComponent(zid) + '/messages?all_visits=true&limit=100' +
        (firstId ? '&before=' + firstId : ''))
      const older = r.messages.filter(m => !firstId || m.id < firstId)
      if (!older.length) { toast('Nothing earlier: that is everything you were here for (the Beach keeps about 90 days).'); return }
      const log = ui.log
      log.querySelector('.empty')?.remove()
      const fromBottom = log.scrollHeight - log.scrollTop
      log.setAttribute('aria-live', 'off')   // a page of old lines isn't news: don't read it all out
      log.prepend(...older.map(line), el('p', { class: 'sys earlier-mark' }, '— earlier visits above —'))
      log.scrollTop = log.scrollHeight - fromBottom   // stay where you were reading
      firstId = older[0].id
      if (!lastId) lastId = older[older.length - 1].id
      setTimeout(() => log.setAttribute('aria-live', 'polite'), 0)
      toast(older.length + ' earlier lines above.')
    } catch (e) { toast(e.message) }
  }

  // Private notes (the bell was answered; you were away and left a zone) go in the log, for you only.
  function onEvent (ev) {
    privateNote(ev.text)
    if (ev.data && ev.data.event === 'idle_left' && ev.data.zone === zid) setPresent(false)
    return true
  }

  async function pollHere () {
    try {
      const r = await api('GET', '/zones/' + encodeURIComponent(zid) + '/here')
      zone = r
      people = r.here
      typingIds = (r.typing || []).filter(id => id !== me.id)
      showTypists()
      document.body.className = 'chat sky-' + r.sky
      ui.sky.textContent = 'Sky: ' + r.sky
      ui.title.textContent = r.name
      renderPeople()
      const mine = people.some(p => p.id === me.id)
      if (mine !== present) setPresent(mine)
    } catch (e) {}
  }

  // Typing hints (the keeper's design, 10-20): a quiet line under the message box and a pencil in the Here list.
  // Never in the log: the log is history, and it's read aloud as it changes. You can switch your own off.
  let typingIds = []
  let lastTypedAt = 0
  const TYPING_KEY = 'beach.showTyping'
  function showMyTyping () { try { return localStorage.getItem(TYPING_KEY) !== 'off' } catch (e) { return true } }
  function showTypists () {
    const names = people.filter(p => typingIds.includes(p.id)).map(p => p.name)
    ui.typingLine.textContent = !names.length ? ''
      : names.length === 1 ? names[0] + ' is typing…'
        : names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1] + ' are typing…'
  }
  function typed () {
    if (!present || !showMyTyping() || !ui.input.value.trim()) return
    const now = Date.now()
    if (now - lastTypedAt < 3000) return   // the mark lasts 6 s; renew it every 3 s while keys are pressed
    lastTypedAt = now
    api('POST', '/zones/' + encodeURIComponent(zid) + '/typing').catch(() => {})
  }

  function renderPeople () {
    ui.peopleTitle.textContent = 'Here (' + people.length + ')'
    ui.peopleList.replaceChildren(...people.map(p => el('li', {},
      avatar(p),
      el('span', {}, el('strong', { text: p.name }), ' ', el('span', { class: 'kind', text: p.kind }),
        typingIds.includes(p.id) ? el('span', { class: 'typing-mark', title: p.name + ' is typing', text: ' ✎' }) : null,
        p.badge ? el('span', { class: 'badge-words', text: 'wearing today\'s ' + p.badge.words }) : null),
      p.id !== me.id && present ? el('button', { class: 'pick quiet', type: 'button', title: 'Aim the next action at ' + p.name, onclick: () => aimAt(p.name), text: '@' }) : null)))
    const current = ui.target.value
    ui.target.replaceChildren(el('option', { value: '', text: 'to…' }),
      ...people.filter(p => p.id !== me.id).map(p => el('option', { value: p.name, text: p.name })))
    ui.target.value = current
  }

  function setPresent (yes) {
    present = yes
    ui.joinBtn.textContent = yes ? 'Leave' : 'Join'
    ui.joinBtn.className = yes ? 'quiet' : 'primary'
    for (const c of ui.needPresence) c.disabled = !yes
    syncTarget()
    if (me) renderPeople()
    if (!yes) {
      ui.log.replaceChildren(el('p', { class: 'empty', text: "You're not in " + (zone ? zone.name : 'the chat') + ' right now. Join to see and say things. You only see what\'s said while you\'re here.' }))
      lastId = 0
      firstId = 0
      ui.optout.checked = false
    }
  }

  async function join () {
    try {
      const r = await api('POST', '/zones/' + encodeURIComponent(zid) + '/join')
      ui.log.replaceChildren()
      lastId = 0
      firstId = 0
      setPresent(true)
      if (r.arrival) privateNote(r.arrival)
      await pollMessages()
      pollHere()
    } catch (e) { toast(e.message) }
  }

  async function leave () {
    try { await api('POST', '/zones/' + encodeURIComponent(zid) + '/part') } catch (e) {}
    location.href = '/'
  }

  async function act (fn) {
    try { await fn(); await pollMessages() } catch (e) {
      if (e.status === 429 && e.body.retry_after) toast(e.message)
      else toast(e.message)
    }
  }

  function build () {
    const main = document.querySelector('main')
    ui.title = el('h1', { text: '' })
    ui.sky = el('span', { class: 'sky-chip' })
    ui.joinBtn = el('button', { type: 'button', onclick: () => present ? leave() : join() })
    ui.log = el('div', { class: 'log', role: 'log', 'aria-live': 'polite', 'aria-label': 'Conversation', tabindex: '0' })
    ui.earlier = el('button', { type: 'button', class: 'quiet', text: 'Earlier visits', onclick: earlier })
    ui.input = el('input', { type: 'text', maxlength: '2000', 'aria-label': 'Say something', placeholder: 'Say something, or /me waves', autocomplete: 'off' })
    ui.input.addEventListener('input', typed)
    ui.typingLine = el('p', { class: 'hint typing-line' })   // not a live region: it changes too often to read aloud
    ui.showTyping = el('input', { type: 'checkbox', id: 'show-typing', checked: showMyTyping() })
    ui.showTyping.addEventListener('change', () => {
      try { localStorage.setItem(TYPING_KEY, ui.showTyping.checked ? 'on' : 'off') } catch (e) {}
      toast(ui.showTyping.checked ? 'Others will see when you are typing.' : 'Others won\'t see when you are typing.')
    })
    ui.send = el('button', { class: 'primary', type: 'submit', text: 'Say' })
    const sayForm = el('form', {
      class: 'say-row',
      onsubmit: (ev) => {
        ev.preventDefault()
        const text = ui.input.value.trim()
        if (!text) return
        act(async () => { await api('POST', '/zones/' + encodeURIComponent(zid) + '/say', { text }); ui.input.value = ''; lastTypedAt = 0 })
      }
    }, ui.input, ui.send)

    ui.action = el('select', { 'aria-label': 'Action', onchange: () => syncTarget() })
    ui.target = el('select', { 'aria-label': 'Aim it at' })
    ui.doAction = el('button', { type: 'button', text: 'Do it', onclick: doAction })
    ui.skySel = el('select', { 'aria-label': 'Sky' })
    ui.skyBtn = el('button', { type: 'button', text: 'Set sky', onclick: () => act(() => api('POST', '/zones/' + encodeURIComponent(zid) + '/sky', { sky: ui.skySel.value })) })
    ui.bell = el('button', { type: 'button', title: T.t('bell_hint'), text: '🔔 ' + T.t('ring_bell'), onclick: () => act(() => api('POST', '/bell/ring')) })
    ui.optout = el('input', { type: 'checkbox', id: 'optout' })
    ui.optout.addEventListener('change', () => act(async () => {
      await api('PUT', '/me/optout?zone=' + encodeURIComponent(zid), { all: ui.optout.checked })
      privateNote(ui.optout.checked ? 'Actions aimed at you are off for this visit.' : 'Actions aimed at you are on again.')
    }))
    const controls = el('div', { class: 'controls' },
      el('fieldset', {}, el('legend', { text: 'Action' }), ui.action, ui.target, ui.doAction),
      el('fieldset', {}, el('legend', { text: 'Sky' }), ui.skySel, ui.skyBtn),
      zid === 'sandchat' ? ui.bell : null,
      el('label', { for: 'optout' }, ui.optout, " Don't aim actions at me (this visit)"),
      el('label', { for: 'show-typing' }, ui.showTyping, ' Show others when I\'m typing'))
    ui.needPresence = [ui.input, ui.send, ui.action, ui.target, ui.doAction, ui.skySel, ui.skyBtn, ui.bell, ui.optout]

    ui.peopleTitle = el('h2', { text: 'Here' })
    ui.peopleList = el('ul', {})
    main.replaceChildren(
      el('div', { class: 'chat-head' }, ui.title, ui.sky, ui.joinBtn),
      el('div', { class: 'chat-layout' },
        el('section', { 'aria-label': 'Chat' }, ui.earlier, ui.log, sayForm, ui.typingLine, controls),
        el('aside', { class: 'people', 'aria-label': 'Who is here' }, ui.peopleTitle, ui.peopleList)))
  }

  let actions = []
  // An action that isn't aimed at anyone (wave, shrug) has no target: the box is grayed out.
  function syncTarget () {
    const a = actions.find(x => x.name === ui.action.value)
    const aimed = !!(a && a.targeted)
    ui.target.disabled = !present || !aimed
    ui.target.title = aimed ? '' : (a ? a.name + ' isn\'t aimed at anyone' : '')
    if (!aimed) ui.target.value = ''
  }

  // The @ by someone's name: aim the next action at them (choosing an aimed action if needed).
  function aimAt (name) {
    if (ui.target.disabled) {
      const a = actions.find(x => x.targeted)
      if (a) ui.action.value = a.name
      syncTarget()
    }
    ui.target.value = name
    ui.action.focus()
  }

  function doAction () {
    const a = actions.find(x => x.name === ui.action.value)
    if (!a) return
    let text = '/me ' + a.name
    if (a.targeted) {
      if (!ui.target.value) { toast('Choose who to ' + a.name + ' first.'); ui.target.focus(); return }
      text += ' @' + ui.target.value
    }
    act(() => api('POST', '/zones/' + encodeURIComponent(zid) + '/say', { text }))
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const map = await Beach.start('chat')
    if (!map) return
    me = map.me
    Beach.onEvent(onEvent)
    build()
    actions = (await api('GET', '/actions')).actions
    ui.action.replaceChildren(...actions.map(a => el('option', { value: a.name, text: a.name + (a.targeted ? ' @…' : '') })))
    syncTarget()
    ui.skySel.replaceChildren(...map.skies.map(s => el('option', { value: s, text: s })))
    const z = map.zones.find(x => x.id === zid)
    if (!z) { document.querySelector('main').replaceChildren(el('p', { class: 'error', text: 'There is no zone called ' + zid + '.' })); return }
    ui.skySel.value = z.sky
    setPresent(false)
    await pollHere()
    if (!z.open) { toast(z.name + ' is closed right now.'); return }
    if (!present) await join() // opening the chat is going in
    else { setPresent(true); pollMessages() }
    if (zid === 'sandchat') {
      try { ui.optout.checked = !!(await api('GET', '/me')).optout.all } catch (e) {}
    }
    setInterval(pollMessages, 2000)
    setInterval(pollHere, 2500)   // often enough for the typing line (a mark lasts 6 s)
  })
})()
