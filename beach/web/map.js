// The front page: an illustrated map with every zone, who's there, and a door into each.
'use strict'
;(() => {
  const { el, svgNode, avatar, api } = Beach

  // Spots along the trail on the map art (fractions of its width and height). Zones take them in the
  // order they were created, so a new zone never moves an old one. SandChat always gets the first.
  const SLOTS = [[0.36, 0.43], [0.66, 0.38], [0.56, 0.72], [0.82, 0.64], [0.26, 0.74], [0.50, 0.19],
    [0.16, 0.40], [0.72, 0.79]]
  const SKY_TINT = {
    dawn: 'rgba(255, 170, 170, .14)',
    morning: 'rgba(255, 245, 200, .08)',
    midday: 'rgba(0, 0, 0, 0)',
    afternoon: 'rgba(255, 210, 120, .08)',
    sunset: 'rgba(255, 120, 50, .18)',
    night: 'rgba(15, 25, 70, .42)'
  }
  const ICON = {
    tables: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="2.5" y="2.5" width="19" height="19" rx="2" fill="#f5e2b3" stroke="#2f2323" stroke-width="1.5"/><path d="M7 2.5h5v5H7zM17 2.5h4.5v5H17M2.5 7.5H7v5H2.5zM12 7.5h5v5h-5zM7 12.5h5v5H7zM17 12.5h4.5v5H17zM2.5 17.5H7v4H2.5zM12 17.5h5v4h-5z" fill="#7a4b2a"/><circle cx="9.5" cy="15" r="2.2" fill="#c2462e" stroke="#2f2323"/></svg>',
    chat: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2 11 Q12 1 22 11 Z" fill="#e0674f" stroke="#2f2323" stroke-width="1.5" stroke-linejoin="round"/><path d="M12 11 V22" stroke="#2f2323" stroke-width="1.8"/></svg>',
    game: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9.5" fill="#fff" stroke="#2f2323" stroke-width="1.5"/><path d="M12 2.5 A9.5 9.5 0 0 1 21.5 12 L12 12Z" fill="#e0674f"/><path d="M2.5 12 A9.5 9.5 0 0 0 12 21.5 L12 12Z" fill="#2a9d8f"/><circle cx="12" cy="12" r="9.5" fill="none" stroke="#2f2323" stroke-width="1.5"/></svg>'
  }
  const MAX_SHOWN = 6

  function countText (z) {
    if (!z.open) return 'closed'
    if (z.kind === 'game') return z.here + ' playing'
    return z.here === 0 ? 'nobody here' : z.here + ' here'
  }

  function go (z) {
    if (!z.open) return
    if (z.tables) location.href = '/boardwalk?zone=' + encodeURIComponent(z.id)
    else if (z.kind === 'chat') location.href = '/chat?zone=' + encodeURIComponent(z.id)
    else if (z.viewer_url) window.open(z.viewer_url, '_blank', 'noopener')
    else Beach.toast(z.name + " doesn't have a viewer yet; the keeper can add one.")
  }

  function crowd (z) {
    const box = el('div', { class: 'crowd' })
    const who = z.who || []
    for (const w of who.slice(0, MAX_SHOWN)) {
      const label = w.kind === 'guest' ? w.name + ' (guest)' : w.name
      const b = el('button', {
        class: 'who',
        type: 'button',
        title: label,
        'aria-label': label,
        onclick: (ev) => { ev.currentTarget.classList.toggle('show') }
      }, avatar(w, { twitch: true }), el('span', { class: 'name-tag', text: label }))
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
    el('span', { class: 'zone-name' }, svgNode(ICON[z.tables ? 'tables' : z.kind] || ICON.chat), z.name),
    el('span', { class: 'count', text: countText(z) }))
    sign.querySelector('svg').setAttribute('class', 'kind-icon')
    const m = el('div', { class: 'zone' + (z.open ? '' : ' closed'), 'data-zone': z.id }, crowd(z), sign)
    m.style.left = (slot[0] * 100) + '%'
    m.style.top = (slot[1] * 100) + '%'
    return m
  }

  function listItem (z) {
    const names = (z.who || []).map(w => w.kind === 'guest' ? w.name + ' (guest)' : w.name)
    return el('li', { class: 'card' + (z.open ? '' : ' closed') },
      el('div', { class: 'row' },
        el('strong', { text: z.name }),
        el('span', { class: 'hint', text: (z.kind === 'game' ? 'game · ' : '') + countText(z) })),
      names.length ? el('div', { class: 'names', text: names.join(', ') }) : null,
      z.open ? el('div', { class: 'row' }, el('button', { class: 'primary', type: 'button', onclick: () => go(z), text: z.tables ? 'Play' : z.kind === 'chat' ? 'Go in' : 'Watch' })) : null)
  }

  function order (zones) {
    return zones.slice().sort((a, b) => (a.kind === 'chat' && a.id === 'sandchat' ? -1 : b.kind === 'chat' && b.id === 'sandchat' ? 1 : a.created_at - b.created_at))
  }

  let mapBox, listBox, arrival
  function render (data) {
    const zones = order(data.zones)
    const sky = (zones.find(z => z.kind === 'chat') || {}).sky
    mapBox.querySelector('.map-sky').style.background = SKY_TINT[sky] || 'transparent'
    mapBox.querySelector('.map-title').textContent = data.beach
    const shown = mapBox.querySelectorAll('.zone')
    shown.forEach(n => n.remove())
    zones.slice(0, SLOTS.length).forEach((z, i) => mapBox.append(marker(z, SLOTS[i])))
    listBox.replaceChildren(...zones.map(listItem))
  }

  async function refresh () {
    if (document.hidden) return
    try {
      const data = await api('GET', '/map')
      render(data)
      const zs = await api('GET', '/zones')
      arrival.textContent = zs.arrival || ''
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
    arrival = el('p', { class: 'arrival' })
    main.replaceChildren(mapBox, arrival, el('h2', { text: "Who's where" }), listBox)
    render(data)
    refresh()
    setInterval(refresh, 5000)
  })
})()
