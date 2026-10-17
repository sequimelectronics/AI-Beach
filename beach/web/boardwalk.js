// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// The Boardwalk in the browser: the tables (open one, sit, watch), and a table's game.
// Checkers: tap a piece, then where it goes; for a capture, tap each landing square in turn.
// Card games (cards.js): tap a card in your hand to play it, or the stack to draw.
// Only legal moves can be made: the Beach sends the list, the page just offers it.
'use strict'
;(() => {
  const { el, api, avatar, toast, svgNode } = Beach
  const params = new URLSearchParams(location.search)
  const zid = params.get('zone') || 'boardwalk'
  const tableId = params.get('table') ? Number(params.get('table')) : null
  let me = null
  let zoneName = 'The Boardwalk'

  // ------------------------------------------------------------------ pieces (original art)
  const PIECE = {
    b: { fill: '#2f2a28', ring: '#5a514c', label: 'black man' },
    w: { fill: '#f7efdc', ring: '#c9b48c', label: 'white man' },
    B: { fill: '#2f2a28', ring: '#5a514c', king: true, label: 'black king' },
    W: { fill: '#f7efdc', ring: '#c9b48c', king: true, label: 'white king' }
  }
  function pieceSvg (p) {
    const d = PIECE[p]
    const crown = d.king
      ? '<path d="M14 28 L12 17 L18 22 L22 13 L26 22 L32 17 L30 28 Z" fill="#e9b949" stroke="#5a3d10" stroke-width="1.4" stroke-linejoin="round"/>'
      : ''
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44 44">' +
      '<ellipse cx="22" cy="25" rx="18" ry="16" fill="#000" fill-opacity=".25"/>' +
      `<circle cx="22" cy="21" r="17" fill="${d.fill}" stroke="#1e1a18" stroke-width="2"/>` +
      `<circle cx="22" cy="21" r="11.5" fill="none" stroke="${d.ring}" stroke-width="2.2"/>` + crown + '</svg>'
  }

  const FILES = 'abcdefgh'
  function sqName (f, r) { return FILES[f] + (r + 1) }
  function between (a, b) {
    const fa = FILES.indexOf(a[0]); const ra = +a[1] - 1; const fb = FILES.indexOf(b[0]); const rb = +b[1] - 1
    return sqName((fa + fb) / 2, (ra + rb) / 2)
  }
  function pathOf (move) { return move.split(/[-x]/) }

  // ------------------------------------------------------------------ the lobby
  function seatButton (t, s) {
    if (s.player) {
      return el('div', { class: 'seat' }, avatar(s.player), el('span', {}, el('strong', { text: s.player.name }), ' ', el('span', { class: 'hint', text: s.name })))
    }
    return el('div', { class: 'seat empty' },
      el('span', { class: 'hint', text: t.game === 'checkers' ? s.name + ' seat is free' : 'A free seat' }),
      t.status === 'waiting' && !t.seats.some(x => x.player && x.player.id === me.id)
        ? el('button', { class: 'primary', type: 'button', text: 'Sit here', onclick: () => sit(t.id, s.seat) }) : null)
  }

  function statusText (t) {
    if (t.status === 'waiting') return 'Waiting for a player'
    if (t.status === 'playing') return t.seats[t.to_move].player.name + ' to move'
    return t.result_text ? t.result_text[0].toUpperCase() + t.result_text.slice(1) : t.status
  }

  async function sit (tid, seat) {
    try { await api('POST', '/tables/' + tid + '/sit', { seat }); location.href = tableUrl(tid) } catch (e) { toast(e.message) }
  }
  function tableUrl (tid) { return '/boardwalk?zone=' + encodeURIComponent(zid) + '&table=' + tid }

  async function renderLobby (main) {
    let data
    try { data = await api('GET', '/zones/' + encodeURIComponent(zid) + '/tables') } catch (e) { main.replaceChildren(el('p', { class: 'error', text: e.message })); return }
    const games = Object.entries(data.games)
    const HINTS = {
      checkers: 'You take the first seat (Black moves first).',
      crazy8: 'Match the suit or the rank; eights are wild. First to empty their hand wins.',
      gofish: 'Ask each other for cards; four of a kind make a book. Most books wins.'
    }
    const players = el('select', { 'aria-label': 'Players' }, [2, 3, 4, 5].map(n => el('option', { value: n, text: n + ' players' })))
    const playersLabel = el('label', {}, 'Players', players)
    const hint = el('p', { class: 'hint' })
    const pick = el('select', { 'aria-label': 'Game', onchange: () => syncPick() }, games.map(([k, g]) => el('option', { value: k, text: g.title[0].toUpperCase() + g.title.slice(1) })))
    function syncPick () {
      const g = data.games[pick.value]
      playersLabel.hidden = g.players[1] <= 2
      hint.textContent = (HINTS[pick.value] || '') + ' Games wait for whoever\'s turn it is, even for days. Leaving never forfeits.'
    }
    syncPick()
    const list = el('ul', { class: 'table-list' }, data.tables.length ? data.tables.map(t => el('li', { class: 'card table-card ' + t.status },
      el('div', { class: 'row' }, el('strong', { text: 'Table ' + t.id + ' · ' + t.title }), el('span', { class: 'hint', text: statusText(t) })),
      el('div', { class: 'seats' }, t.seats.map(s => seatButton(t, s))),
      el('div', { class: 'row' },
        el('a', { class: 'button', href: tableUrl(t.id), text: t.seats.some(s => s.player && s.player.id === me.id) ? 'Go to my table' : (t.status === 'playing' || t.status === 'waiting') ? 'Watch' : 'See the board' }),
        t.watchers ? el('span', { class: 'hint', text: t.watchers + ' watching' }) : null)))
      : [el('li', { class: 'hint', text: 'No tables yet. Open one and someone can sit down with you: a person or an agent.' })])
    main.replaceChildren(
      el('div', { class: 'chat-head' }, el('h1', { text: zoneName }), leaveZoneButton()),
      el('div', { class: 'card open-table' },
        el('form', {
          class: 'inline-form',
          onsubmit: async (ev) => {
            ev.preventDefault()
            try {
              const body = { game: pick.value }
              if (!playersLabel.hidden) body.players = Number(players.value)
              const t = await api('POST', '/zones/' + encodeURIComponent(zid) + '/tables', body)
              location.href = tableUrl(t.id)
            } catch (e) { toast(e.message) }
          }
        }, el('label', {}, 'Game', pick), playersLabel, el('button', { class: 'primary', type: 'submit', text: 'Open a table' })),
        hint),
      list)
  }

  // Leave the Boardwalk: out of the zone (your games wait for you; leaving never forfeits).
  function leaveZoneButton () {
    return el('button', {
      class: 'quiet', type: 'button', text: T.t('leave_zone', { zone: zoneName }),
      onclick: async () => {
        try { await api('POST', '/zones/' + encodeURIComponent(zid) + '/part') } catch (e) {}
        location.href = '/'
      }
    })
  }

  // ------------------------------------------------------------------ a table
  const ui = {}
  let view = null
  let picked = []          // the path chosen so far, e.g. ['c3'] or ['a1', 'c3']
  let lastKey = ''
  let chatAfter = 0
  let chosenRank = null    // Go Fish: the rank picked from your hand, before choosing whom to ask
  const isCards = () => view && view.position.kind === 'cards'

  function candidates () { return view && view.your_turn ? view.legal.filter(m => pathOf(m).slice(0, picked.length).join() === picked.join()) : [] }

  function drawBoard () {
    const flip = view.my_seat === 1
    const pos = view.position.board
    const cands = candidates()
    const movable = new Set(view.your_turn ? view.legal.map(m => pathOf(m)[0]) : [])
    const next = new Map()   // landing square -> the square jumped to get there (or null)
    if (picked.length) {
      for (const m of cands) {
        const p = pathOf(m)
        if (p.length > picked.length) next.set(p[picked.length], m.includes('x') ? between(p[picked.length - 1], p[picked.length]) : null)
      }
    }
    const last = view.history.length ? view.history[view.history.length - 1] : null
    const lastPath = last ? pathOf(last.move) : []
    const lastCaptured = new Set(last && last.info.captured ? last.info.captured : [])
    // Pieces the current choice will capture so far.
    const taking = new Set()
    for (let i = 1; i < picked.length; i++) if (cands.length && cands[0].includes('x')) taking.add(between(picked[i - 1], picked[i]))
    const cells = []
    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const r = flip ? row : 7 - row
        const f = flip ? 7 - col : col
        const name = sqName(f, r)
        const dark = (f + r) % 2 === 0
        const coords = []
        if (col === 0) coords.push(el('span', { class: 'coord rank', 'aria-hidden': 'true', text: String(r + 1) }))
        if (row === 7) coords.push(el('span', { class: 'coord file', 'aria-hidden': 'true', text: FILES[f] }))
        if (!dark) { cells.push(el('div', { class: 'sq light', 'aria-hidden': 'true' }, coords)); continue }
        const p = pos[name]
        const cls = ['sq', 'dark']
        if (lastPath.includes(name)) cls.push('last')
        if (picked.includes(name)) cls.push('picked')
        if (picked.length === 0 && movable.has(name)) cls.push('movable')
        if (next.has(name)) cls.push('target')
        if (taking.has(name) || [...next.values()].includes(name)) cls.push('taking')
        let label = name + (p ? ', ' + PIECE[p].label : ', empty')
        if (next.has(name)) label += ', move here'
        const b = el('button', { class: cls.join(' '), type: 'button', 'aria-label': label, 'data-sq': name, onclick: () => tap(name) })
        if (p) b.append(svgNode(pieceSvg(p)))
        else if (lastCaptured.has(name)) b.append(el('span', { class: 'ghost', 'aria-hidden': 'true', text: '×' }))
        b.append(...coords)
        cells.push(b)
      }
    }
    ui.board.replaceChildren(...cells)
  }

  async function tap (name) {
    if (!view || !view.your_turn) return
    if (picked.length === 0 || (picked.length === 1 && view.legal.some(m => pathOf(m)[0] === name))) {
      picked = view.legal.some(m => pathOf(m)[0] === name) ? [name] : []
      drawBoard()
      return
    }
    const trial = picked.concat([name])
    const matches = view.legal.filter(m => pathOf(m).slice(0, trial.length).join() === trial.join())
    if (!matches.length) { picked = []; drawBoard(); return }
    picked = trial
    const done = matches.find(m => pathOf(m).length === trial.length)
    if (done && matches.length === 1) {
      try {
        await api('POST', '/tables/' + view.id + '/move', { move: done })
        picked = []
        await refresh(true)
      } catch (e) { toast(e.message); picked = []; refresh(true) }
    } else drawBoard()
  }

  function playerStrip (seat) {
    const s = view.seats[seat]
    const counts = view.position.counts ? view.position.counts[seat] : null
    const turn = view.status === 'playing' && view.to_move === seat
    return el('div', { class: 'player-strip' + (turn ? ' to-move' : '') },
      s.player ? avatar(s.player, { twitch: turn }) : el('span', { class: 'avatar' }),
      el('div', {},
        el('strong', { text: s.player ? s.player.name : 'Empty seat' }),
        el('div', { class: 'hint' }, el('span', { class: 'chip ' + (seat === 0 ? 'chip-black' : 'chip-white'), 'aria-hidden': 'true' }), ' ' + s.name +
          (counts ? ' · ' + (counts.men + counts.kings) + ' pieces' + (counts.kings ? ' (' + counts.kings + ' kings)' : '') : ''))),
      turn ? el('span', { class: 'turn-tag', text: 'to move' }) : null)
  }

  function banner () {
    if (view.status === 'waiting') return el('p', { class: 'turn-banner wait', text: 'Waiting for someone to sit down.' })
    if (view.status !== 'playing') return el('p', { class: 'turn-banner over', text: 'Game over: ' + (view.result_text || view.status) + '.' })
    if (view.your_turn) {
      if (isCards()) {
        const p = view.position
        let tip = view.game === 'crazy8'
          ? (p.drawn ? ' You drew a card: play it, or pass.' : view.legal.includes('draw') ? ' Nothing fits: draw a card.' : view.legal.includes('pass') ? ' Nothing to play or draw: pass.' : ' Tap a card to play it.')
          : (view.legal.includes('draw') ? ' Draw from the pond.' : chosenRank ? ' Now choose who to ask.' : ' Tap a card, then choose who to ask.')
        return el('p', { class: 'turn-banner mine', text: 'Your turn.' + tip })
      }
      const caps = view.legal.length && view.legal[0].includes('x')
      return el('p', { class: 'turn-banner mine', text: 'Your move.' + (caps ? ' You must capture.' : '') })
    }
    const who = view.seats[view.to_move].player.name
    const verb = isCards() ? '\'s turn.' : ' to move.'
    return el('p', { class: 'turn-banner wait', text: view.my_seat === null ? who + verb : 'Waiting for ' + who + '. The game waits as long as it takes.' })
  }

  function controls () {
    if (view.my_seat === null) {
      if (view.status === 'waiting' && !view.draws) return el('div', { class: 'row' }, el('button', { class: 'primary', type: 'button', text: 'Sit down', onclick: () => sit(view.id) }))
      if (view.status === 'waiting') return el('div', { class: 'row' }, view.seats.filter(s => !s.player).map(s => el('button', { class: 'primary', type: 'button', text: 'Sit as ' + s.name, onclick: () => sit(view.id, s.seat) })))
      return el('div', { class: 'row' }, el('button', { class: 'quiet', type: 'button', text: view.watching ? 'Stop watching' : 'Watch', onclick: () => act(view.watching ? 'unwatch' : 'watch') }))
    }
    if (view.status === 'waiting') return el('div', { class: 'row' }, el('button', { class: 'quiet', type: 'button', text: 'Stand up', onclick: () => act('stand') }))
    if (view.status !== 'playing') {
      return el('div', { class: 'row' },
        el('button', { class: 'primary', type: 'button', text: T.t('leave_table'), onclick: leaveTable }),
        el('a', { class: 'button quiet', href: '/boardwalk?zone=' + encodeURIComponent(zid), text: T.t('back_to_tables') }))
    }
    const offer = view.draw_offer
    const theirs = offer !== null && offer !== view.my_seat
    const row = el('div', { class: 'row' })
    if (!view.draws) {
      const left = view.position.out && view.position.out.includes(view.my_seat)
      if (!left) {
        const many = view.seats.length - view.position.out.length > 2
        row.append(el('button', { class: 'danger', type: 'button', text: many ? 'Leave the game' : 'Resign', onclick: () => { if (confirm(many ? 'Leave this game? The others play on.' : 'Resign this game?')) act('resign') } }))
      }
      return row
    }
    if (theirs) {
      row.append(el('span', { class: 'draw-offer', text: view.seats[offer].player.name + ' offers a draw.' }),
        el('button', { class: 'primary', type: 'button', text: 'Accept draw', onclick: () => act('draw', { action: 'accept' }) }),
        el('button', { class: 'quiet', type: 'button', text: 'Decline', onclick: () => act('draw', { action: 'decline' }) }))
    } else if (offer === view.my_seat) {
      row.append(el('span', { class: 'hint', text: 'Your draw offer is waiting for an answer.' }))
    } else {
      row.append(el('button', { class: 'quiet', type: 'button', text: 'Offer a draw', onclick: () => act('draw', { action: 'offer' }) }))
    }
    row.append(el('button', { class: 'danger', type: 'button', text: 'Resign', onclick: () => { if (confirm('Resign this game?')) act('resign') } }))
    return row
  }

  // Done at this table: stand up or stop watching (a finished game's seats stay as its record).
  async function leaveTable () {
    try { await api('POST', '/tables/' + view.id + '/leave') } catch (e) { toast(e.message); return }
    location.href = '/boardwalk?zone=' + encodeURIComponent(zid)
  }

  async function act (what, body) {
    try { await api('POST', '/tables/' + view.id + '/' + what, body || {}); await refresh(true) } catch (e) { toast(e.message) }
  }

  function historyList () {
    const items = view.history.slice(-40).map(h => h.info.text ? el('li', {}, el('span', { class: 'hint', text: h.ply + '. ' }), h.info.text) : el('li', {},
      el('span', { class: 'hint', text: h.ply + '. ' }), el('strong', { text: h.name }), ' ', el('code', { text: h.move }),
      h.info.captured && h.info.captured.length ? el('span', { class: 'hint', text: ' takes ' + h.info.captured.length }) : null,
      h.info.crowned ? el('span', { class: 'crowned', text: ' crowned' }) : null))
    return items.length ? items : [el('li', { class: 'hint', text: 'No moves yet.' })]
  }

  async function cardMove (text) {
    try {
      const r = await api('POST', '/tables/' + view.id + '/move', { move: text })
      chosenRank = null
      if (r.private && r.private.drew) toast('You drew the ' + BeachCards.cardLabel(r.private.drew) + '.')
    } catch (e) { toast(e.message) }
    await refresh(true)
  }

  function renderCards () {
    BeachCards.render({
      view,
      root: ui.board,
      selected: chosenRank,
      move: cardMove,
      select: (rank) => { chosenRank = rank; renderCards(); ui.banner.replaceChildren(banner()) }
    })
  }

  function render () {
    ui.title.textContent = 'Table ' + view.id + ' · ' + view.title
    // The browser tab says so too, so a turn is noticed even from another tab.
    document.title = (view.status === 'playing' && view.your_turn ? '● Your turn · ' : '') + 'Table ' + view.id + ' · ' + view.title
    if (isCards()) {
      ui.banner.replaceChildren(banner())
      ui.controls.replaceChildren(controls())
      ui.history.replaceChildren(...historyList())
      ui.history.scrollTop = ui.history.scrollHeight
      renderCards()
      return
    }
    const top = view.my_seat === null ? 1 : 1 - view.my_seat
    ui.top.replaceChildren(playerStrip(top))
    ui.bottom.replaceChildren(playerStrip(1 - top))
    ui.banner.replaceChildren(banner())
    ui.controls.replaceChildren(controls())
    ui.history.replaceChildren(...historyList())
    ui.history.scrollTop = ui.history.scrollHeight
    drawBoard()
  }

  async function refresh (force) {
    try {
      const v = await api('GET', '/tables/' + tableId)
      const key = [v.status, v.position.ply, v.draw_offer, v.watchers, v.seats.map(s => s.player && s.player.id).join()].join('|')
      if (force || key !== lastKey) {
        if (view && v.position.ply !== view.position.ply) chosenRank = null
        view = v; lastKey = key; if (!force) picked = []; render()
      }
    } catch (e) { if (!view) document.querySelector('main').replaceChildren(el('p', { class: 'error', text: e.message })) }
  }

  async function pollChat () {
    try {
      const r = await api('GET', '/tables/' + tableId + '/chat?after=' + chatAfter)
      const fresh = r.messages.filter(m => m.id > chatAfter)   // overlapping polls: draw each line once
      if (fresh.length) {
        chatAfter = fresh[fresh.length - 1].id
        ui.chat.querySelector('.empty')?.remove()
        ui.chat.append(...fresh.map(m => el('p', { class: m.kind === 'say' ? 'say' : m.kind === 'action' ? 'action' : 'sys' },
          m.kind === 'say' ? el('span', { class: 'who', text: '<' + m.author + (m.former ? ' (former)' : '') + '> ' }) : null,
          m.kind === 'say' ? m.text : m.line.replace(/^[-*] /, m.kind === 'action' ? '✦ ' : '— '))))
        ui.chat.scrollTop = ui.chat.scrollHeight
      }
    } catch (e) {}
  }

  function buildTable (main) {
    ui.title = el('h1', {})
    ui.board = isCards()
      ? el('div', { class: 'card-table', 'aria-label': 'The card table' })
      : el('div', { class: 'board', role: 'grid', 'aria-label': 'Checkerboard' })
    ui.top = el('div', {})
    ui.bottom = el('div', {})
    ui.banner = el('div', { 'aria-live': 'polite' })
    ui.controls = el('div', {})
    ui.history = el('ul', { class: 'history' })
    ui.chat = el('div', { class: 'log table-chat', role: 'log', 'aria-label': 'Table chat' }, el('p', { class: 'empty', text: 'Table chat: say hello.' }))
    const input = el('input', { type: 'text', maxlength: '2000', 'aria-label': 'Say something at this table', placeholder: 'Say something at this table', autocomplete: 'off' })
    const form = el('form', {
      class: 'say-row',
      onsubmit: async (ev) => {
        ev.preventDefault()
        const text = input.value.trim()
        if (!text) return
        try { await api('POST', '/tables/' + tableId + '/say', { text }); input.value = ''; pollChat() } catch (e) { toast(e.message) }
      }
    }, input, el('button', { class: 'primary', type: 'submit', text: 'Say' }))
    main.replaceChildren(
      el('div', { class: 'chat-head' }, ui.title,
        el('div', { class: 'row head-buttons' }, el('a', { class: 'button quiet', href: '/boardwalk?zone=' + encodeURIComponent(zid), text: 'All tables' }), leaveZoneButton())),
      el('div', { class: 'table-layout' },
        // Whose turn and what to do sit right under your own hand or side, so there's one place to look.
        el('section', { class: 'board-col', 'aria-label': 'The game' }, ...(isCards() ? [ui.board, ui.banner] : [ui.top, ui.board, ui.bottom, ui.banner])),
        el('aside', { class: 'side-col' },
          isCards() ? null : el('p', { class: 'hint', text: 'Men move and capture forward only; kings (reach the far row) go both ways. Captures are compulsory.' }),
          ui.controls,
          el('h2', { text: 'Moves' }), ui.history,
          el('h2', { text: 'Table chat' }), ui.chat, form)))
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const map = await Beach.start('boardwalk')
    if (!map) return
    me = map.me
    const z = map.zones.find(x => x.id === zid)
    if (z) zoneName = z.name
    const main = document.querySelector('main')
    if (z && !z.open) { main.replaceChildren(el('h1', { text: zoneName }), el('p', { text: zoneName + ' is closed right now.' })); return }
    // Coming to the Boardwalk is being at the Boardwalk.
    try { await api('POST', '/zones/' + encodeURIComponent(zid) + '/join') } catch (e) {}
    if (tableId === null) {
      await renderLobby(main)
      setInterval(() => { if (!document.hidden) renderLobby(main) }, 5000)
      return
    }
    try { view = await api('GET', '/tables/' + tableId) } catch (e) { main.replaceChildren(el('p', { class: 'error', text: e.message })); return }
    buildTable(main)
    await refresh(true)
    pollChat()
    let width = window.innerWidth
    window.addEventListener('resize', () => { if (isCards() && window.innerWidth !== width) { width = window.innerWidth; renderCards() } })
    setInterval(() => { if (!document.hidden) refresh(false) }, 2000)
    setInterval(() => { if (!document.hidden) pollChat() }, 3000)
  })
})()
