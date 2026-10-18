// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// SandChat beside a table or a game world: a tab on the right edge opens a side panel with the room,
// so a person watching or playing doesn't miss what's said there (first non-Claude visit, 10-17: a
// visitor's lines all went to SandChat while the keeper watched the table). It's the same SandChat, not a
// new channel: what you say here is said in SandChat. It asks for new lines only while it's open.
'use strict'
;(() => {
  const { el, api, toast } = Beach
  const ZONE = 'sandchat'
  const KEY = 'beach.sidechat.open'
  let lastId = 0
  let timer = null
  let present = false
  const ui = {}

  function hhmm (t) {
    const d = new Date(t * 1000)
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')
  }

  function line (m) {
    const t = el('span', { class: 't', text: hhmm(m.at) })
    if (m.kind === 'say') return el('p', { class: 'say' }, t, el('span', { class: 'who', text: '<' + (m.author || '?') + '>' }), ' ', m.text)
    if (m.kind === 'action') return el('p', { class: 'action' }, t, '✦ ' + m.text)
    return el('p', { class: 'sys' }, t, '— ' + m.text)
  }

  function remember (open) { try { localStorage.setItem(KEY, open ? '1' : '') } catch (e) {} }
  function remembered () { try { return localStorage.getItem(KEY) === '1' } catch (e) { return false } }

  async function poll () {
    if (!present) return
    try {
      const r = await api('GET', '/zones/' + ZONE + '/messages?after=' + lastId)
      const fresh = r.messages.filter(m => m.id > lastId)
      if (!fresh.length) return
      const atBottom = ui.log.scrollHeight - ui.log.scrollTop - ui.log.clientHeight < 40
      ui.log.querySelector('.empty')?.remove()
      ui.log.append(...fresh.slice(-60).map(line))
      lastId = fresh[fresh.length - 1].id
      if (atBottom) ui.log.scrollTop = ui.log.scrollHeight
    } catch (e) { if (e.status === 409) showJoin() }
  }

  function showJoin () {
    present = false
    ui.body.replaceChildren(
      el('p', { class: 'hint', text: T.t('sidechat_join_hint') }),
      el('button', { class: 'primary', type: 'button', text: T.t('sidechat_join'), onclick: join }))
  }

  function showRoom () {
    present = true
    ui.log = el('div', { class: 'log sidechat-log', role: 'log', 'aria-label': 'SandChat' }, el('p', { class: 'empty', text: T.t('sidechat_quiet') }))
    const input = el('input', { type: 'text', maxlength: '2000', 'aria-label': T.t('sidechat_say'), placeholder: T.t('sidechat_say'), autocomplete: 'off' })
    ui.body.replaceChildren(ui.log, el('form', {
      class: 'say-row',
      onsubmit: async (ev) => {
        ev.preventDefault()
        const text = input.value.trim()
        if (!text) return
        try { await api('POST', '/zones/' + ZONE + '/say', { text }); input.value = ''; poll() } catch (e) { toast(e.message) }
      }
    }, input, el('button', { class: 'primary', type: 'submit', text: T.t('sidechat_send') })))
    lastId = 0
    poll()
  }

  async function join () {
    try { await api('POST', '/zones/' + ZONE + '/join'); showRoom() } catch (e) { toast(e.message) }
  }

  async function open () {
    ui.panel.hidden = false
    ui.tab.setAttribute('aria-expanded', 'true')
    document.body.classList.add('sidechat-open')
    remember(true)
    let me
    try { me = await api('GET', '/me') } catch (e) { return }
    if ((me.zones || []).includes(ZONE)) { if (!present) showRoom() } else showJoin()
    clearInterval(timer)
    timer = setInterval(() => { if (!document.hidden) poll() }, 3000)
  }

  function close () {
    ui.panel.hidden = true
    ui.tab.setAttribute('aria-expanded', 'false')
    document.body.classList.remove('sidechat-open')
    remember(false)
    clearInterval(timer)
  }

  function build () {
    ui.body = el('div', { class: 'sidechat-body' })
    ui.panel = el('aside', { class: 'sidechat', 'aria-label': 'SandChat', hidden: true },
      el('div', { class: 'sidechat-head' }, el('strong', { text: 'SandChat' }),
        el('a', { class: 'hint', href: '/chat?zone=' + ZONE, text: T.t('sidechat_full') }),
        el('button', { class: 'quiet', type: 'button', text: T.t('sidechat_close'), onclick: close })),
      ui.body)
    ui.tab = el('button', {
      class: 'sidechat-tab', type: 'button', 'aria-expanded': 'false', 'aria-controls': 'sidechat',
      onclick: () => (ui.panel.hidden ? open() : close())
    }, '💬 SandChat')
    ui.panel.id = 'sidechat'
    document.body.append(ui.tab, ui.panel)
    if (remembered()) open()
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build)
  else build()
})()
