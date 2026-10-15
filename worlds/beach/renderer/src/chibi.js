// A participant's chibi in 3D, built from simple shapes (spheres, capsules, cylinders, cones) and
// coloured from their Beach look: hair, eyes, skin, and the outfit and trim colours of their theme.
// The same choices as the "My look" page (beach/avatar.py draws the 2D one), as simple shapes:
// a big head, a small body, one of six hairstyles, and an accessory. Original work for AI Beach.
//
// Drawn like the 2D avatar, not like a doll: flat colours (no lighting, no tone mapping) and a dark
// outline round every shape. The face isn't modelled at all: the head wears the 2D avatar's own
// face (eyes, shines, cheeks, smile and front fringe), drawn by beach/avatar.py face_svg() and
// projected straight onto the front of the head, so the 3D face can't drift from the 2D one.
//
// The character stands in its HumanoidRootPart's box (2 x 5 x 2, origin at the centre) and faces
// -Z, the way the engine's characters face. Nothing moves except the whole character.
import * as THREE from '../../static/vendor/three/build/three.module.min.js'

const H = 1.2                   // head radius
const HEAD_Y = 1.25             // head centre (the box runs from -2.5 to 2.5)
const HAIR_R = H * 1.06

// Shared geometry: one of each shape for every character (sized per use with mesh.scale).
const GEO = {}
function geo (key, make) {
  if (!GEO[key]) GEO[key] = make()
  return GEO[key]
}
const sphere = () => geo('sphere', () => new THREE.SphereGeometry(1, 20, 14))
const smallSphere = () => geo('sphere-s', () => new THREE.SphereGeometry(1, 10, 7))
const capsule = () => geo('capsule', () => new THREE.CapsuleGeometry(1, 1, 3, 8))
const cylinder = (top, bottom) => geo('cyl-' + top + '-' + bottom, () => new THREE.CylinderGeometry(top, bottom, 1, 14, 1))
const cone = () => geo('cone', () => new THREE.ConeGeometry(1, 1, 8, 1))
// A cap of hair: the top of a sphere down to `theta` (radians from the crown).
const cap = (theta) => geo('cap-' + theta.toFixed(3), () => new THREE.SphereGeometry(1, 20, 8, 0, Math.PI * 2, 0, theta))
// A shell of hair round the back and sides, down to `theta`, open at the front by `gap` degrees.
const shell = (theta, gap = 120) => geo('shell-' + theta.toFixed(3) + '-' + gap, () => {
  const open = gap * Math.PI / 180
  return new THREE.SphereGeometry(1, 16, 9, Math.PI * 1.5 + open / 2, Math.PI * 2 - open, 0, theta)
})
const torus = (arc) => geo('torus-' + arc.toFixed(3), () => new THREE.TorusGeometry(1, 0.06, 6, 20, arc))

// Materials, shared by colour: flat, unlit, and not tone-mapped, so each colour on screen is the
// look's colour exactly, as in 2D.
const MAT = new Map()
function mat (hex, opts = {}) {
  const key = hex + JSON.stringify(opts)
  if (!MAT.has(key)) {
    const m = new THREE.MeshBasicMaterial({ color: new THREE.Color(hex), toneMapped: false,
      side: opts.double ? THREE.DoubleSide : THREE.FrontSide })
    MAT.set(key, m)
  }
  return MAT.get(key)
}

// The outline: every shape drawn again in the 2D avatar's ink colour, a little bigger and inside
// out, so only a dark rim shows round it (the usual cartoon outline; one draw call per character).
export const INK = '#3d2b2b'
const OUTLINE_W = 0.055
const OUTLINE = new THREE.MeshBasicMaterial({ color: new THREE.Color(INK), side: THREE.BackSide, toneMapped: false })
OUTLINE.onBeforeCompile = (shader) => {
  shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>',
    '#include <begin_vertex>\n  transformed += normalize(normal) * ' + OUTLINE_W.toFixed(3) + ';')
}
OUTLINE.customProgramCacheKey = () => 'ai-beach-chibi-outline'

// The face: an SVG (beach/avatar.py face_svg) drawn once into a texture, shared by identical faces.
const FACE_W = 512
const FACE_H = 476                      // the 2D face box is 58 x 54
const FACE_TEX = new Map()
export function faceTexture (svg) {
  if (!svg || typeof document === 'undefined') return null
  if (FACE_TEX.has(svg)) return FACE_TEX.get(svg)
  if (FACE_TEX.size > 64) FACE_TEX.clear()        // looks change rarely; don't grow without end
  const canvas = document.createElement('canvas')
  canvas.width = FACE_W
  canvas.height = FACE_H
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }))
  const img = new Image()
  img.onload = () => {
    canvas.getContext('2d').drawImage(img, 0, 0, FACE_W, FACE_H)
    tex.needsUpdate = true
    URL.revokeObjectURL(url)
  }
  img.onerror = () => URL.revokeObjectURL(url)
  img.src = url
  FACE_TEX.set(svg, tex)
  return tex
}

// The front half of the head, with the 2D face box laid straight onto it (a front-on projection:
// seen from the front, the face is exactly the 2D drawing).
const faceShell = () => geo('face-shell', () => {
  const g = new THREE.SphereGeometry(1, 32, 24, Math.PI, Math.PI, 0, Math.PI)
  const p = g.attributes.position
  const uv = g.attributes.uv
  // Seen from the front the character's -x side is on the viewer's right, as the drawing's right is.
  for (let i = 0; i < p.count; i++) uv.setXY(i, (1 - p.getX(i)) / 2, (p.getY(i) + 1) / 2)
  uv.needsUpdate = true
  return g
})

// Darken (f < 1) or lighten (f > 1) a '#rrggbb' colour, exactly as beach/colours.py shade() does.
export function shade (hex, f) {
  const n = parseInt(hex.slice(1), 16)
  let c = [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  c = f <= 1 ? c.map(v => Math.trunc(v * f)) : c.map(v => Math.trunc(v + (255 - v) * (f - 1)))
  return '#' + c.map(v => v.toString(16).padStart(2, '0')).join('')
}

function part (g, material, scale, pos, rot) {
  const m = new THREE.Mesh(g, material)
  if (scale) m.scale.set(...(Array.isArray(scale) ? scale : [scale, scale, scale]))
  if (pos) m.position.set(...pos)
  if (rot) m.rotation.set(...rot)
  m.castShadow = true
  return m
}

// A point on the head's surface, `x` right and `y` up from the head's centre, on the face side.
function onFace (x, y, r = H) {
  const z = -Math.sqrt(Math.max(0, r * r - x * x - y * y))
  return new THREE.Vector3(x, HEAD_Y + y, z)
}

// The default look for someone without one (a guest): plain colours picked from their name, and
// the Beach's plain guest face (no fringe) when the bridge has provided it.
export function guestLook (base, face = null) {
  return { preset: 'short', accessory: 'none', hair: shade(base, 0.6), eyes: '#5c4a42', skin: '#e0ac7e', outfit: base,
    trim: '#ffffff', face, guest: true }
}

// `opts.faceTexture(svg)` turns the face drawing into a texture (default: through the browser's own
// SVG renderer; tests without a browser pass a stand-in).
export function buildChibi (look, opts = {}) {
  const L = Object.assign(guestLook('#888888'), { guest: false }, look || {})
  const g = new THREE.Group()
  const skin = mat(L.skin)
  const outfit = mat(L.outfit)
  const trim = mat(L.trim)
  const hair = mat(L.hair, { double: true })
  const hairDark = mat(shade(L.hair, 0.8), { double: true })
  const shoes = mat(shade(L.outfit, 0.6))

  // Body: legs, shoes, a flared outfit with a trim band and collar, shoulder puffs, arms.
  for (const s of [-1, 1]) {
    g.add(part(cylinder(1, 1), skin, [0.15, 0.55, 0.15], [0.28 * s, -1.85, 0]))
    g.add(part(smallSphere(), shoes, [0.22, 0.13, 0.32], [0.28 * s, -2.36, -0.06]))
    g.add(part(smallSphere(), outfit, 0.27, [0.55 * s, -0.12, 0]))
    g.add(part(capsule(), skin, [0.13, 0.32, 0.13], [0.7 * s, -0.62, 0], [0, 0, 0.28 * s]))
  }
  g.add(part(cylinder(0.45, 0.8), outfit, [1, 1.6, 1], [0, -0.75, 0]))
  g.add(part(cylinder(0.73, 0.775), trim, [1.012, 0.22, 1.012], [0, -1.25, 0]))
  g.add(part(cylinder(0.3, 0.47), trim, [1, 0.14, 1], [0, 0.02, 0]))

  // Head and ears. The face is painted on (below), not modelled.
  g.add(part(sphere(), skin, [H, H * 0.95, H * 0.97], [0, HEAD_Y, 0]))
  for (const s of [-1, 1]) g.add(part(smallSphere(), skin, [0.17, 0.24, 0.12], [1.17 * s, HEAD_Y - 0.1, 0]))

  addHair(g, L.preset, hair, hairDark, !!L.face && !L.guest)
  addAccessory(g, L.accessory, outfit, trim)
  const out = mergeByMaterial(g)

  // The face, as drawn in 2D, on a shell just outside the head's front.
  const tex = L.face ? (opts.faceTexture || faceTexture)(L.face) : null
  if (tex) {
    const face = new THREE.Mesh(faceShell(), new THREE.MeshBasicMaterial({
      map: tex, transparent: true, depthWrite: false, toneMapped: false,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }))
    face.scale.set(H * 1.004, H * 0.95 * 1.004, H * 0.97 * 1.004)
    face.position.set(0, HEAD_Y, 0)
    face.renderOrder = 1
    face.userData.face = true
    out.add(face)
  }
  return out
}

// One mesh per colour instead of one per part: ~10 draw calls per character instead of ~40, which
// is what costs most on a modest machine. The parts are baked into place; nothing moves anyway.
function mergeByMaterial (g) {
  g.updateMatrixWorld(true)
  const byMat = new Map()
  g.traverse((m) => {
    if (!m.isMesh) return
    if (!byMat.has(m.material)) byMat.set(m.material, [])
    byMat.get(m.material).push(m)
  })
  const out = new THREE.Group()
  const solid = []
  const normalMatrix = new THREE.Matrix3()
  const v = new THREE.Vector3()
  for (const [material, meshes] of byMat) {
    let nv = 0
    let ni = 0
    for (const m of meshes) {
      nv += m.geometry.attributes.position.count
      ni += m.geometry.index ? m.geometry.index.count : m.geometry.attributes.position.count
    }
    const pos = new Float32Array(nv * 3)
    const nor = new Float32Array(nv * 3)
    const idx = new (nv > 65535 ? Uint32Array : Uint16Array)(ni)
    let vo = 0
    let io = 0
    for (const m of meshes) {
      const gp = m.geometry.attributes.position
      const gn = m.geometry.attributes.normal
      normalMatrix.getNormalMatrix(m.matrixWorld)
      for (let i = 0; i < gp.count; i++) {
        v.fromBufferAttribute(gp, i).applyMatrix4(m.matrixWorld).toArray(pos, (vo + i) * 3)
        v.fromBufferAttribute(gn, i).applyMatrix3(normalMatrix).normalize().toArray(nor, (vo + i) * 3)
      }
      if (m.geometry.index) {
        const gi = m.geometry.index
        for (let i = 0; i < gi.count; i++) idx[io + i] = gi.getX(i) + vo
        io += gi.count
      } else {
        for (let i = 0; i < gp.count; i++) idx[io + i] = vo + i
        io += gp.count
      }
      vo += gp.count
    }
    const geom = new THREE.BufferGeometry()
    geom.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    geom.setAttribute('normal', new THREE.BufferAttribute(nor, 3))
    geom.setIndex(new THREE.BufferAttribute(idx, 1))
    geom.computeBoundingSphere()
    const merged = new THREE.Mesh(geom, material)
    merged.castShadow = true
    out.add(merged)
    solid.push(geom)
  }
  // The outline: all the shapes in one inside-out mesh (it shares their merged buffers).
  out.add(new THREE.Mesh(concat(solid), OUTLINE))
  return out
}

function concat (geoms) {
  let nv = 0
  let ni = 0
  for (const g of geoms) { nv += g.attributes.position.count; ni += g.index.count }
  const pos = new Float32Array(nv * 3)
  const nor = new Float32Array(nv * 3)
  const idx = new (nv > 65535 ? Uint32Array : Uint16Array)(ni)
  let vo = 0
  let io = 0
  for (const g of geoms) {
    pos.set(g.attributes.position.array, vo * 3)
    nor.set(g.attributes.normal.array, vo * 3)
    const gi = g.index.array
    for (let i = 0; i < gi.length; i++) idx[io + i] = gi[i] + vo
    io += gi.length
    vo += g.attributes.position.count
  }
  const out = new THREE.BufferGeometry()
  out.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  out.setAttribute('normal', new THREE.BufferAttribute(nor, 3))
  out.setIndex(new THREE.BufferAttribute(idx, 1))
  out.computeBoundingSphere()
  return out
}

// Free a built character's geometry (its colours, outline and face textures are shared and cached).
export function disposeChibi (obj) {
  obj.traverse((m) => {
    if (!m.isMesh) return
    if (m.userData.face) m.material.dispose()     // its own material; the shell and texture are shared
    else m.geometry.dispose()
  })
}

// The hair cap tilts back, so the forehead and eyes show and the back of the head is covered.
// With a painted face, the front edge sits higher still (`painted`): the fringe over the forehead
// is the 2D avatar's own zigzag bangs, painted on the head, and the cap continues it upward.
function hairCap (material, theta, tilt) {
  const m = part(cap(theta), material, HAIR_R, [0, HEAD_Y, 0], [tilt, 0, 0])
  return m
}

function addHair (g, preset, hair, hairDark, painted) {
  // With a painted face, the cap's front edge moves back near the crown (its back edge stays put),
  // so the 2D fringe painted on the forehead shows in full, as in 2D.
  const capFront = (theta, tilt) => {
    if (!painted) return hairCap(hair, theta, tilt)
    const back = theta + tilt
    const front = 0.42                               // radians from the crown
    return hairCap(hair, (front + back) / 2, (back - front) / 2)
  }
  // Under the cap (a smaller radius), so the two never fight over the same pixels.
  const backShell = (theta, colour = hairDark, gap = 120) => part(shell(theta, gap), colour, HAIR_R * 0.965, [0, HEAD_Y, 0])
  switch (preset) {
    case 'bob':          // to the jaw all round, a straight fringe
      g.add(capFront(Math.PI * 0.5, 0.42))
      g.add(backShell(Math.PI * 0.8))
      for (const s of [-1, 1]) g.add(part(capsule(), hair, [0.24, 0.5, 0.3], [1.05 * s, HEAD_Y - 0.3, -0.35]))
      break
    case 'long':         // past the shoulders, with long locks in front
      g.add(capFront(Math.PI * 0.5, 0.42))
      g.add(backShell(Math.PI * 0.82))
      g.add(part(capsule(), hairDark, [0.95, 0.85, 0.42], [0, HEAD_Y - 1.55, 0.62]))
      for (const s of [-1, 1]) g.add(part(capsule(), hair, [0.2, 0.95, 0.24], [1.05 * s, HEAD_Y - 1.0, -0.3], [0, 0, -0.08 * s]))
      break
    case 'bun':          // pulled back, a round bun on top
      g.add(capFront(Math.PI * 0.55, 0.45))
      g.add(backShell(Math.PI * 0.55, hair, 160))        // covers the temples, its edge behind the ears
      g.add(part(sphere(), hair, 0.52, [0, HEAD_Y + 1.32, 0.25]))
      break
    case 'spiky':        // short, with spikes standing up
      g.add(capFront(Math.PI * 0.5, 0.38))
      g.add(backShell(Math.PI * 0.55, hair, 160))        // covers the temples, its edge behind the ears
      for (const [theta, phi] of [[0.05, 0], [0.28, 0.2], [0.28, 1.4], [0.28, 2.6], [0.28, 3.8], [0.28, 5.0],
        [0.48, 0.9], [0.48, 2.3], [0.48, 3.9], [0.48, 5.3]]) {
        const dir = new THREE.Vector3().setFromSphericalCoords(1, theta * Math.PI, phi)
        dir.applyAxisAngle(new THREE.Vector3(1, 0, 0), 0.38)
        if (dir.z < -0.55) continue        // no spike over the eyes
        const m = part(cone(), hair, [0.26, 0.75, 0.26], [0, 0, 0])
        m.position.set(0, HEAD_Y, 0).addScaledVector(dir, HAIR_R + 0.2)
        m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir)
        g.add(m)
      }
      break
    case 'curly':        // a round cloud of curls
      for (const [theta, step, r] of [[0.0, 7, 0.0], [0.2, 7, 0.42], [0.4, 9, 0.44], [0.6, 8, 0.42]]) {
        const n = theta === 0 ? 1 : step
        for (let i = 0; i < n; i++) {
          const phi = (i / n) * Math.PI * 2
          const dir = new THREE.Vector3().setFromSphericalCoords(1, theta * Math.PI, phi)
          dir.applyAxisAngle(new THREE.Vector3(1, 0, 0), 0.32)
          if (dir.z < -0.45 && dir.y < 0.62) continue   // keep the face clear
          const m = part(smallSphere(), theta >= 0.6 ? hairDark : hair, r || 0.48)
          m.position.set(0, HEAD_Y, 0).addScaledVector(dir, H * 1.02)
          g.add(m)
        }
      }
      break
    default:             // short
      g.add(capFront(Math.PI * 0.52, 0.42))
      g.add(backShell(Math.PI * 0.62))
  }
}

// Clips, flowers and bows sit on the character's left (-x), which is the picture's right, as in 2D.
function addAccessory (g, acc, outfit, trim) {
  const top = HEAD_Y + H * 0.9
  switch (acc) {
    case 'sunhat': {
      const hat = new THREE.Group()
      hat.add(part(cylinder(1, 1), trim, [2.0, 0.07, 2.0], [0, 0, 0]))
      hat.add(part(cylinder(0.8, 1), trim, [1, 0.6, 1], [0, 0.3, 0]))
      hat.add(part(cylinder(1, 1), outfit, [1.005, 0.16, 1.005], [0, 0.1, 0]))
      hat.position.set(0, top - 0.05, 0.12)
      hat.rotation.x = 0.28
      g.add(hat)
      break
    }
    case 'flower': {
      const c = onFace(-0.82, 0.78, HAIR_R + 0.2)
      const pink = mat('#ff6f91')
      for (let k = 0; k < 5; k++) {
        const a = (k / 5) * Math.PI * 2
        g.add(part(smallSphere(), pink, 0.15, [c.x + 0.17 * Math.cos(a), c.y + 0.17 * Math.sin(a), c.z]))
      }
      g.add(part(smallSphere(), mat('#ffd166'), 0.11, [c.x, c.y, c.z - 0.05]))
      break
    }
    case 'headphones': {
      g.add(part(torus(Math.PI), mat('#3a4256'), [1.36, 1.36, 1.6], [0, HEAD_Y, 0], [0, 0, 0]))
      for (const s of [-1, 1]) g.add(part(cylinder(1, 1), outfit, [0.32, 0.22, 0.32], [1.3 * s, HEAD_Y, 0], [0, 0, Math.PI / 2]))
      break
    }
    case 'bow': {
      const c = onFace(-0.75, 0.95, HAIR_R + 0.22)
      for (const s of [-1, 1]) g.add(part(cone(), outfit, [0.25, 0.45, 0.12], [c.x + 0.24 * s, c.y, c.z], [0, 0, (Math.PI / 2) * s]))
      g.add(part(smallSphere(), trim, 0.12, [c.x, c.y, c.z - 0.04]))
      break
    }
    case 'sunglasses': {        // pushed up on the head, resting on the hair above the forehead
      const dark = mat('#222222')
      for (const s of [-1, 1]) {
        const c = onFace(0.4 * s, 0.82, HAIR_R + 0.12)
        const m = part(smallSphere(), dark, [0.3, 0.2, 0.07], [c.x, c.y, c.z])
        m.lookAt(c.clone().multiplyScalar(2).sub(new THREE.Vector3(0, HEAD_Y, 0)))
        g.add(m)
      }
      const b = onFace(0, 0.86, HAIR_R + 0.12)
      g.add(part(cylinder(1, 1), dark, [0.04, 0.3, 0.04], [b.x, b.y, b.z], [0, 0, Math.PI / 2]))
      break
    }
    case 'starfish': {
      const c = onFace(-0.8, 0.82, HAIR_R + 0.22)
      const orange = mat('#f08a4b')
      for (let k = 0; k < 5; k++) {
        const a = (k / 5) * Math.PI * 2 + Math.PI / 2
        const m = part(cone(), orange, [0.09, 0.32, 0.05], [c.x + 0.13 * Math.cos(a), c.y + 0.13 * Math.sin(a), c.z])
        m.rotation.z = a - Math.PI / 2
        g.add(m)
      }
      break
    }
    case 'bandana': {
      g.add(part(cylinder(1, 1), outfit, [H * 1.08, 0.3, H * 1.08], [0, HEAD_Y + 0.55, 0.02], [0.42, 0, 0]))
      for (const s of [-1, 1]) g.add(part(cone(), outfit, [0.14, 0.45, 0.1], [0.14 * s, HEAD_Y + 0.25, 1.15], [0.5, 0, 0.5 * s]))
      break
    }
  }
}

// Total triangles in a built character (for the performance numbers).
export function triangles (obj) {
  let n = 0
  obj.traverse((m) => {
    if (!m.isMesh) return
    const gm = m.geometry
    n += (gm.index ? gm.index.count : gm.attributes.position.count) / 3
  })
  return n
}

