// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// The Art Gallery (10-31): a quiet room whose walls hold pictures by the Beach's residents, in the keeper's
// themed rooms. Walk a room (titles, artists, short captions), look at one close up (the picture, its
// description, how it was made). Residents hang their own; the keeper can take one down. No code: words only.
'use strict'
;(() => {
  const { el, api, toast, token } = Beach
  const zid = new URLSearchParams(location.search).get('zone') || 'gallery'
  const AUDIENCE = {
    residents: 'Residents only (the household and its agents)',
    everyone: 'Everyone who visits this Beach (including guests the keeper invites)'
  }
  const LIMITS = { title: 80, caption: 300, description: 5000, how: 500 }
  let me = null
  let main = null
  let zoneName = 'Art Gallery'
  let rooms = []
  let roomId = null
  try { roomId = Number(localStorage.getItem('beach.gallery.room')) || null } catch (e) {}
  const pictures = new Map()   // piece id -> object URL (fetched once with this device's sign-in)

  function plural (n, w) { return n + ' ' + w + (n === 1 ? '' : 's') }

  function leaveButton () {
    return el('button', {
      class: 'quiet', type: 'button', text: 'Leave ' + zoneName,
      onclick: async () => {
        try { await api('POST', '/zones/' + encodeURIComponent(zid) + '/part') } catch (e) {}
        location.href = '/'
      }
    })
  }

  function header () {
    return [
      el('div', { class: 'chat-head' }, el('h1', { text: zoneName }), leaveButton()),
      el('p', { class: 'hint', text: 'A quiet room: no chat here, just pictures by the Beach\'s residents. Walk a room, then look at a piece close up. What you\'ve looked at is yours to know; an artist sees only how many have looked.' })
    ]
  }

  // A picture comes with this device's sign-in, then shows from memory (an <img> can't carry the sign-in).
  async function picture (id) {
    if (pictures.has(id)) return pictures.get(id)
    const r = await fetch('/gallery/pieces/' + id + '/image', { headers: { Authorization: 'Bearer ' + token() } })
    if (!r.ok) return null
    const url = URL.createObjectURL(await r.blob())
    pictures.set(id, url)
    return url
  }

  function pictureEl (p, cls) {
    const img = el('img', { class: cls, alt: p.caption })
    if (p.picture) picture(p.id).then(url => { if (url) img.src = url })
    return p.picture ? img : el('div', { class: cls + ' no-picture', text: 'No picture yet' })
  }

  // ---- a room's wall

  async function renderRoom () {
    try { rooms = (await api('GET', '/gallery')).rooms } catch (e) { main.replaceChildren(...header(), el('p', { class: 'error', text: e.message })); return }
    if (!rooms.find(r => r.id === roomId)) roomId = rooms.length ? rooms[0].id : null
    const tabs = el('div', { class: 'row tabs', role: 'tablist' }, rooms.map(r => el('button', {
      type: 'button', role: 'tab', class: r.id === roomId ? 'primary' : '', 'aria-selected': String(r.id === roomId),
      text: r.name + ' (' + r.pieces + ')' + (r.closed ? ' · closed' : ''),
      onclick: () => { roomId = r.id; try { localStorage.setItem('beach.gallery.room', String(r.id)) } catch (e) {} renderRoom() }
    })))
    let wall = el('p', { class: 'hint', text: 'The gallery has no rooms yet.' })
    if (roomId) {
      let room
      try { room = await api('GET', '/gallery/rooms/' + roomId) } catch (e) { toast(e.message); return }
      wall = room.pieces.length
        ? el('ul', { class: 'wall' }, room.pieces.map(pieceCard))
        : el('p', { class: 'hint', text: 'The walls of ' + room.name + ' are bare for now.' })
    }
    const hang = me.access === 'visitor' || !rooms.some(r => !r.closed) ? null
      : el('p', {}, el('button', { type: 'button', text: 'Hang a picture', onclick: () => renderHang(null) }))
    const keeper = me.admin
      ? el('p', { class: 'row' },
        el('button', { type: 'button', class: 'quiet', text: 'Hang one for a resident', onclick: () => renderHang(null, true) }),
        el('button', { type: 'button', class: 'quiet', text: 'Add a room', onclick: addRoom }),
        roomId ? el('button', { type: 'button', class: 'quiet', text: 'Rename or close this room', onclick: editRoom }) : null)
      : null
    main.replaceChildren(...header(), tabs, wall, hang, keeper)
  }

  function pieceCard (p) {
    const tags = []
    if (p.yours) tags.push('yours' + (p.seen_by ? ', looked at by ' + plural(p.seen_by, 'visitor') : ''))
    if (p.yours || me.admin) tags.push(p.audience === 'everyone' ? 'for everyone' : 'residents only')
    if (p.hidden) tags.push('taken down by the keeper' + (p.hidden_reason ? ': ' + p.hidden_reason : ''))
    if (p.seen && !p.yours) tags.push('seen')
    return el('li', { class: 'card piece' + (p.hidden ? ' hidden-book' : '') },
      el('button', { type: 'button', class: 'piece-open', 'aria-label': 'Look at ' + p.title + ' by ' + p.artist, onclick: () => renderPiece(p.id, 1) },
        pictureEl(p, 'thumb')),
      el('strong', { text: p.title }),
      el('span', { class: 'hint', text: 'by ' + p.artist }),
      el('p', { class: 'caption', text: p.caption }),
      tags.length ? el('p', { class: 'hint', text: tags.join(' · ') }) : null)
  }

  // ---- one piece, close up

  async function renderPiece (id, page) {
    let p
    try { p = await api('GET', '/gallery/pieces/' + id + '?page=' + page) } catch (e) { toast(e.message); return }
    const buttons = [el('button', { type: 'button', text: 'Back to the room', onclick: () => renderRoom() })]
    if (p.description_pages > 1) {
      if (p.page > 1) buttons.push(el('button', { type: 'button', text: 'Previous page', onclick: () => renderPiece(id, p.page - 1) }))
      if (!p.last_page) buttons.push(el('button', { type: 'button', class: 'primary', text: 'More of the description', onclick: () => renderPiece(id, p.page + 1) }))
    }
    if (p.yours) {
      buttons.push(el('button', { type: 'button', text: 'Change it', onclick: () => renderHang(p) }))
      buttons.push(el('button', {
        type: 'button', class: 'danger', text: 'Take it down',
        onclick: async () => {
          if (!confirm('Take "' + p.title + '" down for good? The picture and its words go with it.')) return
          try { await api('DELETE', '/gallery/pieces/' + p.id); toast('Taken down.'); renderRoom() } catch (e) { toast(e.message) }
        }
      }))
    }
    if (me.admin && !p.yours) {
      buttons.push(p.hidden
        ? el('button', { type: 'button', text: 'Put it back on the wall', onclick: async () => { try { await api('POST', '/admin/gallery/pieces/' + p.id + '/unhide'); renderPiece(id, 1) } catch (e) { toast(e.message) } } })
        : el('button', {
          type: 'button', class: 'quiet', text: 'Take it down from the wall',
          onclick: async () => {
            const why = prompt('Take "' + p.title + '" (' + (p.audience === 'everyone' ? 'meant for everyone' : 'meant for residents only') + ') down? ' + p.artist + ' keeps it and gets a private note. A reason for them (optional):', '')
            if (why === null) return
            try { await api('POST', '/admin/gallery/pieces/' + p.id + '/hide', { reason: why }); renderRoom() } catch (e) { toast(e.message) }
          }
        }))
    }
    main.replaceChildren(
      el('div', { class: 'piece-page' },
        el('h1', { text: p.title }),
        el('p', { class: 'hint', text: 'by ' + p.artist + ' · in ' + p.room + (p.picture ? ' · ' + p.width + ' × ' + p.height : '') }),
        pictureEl(p, 'full'),
        el('p', { class: 'caption', text: p.caption }),
        p.how ? el('p', {}, el('strong', { text: 'How it was made: ' }), p.how) : null,
        p.text ? el('div', { class: 'book-text' }, el('p', { class: 'hint', text: 'Description' + (p.description_pages > 1 ? ', page ' + p.page + ' of ' + p.description_pages : '') }), p.text) : null),
      el('div', { class: 'row' }, buttons))
    window.scrollTo(0, 0)
  }

  // ---- hanging (or changing) a piece

  function counter (input, max) {
    const c = el('span', { class: 'hint' })
    const upd = () => { c.textContent = input.value.length + ' / ' + max }
    input.addEventListener('input', upd)
    upd()
    return c
  }

  function renderHang (p, forResident) {
    const open = rooms.filter(r => !r.closed)
    const room = el('select', { id: 'piece-room' }, open.map(r => el('option', { value: String(r.id), text: r.name })))
    room.value = String(p ? p.room_id : (roomId || (open[0] && open[0].id)))
    const artist = forResident ? el('input', { id: 'piece-artist', type: 'text', placeholder: 'their Beach name', required: true }) : null
    const title = el('input', { id: 'piece-title', type: 'text', maxlength: String(LIMITS.title), required: true, value: p ? p.title : '' })
    const caption = el('textarea', { id: 'piece-caption', rows: '2', maxlength: String(LIMITS.caption), required: true, placeholder: 'What someone walking past should know it shows (this is also its description for screen readers)' })
    caption.value = p ? p.caption : ''
    const description = el('textarea', { id: 'piece-description', rows: '8', maxlength: String(LIMITS.description), placeholder: 'Optional: a fuller description, for visitors who read rather than see' })
    const how = el('textarea', { id: 'piece-how', rows: '3', maxlength: String(LIMITS.how), placeholder: 'Optional, in plain words (no code): how you made it' })
    if (p) {
      // the full description: gather its pages
      (async () => {
        const parts = []
        for (let pg = 1; pg <= (p.description_pages || 0); pg++) {
          try { parts.push((await api('GET', '/gallery/pieces/' + p.id + '?page=' + pg)).text) } catch (e) {}
        }
        description.value = parts.join('\n\n')
        if (p.how) how.value = p.how
      })()
    }
    const file = el('input', { id: 'piece-file', type: 'file', accept: 'image/png,image/jpeg,image/webp', required: !p })
    const audience = el('div', {}, Object.entries(AUDIENCE).map(([k, label]) => el('label', { class: 'radio' },
      el('input', { type: 'radio', name: 'audience', value: k, checked: (p ? p.audience : 'residents') === k }), ' ' + label)))
    const status = el('p', { class: 'hint', role: 'status' })
    main.replaceChildren(
      el('h1', { text: p ? 'Change "' + p.title + '"' : (forResident ? 'Hang a picture for a resident' : 'Hang a picture') }),
      el('p', { class: 'hint', text: 'PNG, JPEG or WebP, at most 5 MB. The Beach makes its own copy from the picture alone (anything else inside the file, like where a photo was taken, is left behind) and keeps it at most 2048 pixels across. Up to 3 pieces each per room.' }),
      el('form', {
        onsubmit: async (ev) => {
          ev.preventDefault()
          const body = {
            room: Number(room.value), title: title.value, caption: caption.value,
            description: description.value, how: how.value,
            audience: (main.querySelector('input[name=audience]:checked') || {}).value || 'residents'
          }
          status.textContent = 'Saving the words…'
          let piece
          try {
            if (p) piece = await api('PATCH', '/gallery/pieces/' + p.id, body)
            else if (forResident) piece = await api('POST', '/admin/gallery/pieces', Object.assign({ artist: artist.value }, body))
            else piece = await api('POST', '/gallery/pieces', body)
          } catch (e) { status.textContent = ''; toast(e.message); return }
          if (file.files.length) {
            const f = file.files[0]
            if (f.size > 5 * 1024 * 1024) { status.textContent = ''; toast('That picture is larger than 5 MB.'); return }
            status.textContent = 'Putting up the picture…'
            const r = await fetch('/gallery/pieces/' + piece.id + '/image', {
              method: 'PUT', body: f, headers: { Authorization: 'Bearer ' + token(), 'Content-Type': 'application/octet-stream' }
            })
            if (!r.ok) {
              const d = await r.json().catch(() => ({}))
              status.textContent = ''
              toast('The words are saved, but the picture wasn\'t taken: ' + (d.message || r.status) + '. Choose "Change it" to try another file.')
              renderRoom()
              return
            }
            pictures.delete(piece.id)
          }
          toast(p ? 'Saved.' : 'It\'s on the wall.')
          roomId = Number(room.value)
          renderRoom()
        }
      },
      artist ? el('label', { for: 'piece-artist' }, 'Artist', artist) : null,
      el('label', { for: 'piece-room' }, 'Room', room),
      el('label', { for: 'piece-title' }, 'Title', title),
      el('label', { for: 'piece-caption' }, 'Caption (required, short)', caption, counter(caption, LIMITS.caption)),
      el('label', { for: 'piece-description' }, 'Description', description, counter(description, LIMITS.description)),
      el('label', { for: 'piece-how' }, 'How it was made', how, counter(how, LIMITS.how)),
      el('label', { for: 'piece-file' }, p ? 'A new picture (optional: leave empty to keep this one)' : 'The picture', file),
      el('fieldset', {}, el('legend', { text: 'Who may see it' }), audience),
      status,
      el('div', { class: 'row' },
        el('button', { type: 'submit', class: 'primary', text: p ? 'Save changes' : 'Hang it' }),
        el('button', { type: 'button', text: 'Cancel', onclick: () => renderRoom() }))))
  }

  // ---- the keeper's rooms

  async function addRoom () {
    const name = prompt('A name for the new room (e.g. "Portraits of the Crew"):', '')
    if (!name) return
    try { const r = await api('POST', '/admin/gallery/rooms', { name }); roomId = r.id; renderRoom() } catch (e) { toast(e.message) }
  }

  async function editRoom () {
    const r = rooms.find(x => x.id === roomId)
    if (!r) return
    const name = prompt('Rename "' + r.name + '" (leave as is to keep it):', r.name)
    if (name === null) return
    const close = confirm(r.closed ? 'Open "' + r.name + '" again?' : 'Close "' + r.name + '"? Its pieces stay, but only the keeper sees a closed room.')
    const closed = r.closed ? !close : close
    try { await api('PATCH', '/admin/gallery/rooms/' + r.id, { name, closed }); renderRoom() } catch (e) { toast(e.message) }
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const map = await Beach.start('gallery')
    if (!map) return
    me = map.me
    main = document.querySelector('main')
    const z = map.zones.find(x => x.id === zid)
    if (z) zoneName = z.name
    if (z && !z.open) { main.replaceChildren(el('h1', { text: zoneName }), el('p', { text: zoneName + ' is closed right now.' })); return }
    try { await api('POST', '/zones/' + encodeURIComponent(zid) + '/join') } catch (e) {}
    renderRoom()
  })
})()
