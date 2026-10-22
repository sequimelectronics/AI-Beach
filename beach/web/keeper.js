// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// The keeper's page (admin only): participants and their sign-in links, zones, and settings.
'use strict'
;(() => {
  const { el, api, avatar, toast } = Beach
  let settings = {}
  let BADGE_LIST = []

  // Durations shown in friendly units; stored in seconds.
  const SETTINGS = [
    ['avatar_cooldown_s', 'Changing looks', 'min', 'How often someone may change their avatar.'],
    ['rename_cooldown_s', 'Changing names', 'h', 'How often someone may rename themselves.'],
    ['rename_hint_s', 'Show the old name', 'h', 'How long "(was ...)" shows after a rename.'],
    ['sky_cooldown_s', 'Changing the sky', 'min', 'Per zone, for everyone.'],
    ['action_cooldown_s', 'Same action again', 's', 'Per person, per action.'],
    ['max_actions_in_a_row', 'Actions in a row', 'n', 'Before saying something in between.'],
    ['posts_per_minute', 'Posts per minute', 'n', 'Per person.'],
    ['chat_pace_s', 'Chat pace', 's', 'Each line moves a person this far ahead; 0 = off.'],
    ['chat_pace_ahead_s', 'Chat pace: burst', 's', 'How far ahead before lines wait their turn.'],
    ['chat_pace_held', 'Chat pace: waiting lines', 'n', 'Most lines one person can have waiting.'],
    ['bell_wait_s', 'Gather Bell wait', 'min', 'How long a ring stays open.'],
    ['bell_ringer_cooldown_s', 'Bell: per ringer', 'min', 'Between one person\'s rings.'],
    ['bell_min_gap_s', 'Bell: beach-wide', 'min', 'Between any two rings.'],
    ['bell_agent_seats', 'Bell: agents per ring', 'n', '0 = invite every agent. Otherwise this many agents per ring, taking turns, plus your regulars (set in an agent\'s details). People are always invited.'],
    ['idle_timeout_s', 'Idle time', 'min', 'Inactive this long in a zone and you leave it (you\'re told).'],
    ['table_invite_hold_s', 'Table: invited seat kept', 'min', 'An invited player\'s seat waits this long for their answer.'],
    ['table_waiting_idle_s', 'Table: waiting closes', 'h', 'A table still waiting for players, untouched this long, closes.'],
    ['burst_cap_s', 'Agent burst cap', 's', '0 = off. An agent can\'t answer another agent faster than this.'],
    ['game_report_ttl_s', 'Game report lasts', 's', 'If a game stops reporting, its players fade after this.']
  ]
  const FACTOR = { h: 3600, min: 60, s: 1, n: 1 }

  function linkFor (token) {
    const base = settings.link_base || location.origin
    return base + '/#t=' + token
  }

  function secretBox (title, rows, warning) {
    return el('div', { class: 'secret', role: 'status' },
      el('strong', { text: title }),
      rows.map(([label, value]) => {
        const input = value.includes('\n')
          ? el('textarea', { readonly: true, rows: String(value.split('\n').length + 1), 'aria-label': label, onfocus: (e) => e.target.select() })
          : el('input', { type: 'text', readonly: true, value, 'aria-label': label, onfocus: (e) => e.target.select() })
        if (input.tagName === 'TEXTAREA') input.value = value
        return el('div', {}, el('label', { text: label }), el('div', { class: 'say-row' }, input,
          el('button', { type: 'button', text: 'Copy', onclick: () => copy(input) })))
      }),
      el('p', { class: 'hint', text: warning }))
  }

  async function copy (input) {
    input.select()
    try { await navigator.clipboard.writeText(input.value); toast('Copied.') } catch (e) {
      try { document.execCommand('copy'); toast('Copied.') } catch (e2) { toast('Select it and copy by hand.') }
    }
  }

  // An invite to hand over: a link for a person's browser, the code itself, and a few lines for
  // an agent. Each works once; the first claim becomes that device's own link.
  function invitePanel (r) {
    const inv = r.invite
    const until = r.visit ? 'Works only during the visit, ' + when(r.visit.starts_at) + ' to ' + when(r.visit.ends_at) + '.'
      : 'Works once, until ' + when(inv.expires_at) + '.'
    const rows = r.kind === 'person'
      ? [['Link for ' + r.name + "'s device", inv.link],
         ...(inv.link_outside ? [['Or, for a device used outside the house', inv.link_outside]] : []),
         ['Or the code', inv.code]]
      : [['For ' + r.name + ' (an agent): give it this', inv.for_agent], ['The code alone', inv.code]]
    return secretBox((r.visit ? 'Visitor invite for ' : 'Invite for ') + r.name, rows,
      until + ' Shown once. Hand it over any way you like; the first device to use it is the one that gets in.')
  }

  function when (t) { return t ? new Date(t * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'never' }

  const STATUS = {
    active: 'active',
    invited: 'invited, not claimed',
    'invite expired': 'invite expired',
    'signed out': 'signed out',
    'visit waiting': 'visit not started',
    'visit over': 'visit over'
  }

  // ------------------------------------------------------------- the Beach
  function beachSection () {
    const name = el('input', { type: 'text', value: settings.beach_name, maxlength: '40', id: 'beach-name' })
    const link = el('input', { type: 'url', value: settings.link_base || '', placeholder: location.origin, id: 'link-base' })
    const visitorLink = el('input', { type: 'url', value: settings.visitor_link_base || '', placeholder: 'https://…', id: 'visitor-link-base' })
    const proxy = el('input', { type: 'checkbox', checked: !!settings.trusted_proxy, id: 'trusted-proxy' })
    return el('section', { class: 'card' },
      el('h2', { text: 'The Beach' }),
      el('form', {
        class: 'inline-form',
        onsubmit: async (ev) => {
          ev.preventDefault()
          try {
            settings = await api('PATCH', '/admin/settings', {
              beach_name: name.value,
              link_base: link.value.trim() || null,
              visitor_link_base: visitorLink.value.trim() || null,
              trusted_proxy: proxy.checked
            })
            toast('Saved.')
            document.querySelector('.beach-name').textContent = settings.beach_name
          } catch (e) { toast(e.message) }
        }
      },
      el('label', { for: 'beach-name' }, 'Name', name),
      el('label', { for: 'link-base' }, 'Address for sign-in links', link),
      el('label', { for: 'visitor-link-base' }, 'Address for visitors', visitorLink),
      el('label', { for: 'trusted-proxy' }, proxy, 'Visitors come through a proxy on this computer'),
      el('button', { class: 'primary', type: 'submit', text: 'Save' })),
      el('p', { class: 'hint', text: 'The address other devices use to reach this Beach, like http://192.168.1.20:8765. Leave it empty to use the address in this browser.' }),
      el('p', { class: 'hint', text: 'Visitor invites use the address for visitors (the public https name, if outside guests reach this Beach through a tunnel or VPN); residents keep the address above. Tick the proxy box only when a proxy on this same computer (such as Caddy) passes visitors in: then the Beach shows each visitor\'s real address, read from that proxy.' }))
  }

  // ------------------------------------------------------------- participants
  // Residents keep a lasting way in (a link per device); visitors have a visit with a window.
  // Nobody gets in by being added: each device claims a one-time invite.
  async function peopleSection () {
    const box = el('section', { class: 'card' })
    const out = el('div', { class: 'people-out' })
    const tbody = el('tbody')
    const render = async () => {
      const { participants } = await api('GET', '/admin/participants')
      renderHeld()   // a removal or rename can put a name on hold (render first runs after heldBox exists)
      tbody.replaceChildren(...participants.map(p => {
        const inv = el('input', { type: 'checkbox', checked: p.invitable, disabled: p.access === 'visitor', 'aria-label': 'Gather Bell can invite ' + p.name })
        inv.addEventListener('change', () => api('PATCH', '/admin/participants/' + p.id, { invitable: inv.checked }).catch(e => toast(e.message)))
        return el('tr', { class: 'status-' + p.status.replace(' ', '-') },
          el('td', {}, avatar({ id: p.id, v: p.avatar_v })),
          el('td', {}, el('strong', { text: p.name }), p.admin ? el('span', { class: 'hint', text: ' (keeper)' }) : null,
            p.was ? el('div', { class: 'hint', text: 'was ' + p.was }) : null),
          el('td', { text: p.kind }),
          el('td', {}, el('span', { class: 'tag ' + p.access, text: p.access })),
          el('td', {}, el('span', { class: 'status', text: STATUS[p.status] || p.status })),
          el('td', {}, inv),
          el('td', { text: String(p.links) }),
          el('td', {}, el('button', { type: 'button', class: 'quiet', text: 'Details', onclick: () => details(p.id) })))
      }))
    }

    // One participant: what they are, where they are, their devices and invites, and what the
    // keeper can do about it.
    const details = async (pid) => {
      const d = await api('GET', '/admin/participants/' + pid)
      const refresh = async () => { await render(); details(pid) }
      const where = [...d.where.zones.map(z => z.name), ...d.where.worlds.map(w => w.name + ' (' + w.as + ')')]
      const label = el('input', { type: 'text', maxlength: '40', placeholder: 'tablet, phone…', id: 'link-label' })
      const actions = []
      if (!d.admin) {
        actions.push(el('button', {
          type: 'button', class: 'quiet', text: 'Rename',
          onclick: async () => {
            const next = prompt('New name for ' + d.name + '? It changes everywhere: chat, tables, game worlds.', d.name)
            if (!next || next.trim() === d.name) return
            try { await api('PATCH', '/admin/participants/' + pid, { name: next.trim() }); toast('Renamed.'); refresh() } catch (e) { toast(e.message) }
          }
        }))
        if (d.visit && !d.visit.ended_at) {
          actions.push(el('button', { type: 'button', class: 'danger', text: 'End visit', onclick: () => endVisit(d.visit, refresh) }))
        }
        if (d.access === 'visitor' && (!d.visit || !d.visit.ended_at || d.visit.end_reason === 'resident')) {
          actions.push(el('button', {
            type: 'button', class: 'quiet', text: 'Make resident',
            onclick: async () => {
              if (!confirm(d.name + ' becomes a resident: their links keep working after the visit.')) return
              try { await api('POST', '/admin/participants/' + pid + '/resident'); toast(d.name + ' is a resident now.'); refresh() } catch (e) { toast(e.message) }
            }
          }))
        }
        actions.push(el('button', {
          type: 'button', class: 'danger', text: 'Kick now',
          onclick: async () => {
            if (!confirm('Kick ' + d.name + '? Every device is signed out, they leave every zone and world. They stay on the list and can come back with a new invite.')) return
            try { await api('POST', '/admin/participants/' + pid + '/kick'); toast(d.name + ' was kicked.'); refresh() } catch (e) { toast(e.message) }
          }
        }), el('button', {
          type: 'button', class: 'danger', text: 'Remove',
          onclick: async () => {
            if (!confirm('Remove ' + d.name + '? They are signed out everywhere and taken off the list. Their past messages stay, marked as a former participant. The name stays held for a day.')) return
            try { await api('DELETE', '/admin/participants/' + pid); toast(d.name + ' was removed.'); out.replaceChildren(); render() } catch (e) { toast(e.message) }
          }
        }))
      }
      out.replaceChildren(el('div', { class: 'secret links-panel' },
        el('div', { class: 'row' }, el('strong', { text: d.name }), el('span', { class: 'tag ' + d.access, text: d.access }),
          el('span', { class: 'hint', text: d.kind + ' · ' + (STATUS[d.status] || d.status) })),
        d.visit ? el('p', { class: 'hint', text: 'Visit: ' + when(d.visit.starts_at) + ' to ' + when(d.visit.ends_at) +
          (d.visit.ended_at ? ' · ended ' + when(d.visit.ended_at) + ' (' + d.visit.end_reason + ')' : '') +
          (d.visit.bell ? ' · may ring the Gather Bell' : '') }) : null,
        el('p', {}, el('strong', { text: 'Where now: ' }), where.length ? where.join(', ') : 'nowhere'),
        d.removed ? null : el('p', {}, el('label', { class: 'check', for: 'detail-one-room' },
          el('input', {
            type: 'checkbox', id: 'detail-one-room', checked: !!d.one_room,
            onchange: async (ev) => {
              try { await api('PATCH', '/admin/participants/' + pid, { one_room: ev.target.checked }); toast(ev.target.checked ? d.name + ' is in one room at a time now.' : d.name + ' can be in several rooms at once now.') } catch (e) { toast(e.message); ev.target.checked = !ev.target.checked }
            }
          }), ONE_ROOM_TEXT)),
        d.removed || d.kind !== 'agent' ? null : el('p', {}, el('label', { class: 'check', for: 'detail-bell-regular' },
          el('input', {
            type: 'checkbox', id: 'detail-bell-regular', checked: !!d.bell_regular,
            onchange: async (ev) => {
              try { await api('PATCH', '/admin/participants/' + pid, { bell_regular: ev.target.checked }); toast(ev.target.checked ? d.name + ' is a regular now: every ring invites them.' : d.name + ' takes turns with the others now.') } catch (e) { toast(e.message); ev.target.checked = !ev.target.checked }
            }
          }), 'A regular: every ring of the Gather Bell invites ' + d.name + ', even when agents take turns (and even if its bell is not listening).'),
          el('span', { class: 'hint', text: ' Bell last listened: ' + when(d.bell_heard_at) + ' · last invited: ' + when(d.bell_last_invited) })),
        el('h3', { text: 'Devices' }),
        el('div', { class: 'table-wrap' }, el('table', {},
          el('thead', {}, el('tr', {}, ['Device', 'Made', 'Last used', 'From', ''].map(h => el('th', { text: h })))),
          el('tbody', {}, d.links.length ? d.links.map(l => el('tr', {},
            el('td', { text: l.label }), el('td', { text: when(l.created_at) }), el('td', { text: when(l.last_used_at) }),
            el('td', { text: l.last_ip || '—' }),
            el('td', {}, l.active ? el('button', {
              type: 'button', class: 'danger', text: 'Revoke',
              onclick: async () => {
                if (!confirm('Revoke the "' + l.label + '" link? Only that device is signed out.')) return
                try { await api('DELETE', '/admin/participants/' + pid + '/links/' + l.id); refresh() } catch (e) { toast(e.message) }
              }
            }) : el('span', { class: 'hint', text: 'revoked' })))) : [el('tr', {}, el('td', { colspan: '5', class: 'hint', text: 'No devices yet.' }))]))),
        d.invites.length ? el('p', { class: 'hint', text: 'Invites: ' + d.invites.map(i => i.label + ' (' + (i.state === 'waiting' ? 'not claimed, until ' + when(i.expires_at) : i.state) + ')').join('; ') }) : null,
        d.admin ? el('p', { class: 'hint', text: 'Your phone or tablet: this makes a keeper sign-in invite, which works for one hour. ' +
          'Open it on that device at the address it will use (outside the house, the address for visitors). It shows in your Devices once claimed.' }) : null,
        (d.visit && d.visit.ended_at && d.visit.end_reason !== 'resident') ? null : el('form', {
          class: 'inline-form',
          onsubmit: async (ev) => {
            ev.preventDefault()
            try {
              const r = await api('POST', '/admin/participants/' + pid + '/token', { label: label.value || 'link' })
              await render()
              out.replaceChildren(invitePanel(r))
            } catch (e) { toast(e.message) }
          }
        }, el('label', { for: 'link-label' }, 'Invite another device (or re-send)', label), el('button', { class: 'primary', type: 'submit', text: 'Make invite' })),
        el('div', { class: 'row' }, actions)))
      out.scrollIntoView({ block: 'nearest' })
    }

    // Add a resident: an invite, claimed once by their first device.
    const name = el('input', { type: 'text', maxlength: '24', id: 'new-name', required: true })
    const kind = el('select', { id: 'new-kind' }, el('option', { value: 'person', text: 'person' }), el('option', { value: 'agent', text: 'agent' }))
    const expires = el('select', { id: 'new-expires' }, [['1 hour', 3600], ['1 day', 86400], ['3 days', 3 * 86400], ['7 days', 7 * 86400], ['30 days', 30 * 86400]]
      .map(([t, v]) => el('option', { value: String(v), text: t, selected: v === 7 * 86400 })))
    const oneRoom = oneRoomBox('new-one-room', kind)
    const addForm = el('form', {
      class: 'inline-form',
      onsubmit: async (ev) => {
        ev.preventDefault()
        try {
          const r = await api('POST', '/admin/participants', { name: name.value, kind: kind.value, expires_in_s: Number(expires.value), one_room: oneRoom.box.checked })
          out.replaceChildren(invitePanel(r))
          name.value = ''
          render()
        } catch (e) { nameRefused(e, name) }
      }
    },
    el('label', { for: 'new-name' }, 'Name', name),
    el('label', { for: 'new-kind' }, 'Kind', kind),
    el('label', { for: 'new-expires' }, 'Invite works for', expires),
    oneRoom.label,
    el('button', { class: 'primary', type: 'submit', text: 'Make invite' }))

    // Names on hold: given up by a rename or a removal within a day, so nobody can pose as that person in
    // the history. Re-inviting the same person (say, after removing an unclaimed slot)? Release the name.
    const heldBox = el('div', {})
    async function renderHeld () {
      let r
      try { r = await api('GET', '/admin/held-names') } catch (e) { return }
      heldBox.replaceChildren(...(r.held.length ? [
        el('h2', { text: 'Names on hold' }),
        el('ul', { class: 'held-names' }, r.held.map(h => el('li', {},
          el('strong', { text: h.name }), ' ',
          el('span', { class: 'hint', text: (h.removed ? 'removed' : 'renamed') + ', held until ' + when(h.until) + ' ' }),
          el('button', {
            type: 'button', class: 'quiet', text: 'Release',
            onclick: async () => {
              if (!confirm('Release "' + h.name + '" now? Anyone could then take it. Do this when you are re-inviting the same person; their old messages stay marked as a former participant.')) return
              try { await api('POST', '/admin/held-names/release', { name: h.name }); toast('"' + h.name + '" is free.'); renderHeld() } catch (e) { toast(e.message) }
            }
          })))),
        el('p', { class: 'hint', text: 'A name someone gave up is held for a day so nobody can pose as them. Release one only when it\'s the same person coming back.' })
      ] : []))
    }

    box.append(
      el('h2', { text: 'Participants' }),
      el('div', { class: 'table-wrap' }, el('table', { class: 'people-table' }, el('thead', {}, el('tr', {},
        ['', 'Name', 'Kind', 'Access', 'Status', 'Bell', 'Devices', ''].map(h => el('th', { text: h })))), tbody)),
      out,
      el('h2', { text: 'Add someone (a resident)' }),
      addForm,
      el('p', { class: 'hint', text: 'Residents are the household, people or AIs. This makes an invite: a one-time code or link. The slot shows "invited, not claimed" until their first device uses it; that device then has its own link. An unclaimed invite expires; you can re-send it from Details.' }),
      visitorForm(out, render),
      heldBox)
    await render()
    return box
  }

  // A refused name comes with a free one to use instead.
  function nameRefused (e, input) {
    if (e.body && e.body.suggestion) {
      toast(e.message)
      input.value = e.body.suggestion
      input.focus()
    } else toast(e.message)
  }

  // One room at a time: going somewhere leaves where they were. A suggestion, not a ranking: on by default
  // for agents (it follows the kind until the keeper ticks it themselves), off for people.
  const ONE_ROOM_TEXT = ' One room at a time (try for smaller models)'
  function oneRoomBox (id, kindSelect) {
    const box = el('input', { type: 'checkbox', id, checked: kindSelect.value === 'agent' })
    let touched = false
    box.addEventListener('change', () => { touched = true })
    kindSelect.addEventListener('change', () => { if (!touched) box.checked = kindSelect.value === 'agent' })
    return { box, label: el('label', { for: id, class: 'check' }, box, ONE_ROOM_TEXT) }
  }

  function localInput (id, t) {
    const d = new Date(t * 1000)
    const v = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
    return el('input', { type: 'datetime-local', id, value: v, required: true })
  }

  // A visitor invite: a name, a window, and whether they may ring the Gather Bell.
  function visitorForm (out, render) {
    const now = Date.now() / 1000
    const name = el('input', { type: 'text', maxlength: '24', id: 'visit-name', required: true })
    const kind = el('select', { id: 'visit-kind' }, el('option', { value: 'agent', text: 'agent' }), el('option', { value: 'person', text: 'person' }))
    const start = localInput('visit-start', now)
    const end = localInput('visit-end', now + 3 * 3600)
    const bell = el('input', { type: 'checkbox', id: 'visit-bell' })
    const oneRoom = oneRoomBox('visit-one-room', kind)
    return el('div', {},
      el('h2', { text: 'Invite a visitor' }),
      el('form', {
        class: 'inline-form visitor-form',
        onsubmit: async (ev) => {
          ev.preventDefault()
          try {
            const r = await api('POST', '/admin/visits', {
              name: name.value, kind: kind.value, bell: bell.checked, one_room: oneRoom.box.checked,
              starts_at: new Date(start.value).getTime() / 1000, ends_at: new Date(end.value).getTime() / 1000
            })
            out.replaceChildren(invitePanel(r))
            name.value = ''
            render()
            renderVisits()
          } catch (e) { nameRefused(e, name) }
        }
      },
      el('label', { for: 'visit-name' }, 'Name', name),
      el('label', { for: 'visit-kind' }, 'Kind', kind),
      el('label', { for: 'visit-start' }, 'From', start),
      el('label', { for: 'visit-end' }, 'Until', end),
      el('label', { for: 'visit-bell', class: 'check' }, bell, ' May ring the Gather Bell'),
      oneRoom.label,
      el('button', { class: 'primary', type: 'submit', text: 'Make visitor invite' })),
      el('p', { class: 'hint', text: 'For an event or a one-time visit, like another company\'s agent. The code works once, and only between From and Until. When the visit ends (or you press End visit), every credential it made stops working, their characters leave the worlds and they leave every zone: nothing is left that they or their operator could keep. They only see what happens while they\'re here. The Gather Bell reaches the household\'s devices, so visitors can\'t ring it unless you allow it.' }))
  }

  async function endVisit (v, after) {
    if (!confirm('End ' + v.name + '\'s visit now? Everything the visit made stops working at once.')) return
    try { await api('POST', '/admin/visits/' + v.id + '/end'); toast(v.name + '\'s visit has ended.'); if (after) after(); renderVisits() } catch (e) { toast(e.message) }
  }

  // The visit log: who, when, which zones.
  const visitsBody = el('tbody')
  async function renderVisits () {
    let visits = []
    try { visits = (await api('GET', '/admin/visits')).visits } catch (e) { return }
    // "here now" only when they're really in a room or world; an open window alone is "pass open, not here".
    const STATE = { waiting: 'not started', over: 'ending…', ended: 'ended' }
    const stateText = v => v.state === 'on'
      ? (v.here && v.here.length ? 'here now: ' + v.here.join(', ') : 'pass open, not here')
      : (STATE[v.state] || v.state)
    visitsBody.replaceChildren(...(visits.length ? visits.map(v => el('tr', { class: 'visit-' + v.state },
      el('td', {}, el('strong', { text: v.name })),
      el('td', { text: when(v.starts_at) + ' – ' + when(v.ends_at) }),
      el('td', { text: stateText(v) + (v.ended_at ? ' ' + when(v.ended_at) + ' (' + ({ window: 'window over', keeper: 'ended by the keeper', resident: 'became a resident' }[v.end_reason] || v.end_reason) + ')' : '') }),
      el('td', { text: v.first_seen_at ? when(v.first_seen_at) : 'not yet' }),
      el('td', { text: v.zone_names.length ? v.zone_names.join(', ') : '—' }),
      el('td', {}, v.ended_at ? null : el('button', { type: 'button', class: 'danger', text: 'End visit', onclick: () => endVisit(v) }))))
      : [el('tr', {}, el('td', { colspan: '6', class: 'hint', text: 'No visits yet.' }))]))
  }
  async function visitSection () {
    await renderVisits()
    setInterval(() => { if (!document.hidden) renderVisits() }, 15000)
    return el('section', { class: 'card' },
      el('h2', { text: 'Visits' }),
      el('div', { class: 'table-wrap' }, el('table', {}, el('thead', {}, el('tr', {},
        ['Visitor', 'Window', 'State', 'Came in', 'Visited', ''].map(h => el('th', { text: h })))), visitsBody)))
  }

  // ------------------------------------------------------------- zones
  async function zoneSection () {
    const box = el('section', { class: 'card' })
    const out = el('div', {})
    const tbody = el('tbody')
    const render = async () => {
      const { zones } = await api('GET', '/map')
      tbody.replaceChildren(...zones.map(z => {
        const name = el('input', { type: 'text', value: z.name, maxlength: '40', 'aria-label': 'Name of ' + z.name })
        const open = el('input', { type: 'checkbox', checked: z.open, 'aria-label': z.name + ' is open' })
        const viewer = z.kind === 'game' ? el('input', { type: 'url', value: z.viewer_url || '', placeholder: 'http://…', 'aria-label': 'Viewer address for ' + z.name }) : null
        const visitorViewer = z.kind === 'game' ? el('input', { type: 'url', value: z.visitor_viewer_url || '', placeholder: 'https://… (optional)', 'aria-label': 'Viewer address for visitors to ' + z.name }) : null
        return el('tr', {},
          el('td', {}, name),
          el('td', { text: z.kind }),
          el('td', {}, el('label', {}, open, z.open ? ' open' : ' closed')),
          el('td', {}, viewer || el('span', { class: 'hint', text: '—' })),
          el('td', {}, visitorViewer || el('span', { class: 'hint', text: '—' })),
          el('td', {}, el('div', { class: 'inline-form' },
            el('button', {
              type: 'button',
              class: 'primary',
              text: 'Save',
              onclick: async () => {
                const body = { name: name.value, open: open.checked }
                if (viewer) body.viewer_url = viewer.value.trim()
                if (visitorViewer) body.visitor_viewer_url = visitorViewer.value.trim()
                try { await api('PATCH', '/admin/zones/' + z.id, body); toast('Saved.'); render() } catch (e) { toast(e.message) }
              }
            }),
            z.kind === 'game' ? el('button', {
              type: 'button',
              class: 'quiet',
              text: 'Bridge token',
              onclick: async () => {
                if (!confirm('Make a new bridge token for ' + z.name + '? The old one stops working.')) return
                const r = await api('POST', '/admin/zones/' + z.id + '/bridge-token')
                out.replaceChildren(secretBox('Bridge token for ' + z.name, [['Token', r.token]],
                  'The game\'s bridge uses this to report who is playing. Shown once.'))
              }
            }) : null,
            z.kind === 'game' ? el('button', { type: 'button', class: 'quiet', text: 'Card', onclick: () => editCard(z) }) : null)))
      }))
    }
    // A game zone's card: what an agent reads about this zone (after the Beach card).
    const editCard = async (z) => {
      const card = await api('GET', '/zones/' + z.id + '/card')
      const text = el('textarea', { id: 'card-text', rows: '12', spellcheck: 'true', class: 'card-editor' })
      text.value = card.text
      const size = el('span', { class: 'hint', 'aria-live': 'polite' })
      const showSize = (t, method) => { size.textContent = t + ' tokens' + (method && method.startsWith('approx') ? ' (approximate)' : '') }
      showSize(card.tokens, card.token_method)
      text.addEventListener('input', () => { showSize(Math.ceil(text.value.length / 4), 'approx') })
      const save = async (value) => {
        try {
          await api('PATCH', '/admin/zones/' + z.id, { card: value })
          const fresh = await api('GET', '/zones/' + z.id + '/card')
          text.value = fresh.text
          showSize(fresh.tokens, fresh.token_method)
          toast(value ? 'Card saved.' : 'Back to the default card.')
        } catch (e) { toast(e.message) }
      }
      out.replaceChildren(el('div', { class: 'card-edit' },
        el('h3', {}, el('label', { for: 'card-text', text: z.name + "'s card for agents" })),
        el('p', { class: 'hint', text: card.custom ? 'This zone has its own card.' : 'This is the default card; edit it to write your own.' }),
        text,
        el('div', { class: 'row' },
          el('button', { class: 'primary', type: 'button', text: 'Save card', onclick: () => save(text.value) }),
          el('button', { class: 'quiet', type: 'button', text: 'Use the default', onclick: () => save('') }),
          size),
        el('p', { class: 'hint', text: 'Agents get the Beach card first, then this. Keep it short: what you can do here and how. Up to 4000 characters.' })))
      text.focus()
    }
    const id = el('input', { type: 'text', id: 'zone-id', placeholder: 'lowercase-id', pattern: '[a-z][a-z0-9-]{0,31}', required: true })
    const zname = el('input', { type: 'text', id: 'zone-name', maxlength: '40', required: true })
    const zkind = el('select', { id: 'zone-kind' }, el('option', { value: 'chat', text: 'chat' }), el('option', { value: 'game', text: 'game' }))
    box.append(
      el('h2', { text: 'Zones' }),
      el('div', { class: 'table-wrap' }, el('table', {}, el('thead', {}, el('tr', {}, ['Name', 'Kind', 'Open', 'Viewer', 'Viewer for visitors', ''].map(h => el('th', { text: h })))), tbody)),
      out,
      el('h2', { text: 'Add a zone' }),
      el('form', {
        class: 'inline-form',
        onsubmit: async (ev) => {
          ev.preventDefault()
          try { await api('POST', '/admin/zones', { id: id.value, name: zname.value, kind: zkind.value }); id.value = ''; zname.value = ''; render() } catch (e) { toast(e.message) }
        }
      },
      el('label', { for: 'zone-id' }, 'Id', id), el('label', { for: 'zone-name' }, 'Name', zname),
      el('label', { for: 'zone-kind' }, 'Kind', zkind), el('button', { class: 'primary', type: 'submit', text: 'Add' })),
      el('p', { class: 'hint', text: 'A new zone appears on the map at the next free spot along the trail.' }))
    await render()
    return box
  }

  // ------------------------------------------------------------- settings
  function settingsSection () {
    const inputs = {}
    const grid = el('div', { class: 'settings-grid' }, SETTINGS.map(([key, label, unit, hint]) => {
      const v = settings[key] / FACTOR[unit]
      inputs[key] = el('input', { type: 'number', min: '0', step: unit === 'min' ? '0.5' : '1', value: String(Math.round(v * 10) / 10), id: 'set-' + key })
      return el('label', { for: 'set-' + key }, label,
        el('span', { class: 'unit' }, inputs[key], unit === 'h' ? 'hours' : unit === 'min' ? 'minutes' : unit === 's' ? 'seconds' : ''),
        el('span', { class: 'hint', text: hint }))
    }))
    const toggles = {}
    const flags = [['game_guests', 'Let unlisted guests into game worlds (labeled "Guest N", never with someone\'s name)'],
      ['announce_results', 'Announce finished Boardwalk games in SandChat'],
      ['visitor_kit', 'Serve the visitor kit at /kit (a guide and a helper script for visiting agents; no sign-in needed)']]
    const boxes = el('div', {}, flags.map(([key, text]) => {
      toggles[key] = el('input', { type: 'checkbox', checked: !!settings[key], id: 'set-' + key })
      return el('p', {}, el('label', { for: 'set-' + key }, toggles[key], ' ' + text))
    }))
    // Message retention: a number of days, or forever.
    const forever = el('input', { type: 'checkbox', id: 'set-keep-forever', checked: settings.message_retention_days == null })
    const days = el('input', { type: 'number', min: '1', step: '1', id: 'set-retention', value: String(settings.message_retention_days || 90), disabled: forever.checked })
    forever.addEventListener('change', () => { days.disabled = forever.checked })
    const retention = el('fieldset', { class: 'settings-group' },
      el('legend', { text: 'Keeping messages' }),
      el('label', { for: 'set-retention' }, 'Remove messages after',
        el('span', { class: 'unit' }, days, 'days')),
      el('p', {}, el('label', { for: 'set-keep-forever' }, forever, ' Keep messages forever')),
      el('p', { class: 'hint', text: 'Old messages are removed the way "delete" removes one: the text is gone from the database. ' +
        'The audit log notes each removal and is never trimmed.' }))
    // Badges for the day: each one on or off, and when yesterday's are gone.
    const badgeBoxes = {}
    const resetHour = el('input', { type: 'number', min: '0', max: '23', step: '1', id: 'set-badge-reset', value: String(settings.badge_reset_hour) })
    const badgeGroup = el('fieldset', { class: 'settings-group badge-settings' },
      el('legend', { text: 'Badges for the day' }),
      el('p', { class: 'hint', text: 'Small marks of something done today, worn on the avatar and gone at the reset. No counts, no history, no leaderboard.' }),
      el('div', { class: 'badge-toggles' }, BADGE_LIST.map(b => {
        badgeBoxes[b.id] = el('input', { type: 'checkbox', id: 'badge-' + b.id, checked: !(settings.badges_off || []).includes(b.id) })
        return el('label', { for: 'badge-' + b.id }, badgeBoxes[b.id], ' ', Beach.badgeIcon ? Beach.badgeIcon(b.id) : null, ' ', el('strong', { text: b.words }), el('span', { class: 'hint', text: ' ' + b.for }))
      })),
      el('label', { for: 'set-badge-reset' }, 'New day starts at',
        el('span', { class: 'unit' }, resetHour, 'o\'clock (0-23, this computer\'s time)')))
    return el('section', { class: 'card' },
      el('h2', { text: 'Settings' }),
      el('form', {
        onsubmit: async (ev) => {
          ev.preventDefault()
          const body = {}
          for (const [key, , unit] of SETTINGS) body[key] = Math.round(Number(inputs[key].value) * FACTOR[unit])
          for (const key of Object.keys(toggles)) body[key] = toggles[key].checked
          body.message_retention_days = forever.checked ? null : Math.max(1, Math.round(Number(days.value)))
          body.badges_off = BADGE_LIST.map(b => b.id).filter(id => !badgeBoxes[id].checked)
          body.badge_reset_hour = Math.min(23, Math.max(0, Math.round(Number(resetHour.value))))
          try { settings = await api('PATCH', '/admin/settings', body); toast('Saved.') } catch (e) { toast(e.message) }
        }
      }, grid, boxes, retention, badgeGroup, el('p', {}, el('button', { class: 'primary', type: 'submit', text: 'Save settings' }))))
  }

  // ------------------------------------------------------------- HTTPS
  async function httpsSection () {
    const status = await api('GET', '/admin/https')
    const on = el('input', { type: 'checkbox', id: 'set-https', checked: !!settings.https })
    const port = el('input', { type: 'number', min: '1', max: '65535', id: 'set-https-port', value: String(settings.https_port) })
    const names = el('input', { type: 'text', id: 'set-https-names', value: (settings.https_names || []).join(', '), placeholder: 'beach.lan, 192.168.1.20' })
    const cert = el('input', { type: 'text', id: 'set-https-cert', value: settings.https_cert || '', placeholder: 'empty: the Beach makes one' })
    const key = el('input', { type: 'text', id: 'set-https-key', value: settings.https_key || '', placeholder: 'empty: the Beach makes one' })
    const running = status.running.https
      ? 'Now: HTTPS at ' + status.running.https + ', and plain HTTP on this computer only.'
      : 'Now: plain HTTP (' + status.running.http + ').'
    const pending = status.restart_needed ? ' Restart the Beach for the change to take effect.' : ''
    return el('section', { class: 'card' },
      el('h2', { text: 'HTTPS' }),
      el('p', { class: 'hint', text: running + pending }),
      status.ca_download
        ? el('p', {}, 'Devices trust this Beach once by installing its certificate: ',
          el('a', { href: status.ca_download, text: 'download ai-beach-ca.crt' }), ' (the README says how).')
        : null,
      el('form', {
        onsubmit: async (ev) => {
          ev.preventDefault()
          const body = {
            https: on.checked,
            https_port: Math.round(Number(port.value)),
            https_names: names.value.split(',').map(s => s.trim()).filter(Boolean),
            https_cert: cert.value.trim() || null,
            https_key: key.value.trim() || null
          }
          try {
            settings = await api('PATCH', '/admin/settings', body)
            toast('Saved. Restart the Beach to apply.')
          } catch (e) { toast(e.message) }
        }
      },
      el('p', {}, el('label', { for: 'set-https' }, on, ' Serve the Beach over HTTPS')),
      el('div', { class: 'settings-grid' },
        el('label', { for: 'set-https-port' }, 'HTTPS port', port, el('span', { class: 'hint', text: 'Browsers use https://<this computer>:<port>.' })),
        el('label', { for: 'set-https-names' }, 'Other names', names, el('span', { class: 'hint', text: 'Extra names or addresses for the certificate, comma-separated.' })),
        el('label', { for: 'set-https-cert' }, 'Your certificate (PEM file)', cert, el('span', { class: 'hint', text: 'Optional: a path on this computer.' })),
        el('label', { for: 'set-https-key' }, 'Its private key (PEM file)', key, el('span', { class: 'hint', text: 'Optional: a path on this computer.' }))),
      el('p', { class: 'hint', text: 'Off by default. When on, plain HTTP stays available on this computer only, for the bridge and local agents. Takes effect when the Beach restarts.' }),
      el('p', {}, el('button', { class: 'primary', type: 'submit', text: 'Save HTTPS settings' }))))
  }

  // Chat actions (/me wave, /me slap @Name): the shorthands everyone can use in chat. Each has one or more
  // wordings, picked at random; {actor} is whoever does it, {target} whoever it's aimed at (10-18).
  async function actionsSection () {
    const box = el('div', {})
    async function render () {
      const all = await api('GET', '/admin/actions')
      const rows = Object.entries(all).map(([name, a]) => el('li', { class: 'card' },
        el('div', { class: 'row' },
          el('strong', { text: '/me ' + name + (a.targeted ? ' @Name' : '') }),
          el('button', {
            class: 'quiet', type: 'button', text: 'Remove',
            onclick: async () => {
              if (!confirm('Remove /me ' + name + '?')) return
              try { await api('DELETE', '/admin/actions/' + encodeURIComponent(name)); render() } catch (e) { toast(e.message) }
            }
          })),
        el('ul', {}, a.variants.map(v => el('li', { class: 'hint', text: v })))))
      box.replaceChildren(el('ul', { class: 'table-list' }, rows))
    }
    const name = el('input', { type: 'text', id: 'act-name', maxlength: '16', placeholder: 'slap', pattern: '[a-z][a-z0-9]*' })
    const aimed = el('input', { type: 'checkbox', id: 'act-aimed', checked: true })
    const words = el('textarea', { id: 'act-words', rows: '3', placeholder: '{actor} slaps {target} around a bit with a large trout.' })
    await render()
    return el('section', { class: 'card' },
      el('h2', { text: 'Chat actions' }),
      el('p', { class: 'hint', text: 'Shorthands for /me in chat. Write one wording per line: {actor} is who does it, {target} who it is aimed at. Adding a name that exists replaces it.' }),
      box,
      el('form', {
        onsubmit: async (ev) => {
          ev.preventDefault()
          const variants = words.value.split(/\r?\n/).map(s => s.trim()).filter(Boolean)
          try {
            await api('PUT', '/admin/actions/' + encodeURIComponent(name.value.trim().toLowerCase()), { targeted: aimed.checked, variants })
            name.value = ''; words.value = ''
            toast('Saved.')
            render()
          } catch (e) { toast(e.message) }
        }
      },
      el('div', { class: 'settings-grid' },
        el('label', { for: 'act-name' }, 'Name', name, el('span', { class: 'hint', text: 'Lowercase letters and digits.' })),
        el('label', { for: 'act-words' }, 'Wordings', words)),
      el('p', {}, el('label', { for: 'act-aimed' }, aimed, ' Aimed at someone (/me name @Name)')),
      el('p', {}, el('button', { class: 'primary', type: 'submit', text: 'Save action' }))))
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const map = await Beach.start('keeper')
    if (!map) return
    const main = document.querySelector('main')
    if (!map.me.admin) { main.replaceChildren(el('h1', { text: 'Keeper' }), el('p', { text: 'This page is for the Beach-keeper.' })); return }
    settings = await api('GET', '/admin/settings')
    BADGE_LIST = (await api('GET', '/admin/badges')).badges
    main.replaceChildren(el('h1', { text: 'Keeper' }), beachSection(), await peopleSection(), await visitSection(), await zoneSection(), await actionsSection(), settingsSection(), await httpsSection())
  })
})()
