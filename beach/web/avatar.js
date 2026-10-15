// The avatar builder (My look): hair style and color, clothing theme and accessory, skin, eye color.
// Every change is drawn by the Beach itself (one renderer, one set of color rules); nothing is
// saved until you press Save, and looks can only change once in a while so people know who's who.
'use strict'
;(() => {
  const { el, api, svgNode, toast, minutes } = Beach
  const LABELS = {
    presets: { short: 'Short', bob: 'Bob', long: 'Long', bun: 'Bun', spiky: 'Spiky', curly: 'Curly' },
    accessories: { none: 'None', sunhat: 'Sun hat', flower: 'Flower', headphones: 'Headphones', bow: 'Bow', sunglasses: 'Sunglasses', starfish: 'Starfish clip', bandana: 'Bandana' }
  }
  let rec = null
  let saved = null
  let timer = null
  const ui = {}

  function radios (name, options, labelFor, extra) {
    return el('div', { class: 'choices', role: 'radiogroup', 'aria-label': name },
      options.map(v => el('label', {},
        el('input', { type: 'radio', name, value: v, onchange: () => change(name, v) }),
        extra ? extra(v) : null,
        labelFor(v))))
  }

  let QUICK = {}
  function colorField (field, title) {
    const text = el('input', { type: 'text', id: field, autocomplete: 'off', spellcheck: 'false', 'aria-describedby': field + '-err', placeholder: 'a name or #rrggbb' })
    const pick = el('input', { type: 'color', 'aria-label': title + ' color picker' })
    const err = el('div', { class: 'field-error error', id: field + '-err', 'aria-live': 'polite' })
    text.addEventListener('input', () => change(field, text.value, true))
    pick.addEventListener('input', () => { text.value = pick.value; change(field, pick.value) })
    ui[field] = { text, pick, err }
    return el('div', {},
      el('h2', {}, el('label', { for: field, text: title })),
      el('div', { class: 'color-row' }, text, pick),
      err,
      el('div', { class: 'choices' },
        QUICK[field].map(([c, hex]) => el('label', { title: c },
          el('input', { type: 'radio', name: field + '-quick', value: c, onchange: () => { text.value = c; change(field, c) } }),
          dot(hex), c))))
  }

  function dot (color, b) {
    const s = el('span', { class: 'swatch' + (b ? ' half' : '') })
    if (b) { s.style.setProperty('--a', color); s.style.setProperty('--b', b) } else s.style.background = color
    return s
  }

  function change (field, value, typing) {
    const next = Object.assign({}, rec, { [field]: value })
    clearTimeout(timer)
    timer = setTimeout(() => preview(next, field), typing ? 350 : 0)
  }

  async function preview (next, field) {
    try {
      const r = await api('POST', '/avatar/preview', next)
      rec = r.avatar
      for (const f of ['hair', 'eyes']) ui[f].err.textContent = ''
      ui.figure.replaceChildren(svgNode(r.svg))
      for (const f of ['hair', 'eyes']) {
        ui[f].pick.value = r.colors[f]
        if (document.activeElement !== ui[f].text) ui[f].text.value = rec[f]
      }
      ui.describe.textContent = r.describe
      ui.save.disabled = JSON.stringify(rec) === JSON.stringify(saved) || ui.wait > 0
    } catch (e) {
      if (field && ui[field] && ui[field].err) ui[field].err.textContent = e.message.replace(/^\w+: /, '')
      else toast(e.message)
    }
  }

  function reflect () {
    for (const g of ['preset', 'theme', 'skin', 'accessory']) {
      const r = document.querySelector('input[name=' + g + '][value="' + rec[g] + '"]')
      if (r) r.checked = true
    }
    for (const f of ['hair', 'eyes']) ui[f].text.value = rec[f]
  }

  function showWait () {
    if (ui.wait > 0) {
      ui.status.textContent = 'You can change your look again in about ' + minutes(ui.wait) + '. (Looks change slowly so everyone can tell who\'s who.)'
      ui.save.disabled = true
    } else {
      ui.status.textContent = saved && JSON.stringify(saved) !== JSON.stringify(rec) ? '' : 'Pick anything; nothing changes until you save.'
    }
  }

  async function save () {
    try {
      const r = await api('PUT', '/me/avatar', rec)
      saved = r.avatar
      ui.wait = r.next_change_in
      toast('Saved. This is how you\'ll look around the Beach.')
      showWait()
    } catch (e) {
      if (e.body && e.body.retry_after) ui.wait = e.body.retry_after
      ui.status.textContent = e.message
    }
  }

  async function downloadPicture () {
    const r = await fetch('/me/avatar.png?size=256', { headers: { Authorization: 'Bearer ' + Beach.token() } })
    const url = URL.createObjectURL(await r.blob())
    const a = el('a', { href: url, download: 'my-avatar.png' })
    document.body.append(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
  }

  // Your name: one name everywhere (chat, tables, game worlds). Renames are announced, like /nick.
  async function nameCard () {
    const info = await api('GET', '/me')
    const input = el('input', { type: 'text', id: 'my-name', value: info.name, maxlength: '24', autocomplete: 'off' })
    const status = el('p', { class: 'hint', 'aria-live': 'polite' })
    const wait = info.next_rename_in
    if (wait > 0) status.textContent = 'You can rename yourself again in about ' + Math.ceil(wait / 3600) + ' h.'
    else status.textContent = 'Your name is the same in every zone, at every table and in every game.'
    if (info.was) status.textContent += ' (You were ' + info.was + ' until recently.)'
    return el('section', { class: 'card name-card' },
      el('form', {
        class: 'inline-form',
        onsubmit: async (ev) => {
          ev.preventDefault()
          if (input.value.trim() === info.name) return
          if (!confirm('Change your name to ' + input.value.trim() + ' everywhere? Everyone will see "' + info.name + ' is now known as ' + input.value.trim() + '".')) return
          try {
            await api('PUT', '/me/name', { name: input.value.trim() })
            toast('Renamed.')
            setTimeout(() => location.reload(), 800)
          } catch (e) { status.textContent = e.message }
        }
      }, el('label', { for: 'my-name' }, 'My name', input), el('button', { class: 'primary', type: 'submit', text: 'Rename', disabled: wait > 0 })),
      status)
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const map = await Beach.start('avatar')
    if (!map) return
    const [mine, opts] = await Promise.all([api('GET', '/me/avatar'), api('GET', '/avatar/options')])
    rec = mine.avatar
    QUICK = opts.quick
    saved = mine.chosen ? mine.avatar : null
    ui.wait = mine.next_change_in
    ui.figure = el('span', { class: 'avatar' })
    ui.describe = el('p', { class: 'describe', 'aria-live': 'polite' })
    ui.save = el('button', { class: 'primary', type: 'button', text: 'Save my look', onclick: save })
    ui.status = el('p', { class: 'hint', 'aria-live': 'polite' })
    const main = document.querySelector('main')
    main.replaceChildren(
      el('h1', { text: 'My look' }),
      await nameCard(),
      el('div', { class: 'builder' },
        el('div', { class: 'preview card' }, ui.figure, ui.describe, ui.save, ui.status,
          el('p', {}, el('button', { class: 'quiet', type: 'button', text: 'Download my picture', onclick: downloadPicture }))),
        // In pairs that belong together: hair style with hair color, clothing with accessory.
        el('div', {},
          el('div', { class: 'look-pair' },
            el('h2', { text: 'Hair style' }), radios('preset', opts.presets, v => LABELS.presets[v] || v),
            colorField('hair', 'Hair color')),
          el('div', { class: 'look-pair' },
            el('h2', { text: 'Clothing theme' }), radios('theme', Object.keys(opts.themes), v => v.replace('-', ' '), v => dot(opts.themes[v].outfit, opts.themes[v].trim)),
            el('h2', { text: 'Accessory' }), radios('accessory', opts.accessories, v => LABELS.accessories[v] || v)),
          el('h2', { text: 'Skin' }), radios('skin', Object.keys(opts.skins), v => v, v => dot(opts.skins[v])),
          colorField('eyes', 'Eye color'))))
    reflect()
    await preview(rec)
    showWait()
  })
})()
