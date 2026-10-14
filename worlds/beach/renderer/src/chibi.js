// A participant's chibi in 3D, built from simple shapes (spheres, capsules, cylinders, discs) and
// coloured from their Beach look: hair, eyes, skin, and the outfit and trim colours of their theme.
// The same choices as the "My look" page (beach/avatar.py draws the 2D one), as simple shapes:
// a big head, a small body, one of six hairstyles, and an accessory. Original work for AI Beach.
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
const disc = () => geo('disc', () => new THREE.CircleGeometry(1, 18))
const capsule = () => geo('capsule', () => new THREE.CapsuleGeometry(1, 1, 3, 8))
const cylinder = (top, bottom) => geo('cyl-' + top + '-' + bottom, () => new THREE.CylinderGeometry(top, bottom, 1, 14, 1))
const cone = () => geo('cone', () => new THREE.ConeGeometry(1, 1, 8, 1))
// A cap of hair: the top of a sphere down to `theta` (radians from the crown).
const cap = (theta) => geo('cap-' + theta.toFixed(3), () => new THREE.SphereGeometry(1, 20, 8, 0, Math.PI * 2, 0, theta))
// A shell of hair round the back and sides (open at the front), down to `theta`.
const shell = (theta) => geo('shell-' + theta.toFixed(3), () =>
  new THREE.SphereGeometry(1, 16, 9, Math.PI * 11 / 6, Math.PI * 4 / 3, 0, theta))
const torus = (arc) => geo('torus-' + arc.toFixed(3), () => new THREE.TorusGeometry(1, 0.06, 6, 20, arc))

// Materials, shared by colour.
const MAT = new Map()
function mat (hex, opts = {}) {
  const key = hex + JSON.stringify(opts)
  if (!MAT.has(key)) {
    const Kind = opts.unlit ? THREE.MeshBasicMaterial : THREE.MeshLambertMaterial
    const m = new Kind({ color: new THREE.Color(hex), side: opts.double ? THREE.DoubleSide : THREE.FrontSide })
    // A little of the colour glows by itself, so shadowed sides keep their colour (the 2D look is flat).
    if (!opts.unlit) m.emissive = new THREE.Color(hex).multiplyScalar(0.28)
    if (opts.opacity !== undefined) { m.transparent = true; m.opacity = opts.opacity; m.depthWrite = false }
    MAT.set(key, m)
  }
  return MAT.get(key)
}

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

// A flat layer lying on the face at (x, y), lifted `lift` off the surface (a disc unless given).
function faceDisc (material, x, y, rx, ry, lift, shape = disc(), turn = 0) {
  const p = onFace(x, y)
  const n = p.clone().sub(new THREE.Vector3(0, HEAD_Y, 0)).normalize()
  const m = new THREE.Mesh(shape, material)
  m.scale.set(rx, ry, 1)
  m.position.copy(p).addScaledVector(n, lift)
  m.lookAt(m.position.clone().add(n))
  m.rotateZ(turn)
  return m
}
const smile = () => geo('smile', () => new THREE.TorusGeometry(1, 0.17, 5, 14, Math.PI))

// The default look for someone without one (a guest): plain colours picked from their name.
export function guestLook (base) {
  return { preset: 'short', accessory: 'none', hair: shade(base, 0.6), eyes: '#5c4a42', skin: '#e0ac7e', outfit: base, trim: '#ffffff' }
}

export function buildChibi (look) {
  const L = Object.assign(guestLook('#888888'), look || {})
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

  // Head: face, ears, eyes (outline, iris in the eye colour, pupil, two highlights), cheeks, mouth.
  g.add(part(sphere(), skin, [H, H * 0.95, H * 0.97], [0, HEAD_Y, 0]))
  for (const s of [-1, 1]) g.add(part(smallSphere(), skin, [0.17, 0.24, 0.12], [1.17 * s, HEAD_Y - 0.1, 0]))
  const ink = mat('#2b2233', { unlit: true })
  const iris = mat(L.eyes, { unlit: true })
  const pupil = mat('#1a1420', { unlit: true })
  const white = mat('#ffffff', { unlit: true })
  for (const s of [-1, 1]) {
    const x = 0.44 * s
    g.add(faceDisc(ink, x, -0.12, 0.25, 0.32, 0.004))
    g.add(faceDisc(iris, x, -0.15, 0.2, 0.26, 0.008))
    g.add(faceDisc(pupil, x, -0.21, 0.1, 0.14, 0.012))
    g.add(faceDisc(white, x - 0.08, -0.03, 0.075, 0.075, 0.016))
    g.add(faceDisc(white, x + 0.07, -0.29, 0.04, 0.04, 0.016))
    g.add(faceDisc(mat('#ff6f7f', { unlit: true, opacity: 0.35 }), 0.68 * s, -0.42, 0.2, 0.11, 0.006))
  }
  g.add(faceDisc(mat('#7a3333', { unlit: true }), 0, -0.48, 0.14, 0.1, 0.01, smile(), Math.PI))   // a small smile

  addHair(g, L.preset, hair, hairDark)
  addAccessory(g, L.accessory, outfit, trim)
  return mergeByMaterial(g)
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
    merged.castShadow = !material.transparent && material.isMeshLambertMaterial
    out.add(merged)
  }
  return out
}

// Free a built character's geometry (its materials are shared and stay cached).
export function disposeChibi (obj) {
  obj.traverse((m) => { if (m.isMesh) m.geometry.dispose() })
}

// The hair cap tilts back, so the forehead and eyes show and the back of the head is covered.
function hairCap (material, theta, tilt) {
  const m = part(cap(theta), material, HAIR_R, [0, HEAD_Y, 0], [tilt, 0, 0])
  return m
}

function addHair (g, preset, hair, hairDark) {
  // Under the cap (a smaller radius), so the two never fight over the same pixels.
  const backShell = (theta) => part(shell(theta), hairDark, HAIR_R * 0.965, [0, HEAD_Y, 0])
  switch (preset) {
    case 'bob':          // to the jaw all round, a straight fringe
      g.add(hairCap(hair, Math.PI * 0.5, 0.42))
      g.add(backShell(Math.PI * 0.8))
      for (const s of [-1, 1]) g.add(part(capsule(), hair, [0.24, 0.5, 0.3], [1.05 * s, HEAD_Y - 0.3, -0.35]))
      break
    case 'long':         // past the shoulders, with long locks in front
      g.add(hairCap(hair, Math.PI * 0.5, 0.42))
      g.add(backShell(Math.PI * 0.82))
      g.add(part(capsule(), hairDark, [0.95, 0.85, 0.42], [0, HEAD_Y - 1.55, 0.62]))
      for (const s of [-1, 1]) g.add(part(capsule(), hair, [0.2, 0.95, 0.24], [1.05 * s, HEAD_Y - 1.0, -0.3], [0, 0, -0.08 * s]))
      break
    case 'bun':          // pulled back, a round bun on top
      g.add(hairCap(hair, Math.PI * 0.55, 0.45))
      g.add(part(sphere(), hair, 0.52, [0, HEAD_Y + 1.32, 0.25]))
      break
    case 'spiky':        // short, with spikes standing up
      g.add(hairCap(hair, Math.PI * 0.5, 0.38))
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
      g.add(hairCap(hair, Math.PI * 0.52, 0.42))
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

