// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// Card games at the Boardwalk, in the browser: the card art (original SVG faces and backs) and the
// card table (your hand fanned at the bottom, the pile, the draw stack, everyone's card counts).
// The page shows only what the Beach sends this player: their own hand and everyone's counts.
// It never decides what's legal: every tap becomes one of the moves in the Beach's `legal` list.
'use strict'
;(() => {
  const { el, svgNode, avatar } = Beach

  // ------------------------------------------------------------------ the art
  const RED = '#c0312f'
  const DARK = '#1f2b38'
  const SUIT = {
    S: { name: 'spades', color: DARK, path: 'M5 0C8.6 3.2 10 4.9 10 6.3A2.4 2.4 0 0 1 5.7 7.6L6.6 10H3.4L4.3 7.6A2.4 2.4 0 0 1 0 6.3C0 4.9 1.4 3.2 5 0Z' },
    H: { name: 'hearts', color: RED, path: 'M5 9.6C1.4 6.6 0 4.8 0 3A2.7 2.7 0 0 1 5 1.6A2.7 2.7 0 0 1 10 3C10 4.8 8.6 6.6 5 9.6Z' },
    D: { name: 'diamonds', color: RED, path: 'M5 0L9.2 5L5 10L0.8 5Z' },
    C: { name: 'clubs', color: DARK, path: 'M5 0.2A2.35 2.35 0 0 1 6.9 4A2.35 2.35 0 1 1 6 7.6L6.8 10H3.2L4 7.6A2.35 2.35 0 1 1 3.1 4A2.35 2.35 0 0 1 5 0.2Z' }
  }
  const RANK_WORD = { A: 'ace', J: 'jack', Q: 'queen', K: 'king' }

  function pip (s, x, y, size, flip) {
    const k = size / 10
    const rot = flip ? ` rotate(180 ${x} ${y})` : ''
    return `<path d="${SUIT[s].path}" fill="${SUIT[s].color}" transform="${rot.trim()} translate(${x - 5 * k} ${y - 5 * k}) scale(${k})"/>`
  }

  // Where the pips go, on a 60 x 84 card.
  const L = 20; const M = 30; const R = 40
  const PIPS = {
    2: [[M, 18], [M, 66]],
    3: [[M, 18], [M, 42], [M, 66]],
    4: [[L, 18], [R, 18], [L, 66], [R, 66]],
    5: [[L, 18], [R, 18], [M, 42], [L, 66], [R, 66]],
    6: [[L, 18], [R, 18], [L, 42], [R, 42], [L, 66], [R, 66]],
    7: [[L, 18], [R, 18], [M, 30], [L, 42], [R, 42], [L, 66], [R, 66]],
    8: [[L, 18], [R, 18], [M, 30], [L, 42], [R, 42], [M, 54], [L, 66], [R, 66]],
    9: [[L, 18], [R, 18], [L, 34], [R, 34], [M, 42], [L, 50], [R, 50], [L, 66], [R, 66]],
    10: [[L, 18], [R, 18], [M, 26], [L, 34], [R, 34], [L, 50], [R, 50], [M, 58], [L, 66], [R, 66]]
  }

  // The court cards get a small beach picture each: a sailboat (jack), a scallop shell (queen),
  // the sun (king). Simple shapes, drawn here.
  function court (r, s) {
    const c = SUIT[s].color
    const tint = s === 'H' || s === 'D' ? '#fbe3dc' : '#e1ebf3'
    let pic = ''
    if (r === 'J') {
      pic = `<path d="M30 21V40" stroke="${DARK}" stroke-width="1.4"/><path d="M31 22L41 38H31Z" fill="#fffaf0" stroke="${DARK}" stroke-width="1.2" stroke-linejoin="round"/>` +
        `<path d="M29 25L21 38H29Z" fill="${c}" stroke="${DARK}" stroke-width="1.2" stroke-linejoin="round"/>` +
        `<path d="M19 40H42L38 45H23Z" fill="#8a5a36" stroke="${DARK}" stroke-width="1.2" stroke-linejoin="round"/>`
    } else if (r === 'Q') {
      pic = `<path d="M30 44L19 31A12 12 0 0 1 41 31Z" fill="#f6d8b8" stroke="${DARK}" stroke-width="1.3" stroke-linejoin="round"/>` +
        [-8.5, -4.2, 0, 4.2, 8.5].map(dx => `<path d="M30 44L${30 + dx * 1.15} ${dx === 0 ? 20.5 : 23 + Math.abs(dx) * 0.55}" stroke="${c}" stroke-width="1.2"/>`).join('') +
        `<path d="M26 44H34L33 47H27Z" fill="#f6d8b8" stroke="${DARK}" stroke-width="1.2"/>`
    } else {
      const rays = Array.from({ length: 10 }, (_, i) => {
        const a = (i / 10) * Math.PI * 2
        return `<path d="M${(30 + Math.cos(a) * 8.5).toFixed(1)} ${(33 + Math.sin(a) * 8.5).toFixed(1)}L${(30 + Math.cos(a) * 12.5).toFixed(1)} ${(33 + Math.sin(a) * 12.5).toFixed(1)}" stroke="#e39a1f" stroke-width="2" stroke-linecap="round"/>`
      }).join('')
      pic = rays + `<circle cx="30" cy="33" r="7" fill="#f7c23c" stroke="${DARK}" stroke-width="1.2"/>` +
        `<path d="M27 35Q30 37.5 33 35" fill="none" stroke="${DARK}" stroke-width="1.1" stroke-linecap="round"/>`
    }
    return `<rect x="12" y="12" width="36" height="60" rx="4" fill="${tint}" stroke="${c}" stroke-width="1.2"/>` + pic +
      `<text x="30" y="64" text-anchor="middle" font-size="15" font-weight="800" fill="${c}" font-family="Georgia, 'Times New Roman', serif">${r}</text>`
  }

  function faceSvg (code) {
    const r = code.slice(0, -1); const s = code.slice(-1)
    const c = SUIT[s].color
    let middle = ''
    if (r === 'A') middle = pip(s, 30, 42, 24)
    else if (PIPS[r]) middle = PIPS[r].map(([x, y]) => pip(s, x, y, 10, y > 42)).join('')
    else middle = court(r, s)
    const index = (flip) => {
      const g = `<text x="7" y="13" text-anchor="middle" font-size="${r === '10' ? 9.5 : 11}" font-weight="800" fill="${c}" font-family="system-ui, Arial, sans-serif" letter-spacing="${r === '10' ? -0.8 : 0}">${r}</text>` + pip(s, 7, 19.5, 7)
      return flip ? `<g transform="rotate(180 30 42)">${g}</g>` : g
    }
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 84">' +
      '<rect x="0.75" y="0.75" width="58.5" height="82.5" rx="5" fill="#fffdf8" stroke="#3a3330" stroke-width="1.5"/>' +
      middle + index(false) + index(true) + '</svg>'
  }

  // The back: the sea, a band of waves, and a little sun. Same for every card.
  const BACK = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 84">' +
    '<rect x="0.75" y="0.75" width="58.5" height="82.5" rx="5" fill="#fffdf8" stroke="#3a3330" stroke-width="1.5"/>' +
    '<rect x="4" y="4" width="52" height="76" rx="3" fill="#1f6f8b"/>' +
    [14, 26, 38, 50, 62, 74].map((y, i) => `<path d="M4 ${y}q6.5 -${i % 2 ? 4 : 3} 13 0t13 0t13 0t13 0" fill="none" stroke="${i % 2 ? '#8fd0de' : '#4fa3bb'}" stroke-width="2.2"/>`).join('') +
    '<circle cx="30" cy="42" r="10.5" fill="#1f6f8b" stroke="#fffdf8" stroke-width="2"/>' +
    '<circle cx="30" cy="42" r="6" fill="#f7c23c"/></svg>'

  function cardLabel (code) {
    const r = code.slice(0, -1); const s = code.slice(-1)
    return (RANK_WORD[r] || r) + ' of ' + SUIT[s].name
  }
  function cardNode (code, attrs) {
    const n = el('span', Object.assign({ class: 'pcard', role: 'img', 'aria-label': cardLabel(code) }, attrs || {}))
    n.append(svgNode(faceSvg(code)))
    return n
  }
  function backNode (attrs) {
    const n = el('span', Object.assign({ class: 'pcard back', 'aria-hidden': 'true' }, attrs || {}))
    n.append(svgNode(BACK))
    return n
  }
  function suitIcon (s, size) {
    const n = el('span', { class: 'suit-icon', 'aria-hidden': 'true' })
    n.append(svgNode(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="${size || 20}" height="${size || 20}">${pip(s, 5, 5, 10)}</svg>`))
    return n
  }

  // ------------------------------------------------------------------ the table
  // ctx: { view, root, move(text), me }
  function render (ctx) {
    const { view, root } = ctx
    const p = view.position
    const crazy = view.game === 'crazy8'
    const seats = view.seats
    const mine = view.my_seat
    const selected = ctx.selected || null
    root.replaceChildren()

    // Opponents (everyone but me, in turn order starting after me), with card counts.
    const order = seats.map(s => s.seat)
    const start = mine === null ? 0 : (mine + 1) % seats.length
    const others = order.slice(start).concat(order.slice(0, start)).filter(s => s !== mine)
    const asks = view.your_turn && !crazy ? view.legal.filter(m => m.startsWith('ask ')) : []
    root.append(el('div', { class: 'opponents' }, others.map(s => {
      const seat = seats[s]
      const turn = view.status === 'playing' && view.to_move === s
      const out = p.out.includes(s)
      const n = p.counts[s]
      const fan = el('span', { class: 'mini-fan', 'aria-hidden': 'true' })
      for (let i = 0; i < Math.min(n, 7); i++) fan.append(backNode())
      const name = seat.player ? seat.player.name : 'Empty seat'
      const askThis = selected ? asks.find(m => m === 'ask ' + name + ' ' + selected + 's') : null
      return el('div', { class: 'opp' + (turn ? ' to-move' : '') + (out ? ' out' : '') },
        seat.player ? avatar(seat.player, { twitch: turn }) : el('span', { class: 'avatar' }),
        el('div', { class: 'opp-info' },
          el('strong', { text: name }),
          el('span', { class: 'count', text: out ? 'left the game' : n + (n === 1 ? ' card' : ' cards') }),
          fan,
          !crazy && p.books[s].length ? el('span', { class: 'books', text: 'Books: ' + p.books[s].map(r => r + 's').join(' ') }) : null),
        turn ? el('span', { class: 'turn-tag', text: 'their turn' }) : null,
        askThis ? el('button', { class: 'primary ask', type: 'button', text: 'Ask ' + name + ' for ' + selected + 's', onclick: () => ctx.move(askThis) }) : null)
    })))

    // The middle: the draw stack (and the pile, in Crazy Eights).
    const canDraw = view.your_turn && view.legal.includes('draw')
    const stack = el(canDraw ? 'button' : 'div', {
      class: 'stack' + (canDraw ? ' can-draw' : ''),
      type: canDraw ? 'button' : null,
      'aria-label': (crazy ? 'Draw stack, ' : 'The pond, ') + p.stock + ' cards' + (canDraw ? ': tap to draw' : ''),
      onclick: canDraw ? () => ctx.move('draw') : null
    }, p.stock ? backNode() : el('span', { class: 'pcard empty' }),
    el('span', { class: 'stack-count', text: p.stock + (crazy ? ' to draw' : ' in the pond') }))
    const middle = el('div', { class: 'middle' }, stack)
    if (crazy) {
      const follow = p.suit !== p.top.slice(-1)
      middle.append(el('div', { class: 'pile' }, cardNode(p.top),
        el('span', { class: 'stack-count' }, follow ? el('span', {}, 'Play ', suitIcon(p.suit, 16), ' ' + SUIT[p.suit].name) : 'The pile')))
    }
    root.append(middle)

    // My books (Go Fish), then my hand.
    if (mine !== null) {
      const me = seats[mine]
      const turn = view.status === 'playing' && view.to_move === mine
      root.append(el('div', { class: 'me-row' + (turn ? ' to-move' : '') },
        el('strong', { text: me.player ? me.player.name : 'You' }),
        el('span', { class: 'count', text: p.out.includes(mine) ? 'You left this game' : (p.hand ? p.hand.length : 0) + ' cards' }),
        !crazy && p.books[mine].length ? el('span', { class: 'books', text: 'Your books: ' + p.books[mine].map(r => r + 's').join(' ') }) : null))
      root.append(handNode(ctx))
      const buttons = el('div', { class: 'hand-actions' })
      if (canDraw) buttons.append(el('button', { class: 'primary', type: 'button', text: crazy ? 'Draw a card' : 'Draw from the pond', onclick: () => ctx.move('draw') }))
      if (view.your_turn && view.legal.includes('pass')) buttons.append(el('button', { class: 'primary', type: 'button', text: 'Pass', onclick: () => ctx.move('pass') }))
      if (buttons.childNodes.length) root.append(buttons)
    } else {
      root.append(el('p', { class: 'hint watching-note', text: 'You\'re watching: everyone\'s hands stay hidden, so you see how many cards each player holds.' }))
    }
  }

  function playsFor (view, code) {
    return view.your_turn ? view.legal.filter(m => m === 'play ' + code || m.startsWith('play ' + code + ' ')) : []
  }

  function handNode (ctx) {
    const { view } = ctx
    const p = view.position
    const crazy = view.game === 'crazy8'
    const hand = p.hand || []
    const box = el('div', { class: 'hand', role: 'group', 'aria-label': 'Your hand' })
    const n = hand.length
    // Fan: spread the cards over the width there is, overlapping when there are many.
    // (Room is left at both ends for the outer cards' tilt.)
    const width = Math.max(220, Math.min((ctx.root.clientWidth || 600) - 56, 680))
    const cw = width < 420 ? 56 : 72
    box.style.setProperty('--cw', cw + 'px')
    const step = n > 1 ? Math.min(cw * 0.78, (width - cw) / (n - 1)) : 0
    box.style.setProperty('--step', step.toFixed(1) + 'px')
    box.style.height = Math.round(cw * 1.4 + 26) + 'px'
    const total = cw + step * (n - 1)
    hand.forEach((code, i) => {
      const t = n > 1 ? i / (n - 1) - 0.5 : 0
      const plays = crazy ? playsFor(view, code) : []
      const rank = code.slice(0, -1)
      const askable = !crazy && view.your_turn && view.legal.some(m => m.endsWith(' ' + rank + 's'))
      const drawn = crazy && p.drawn === code
      const live = plays.length > 0 || askable
      const chosen = !crazy && ctx.selected === rank
      const cls = ['in-hand']
      if (live) cls.push('playable')
      if (view.your_turn && !live) cls.push('dim')
      if (drawn) cls.push('drawn')
      if (chosen) cls.push('chosen')
      const b = el(live ? 'button' : 'span', {
        class: cls.join(' '),
        type: live ? 'button' : null,
        'aria-label': cardLabel(code) + (live ? (crazy ? ': play it' : ': ask for ' + rank + 's') : ''),
        onclick: live ? () => tapCard(ctx, code, plays) : null
      }, cardNode(code))
      // Set through the style object: the Beach's pages allow no inline style attributes.
      b.style.left = `calc(50% - ${(total / 2).toFixed(1)}px + ${(step * i).toFixed(1)}px)`
      b.style.transform = `rotate(${(t * Math.min(24, n * 2.4)).toFixed(1)}deg) translateY(${(Math.abs(t) * Math.min(18, n * 1.6)).toFixed(1)}px)`
      box.append(b)
    })
    if (!n) box.append(el('p', { class: 'hint empty-hand', text: crazy ? 'No cards.' : 'Your hand is empty: draw from the pond on your turn.' }))
    return box
  }

  function tapCard (ctx, code, plays) {
    const crazy = ctx.view.game === 'crazy8'
    if (!crazy) {
      const rank = code.slice(0, -1)
      ctx.select(ctx.selected === rank ? null : rank)
      return
    }
    if (plays.length === 1) { ctx.move(plays[0]); return }
    suitPicker(ctx, code, plays)
  }

  // An eight is wild: choose the suit the next player must follow.
  function suitPicker (ctx, code, plays) {
    const close = () => dlg.remove()
    const dlg = el('div', { class: 'suit-picker', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Name the next suit' },
      el('div', { class: 'suit-box' },
        el('div', { class: 'suit-head' }, cardNode(code), el('div', {},
          el('h2', { text: 'Eights are wild' }),
          el('p', { text: 'Name the suit the next player has to follow.' }))),
        el('div', { class: 'suit-grid' }, ['S', 'H', 'D', 'C'].map(s => {
          const m = plays.find(x => x.endsWith(' name ' + SUIT[s].name))
          return el('button', { class: 'suit-btn suit-' + s, type: 'button', onclick: () => { close(); ctx.move(m) } },
            suitIcon(s, 34), el('span', { text: SUIT[s].name[0].toUpperCase() + SUIT[s].name.slice(1) }))
        })),
        el('button', { class: 'quiet', type: 'button', text: 'Keep it for now', onclick: close })))
    dlg.addEventListener('click', ev => { if (ev.target === dlg) close() })
    dlg.addEventListener('keydown', ev => { if (ev.key === 'Escape') close() })
    document.body.append(dlg)
    dlg.querySelector('.suit-btn').focus()
  }

  window.BeachCards = { render, faceSvg, BACK, cardNode, backNode, cardLabel, SUIT }
})()
