// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// The front page: an illustrated map with every zone, who's there, and a door into each.
'use strict'
;(() => {
  const { el, svgNode, avatar, api } = Beach

  // Spots along the trail on the map art (fractions of its width and height). Zones take them in the
  // order they were created, so a new zone never moves an old one. SandChat always gets the first.
  const SLOTS = [[0.36, 0.43], [0.66, 0.38], [0.56, 0.72], [0.82, 0.64], [0.26, 0.74], [0.50, 0.19],
    [0.16, 0.40], [0.72, 0.79]]
  // The same eight spots along the trail of the upright map, for phones held portrait.
  const SLOTS_PORTRAIT = [[0.35, 0.25], [0.66, 0.37], [0.33, 0.53], [0.68, 0.63], [0.35, 0.75], [0.66, 0.86],
    [0.62, 0.15], [0.30, 0.89]]
  const PORTRAIT = window.matchMedia('(orientation: portrait) and (max-width: 820px)')
  const slots = () => PORTRAIT.matches ? SLOTS_PORTRAIT : SLOTS
  const SKY_TINT = {
    dawn: 'rgba(255, 170, 170, .14)',
    morning: 'rgba(255, 245, 200, .08)',
    midday: 'rgba(0, 0, 0, 0)',
    afternoon: 'rgba(255, 210, 120, .08)',
    sunset: 'rgba(255, 120, 50, .18)',
    night: 'rgba(15, 25, 70, .42)'
  }
  const ICON = {
    // The Reading Room: three books on a shelf, one leaning.
    books: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2 20.5H22" stroke="#7a4b2a" stroke-width="2" stroke-linecap="round"/><rect x="4" y="6" width="4" height="13.5" rx=".6" fill="#4f7fa8" stroke="#2f2323"/><rect x="8.5" y="4" width="4.2" height="15.5" rx=".6" fill="#e0674f" stroke="#2f2323"/><rect x="14.6" y="7" width="4" height="13" rx=".6" fill="#f2c14e" stroke="#2f2323" transform="rotate(14 16.6 13.5)"/></svg>',
    tables: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="2.5" y="2.5" width="19" height="19" rx="2" fill="#f5e2b3" stroke="#2f2323" stroke-width="1.5"/><path d="M7 2.5h5v5H7zM17 2.5h4.5v5H17M2.5 7.5H7v5H2.5zM12 7.5h5v5h-5zM7 12.5h5v5H7zM17 12.5h4.5v5H17zM2.5 17.5H7v4H2.5zM12 17.5h5v4h-5z" fill="#7a4b2a"/><circle cx="9.5" cy="15" r="2.2" fill="#c2462e" stroke="#2f2323"/></svg>',
    chat: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2 11 Q12 1 22 11 Z" fill="#e0674f" stroke="#2f2323" stroke-width="1.5" stroke-linejoin="round"/><path d="M12 11 V22" stroke="#2f2323" stroke-width="1.8"/></svg>',
    game: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9.5" fill="#fff" stroke="#2f2323" stroke-width="1.5"/><path d="M12 2.5 A9.5 9.5 0 0 1 21.5 12 L12 12Z" fill="#e0674f"/><path d="M2.5 12 A9.5 9.5 0 0 0 12 21.5 L12 12Z" fill="#2a9d8f"/><circle cx="12" cy="12" r="9.5" fill="none" stroke="#2f2323" stroke-width="1.5"/></svg>'
  }
  const MAX_SHOWN = 6

  function countText (z) {
    if (!z.open) return T.t('closed')
    if (z.kind === 'game') return T.t('n_playing', { n: z.here }) + (z.watching ? ' · ' + T.t('n_watching', { n: z.watching }) : '')
    return z.here === 0 ? T.t('nobody_here') : T.t('n_here', { n: z.here })
  }

  // A game world opens on its own Beach page (the bar stays; Play, Watch and Leave are there).
  function go (z, what) {
    if (!z.open) return
    location.href = Beach.zoneHref(z) + (what ? '&do=' + what : '')
  }

  // Leave a zone you're in: a chat (part), a world you play in, or a world you watch.
  async function leave (z, button) {
    if (button) button.disabled = true
    const id = encodeURIComponent(z.id)
    try {
      if (z.you === 'playing') await api('DELETE', '/zones/' + id + '/play')
      else if (z.you === 'watching') await api('DELETE', '/zones/' + id + '/watch')
      else await api('POST', '/zones/' + id + '/part')
      Beach.toast(z.you === 'watching' ? T.t('world_stopped_watching', { zone: z.name }) : T.t('world_left', { zone: z.name }))
    } catch (e) { Beach.toast(e.message) }
    refresh()
    Beach.refreshBar()
  }

  // The buttons under a zone: if you're there, that you're there plus Leave; else the way in
  // (Play and Watch for a world).
  function buttons (z, cls) {
    if (!z.open) return []
    const stop = (fn) => (ev) => { ev.stopPropagation(); fn(ev) }
    if (z.you) {
      return [
        cls === 'play-pill' ? null : el('span', { class: 'you-are' }, Beach.pin(z.you), T.t('you_' + z.you)),
        el('button', { class: cls + ' leaving', type: 'button', text: z.you === 'watching' ? T.t('stop_watching') : T.t('leave'),
          'aria-label': (z.you === 'watching' ? T.t('stop_watching') : T.t('leave')) + ' ' + z.name, onclick: stop(ev => leave(z, ev.currentTarget)) })]
    }
    if (z.kind === 'game') {
      return [el('button', { class: cls, type: 'button', text: T.t('play'), 'aria-label': T.t('play') + ' ' + z.name, onclick: stop(() => go(z, 'play')) }),
        el('button', { class: cls + ' watch', type: 'button', text: T.t('watch'), 'aria-label': T.t('watch') + ' ' + z.name, onclick: stop(() => go(z, 'watch')) })]
    }
    return [el('button', { class: cls, type: 'button', text: z.tables ? T.t('play') : T.t('go_in'), onclick: stop(() => go(z)) })]
  }

  function crowd (z) {
    const box = el('div', { class: 'crowd' })
    const who = z.who || []
    for (const w of who.slice(0, MAX_SHOWN)) {
      const label = w.kind === 'guest' ? w.name + ' (guest)' : w.watching ? w.name + ' (' + T.t('watching_tag') + ')' : w.name
      const full = label + (w.badge ? ', wearing today\'s ' + w.badge.words : '')
      const b = el('button', {
        class: 'who',
        type: 'button',
        title: full,
        'aria-label': full,
        onclick: (ev) => { ev.currentTarget.classList.toggle('show') }
      }, avatar(w, { twitch: !w.watching }), el('span', { class: 'name-tag', text: label }))
      if (w.watching) b.classList.add('watching')
      box.append(b)
    }
    if (who.length > MAX_SHOWN) box.append(el('span', { class: 'more', text: '+' + (who.length - MAX_SHOWN) }))
    return box
  }

  function marker (z, slot) {
    const sign = el('button', {
      class: 'sign',
      type: 'button',
      'aria-disabled': z.open ? null : 'true',
      onclick: () => go(z)
    },
    el('span', { class: 'zone-name' }, svgNode(ICON[z.tables ? 'tables' : (z.books ? 'books' : z.kind)] || ICON.chat), z.name),
    el('span', { class: 'count', text: countText(z) }),
    z.you ? el('span', { class: 'you-line' }, Beach.pin(z.you), T.t('you_' + z.you)) : null)
    sign.querySelector('svg').setAttribute('class', 'kind-icon')
    const m = el('div', { class: 'zone' + (z.open ? '' : ' closed') + (z.you ? ' in' : ''), 'data-zone': z.id }, crowd(z), sign,
      el('div', { class: 'pills' }, buttons(z, 'play-pill')))
    m.style.left = (slot[0] * 100) + '%'
    m.style.top = (slot[1] * 100) + '%'
    return m
  }

  function names (z) {
    return (z.who || []).map(w => w.kind === 'guest' ? w.name + ' (guest)' : w.watching ? w.name + ' (' + T.t('watching_tag') + ')' : w.name)
  }

  // Phones (and zones beyond the map's spots): a card per zone, with its buttons.
  function listItem (z) {
    const who = names(z)
    return el('li', { class: 'card' + (z.open ? '' : ' closed') + (z.you ? ' in' : '') },
      el('div', { class: 'row' },
        el('strong', { text: z.name }), z.you ? Beach.pin(z.you) : null,
        el('span', { class: 'hint', text: (z.kind === 'game' ? 'game · ' : '') + countText(z) })),
      who.length ? el('div', { class: 'names', text: who.join(', ') }) : null,
      z.open ? el('div', { class: 'row' }, z.you ? el('a', { class: 'button', href: Beach.zoneHref(z), text: T.t('open') }) : null,
        buttons(z, 'primary')) : null)
  }

  // Wide screens: the markers already show each zone and its buttons, so Who's where is only
  // the names, beside the map (and a card for any zone the map has no spot for).
  function whoLine (z) {
    const who = names(z)
    if (!who.length) return null
    return el('li', {}, el('strong', { text: z.name + ': ' }), who.join(', '))
  }

  const order = Beach.zoneOrder
  // Wide screens put the map beside a column (who's where, your badges); phones stack them.
  const WIDE = window.matchMedia('(min-width: 1000px) and (orientation: landscape)')

  let mapBox, listBox, whoBox, whoTitle, arrival, badgesBox
  let badgesKey = ''

  // Today's badges: yours to wear (one at a time), gone at the Beach's daily reset.
  async function renderBadges () {
    let mine
    try { mine = await api('GET', '/me/badges') } catch (e) { return }
    const key = JSON.stringify(mine)
    if (key === badgesKey) return
    badgesKey = key
    if (!mine.today.length) { badgesBox.replaceChildren(); badgesBox.hidden = true; return }
    badgesBox.hidden = false
    const wear = async (w) => { try { await api('PUT', '/me/badges', { wear: w }); badgesKey = ''; renderBadges(); refresh() } catch (e) { Beach.toast(e.message) } }
    badgesBox.replaceChildren(
      el('h2', { text: 'Your badges today' }),
      el('p', { class: 'hint', text: 'For things you did today. Wear one on your avatar; they\'re gone tomorrow.' }),
      el('ul', {}, mine.today.map(b => el('li', {}, el('button', {
        type: 'button', class: 'quiet', 'aria-pressed': String(mine.wearing === b.id), title: b.for, onclick: () => wear(b.id)
      }, Beach.badgeIcon(b.id), el('span', { text: b.words + (mine.wearing === b.id ? ' (wearing)' : '') })))),
      el('li', {}, el('button', { type: 'button', class: 'quiet', 'aria-pressed': String(!mine.wearing), onclick: () => wear(null), text: mine.wearing ? 'Wear none' : 'Wearing none' }))))
  }
  function render (data) {
    const zones = order(data.zones)
    const sky = (zones.find(z => z.kind === 'chat') || {}).sky
    mapBox.querySelector('.map-sky').style.background = SKY_TINT[sky] || 'transparent'
    mapBox.querySelector('.map-title').textContent = data.beach
    const shown = mapBox.querySelectorAll('.zone')
    shown.forEach(n => n.remove())
    const portrait = PORTRAIT.matches
    mapBox.classList.toggle('portrait', portrait)
    const art = portrait ? '/web/map-art-portrait.svg' : '/web/map-art.svg'
    const img = mapBox.querySelector('img')
    if (img.getAttribute('src') !== art) img.setAttribute('src', art)
    zones.slice(0, slots().length).forEach((z, i) => mapBox.append(marker(z, slots()[i])))
    if (WIDE.matches) {
      whoBox.replaceChildren(...zones.slice(0, slots().length).map(whoLine).filter(Boolean))
      listBox.replaceChildren(...zones.slice(slots().length).map(listItem))
    } else {
      whoBox.replaceChildren()
      listBox.replaceChildren(...zones.map(listItem))
    }
    // Nobody anywhere: the line above the list already says the beach is quiet.
    whoTitle.hidden = !whoBox.childElementCount && !listBox.childElementCount
  }

  async function refresh () {
    if (document.hidden) return
    try {
      const data = await api('GET', '/map')
      render(data)
      const zs = await api('GET', '/zones')
      arrival.textContent = zs.arrival || ''
      renderBadges()
    } catch (e) { /* keep the last picture; try again shortly */ }
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const data = await Beach.start('map')
    if (!data) return
    const main = document.querySelector('main')
    mapBox = el('div', { class: 'map-wrap' },
      el('img', { src: '/web/map-art.svg', alt: '' }),
      el('div', { class: 'map-sky' }),
      el('div', { class: 'map-title', role: 'heading', 'aria-level': '1' }))
    listBox = el('ul', { class: 'zone-list', 'aria-label': 'Zones' })
    whoBox = el('ul', { class: 'who-where' })
    whoTitle = el('h2', { class: 'who-title', text: "Who's where" })
    arrival = el('p', { class: 'arrival' })
    badgesBox = el('section', { class: 'card my-badges', hidden: true, 'aria-label': 'Your badges today' })
    document.body.classList.add('map-page')
    main.replaceChildren(el('div', { class: 'map-layout' }, mapBox,
      el('aside', { class: 'map-side' }, arrival, whoTitle, whoBox, listBox, badgesBox)))
    render(data)
    let last = data
    refresh()
    setInterval(refresh, 5000)
    // Turning the phone (or resizing the window) redraws the map to fit.
    const redraw = () => { api('GET', '/map').then(d => { last = d; render(d) }).catch(() => render(last)) }
    PORTRAIT.addEventListener('change', redraw)
    WIDE.addEventListener('change', redraw)
  })
})()
