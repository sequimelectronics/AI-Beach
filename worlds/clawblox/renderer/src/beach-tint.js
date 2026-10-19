// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// Beach colors on Clawblox's own character (the claw guy), for the ClawBlox zone. Original work
// for AI Beach; the model itself is Clawblox's and is not changed or copied.
//
// The model's colors are painted into one texture, shown unlit (an emissive map): a red shell
// with gold plates, dark lines and eyes. To tell players apart, each player's model gets its own
// copy of the material with a few lines added to its shader: the shell becomes the participant's
// outfit color and the plates their trim color, with the painted shading kept. Dark lines, eyes
// and highlights (anything gray or nearly black) stay as painted. Players without a Beach look
// keep the original colors.
import * as THREE from '../../static/vendor/three/build/three.module.min.js'

let tints = {}
let timer = null
let last = 0
// Names drawn without a look yet (someone who just arrived): while there are any, look again every
// 1.5 s instead of every 10 s, for up to a minute each (10-19: a new arrival took up to 15 s).
const waiting = new Map()

async function refresh () {
  try {
    const url = new URL('static/tints.json', document.baseURI)
    url.searchParams.set('t', String(Date.now()))
    const r = await fetch(url, { cache: 'no-store' })
    tints = r.ok ? ((await r.json()).players || {}) : {}
  } catch (_) {
    tints = {}
  }
}

export function startTints () {
  if (timer) return
  refresh()
  last = Date.now()
  timer = setInterval(() => {
    const now = Date.now()
    let soon = false
    for (const [name, since] of waiting) {
      if (tints[name]) waiting.delete(name)
      else if (now - since <= 60000) soon = true   // past a minute: remembered, so it isn't re-added
    }
    if (soon || now - last >= 10000) { last = now; refresh() }
  }, 1500)
}

// '#rrggbb' -> the color's sRGB components as numbers 0..1 (the shader works in sRGB).
function srgb (hex) {
  const n = parseInt(String(hex).slice(1), 16)
  return new THREE.Vector3(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255)
}

const RECOLOR = `
uniform vec3 beachShell;
uniform vec3 beachPlate;
uniform float beachOn;
vec3 beachHsv (vec3 c) {
  vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
  vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
  vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
  float d = q.x - min(q.w, q.y);
  return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + 1e-10)), d / (q.x + 1e-10), q.x);
}
vec3 beachRecolor (vec3 lin) {
  if (beachOn < 0.5) return lin;
  vec3 c = pow(max(lin, vec3(0.0)), vec3(1.0 / 2.2));       // to sRGB, to judge hues as painted
  vec3 hsv = beachHsv(c);
  float hue = hsv.x * 360.0;
  if (hue > 300.0) hue -= 360.0;                           // reds just below 0 count as red
  if (hsv.y < 0.3 || hsv.z < 0.1) return lin;              // lines, eyes, highlights: as painted
  float plate = smoothstep(12.0, 22.0, hue);               // red shell -> gold plates
  vec3 shell = clamp(beachShell * (hsv.z / 0.52), 0.0, 1.0);
  vec3 plates = clamp(beachPlate * (hsv.z / 0.72), 0.0, 1.0);
  return pow(mix(shell, plates, plate), vec3(2.2));
}
`

function tintable (material) {
  const m = material.clone()
  m.userData.beach = { shell: { value: new THREE.Vector3(1, 0, 0) }, plate: { value: new THREE.Vector3(1, 1, 0) }, on: { value: 0 } }
  m.onBeforeCompile = (shader) => {
    shader.uniforms.beachShell = m.userData.beach.shell
    shader.uniforms.beachPlate = m.userData.beach.plate
    shader.uniforms.beachOn = m.userData.beach.on
    shader.fragmentShader = RECOLOR + shader.fragmentShader.replace(
      '#include <emissivemap_fragment>',
      `#ifdef USE_EMISSIVEMAP
        vec4 emissiveColor = texture2D( emissiveMap, vEmissiveMapUv );
        totalEmissiveRadiance *= beachRecolor( emissiveColor.rgb );
      #endif`)
  }
  m.customProgramCacheKey = () => 'ai-beach-claw-tint'   // one shader program for every player
  return m
}

// Give a loaded model (under `root`) a player's colors. Called every frame: it only walks the
// model's few nodes and changes nothing unless the look changed or the model was (re)loaded.
export function tintModel (root, name) {
  const look = name ? tints[name] : null
  if (name && !look && !waiting.has(name)) waiting.set(name, Date.now())
  const key = look ? look.outfit + look.trim : ''
  root.traverse((node) => {
    if (!node.isMesh || !node.material || Array.isArray(node.material)) return
    if (!node.material.userData.beach) node.material = tintable(node.material)   // its own copy
    const u = node.material.userData.beach
    if (u.key === key) return
    u.key = key
    u.on.value = look ? 1 : 0
    if (look) {
      u.shell.value.copy(srgb(look.outfit))
      u.plate.value.copy(srgb(look.trim))
    }
  })
}
