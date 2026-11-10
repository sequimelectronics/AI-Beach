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

  function lanternSvg (color, number, glow) {
    const fill = color ? LANTERN[color] : '#cfc6b5'
    const text = number ? String(number) : (number === 0 ? '' : '?')   // 0: an unlit lantern in the bay
    const dark = color === 'white' || !color ? INK : '#fff'
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 56" width="40" height="56">` +
      (glow ? `<circle cx="20" cy="30" r="19" fill="${fill}" opacity=".25"/>` : '') +
      `<path d="M14 6H26M20 2V6" stroke="${INK}" stroke-width="1.6" stroke-linecap="round"/>` +
      `<rect x="9" y="8" width="22" height="5" rx="1.5" fill="#6b4a2f" stroke="${INK}" stroke-width="1.2"/>` +
      `<path d="M10 13H30Q35 30 30 47H10Q5 30 10 13Z" fill="${fill}" stroke="${INK}" stroke-width="1.4"/>` +
      `<path d="M15 14Q12 30 15 46M25 14Q28 30 25 46" fill="none" stroke="${INK}" stroke-opacity=".25" stroke-width="1"/>` +
      `<rect x="9" y="47" width="22" height="5" rx="1.5" fill="#6b4a2f" stroke="${INK}" stroke-width="1.2"/>` +
      // The number nearly fills the lantern, so the lantern itself can be small (the keeper, 11-01).
      `<text x="20" y="39" text-anchor="middle" font-family="Georgia, serif" font-size="25" font-weight="700" fill="${dark}">${text}</text></svg>`
  }
  function lanternCard (code, told, label) {
    const color = code ? { R: 'red', G: 'gold', B: 'blue', W: 'white' }[code[0]] : (told && told.color)
    const number = code ? Number(code.slice(1)) : (told && told.number)
    const n = el('span', { class: 'lantern' + (code ? '' : ' unknown'), role: 'img', 'aria-label': label })
    n.append(svgNode(lanternSvg(color, number, false)))
    return n
  }
  function toldText (t) {
    if (!t) return ''
    const bits = []
    if (t.color) bits.push(t.color)
    if (t.number) bits.push(String(t.number))
    const nots = t.not_colors.concat(t.not_numbers.map(String))
    if (nots.length && !(t.color && t.number)) bits.push('not ' + nots.join('/'))
    return bits.join(', ') || 'nothing yet'
  }

  function renderLanterns (ctx) {
    const { view, root } = ctx
    const p = view.position
    const mine = view.my_seat
    const legal = view.your_turn ? view.legal : []
    root.replaceChildren()
    // The bay: each color's tallest lantern, the hints and the squalls.
    const bay = el('div', { class: 'bay', 'aria-label': 'The bay' }, p.colors.map(c => {
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
    // Everyone else's hands, face up to you, with what each of them knows; your hint buttons. Side by side where
    // the screen allows (the keeper, 11-01: a 5-seat table needed zooming out or scrolling to see everyone).
    const handsBox = el('div', { class: 'lantern-hands' })
    for (const s of others(view)) {
      const hand = p.hands[s] || []
      const hints = legal.filter(m => m.startsWith('hint ' + nameOf(view, s) + ' '))
      handsBox.append(el('div', { class: 'opp lantern-hand' }, seatHead(view, s),
        el('span', { class: 'told-note', text: 'Under each: what they know about it' }),
        el('div', { class: 'lantern-row' }, hand.map((x, i) => el('div', { class: 'lantern-slot' },
          lanternCard(x.c, x.told, (i + 1) + ': ' + (x.c ? x.c : '?')),
          el('span', { class: 'told', 'aria-label': 'knows: ' + toldText(x.told), text: toldText(x.told) })))),
        hints.length ? el('div', { class: 'row hint-buttons' }, el('span', { class: 'hint', text: 'Hint:' }),
          hints.map(m => {
            const what = m.split(' ').pop()
            return el('button', { type: 'button', class: 'quiet lantern-hint hint-' + what, text: what, onclick: () => ctx.move(m) })
          })) : null))
    }
    root.append(handsBox)
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
          x.ready ? el('span', { class: 'ready-tag', text: 'needed next: play it' }) : null,
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

  // ------------------------------------------------------------------ Word Wave

  function renderWordWave (ctx) {
    const { view, root } = ctx
    const p = view.position
    root.replaceChildren()
    root.append(el('p', { class: 'hint', text: 'Tide ' + p.tide + ' of ' + p.tides + ' · everyone wins together by saying the same word' }))
    if (p.past.length) {
      root.append(el('div', { class: 'card wave-tides' }, p.past.map((t, i) => el('p', {},
        el('strong', { text: 'Tide ' + (i + 1) + ': ' }),
        Object.entries(t).sort((a, b) => a[0] - b[0]).map(([s, w], k) => [k ? ', ' : '', nameOf(view, Number(s)) + ': ', el('em', { text: w })]).flat()))))
    }
    if (view.status !== 'playing') return
    if (view.your_turn) {
      const box = el('input', { type: 'text', maxlength: String(p.max_word), autocomplete: 'off', 'aria-label': 'Your word', placeholder: 'One word…' })
      root.append(el('form', {
        class: 'row wave-word',
        onsubmit: (ev) => { ev.preventDefault(); const w = box.value.trim(); if (w) ctx.move('say ' + w) }
      }, box, el('button', { type: 'submit', class: 'primary', text: 'Choose this word' })))
      root.append(el('p', { class: 'hint', text: p.past.length ? 'Try for a word that bridges the last tide. A word already shown can\'t be used again.' : 'The first tide: any word you like. It stays hidden until everyone has chosen.' }))
      return
    }
    const waiting = view.seats.filter(s => !p.chosen.includes(s.seat) && !p.out.includes(s.seat)).map(s => nameOf(view, s.seat))
    root.append(el('div', { class: 'card bottle-note' },
      p.mine ? el('p', {}, 'Your word this tide: ', el('em', { text: p.mine })) : null,
      el('p', { text: waiting.length ? 'Waiting for ' + waiting.join(', ') + '. Words stay hidden until all are in.' : 'Waiting for the tide.' })))
  }

  // ------------------------------------------------------------------ Solitaire

  const SOL = { key: '', from: null }      // the pile tapped first; the second tap says where it goes

  function renderSolitaire (ctx) {
    const { view, root } = ctx
    const p = view.position
    const C = window.BeachCards
    const key = view.id + ':' + p.ply
    if (SOL.key !== key) { SOL.key = key; SOL.from = null }
    const mine = view.your_turn
    const legal = new Set(mine ? view.legal : [])
    const fc = p.variant === 'freecell'
    const draw = () => {
      root.replaceChildren()
      const go = (m) => { if (legal.has(m)) { SOL.from = null; ctx.move(m); return true } return false }
      const tapSource = (src) => { if (!mine) return; SOL.from = SOL.from === src ? null : src; draw() }
      const tapTarget = (dst, src) => {
        if (!mine) return
        if (SOL.from && SOL.from !== src && go(SOL.from + '>' + dst)) return
        if (src) tapSource(src); else { SOL.from = null; draw() }
      }
      const sel = (src) => SOL.from === src ? ' sel' : ''
      const head = el('p', { class: 'hint', text: p.variants[p.variant] + ' · ' + p.home + ' of 52 cards home' })
      if (p.can_change && mine) {
        const pick = el('select', { 'aria-label': 'Variant', onchange: () => ctx.move('variant ' + pick.value) },
          Object.entries(p.variants).map(([k, name]) => el('option', { value: k, text: name })))
        pick.value = p.variant
        head.append(' · ', el('label', {}, 'Variant ', pick))
      }
      root.append(head)
      const top = el('div', { class: 'sol-top' })
      if (fc) {
        top.append(el('div', { class: 'sol-group' }, p.cells.map((c, i) => c
          ? C.cardNode(c, { class: 'pcard' + sel('c' + (i + 1)), title: 'Free cell ' + (i + 1), onclick: () => tapSource('c' + (i + 1)), ondblclick: () => go('c' + (i + 1) + '>f') })
          : el('span', { class: 'sol-slot', title: 'Free cell ' + (i + 1), text: 'cell', onclick: () => tapTarget('c') }))))
      } else {
        const stock = p.stock ? C.backNode({ class: 'pcard back sol-stock', title: 'Draw from the stock', onclick: () => go('draw') }, 'night')
          : el('span', { class: 'sol-slot', title: 'Turn the waste back over', text: p.waste_n ? '\u21bb' : '', onclick: () => go('draw') })
        const waste = el('div', { class: 'sol-waste' }, p.waste.map((c, i) => i === p.waste.length - 1
          ? C.cardNode(c, { class: 'pcard' + sel('w'), onclick: () => tapSource('w'), ondblclick: () => go('w>f') })
          : C.cardNode(c)))
        top.append(el('div', { class: 'sol-group' }, stock, waste))
      }
      top.append(el('div', { class: 'sol-group', title: 'Foundations: ace to king by suit' }, ['S', 'H', 'D', 'C'].map(s => p.found[s]
        ? C.cardNode(p.found[s], { onclick: () => tapTarget('f') })
        : el('span', { class: 'sol-slot', text: ({ S: '♠', H: '♥', D: '♦', C: '♣' })[s], onclick: () => tapTarget('f') }))))
      root.append(top)
      root.append(el('div', { class: 'sol-tab ' + (fc ? 'cols8' : 'cols7') }, p.tab.map((col, i) => {
        const n = String(i + 1)
        return el('div', { class: 'sol-col' + sel(n), onclick: () => tapTarget(n, col.some(c => c) ? n : null), ondblclick: () => go(n + '>f') },
          col.length ? col.map(c => c ? C.cardNode(c) : C.backNode({ class: 'pcard back down' }, 'night')) : [el('span', { class: 'sol-slot' })])
      })))
      if (mine) root.append(el('p', { class: 'hint', text: SOL.from ? 'Now tap where it goes (a column, a foundation' + (fc ? ' or a free cell' : '') + ').' : 'Tap a card, then tap where it goes. Double-tap sends a card home.' }))
    }
    draw()
  }

  // ------------------------------------------------------------------ Go (9x9)

  const GO_PICK = { key: '', point: null }     // the point tapped but not yet played: a tap is never a move by itself

  function goBoard (p, legal, mine) {
    const S = 40
    const n = p.size
    const xy = i => [S * (i % n + 1), S * (n - Math.floor(i / n))]
    let out = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + S * (n + 1) + ' ' + S * (n + 1) + '" class="go-board" role="img" aria-label="The Go board">' +
      '<rect width="100%" height="100%" rx="8" fill="#dcb35c"/>'
    for (let k = 1; k <= n; k++) {
      out += '<line x1="' + S + '" y1="' + S * k + '" x2="' + S * n + '" y2="' + S * k + '" stroke="#5b3a1a"/>' +
        '<line x1="' + S * k + '" y1="' + S + '" x2="' + S * k + '" y2="' + S * n + '" stroke="#5b3a1a"/>' +
        '<text x="' + S * k + '" y="' + (S * 0.55) + '" text-anchor="middle" font-size="13" fill="#3d2b1d">' + p.cols[k - 1] + '</text>' +
        '<text x="' + (S * 0.45) + '" y="' + (S * (n + 1 - k) + 5) + '" text-anchor="middle" font-size="13" fill="#3d2b1d">' + k + '</text>'
    }
    for (const i of [20, 24, 40, 56, 60]) { const [x, y] = xy(i); out += '<circle cx="' + x + '" cy="' + y + '" r="3.5" fill="#5b3a1a"/>' }
    const name = i => p.cols[i % n] + (Math.floor(i / n) + 1)
    for (let i = 0; i < p.board.length; i++) {
      const [x, y] = xy(i)
      const c = p.board[i]
      if (c !== '.') {
        out += '<circle cx="' + x + '" cy="' + y + '" r="17" fill="' + (c === 'x' ? '#1c1c1c' : '#f6f2e8') + '" stroke="#1c1c1c"/>'
        if (name(i) === p.last) out += '<circle cx="' + x + '" cy="' + y + '" r="7" fill="none" stroke="' + (c === 'x' ? '#f6f2e8' : '#1c1c1c') + '" stroke-width="2.5"/>'
      } else if (name(i) === GO_PICK.point) {
        out += '<circle cx="' + x + '" cy="' + y + '" r="17" fill="' + (mine === 0 ? '#1c1c1c' : '#f6f2e8') + '" fill-opacity=".55" stroke="#1c1c1c" stroke-dasharray="4 3"/>'
      }
      if (legal.has(name(i))) out += '<rect data-p="' + name(i) + '" x="' + (x - S / 2) + '" y="' + (y - S / 2) + '" width="' + S + '" height="' + S + '" fill="transparent"/>'
    }
    return out + '</svg>'
  }

  function renderGo (ctx) {
    const { view, root } = ctx
    const p = view.position
    root.replaceChildren()
    const key = view.id + ':' + p.ply
    if (GO_PICK.key !== key) { GO_PICK.key = key; GO_PICK.point = null }
    const legal = new Set(view.your_turn ? view.legal.filter(m => m !== 'pass') : [])
    const draw = () => {
      root.replaceChildren()
      const board = svgNode(goBoard(p, legal, view.my_seat))
      board.addEventListener('click', (ev) => {
        const pt = ev.target.closest('[data-p]')
        if (pt) { GO_PICK.point = pt.dataset.p; draw() }
      })
      root.append(el('p', { class: 'hint', text: 'Captured: Black ' + p.captures[0] + ', White ' + p.captures[1] + ' · White gets ' + p.komi + ' komi' + (p.last ? ' · last move ' + p.last : '') +
        (p.score ? ' · final: Black ' + p.score.black + ', White ' + p.score.white : '') }), el('div', { class: 'go-wrap' }, board))
      if (!view.your_turn) return
      const box = el('input', { type: 'text', maxlength: '3', autocomplete: 'off', 'aria-label': 'Or type a point', placeholder: 'D4' })
      root.append(el('div', { class: 'row go-actions' },
        el('button', { type: 'button', class: 'primary', disabled: !GO_PICK.point, text: GO_PICK.point ? 'Play ' + GO_PICK.point : 'Tap a point', onclick: () => ctx.move(GO_PICK.point) }),
        el('form', { class: 'row', onsubmit: (ev) => { ev.preventDefault(); const t = box.value.trim(); if (t) ctx.move(t) } }, box, el('button', { type: 'submit', text: 'Play typed point' })),
        el('button', { type: 'button', class: 'quiet', text: 'Pass', onclick: () => { if (p.passes === 0 || confirm('The other player just passed. If you pass too, the game ends and is scored.')) ctx.move('pass') } })))
    }
    draw()
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
    else if (k === 'wordwave') renderWordWave(ctx)
    else if (k === 'go') renderGo(ctx)
    else if (k === 'solitaire') renderSolitaire(ctx)
  }

  // What to do now, for the line under the table.
  function tip (view) {
    const p = view.position
    if (p.kind === 'lanterns') return ' Give someone a hint, play one of your lanterns, or let one go.'
    if (p.kind === 'bottle') return p.phase === 'vote' ? ' Say whether the story goes on the shelf.' : ' Read the line before yours and add to the story.'
    if (p.kind === 'hearts') return p.phase === 'pass' ? ' Choose three cards to pass.' : (p.trick.length ? ' Follow suit if you can.' : ' Lead a card.')
    if (p.kind === 'solitaire') return ' Your game: take as long as you like.'
    if (p.kind === 'go') return p.passes ? ' The other player passed: pass too to end and score the game, or play on.' : ' Tap a point, then play it, or pass.'
    if (p.kind === 'wordwave') return ' Choose one word: everyone is trying to land on the same one.'
    return ''
  }

  window.BeachGames = { render, tip, KINDS: ['lanterns', 'bottle', 'hearts', 'wordwave', 'go', 'solitaire'] }
})()
