// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// The Boardwalk's newer tables in the browser (10-19): Lanterns o'er the Bay, Message in a Bottle and
// Hearts. Like cards.js, the page never decides what's legal: every button becomes one of the moves in
// the Beach's `legal` list (or, for a story line or a pass, a move the Beach then checks).
'use strict'
;(() => {
  const { el, svgNode, avatar } = Beach
  const LANTERN = { red: '#d8483a', gold: '#e8a92a', blue: '#3f7fc4', white: '#f4efe2' }
  const INK = '#2f2323'
  // A corked bottle with a rolled note inside, bobbing on two ripples.
  const BOTTLE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 40" width="96" height="60">' +
    '<path d="M4 34Q12 30 20 34T36 34T52 34T64 34" fill="none" stroke="#5aa6c8" stroke-width="2" stroke-linecap="round"/>' +
    '<g transform="rotate(-18 32 20)"><rect x="12" y="12" width="34" height="16" rx="7" fill="#bfe3d6" fill-opacity=".75" stroke="#2f2323" stroke-width="1.5"/>' +
    '<path d="M46 16H52V24H46" fill="#bfe3d6" stroke="#2f2323" stroke-width="1.5"/><rect x="52" y="16.5" width="5" height="7" rx="1" fill="#a77a4f" stroke="#2f2323" stroke-width="1.2"/>' +
    '<rect x="18" y="16" width="20" height="8" rx="3" fill="#f4ecd8" stroke="#2f2323" stroke-width="1"/></g></svg>'
  const picks = {}        // per table: Hearts cards chosen to pass, kept across redraws

  function nameOf (view, s) { const p = view.seats[s] && view.seats[s].player; return p ? p.name : 'seat ' + (s + 1) }
  function others (view) {
    const order = view.seats.map(s => s.seat)
    const mine = view.my_seat
    const start = mine === null ? 0 : (mine + 1) % order.length
    return order.slice(start).concat(order.slice(0, start)).filter(s => s !== mine)
  }
  function seatHead (view, s, extra) {
    const seat = view.seats[s]
    const turn = view.status === 'playing' && view.to_move === s
    const out = view.position.out.includes(s)
    return el('div', { class: 'opp-head' + (turn ? ' to-move' : '') + (out ? ' out' : '') },
      seat.player ? avatar(seat.player, { twitch: turn }) : el('span', { class: 'avatar' }),
      el('strong', { text: nameOf(view, s) }),
      out ? el('span', { class: 'hint', text: 'left the game' }) : extra || null,
      turn ? el('span', { class: 'turn-tag', text: 'their turn' }) : null)
  }

  // ------------------------------------------------------------------ Lanterns o'er the Bay

  function lanternSvg (colour, number, glow) {
    const fill = colour ? LANTERN[colour] : '#cfc6b5'
    const text = number ? String(number) : (number === 0 ? '' : '?')   // 0: an unlit lantern in the bay
    const dark = colour === 'white' || !colour ? INK : '#fff'
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 56" width="40" height="56">` +
      (glow ? `<circle cx="20" cy="30" r="19" fill="${fill}" opacity=".25"/>` : '') +
      `<path d="M14 6H26M20 2V6" stroke="${INK}" stroke-width="1.6" stroke-linecap="round"/>` +
      `<rect x="9" y="8" width="22" height="5" rx="1.5" fill="#6b4a2f" stroke="${INK}" stroke-width="1.2"/>` +
      `<path d="M10 13H30Q35 30 30 47H10Q5 30 10 13Z" fill="${fill}" stroke="${INK}" stroke-width="1.4"/>` +
      `<path d="M15 14Q12 30 15 46M25 14Q28 30 25 46" fill="none" stroke="${INK}" stroke-opacity=".25" stroke-width="1"/>` +
      `<rect x="9" y="47" width="22" height="5" rx="1.5" fill="#6b4a2f" stroke="${INK}" stroke-width="1.2"/>` +
      `<text x="20" y="35" text-anchor="middle" font-family="Georgia, serif" font-size="15" font-weight="700" fill="${dark}">${text}</text></svg>`
  }
  function lanternCard (code, told, label) {
    const colour = code ? { R: 'red', G: 'gold', B: 'blue', W: 'white' }[code[0]] : (told && told.colour)
    const number = code ? Number(code.slice(1)) : (told && told.number)
    const n = el('span', { class: 'lantern' + (code ? '' : ' unknown'), role: 'img', 'aria-label': label })
    n.append(svgNode(lanternSvg(colour, number, false)))
    return n
  }
  function toldText (t) {
    if (!t) return ''
    const bits = []
    if (t.colour) bits.push(t.colour)
    if (t.number) bits.push(String(t.number))
    const nots = t.not_colours.concat(t.not_numbers.map(String))
    if (nots.length && !(t.colour && t.number)) bits.push('not ' + nots.join('/'))
    return bits.join(', ') || 'nothing yet'
  }

  function renderLanterns (ctx) {
    const { view, root } = ctx
    const p = view.position
    const mine = view.my_seat
    const legal = view.your_turn ? view.legal : []
    root.replaceChildren()
    // The bay: each colour's tallest lantern, the hints and the squalls.
    const bay = el('div', { class: 'bay', 'aria-label': 'The bay' }, p.colours.map(c => {
      const n = el('div', { class: 'bay-row' })
      n.append(el('span', { class: 'lantern lit' + (p.lit[c] ? '' : ' dark') },
        svgNode(lanternSvg(c, p.lit[c], p.lit[c] > 0))))
      n.append(el('span', { class: 'hint', text: c + ' ' + p.lit[c] + '/5' }))
      return n
    }))
    const dots = (k, max, cls) => el('span', { class: 'dots ' + cls, 'aria-hidden': 'true' },
      Array.from({ length: max }, (_, i) => el('span', { class: i < k ? 'on' : '' })))
    root.append(el('div', { class: 'bay-wrap' }, bay,
      el('div', { class: 'bay-facts' },
        el('p', {}, el('strong', { text: p.score + ' of 20 lit' }), ' · deck ' + p.deck + (p.last_turns ? ' · last turns!' : '')),
        el('p', { 'aria-label': p.hints + ' of ' + p.max_hints + ' hints left' }, 'Hints ', dots(p.hints, p.max_hints, 'hints')),
        el('p', { 'aria-label': p.squalls + ' of ' + p.max_squalls + ' squalls' }, 'Squalls ', dots(p.squalls, p.max_squalls, 'squalls')),
        p.lost.length ? el('p', { class: 'hint', text: 'Lost: ' + p.lost.map(c => ({ R: 'red ', G: 'gold ', B: 'blue ', W: 'white ' }[c[0]] + c.slice(1))).join(', ') }) : null)))
    // Everyone else's hands, face up to you, with what each of them knows; your hint buttons.
    for (const s of others(view)) {
      const hand = p.hands[s] || []
      const hints = legal.filter(m => m.startsWith('hint ' + nameOf(view, s) + ' '))
      root.append(el('div', { class: 'opp lantern-hand' }, seatHead(view, s),
        el('div', { class: 'lantern-row' }, hand.map((x, i) => el('div', { class: 'lantern-slot' },
          lanternCard(x.c, x.told, (i + 1) + ': ' + (x.c ? x.c : '?')),
          el('span', { class: 'told', text: 'knows: ' + toldText(x.told) })))),
        hints.length ? el('div', { class: 'row hint-buttons' }, el('span', { class: 'hint', text: 'Hint:' }),
          hints.map(m => {
            const what = m.split(' ').pop()
            return el('button', { type: 'button', class: 'quiet lantern-hint hint-' + what, text: what, onclick: () => ctx.move(m) })
          })) : null))
    }
    // Your own hand: facing away from you; what you've been told about each card.
    if (mine !== null) {
      const hand = p.hands[mine] || []
      root.append(el('div', { class: 'me-row' + (view.your_turn ? ' to-move' : '') },
        el('strong', { text: 'Your lanterns' }), el('span', { class: 'hint', text: 'They face away from you: hints tell you what they are.' })))
      root.append(el('div', { class: 'lantern-row mine' }, hand.map((x, i) => {
        const k = i + 1
        const play = legal.includes('play ' + k)
        const drop = legal.includes('discard ' + k)
        return el('div', { class: 'lantern-slot' },
          lanternCard(null, x.told, 'your card ' + k),
          el('span', { class: 'told', text: k + ': ' + toldText(x.told) }),
          play || drop ? el('div', { class: 'slot-buttons' },
            play ? el('button', { type: 'button', class: 'primary', text: 'Play', onclick: () => ctx.move('play ' + k) }) : null,
            drop ? el('button', { type: 'button', class: 'quiet', text: 'Let go', onclick: () => ctx.move('discard ' + k) }) : null) : null)
      })))
    } else {
      root.append(el('p', { class: 'hint watching-note', text: 'You\'re watching: you can see every lantern. Please don\'t tell the players theirs.' }))
    }
  }

  // ------------------------------------------------------------------ Message in a Bottle

  function renderBottle (ctx) {
    const { view, root } = ctx
    const p = view.position
    root.replaceChildren()
    const writers = view.seats.map(s => nameOf(view, s.seat) + ' ' + p.written[s.seat] + '/' + p.rounds).join(' · ')
    root.append(el('p', { class: 'hint', text: p.count + ' line' + (p.count === 1 ? '' : 's') + ' in the bottle · ' + writers }))
    if (p.lines) {
      // The reveal: the whole story, each part with its writer.
      root.append(el('article', { class: 'card bottle-story' },
        el('h2', { text: p.phase === 'vote' ? 'The story, revealed!' : 'The story' }),
        el('p', { class: 'opening' }, el('em', { text: p.opening })),
        p.lines.map(ln => el('p', {}, ln.text, ' ', el('span', { class: 'hint', text: '(' + nameOf(view, ln.seat) + ')' })))))
      if (p.phase === 'vote') {
        const said = Object.entries(p.votes).map(([s, v]) => nameOf(view, Number(s)) + ': ' + ({ everyone: 'shelve it for everyone', residents: 'shelve it for residents', keep: 'keep it here' })[v])
        root.append(el('p', { class: 'hint', text: 'Should it go on the Reading Room\'s bottle-stories shelf? It goes only if nobody says keep it here.' + (said.length ? ' So far: ' + said.join('; ') + '.' : '') }))
        if (view.your_turn) {
          root.append(el('div', { class: 'row' },
            el('button', { type: 'button', class: 'primary', text: 'Shelve it for everyone', onclick: () => ctx.move('shelve everyone') }),
            el('button', { type: 'button', text: 'Shelve it for residents', onclick: () => ctx.move('shelve residents') }),
            el('button', { type: 'button', class: 'quiet', text: 'Keep it here', onclick: () => ctx.move('keep it here') })))
        }
      }
      return
    }
    if (view.your_turn && p.before) {
      const box = el('textarea', { rows: '3', maxlength: String(p.max_line), 'aria-label': 'Your line', placeholder: 'A line or two that follows on…' })
      const count = el('span', { class: 'hint', text: '0 / ' + p.max_line })
      box.addEventListener('input', () => { count.textContent = box.value.length + ' / ' + p.max_line })
      root.append(el('div', { class: 'card bottle-note' },
        el('p', { class: 'hint', text: p.first ? 'The bottle washes up with this opening line:' : 'The line before yours (all you can see):' }),
        el('p', { class: 'before' }, el('em', { text: p.before }))),
      el('form', {
        class: 'bottle-write',
        onsubmit: (ev) => { ev.preventDefault(); const t = box.value.trim(); if (t) ctx.move('write ' + t) }
      }, box, el('div', { class: 'row' }, count, el('button', { type: 'submit', class: 'primary', text: 'Add it and pass the bottle' }))))
      return
    }
    const who = view.status === 'playing' ? nameOf(view, view.to_move) : null
    root.append(el('div', { class: 'card bottle-note' },
      el('p', { class: 'bottle-art', 'aria-hidden': 'true' }, svgNode(BOTTLE)),
      el('p', { text: who ? 'The bottle is with ' + who + '. The story stays a secret until the last line is in.' : 'Waiting for the bottle.' })))
  }

  // ------------------------------------------------------------------ Hearts

  function renderHearts (ctx) {
    const { view, root } = ctx
    const p = view.position
    const mine = view.my_seat
    const C = window.BeachCards
    root.replaceChildren()
    root.append(el('div', { class: 'opponents' }, others(view).map(s => el('div', { class: 'opp' },
      seatHead(view, s, el('span', { class: 'count', text: p.counts[s] + ' cards' })),
      el('span', { class: 'hint', text: 'score ' + p.scores[s] + ' · this hand ' + p.points[s] }),
      p.phase === 'pass' && p.chosen.includes(s) ? el('span', { class: 'hint', text: 'has chosen a pass' }) : null))))
    // The trick in the middle.
    const trick = el('div', { class: 'trick' }, p.trick.length
      ? p.trick.map(([s, c]) => el('div', { class: 'trick-card' }, C.cardNode(c), el('span', { class: 'hint', text: nameOf(view, s) })))
      : el('p', { class: 'hint', text: p.phase === 'pass' ? 'Passing ' + p.direction + ': everyone chooses three cards.' : (view.status === 'playing' ? nameOf(view, view.to_move) + ' leads.' : '') }))
    root.append(el('div', { class: 'middle' }, trick,
      el('p', { class: 'hint', text: 'Game to ' + p.target + ', lowest wins' + (p.broken ? ' · hearts broken' : '') })))
    if (mine === null) {
      root.append(el('p', { class: 'hint watching-note', text: 'You\'re watching: everyone\'s hands stay hidden.' }))
      return
    }
    root.append(el('div', { class: 'me-row' + (view.your_turn ? ' to-move' : '') },
      el('strong', { text: 'You' }), el('span', { class: 'hint', text: 'score ' + p.scores[mine] + ' · this hand ' + p.points[mine] })))
    const key = view.id + ':' + p.ply
    const passing = view.your_turn && p.phase === 'pass'
    const chosen = passing ? (picks[key] = picks[key] || []) : []
    const hand = p.hand || []
    const playable = new Set(view.your_turn && p.phase === 'play' ? view.legal.map(m => m.slice(5)) : [])
    const box = el('div', { class: 'hand-flat', role: 'group', 'aria-label': 'Your hand' }, hand.map(code => {
      const live = passing || playable.has(code)
      const isChosen = chosen.includes(code) || (p.passing || []).includes(code)
      return el(live ? 'button' : 'span', {
        class: 'in-hand' + (live ? ' playable' : '') + (view.your_turn && !live ? ' dim' : '') + (isChosen ? ' chosen' : ''),
        type: live ? 'button' : null,
        'aria-label': C.cardLabel(code) + (passing ? (isChosen ? ': chosen to pass' : ': choose to pass') : live ? ': play it' : ''),
        onclick: live ? () => {
          if (passing) {
            const i = chosen.indexOf(code)
            if (i >= 0) chosen.splice(i, 1)
            else if (chosen.length < 3) chosen.push(code)
            renderHearts(ctx)
          } else ctx.move('play ' + code)
        } : null
      }, C.cardNode(code))
    }))
    root.append(box)
    if (passing) {
      root.append(el('div', { class: 'hand-actions' },
        el('button', { type: 'button', class: 'primary', disabled: chosen.length !== 3,
          text: chosen.length === 3 ? 'Pass these three ' + (p.direction === 'across' ? 'across' : 'to the ' + p.direction) : 'Choose ' + (3 - chosen.length) + ' more',
          onclick: () => ctx.move('pass ' + chosen.join(' ')) })))
    }
  }

  // ------------------------------------------------------------------ shared

  function render (ctx) {
    const k = ctx.view.position.kind
    if (k === 'lanterns') renderLanterns(ctx)
    else if (k === 'bottle') renderBottle(ctx)
    else if (k === 'hearts') renderHearts(ctx)
  }

  // What to do now, for the line under the table.
  function tip (view) {
    const p = view.position
    if (p.kind === 'lanterns') return ' Give someone a hint, play one of your lanterns, or let one go.'
    if (p.kind === 'bottle') return p.phase === 'vote' ? ' Say whether the story goes on the shelf.' : ' Read the line before yours and add to the story.'
    if (p.kind === 'hearts') return p.phase === 'pass' ? ' Choose three cards to pass.' : (p.trick.length ? ' Follow suit if you can.' : ' Lead a card.')
    return ''
  }

  window.BeachGames = { render, tip, KINDS: ['lanterns', 'bottle', 'hearts'] }
})()
