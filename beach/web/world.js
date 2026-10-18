// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// A game world's Beach page: the bar stays on top, with Play, Watch and Leave, and the world's own
// viewer framed below it. Nobody is in a world unseen: Play puts your character on the sand;
// Watch puts your name at the world's watch spot (no character), and the world says so.
'use strict'
;(() => {
  const { el, api, toast } = Beach
  const params = new URLSearchParams(location.search)
  const zid = params.get('zone') || ''
  const want = params.get('do')            // from the map's Play / Watch
  const KEEP = 'beach_watching:' + zid     // this tab was watching (so a reload keeps watching)
  let zone = null
  let mode = 'none'                        // 'none' | 'playing' | 'watching'
  let beat = null
  let told = false                         // the page has said the world took your character out
  const ui = {}

  const zpath = () => '/zones/' + encodeURIComponent(zid)
  function remember (on) { try { on ? sessionStorage.setItem(KEEP, '1') : sessionStorage.removeItem(KEEP) } catch (e) {} }
  function remembered () { try { return sessionStorage.getItem(KEEP) === '1' } catch (e) { return false } }

  function say (text, extra) {
    ui.message.replaceChildren(...(text ? [el('span', { text }), ...(extra || [])] : []))
    ui.message.hidden = !text
  }

  function setMode (m, viewer) {
    mode = m
    clearInterval(beat)
    beat = null
    if (m === 'watching') {
      remember(true)
      beat = setInterval(() => { if (mode === 'watching') api('POST', zpath() + '/watch').catch(() => {}) }, 60000)
    } else remember(false)
    const name = zone.name
    const limit = zone.idle_limit_s ? Beach.minutes(zone.idle_limit_s) : null
    ui.status.replaceChildren(
      m === 'none' ? el('span', { text: T.t('world_choose') })
        : el('span', {}, Beach.pin(m), ' ', m === 'playing'
          ? T.t(limit ? 'world_playing' : 'world_playing_plain', { zone: name, limit })
          : T.t('world_watching', { zone: name })))
    const buttons = []
    if (m !== 'playing') buttons.push(el('button', { class: 'primary', type: 'button', text: T.t('play'), onclick: () => play(told) }))
    if (m === 'none') buttons.push(el('button', { type: 'button', text: T.t('watch'), onclick: watch }))
    if (m === 'playing') buttons.push(el('button', { class: 'quiet', type: 'button', text: T.t('leave'), onclick: leave }))
    if (m === 'watching') buttons.push(el('button', { class: 'quiet', type: 'button', text: T.t('stop_watching'), onclick: leave }))
    ui.buttons.replaceChildren(...buttons)
    ui.frame = null
    if (m === 'none') { ui.stage.replaceChildren(); return }
    if (!viewer) {
      ui.stage.replaceChildren(el('div', { class: 'world-empty card' }, el('p', { text: T.t('world_no_viewer', { zone: name }) })))
      return
    }
    // The world's own viewer. The session (Play) is after '#', so it never reaches a server log.
    const frame = el('iframe', {
      class: 'world-frame',
      src: viewer,
      title: name + (m === 'watching' ? ' (watching)' : ''),
      allow: 'fullscreen',
      referrerpolicy: 'no-referrer'
    })
    // The viewer lets you walk by clicking (worlds/beach/renderer): hand it the character's session
    // when it loads or asks. Only to that frame, at the viewer's own origin; never when watching.
    frame.addEventListener('load', () => sendSession(frame, viewer, m))
    ui.frame = { frame, viewer, mode: m }
    ui.stage.replaceChildren(frame)
    Beach.refreshBar()
  }

  function sendSession (frame, viewer, m) {
    if (m !== 'playing' || !frame.contentWindow) return
    try {
      const u = new URL(viewer, location.href)
      const h = new URLSearchParams(u.hash.replace(/^#/, ''))
      if (!h.get('session')) return
      frame.contentWindow.postMessage({ type: 'beach-session', session: h.get('session'), player: h.get('player') || '' }, u.origin)
    } catch (e) {}
  }
  window.addEventListener('message', (ev) => {
    const f = ui.frame
    if (!f || ev.source !== f.frame.contentWindow || !ev.data || ev.data.type !== 'beach-session-please') return
    sendSession(f.frame, f.viewer, f.mode)
  })

  async function play (again) {
    say('')
    try {
      const r = await api('POST', zpath() + '/play', again ? { again: true } : {})
      setMode('playing', r.viewer)
    } catch (e) {
      if (e.body && e.body.removed) {
        // The world took your last character out: say so, and let you choose to come back.
        told = true
        setMode('none')
        say(e.message, [el('button', { class: 'primary', type: 'button', text: T.t('play_again'), onclick: () => play(true) })])
      } else say(e.message)
    }
  }

  async function watch () {
    say('')
    try {
      const r = await api('POST', zpath() + '/watch')
      setMode('watching', r.viewer)
    } catch (e) { say(e.message) }
  }

  async function leave () {
    const was = mode
    try { await api('DELETE', zpath() + (was === 'watching' ? '/watch' : '/play')) } catch (e) { toast(e.message) }
    setMode('none')
    say(was === 'watching' ? T.t('world_stopped_watching', { zone: zone.name }) : T.t('world_left', { zone: zone.name }))
    Beach.refreshBar()
  }

  // If the world takes your character out (you were idle too long), say so here.
  async function check () {
    if (document.hidden || mode !== 'playing') return
    try {
      const r = await api('GET', zpath() + '/play')
      if (!r.playing && mode === 'playing') { setMode('none'); Beach.refreshBar() }
    } catch (e) {}
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const map = await Beach.start('world')
    if (!map) return
    const main = document.querySelector('main')
    zone = map.zones.find(z => z.id === zid && z.kind === 'game')
    if (!zone) { main.replaceChildren(el('p', { class: 'error', text: 'There is no game world called ' + zid + '.' })); return }
    document.title = zone.name + ' · ' + map.beach
    ui.status = el('p', { class: 'world-status' })
    ui.buttons = el('div', { class: 'row world-buttons' })
    ui.message = el('div', { class: 'notice world-message', role: 'status', hidden: true })
    ui.stage = el('div', { class: 'world-stage' })
    main.replaceChildren(
      el('div', { class: 'chat-head' }, el('h1', { text: zone.name }), ui.buttons),
      ui.status, ui.message, ui.stage)
    Beach.onEvent(ev => {
      if (!ev.data || ev.data.zone !== zid || ev.data.event !== 'world_removed') return false
      told = true
      setMode('none')
      say(ev.text, [el('button', { class: 'primary', type: 'button', text: T.t('play_again'), onclick: () => play(true) })])
      return true
    })
    history.replaceState(null, '', location.pathname + '?zone=' + encodeURIComponent(zid))
    if (!zone.open) { setMode('none'); ui.buttons.replaceChildren(); say(zone.name + ' is closed right now.'); return }
    if (!zone.connected) { setMode('none'); ui.buttons.replaceChildren(); say(T.t('world_not_connected', { zone: zone.name })); return }
    let now = { playing: false, watching: false }
    try { now = await api('GET', zpath() + '/play') } catch (e) {}
    if (want === 'play' || (now.playing && want !== 'watch')) await play(false)
    else if (want === 'watch' || now.watching || remembered()) await watch()
    else setMode('none')
    setInterval(check, 5000)
    // Closing the tab or going elsewhere ends a watch (a reload of this tab picks it up again).
    window.addEventListener('pagehide', () => {
      if (mode !== 'watching') return
      try {
        fetch(zpath() + '/watch', { method: 'DELETE', keepalive: true, headers: { Authorization: 'Bearer ' + Beach.token() } })
      } catch (e) {}
    })
  })
})()
