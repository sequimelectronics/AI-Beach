// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// Follow a world's live spectator stream the way the Clawblox viewer does (a full state, then deltas
// with "rm" entries for removed parts) and print, every second, the players listed and the character
// bodies (entities with a PlayerName) a viewer would still draw. Node 22 or later (built-in WebSocket).
//     node scripts/viewer_stream.cjs ws://127.0.0.1:8100/spectate/ws?spectator_token=... <seconds>
const [url, secs] = process.argv.slice(2)
let state = null
function apply (base, d) {
  const next = { ...base, players: Array.isArray(d.players) ? d.players : base.players, entities: base.entities.slice() }
  const idx = new Map(next.entities.map((e, i) => [e.id, i]))
  const rm = new Set()
  for (const e of d.entities || []) {
    if (e.rm) { rm.add(e.id); continue }
    if (e.add) { if (idx.has(e.id)) next.entities[idx.get(e.id)] = e.add; else { idx.set(e.id, next.entities.length); next.entities.push(e.add) } rm.delete(e.id); continue }
  }
  next.entities = next.entities.filter(e => !rm.has(e.id))
  return next
}
const ws = new WebSocket(url)
ws.onmessage = (ev) => {
  const d = JSON.parse(String(ev.data))
  if (d.type === 'spectator_delta') { if (state) state = apply(state, d) } else if (!d.type && Array.isArray(d.entities)) state = d
}
const t0 = Date.now()
const timer = setInterval(() => {
  if (!state) return
  const bodies = state.entities.filter(e => e.attributes && e.attributes.PlayerName).map(e => e.attributes.PlayerName)
  console.log(JSON.stringify({ t: Math.round((Date.now() - t0) / 1000), players: state.players.map(p => p.attributes?.BeachName || p.name), bodies }))
  if (Date.now() - t0 > Number(secs) * 1000) { clearInterval(timer); ws.close(); process.exit(0) }
}, 1000)
