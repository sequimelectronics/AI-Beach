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
  const NOTE = 'The show\'s words appear here as they\'re spoken. They\'re never kept after the show.'

  function mmss (s) {
    s = Math.max(0, Math.floor(s))
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0')
  }

  function build () {
    ui.title = el('h2', { class: 'screen-title', text: 'The screen' })
    ui.lines = el('div', { class: 'screen-lines', role: 'log', 'aria-live': 'polite', 'aria-label': 'The show\'s words', tabindex: '0' })
    ui.note = el('p', { class: 'hint', text: NOTE })
    ui.keeper = el('div', { class: 'screen-keeper' })
    // The keeper's controls fold away above the screen: the show's words are the movie, so the screen gets the room
    // (the keeper, 11-02). Open when nothing's showing, folded during a show.
    ui.drawer = el('details', { class: 'keeper-drawer', hidden: true },
      el('summary', { text: 'Keeper: shows and projectors' }), ui.keeper)
    ui.box = el('section', { class: 'screen', 'aria-label': 'The Drive-In screen' }, ui.drawer, ui.title, ui.lines, ui.note)
    // Two columns: the screen on the left, full height; the chat (and who's here) in a panel on the right.
    const layout = document.querySelector('.chat-layout')
    const stage = el('div', { class: 'drivein-stage' })
    layout.before(stage)
    stage.append(ui.box, layout)
  }

  async function poll () {
    if (document.hidden) return
    let r
    try { r = await api('GET', '/drivein/screen?after=' + last) } catch (e) {
      ui.title.textContent = 'The screen'
      ui.note.textContent = e.status === 409 ? 'Join the Drive-In to see the screen.' : e.message
      return
    }
    ui.note.textContent = NOTE      // back to normal once the screen answers again (the keeper, 11-03: "join" stayed)
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
      // "(seen) ..." lines describe the picture (step 2); they look different from the spoken words.
      const seen = ln.text.startsWith('(seen) ')
      ui.lines.append(el('p', seen ? { class: 'seen' } : {},
        el('span', { class: 't', text: mmss(ln.at - (r.started_at || ln.at)) }), ' ',
        seen ? el('span', { class: 'seen-tag', text: 'seen' }) : '',
        seen ? ln.text.slice(7) : ln.text))
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
    ui.drawer.hidden = false
    ui.drawer.open = !showing
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
      // The keeper's routine (11-01), as short as it goes: the projector does the rest (the helper, the show's
      // title, ending it when its window closes).
      el('details', { class: 'howto', open: true },
        el('summary', { text: 'How to project a show' }),
        el('ol', {},
          el('li', { text: 'Open your video or game, and pause it.' }),
          el('li', { text: 'Double-click Drive-In Projector on your desktop.' }),
          el('li', { text: 'Type the title, then the number of your app.' }),
          el('li', { text: 'Press Play, and come talk. Close the projector\'s window to end the show.' })),
        el('p', { class: 'hint', text: 'Showing from a browser? Use a browser window just for the Drive-In: a browser plays all its tabs together.' })),
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
      el('label', { for: 'show-title' }, 'Or start a show from here (the projector can also do it)', name),
      el('fieldset', {}, el('legend', { text: 'What are you showing?' }),
        el('label', { class: 'radio' }, prog, ' An app (a game, a player): then run the Drive-In Projector'),
        el('label', { class: 'radio' }, tab, ' A browser tab (coming next)')),
      el('button', { type: 'submit', class: 'primary', text: 'Start the show' })),
      projectors())
  }

  // A new code stays on the page, with a Copy button and the command to paste it into, until Done (the keeper, 11-01:
  // a pop-up made her copy it, hold it in her head, click OK, then go and paste).
  const CLAIM = 'py -E -P E:\\DriveIn\\projector\\projector.py claim --config E:\\DriveIn\\projector\\projector.json'

  function copyButton (text, label) {
    return el('button', {
      type: 'button', text: label,
      onclick: async (ev) => {
        try { await navigator.clipboard.writeText(text); ev.target.textContent = 'Copied ✓' } catch (e) { toast('Select it and copy it by hand: the browser didn\'t allow copying.') }
      }
    })
  }

  function projectors () {
    const list = el('ul', { class: 'projectors' })
    const fresh = el('div', { class: 'projector-code' })
    const label = el('input', { type: 'text', id: 'projector-label', maxlength: '40', value: 'my PC' })
    const box = el('details', {}, el('summary', { text: 'Projector sign-ins' }),
      el('p', { class: 'hint', text: 'The projector program has its own sign-in: it can open a show, send its words and end it, nothing else.' }),
      list,
      el('div', { class: 'row' },
        el('label', { for: 'projector-label' }, 'Name ', label),
        el('button', {
          type: 'button', text: 'Make a projector code',
          onclick: async () => {
            try {
              const r = await api('POST', '/admin/drivein/projectors', { label: label.value })
              fresh.replaceChildren(
                el('p', {}, el('strong', { text: 'Code for "' + r.label + '": ' }), el('code', { class: 'big-code', text: r.code }), ' ', copyButton(r.code, 'Copy the code')),
                el('p', { class: 'hint', text: 'It works once, within an hour. Run this on the computer that plays the shows, then paste the code at its prompt:' }),
                el('p', {}, el('code', { text: CLAIM }), ' ', copyButton(CLAIM, 'Copy the command')),
                el('button', { type: 'button', class: 'quiet', text: 'Done', onclick: () => { fresh.replaceChildren(); refresh() } }))
              refresh()
            } catch (e) { toast(e.message) }
          }
        })),
      fresh)
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
