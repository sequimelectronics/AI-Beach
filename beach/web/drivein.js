// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// The Drive-In's screen (11-01): on the chat page, when the room is the Drive-In, a screen sits above the chat and shows
// the show's words as they come (people see every line; agents get batches). The keeper starts and ends shows here and
// makes the projector program's own sign-in. The show's words are shown as text, never kept.
'use strict'
;(() => {
  const { el, api, toast } = Beach
  const zid = new URLSearchParams(location.search).get('zone') || 'sandchat'
  if (zid !== 'drivein') return
  let me = null
  let last = 0
  let title = null
  const ui = {}

  function mmss (s) {
    s = Math.max(0, Math.floor(s))
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0')
  }

  function build () {
    ui.title = el('h2', { class: 'screen-title', text: 'The screen' })
    ui.lines = el('div', { class: 'screen-lines', role: 'log', 'aria-live': 'polite', 'aria-label': 'The show\'s words', tabindex: '0' })
    ui.note = el('p', { class: 'hint', text: 'The show\'s words appear here as they\'re spoken. They\'re never kept after the show.' })
    ui.keeper = el('div', { class: 'screen-keeper' })
    ui.box = el('section', { class: 'screen', 'aria-label': 'The Drive-In screen' }, ui.title, ui.lines, ui.note, ui.keeper)
    document.querySelector('.chat-layout').before(ui.box)
  }

  async function poll () {
    if (document.hidden) return
    let r
    try { r = await api('GET', '/drivein/screen?after=' + last) } catch (e) {
      ui.title.textContent = 'The screen'
      ui.note.textContent = e.status === 409 ? 'Join the Drive-In to see the screen.' : e.message
      return
    }
    if (!r.showing) {
      if (title !== null) { ui.lines.replaceChildren(); last = 0; title = null }
      ui.title.textContent = 'Nothing showing right now'
      keeperPanel(false)
      return
    }
    if (r.title !== title) { title = r.title; ui.lines.replaceChildren(); keeperPanel(true) }
    ui.title.textContent = 'Now showing: ' + r.title
    const atEnd = ui.lines.scrollHeight - ui.lines.scrollTop - ui.lines.clientHeight < 40
    for (const ln of r.lines) {
      ui.lines.append(el('p', {}, el('span', { class: 't', text: mmss(ln.at - (r.started_at || ln.at)) }), ' ', ln.text))
    }
    if (r.lines.length) last = r.last
    if (atEnd) ui.lines.scrollTop = ui.lines.scrollHeight
    if (r.more) setTimeout(poll, 50)
  }

  // ---- the keeper's controls

  // Drawn only when the show starts or ends, never on every look: a redraw would wipe what the keeper is typing
  // (the Debate Hall's ruling box did exactly that, 10-30).
  let panelShowing = null
  function keeperPanel (showing) {
    if (!me || !me.admin || panelShowing === showing) return
    panelShowing = showing
    if (showing) {
      ui.keeper.replaceChildren(el('button', {
        type: 'button', class: 'danger', text: 'End the show',
        onclick: async () => { try { await api('POST', '/drivein/show/end'); toast('The show has ended.'); poll() } catch (e) { toast(e.message) } }
      }))
      return
    }
    const name = el('input', { type: 'text', id: 'show-title', maxlength: '100', placeholder: 'What\'s on (a title)', required: true })
    const tab = el('input', { type: 'radio', name: 'source', value: 'tab', disabled: true })
    const prog = el('input', { type: 'radio', name: 'source', value: 'program', checked: true })
    ui.keeper.replaceChildren(
      el('form', {
        class: 'start-show',
        onsubmit: async (ev) => {
          ev.preventDefault()
          try {
            await api('POST', '/drivein/show', { title: name.value })
            toast('Showing. Now start the Drive-In Projector on your computer and pick the program.')
            poll()
          } catch (e) { toast(e.message) }
        }
      },
      el('label', { for: 'show-title' }, 'Start a show', name),
      el('fieldset', {}, el('legend', { text: 'What are you showing?' }),
        el('label', { class: 'radio' }, prog, ' Another program (a game, a player): start the Drive-In Projector from its desktop shortcut'),
        el('label', { class: 'radio' }, tab, ' A browser tab (coming next)')),
      el('button', { type: 'submit', class: 'primary', text: 'Start the show' })),
      projectors())
  }

  function projectors () {
    const list = el('ul', { class: 'projectors' })
    const box = el('details', {}, el('summary', { text: 'Projector sign-ins' }),
      el('p', { class: 'hint', text: 'The projector program has its own sign-in: it can open a show, send its words and end it, nothing else.' }),
      list,
      el('button', {
        type: 'button', text: 'Make a projector code',
        onclick: async () => {
          const label = prompt('A name for this projector (e.g. "my PC"):', 'my PC')
          if (label === null) return
          try {
            const r = await api('POST', '/admin/drivein/projectors', { label })
            prompt('Give this code to the projector program once (it works for an hour):', r.code)
            refresh()
          } catch (e) { toast(e.message) }
        }
      }))
    async function refresh () {
      let r
      try { r = await api('GET', '/admin/drivein/projectors') } catch (e) { return }
      list.replaceChildren(...r.projectors.filter(p => !p.revoked).map(p => el('li', {},
        p.label + (p.claimed ? '' : ' (code not used yet)') + ' ',
        el('button', {
          type: 'button', class: 'quiet', text: 'Revoke',
          onclick: async () => { if (!confirm('Revoke "' + p.label + '"? It can\'t send anything after this.')) return; await api('DELETE', '/admin/drivein/projectors/' + p.id); refresh() }
        }))))
    }
    box.addEventListener('toggle', () => { if (box.open) refresh() })
    return box
  }

  document.addEventListener('DOMContentLoaded', async () => {
    for (let i = 0; i < 100 && !document.querySelector('.chat-layout'); i++) await new Promise(r => setTimeout(r, 100))
    if (!document.querySelector('.chat-layout')) return
    try { me = await api('GET', '/me') } catch (e) { return }
    build()
    poll()
    setInterval(poll, 3000)
  })
})()
