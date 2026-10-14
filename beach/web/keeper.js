// The keeper's page (admin only): participants and their sign-in links, zones, and settings.
'use strict'
;(() => {
  const { el, api, avatar, toast } = Beach
  let settings = {}

  // Durations shown in friendly units; stored in seconds.
  const SETTINGS = [
    ['avatar_cooldown_s', 'Changing looks', 'min', 'How often someone may change their avatar.'],
    ['rename_cooldown_s', 'Changing names', 'h', 'How often someone may rename themselves.'],
    ['rename_hint_s', 'Show the old name', 'h', 'How long "(was ...)" shows after a rename.'],
    ['sky_cooldown_s', 'Changing the sky', 'min', 'Per zone, for everyone.'],
    ['action_cooldown_s', 'Same action again', 's', 'Per person, per action.'],
    ['max_actions_in_a_row', 'Actions in a row', 'n', 'Before saying something in between.'],
    ['posts_per_minute', 'Posts per minute', 'n', 'Per person.'],
    ['bell_wait_s', 'Desk Bell wait', 'min', 'How long a ring stays open.'],
    ['bell_ringer_cooldown_s', 'Bell: per ringer', 'min', 'Between one person\'s rings.'],
    ['bell_min_gap_s', 'Bell: beach-wide', 'min', 'Between any two rings.'],
    ['idle_timeout_s', 'Idle time', 'min', 'Quiet this long and you drift off.'],
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
        const input = el('input', { type: 'text', readonly: true, value, 'aria-label': label, onfocus: (e) => e.target.select() })
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

  function credentials (name, kind, token) {
    const rows = kind === 'person' ? [['Sign-in link for ' + name, linkFor(token)], ['Token', token]] : [['Token for ' + name, token], ['Sign-in link (if they use a browser)', linkFor(token)]]
    return secretBox(kind === 'person' ? 'Give ' + name + ' this link' : 'Give ' + name + "'s host this token",
      rows, 'Shown once. Anyone holding it can be ' + name + ' here. If it gets out, revoke that link under "Links": their other devices keep working.')
  }

  // ------------------------------------------------------------- the Beach
  function beachSection () {
    const name = el('input', { type: 'text', value: settings.beach_name, maxlength: '40', id: 'beach-name' })
    const link = el('input', { type: 'url', value: settings.link_base || '', placeholder: location.origin, id: 'link-base' })
    return el('section', { class: 'card' },
      el('h2', { text: 'The Beach' }),
      el('form', {
        class: 'inline-form',
        onsubmit: async (ev) => {
          ev.preventDefault()
          try {
            settings = await api('PATCH', '/admin/settings', { beach_name: name.value, link_base: link.value.trim() || null })
            toast('Saved.')
            document.querySelector('.beach-name').textContent = settings.beach_name
          } catch (e) { toast(e.message) }
        }
      },
      el('label', { for: 'beach-name' }, 'Name', name),
      el('label', { for: 'link-base' }, 'Address for sign-in links', link),
      el('button', { class: 'primary', type: 'submit', text: 'Save' })),
      el('p', { class: 'hint', text: 'The address other devices use to reach this Beach, like http://192.168.1.20:8765. Leave it empty to use the address in this browser.' }))
  }

  // ------------------------------------------------------------- participants
  async function peopleSection () {
    const box = el('section', { class: 'card' })
    const out = el('div', {})
    const render = async () => {
      const { participants } = await api('GET', '/admin/participants')
      const rows = participants.map(p => {
        const rename = el('button', {
          type: 'button',
          class: 'quiet',
          text: 'Rename',
          onclick: async () => {
            const next = prompt('New name for ' + p.name + '? It changes everywhere: chat, tables, game worlds.', p.name)
            if (!next || next.trim() === p.name) return
            try { await api('PATCH', '/admin/participants/' + p.id, { name: next.trim() }); toast('Renamed.'); render() } catch (e) { toast(e.message) }
          }
        })
        const inv = el('input', { type: 'checkbox', checked: p.invitable, 'aria-label': 'Desk Bell can invite ' + p.name })
        inv.addEventListener('change', () => api('PATCH', '/admin/participants/' + p.id, { invitable: inv.checked }).catch(e => toast(e.message)))
        return el('tr', {},
          el('td', {}, avatar({ id: p.id, v: p.avatar_v })),
          el('td', {}, el('strong', { text: p.name }), p.admin ? el('span', { class: 'hint', text: ' (admin)' }) : null,
            p.was ? el('div', { class: 'hint', text: 'was ' + p.was }) : null),
          el('td', { text: p.kind }),
          el('td', {}, rename),
          el('td', {}, inv),
          el('td', { text: p.has_token ? (p.links === 1 ? '1 link' : p.links + ' links') : 'signed out' }),
          el('td', {}, p.admin ? null : el('button', {
            type: 'button',
            class: 'quiet',
            text: 'Links',
            onclick: () => showLinks(p)
          })))
      })
      table.querySelector('tbody').replaceChildren(...rows)
    }
    // One person's sign-in links: one per device, each revocable on its own.
    const showLinks = async (p) => {
      const { links } = await api('GET', '/admin/participants/' + p.id + '/links')
      const label = el('input', { type: 'text', maxlength: '40', placeholder: 'tablet, phone…', id: 'link-label' })
      const when = (t) => t ? new Date(t * 1000).toLocaleString() : 'never'
      out.replaceChildren(el('div', { class: 'secret links-panel' },
        el('strong', { text: p.name + "'s sign-in links" }),
        el('table', {}, el('thead', {}, el('tr', {}, ['Link', 'Made', 'Last used', ''].map(h => el('th', { text: h })))),
          el('tbody', {}, links.map(l => el('tr', {},
            el('td', { text: l.label }), el('td', { text: when(l.created_at) }), el('td', { text: when(l.last_used_at) }),
            el('td', {}, l.active ? el('button', {
              type: 'button',
              class: 'danger',
              text: 'Revoke',
              onclick: async () => {
                if (!confirm('Revoke the "' + l.label + '" link? Only that device is signed out.')) return
                try { await api('DELETE', '/admin/participants/' + p.id + '/links/' + l.id); await render(); showLinks(p) } catch (e) { toast(e.message) }
              }
            }) : el('span', { class: 'hint', text: 'revoked' })))))),
        el('form', {
          class: 'inline-form',
          onsubmit: async (ev) => {
            ev.preventDefault()
            const r = await api('POST', '/admin/participants/' + p.id + '/token', { label: label.value || 'link' })
            await render()
            out.replaceChildren(credentials(p.name, p.kind, r.token))
          }
        }, el('label', { for: 'link-label' }, 'New link for', label), el('button', { class: 'primary', type: 'submit', text: 'Make link' })),
        el('p', {}, el('button', {
          type: 'button',
          class: 'danger',
          text: 'Sign out everywhere',
          onclick: async () => {
            if (!confirm('Sign ' + p.name + ' out on every device?')) return
            await api('DELETE', '/admin/participants/' + p.id + '/token')
            await render()
            showLinks(p)
          }
        })),
        el('p', { class: 'hint', text: 'Give each device its own link. If one gets out, revoke just that one: the others keep working.' })))
    }
    const table = el('table', {}, el('thead', {}, el('tr', {},
      ['', 'Name', 'Kind', '', 'Bell', 'Access', ''].map(h => el('th', { text: h })))), el('tbody'))
    const name = el('input', { type: 'text', maxlength: '24', id: 'new-name', required: true })
    const kind = el('select', { id: 'new-kind' }, el('option', { value: 'person', text: 'person' }), el('option', { value: 'agent', text: 'agent' }))
    box.append(
      el('h2', { text: 'Participants' }),
      el('div', { class: 'table-wrap' }, table),
      el('h2', { text: 'Add someone' }),
      el('form', {
        class: 'inline-form',
        onsubmit: async (ev) => {
          ev.preventDefault()
          try {
            const r = await api('POST', '/admin/participants', { name: name.value, kind: kind.value })
            out.replaceChildren(credentials(r.name, r.kind, r.token))
            name.value = ''
            render()
          } catch (e) { toast(e.message) }
        }
      },
      el('label', { for: 'new-name' }, 'Name', name),
      el('label', { for: 'new-kind' }, 'Kind', kind),
      el('button', { class: 'primary', type: 'submit', text: 'Add' })),
      out,
      el('p', { class: 'hint', text: 'A name is the same everywhere: chat, tables and every game world. Renaming changes it everywhere, and for a day others see "(was ...)" next to it.' }))
    await render()
    return box
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
        return el('tr', {},
          el('td', {}, name),
          el('td', { text: z.kind }),
          el('td', {}, el('label', {}, open, z.open ? ' open' : ' closed')),
          el('td', {}, viewer || el('span', { class: 'hint', text: '—' })),
          el('td', {}, el('div', { class: 'inline-form' },
            el('button', {
              type: 'button',
              class: 'primary',
              text: 'Save',
              onclick: async () => {
                const body = { name: name.value, open: open.checked }
                if (viewer) body.viewer_url = viewer.value.trim()
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
      el('div', { class: 'table-wrap' }, el('table', {}, el('thead', {}, el('tr', {}, ['Name', 'Kind', 'Open', 'Viewer', ''].map(h => el('th', { text: h })))), tbody)),
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
    const flags = [['game_guests', 'Let unlisted guests into game worlds (labelled "Guest N", never with someone\'s name)'],
      ['announce_results', 'Announce finished Boardwalk games in SandChat']]
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
    return el('section', { class: 'card' },
      el('h2', { text: 'Settings' }),
      el('form', {
        onsubmit: async (ev) => {
          ev.preventDefault()
          const body = {}
          for (const [key, , unit] of SETTINGS) body[key] = Math.round(Number(inputs[key].value) * FACTOR[unit])
          for (const key of Object.keys(toggles)) body[key] = toggles[key].checked
          body.message_retention_days = forever.checked ? null : Math.max(1, Math.round(Number(days.value)))
          try { settings = await api('PATCH', '/admin/settings', body); toast('Saved.') } catch (e) { toast(e.message) }
        }
      }, grid, boxes, retention, el('p', {}, el('button', { class: 'primary', type: 'submit', text: 'Save settings' }))))
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

  document.addEventListener('DOMContentLoaded', async () => {
    const map = await Beach.start('keeper')
    if (!map) return
    const main = document.querySelector('main')
    if (!map.me.admin) { main.replaceChildren(el('h1', { text: 'Keeper' }), el('p', { text: 'This page is for the Beach-keeper.' })); return }
    settings = await api('GET', '/admin/settings')
    main.replaceChildren(el('h1', { text: 'Keeper' }), beachSection(), await peopleSection(), await zoneSection(), settingsSection(), await httpsSection())
  })
})()
