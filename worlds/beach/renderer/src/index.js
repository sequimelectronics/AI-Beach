// SPDX-License-Identifier: MIT
// Beach renderer for AI-Beach. Derived from Clawblox's worlds/mesa-island/renderer/src/index.js
// (MIT, Copyright (c) 2026 nacloos; see LICENSE.clawblox and NOTICE.md in this folder).
// Changes: beach roles (sand, sea floor, goal posts, plot markers, balls, sand pieces),
// players drawn as their Beach chibi (./chibi.js, ours) instead of a GLB model, and a banner for
// world announcements.
// three.js is vendored next to the world (static/vendor/three, MIT) and bundled in, so the viewer
// never fetches it from the internet.
import * as THREE from '../../static/vendor/three/build/three.module.min.js'
import { buildChibi, disposeChibi, guestLook } from './chibi.js'

const COLLIDER_DEBUG_FILL_MATERIAL = new THREE.MeshBasicMaterial({
  color: 0x00d8ff,
  transparent: true,
  opacity: 0.08,
  depthWrite: false,
  depthTest: false,
  toneMapped: false,
})

const COLLIDER_DEBUG_LINE_MATERIAL = new THREE.LineBasicMaterial({
  color: 0x00d8ff,
  transparent: true,
  opacity: 0.95,
  depthTest: false,
  toneMapped: false,
})

function rotationToQuaternion(rot) {
  const m = new THREE.Matrix4()
  m.set(
    rot[0][0], rot[0][1], rot[0][2], 0,
    rot[1][0], rot[1][1], rot[1][2], 0,
    rot[2][0], rot[2][1], rot[2][2], 0,
    0, 0, 0, 1,
  )
  return new THREE.Quaternion().setFromRotationMatrix(m)
}

function resolveEntityModelUrl(entity) {
  if (typeof entity.model_url === 'string' && entity.model_url.length > 0) {
    return entity.model_url
  }
  const attrs = entity.attributes
  if (attrs && typeof attrs.ModelUrl === 'string' && attrs.ModelUrl.length > 0) {
    return attrs.ModelUrl
  }
  return null
}

function resolveEntityColorHex(entity) {
  const color = entity?.render?.color
  if (!Array.isArray(color) || color.length < 3) {
    console.warn(`Entity ${entity?.id ?? '?'} (role=${entity?.render?.role ?? '?'}) missing render.color`)
    return 0xff00ff
  }
  return (Math.round(color[0] * 255) << 16) |
    (Math.round(color[1] * 255) << 8) |
    Math.round(color[2] * 255)
}

function resolveEntityColor(entity) {
  const color = entity?.render?.color
  if (!Array.isArray(color) || color.length < 3) {
    console.warn(`Entity ${entity?.id ?? '?'} (role=${entity?.render?.role ?? '?'}) missing render.color`)
    return new THREE.Color(0xff00ff)
  }
  return new THREE.Color(color[0], color[1], color[2])
}

function createRockLikeMaterial(color) {
  return new THREE.MeshStandardMaterial({
    color,
    roughness: 0.95,
    metalness: 0.0,
    flatShading: true,
  })
}

function readDebugFlag(name) {
  if (typeof globalThis?.location?.search !== 'string') return false
  const params = new URLSearchParams(globalThis.location.search)
  const raw = params.get(name)
  if (raw == null) return false
  const normalized = raw.trim().toLowerCase()
  return normalized === '' || normalized === '1' || normalized === 'true' || normalized === 'yes' || normalized === 'on'
}

function resolveColliderShape(entity) {
  if (typeof entity?.shape === 'string' && entity.shape.length > 0) {
    return entity.shape
  }

  const primitive = typeof entity?.render?.primitive === 'string'
    ? entity.render.primitive.toLowerCase()
    : ''
  if (primitive === 'sphere' || primitive === 'ball') return 'Ball'
  if (primitive === 'cylinder') return 'Cylinder'
  if (primitive === 'wedge') return 'Wedge'

  const role = typeof entity?.render?.role === 'string' ? entity.render.role : ''
  if (role === 'Ring') return 'Ring'
  return 'Block'
}

function createWedgeGeometry(size) {
  const hx = size[0] * 0.5
  const hy = size[1] * 0.5
  const hz = size[2] * 0.5
  const vertices = new Float32Array([
    -hx, -hy, -hz,
    hx, -hy, -hz,
    -hx, -hy, hz,
    hx, -hy, hz,
    -hx, hy, -hz,
    -hx, hy, hz,
  ])
  const indices = [
    0, 1, 2,
    1, 3, 2,
    0, 4, 1,
    2, 3, 5,
    0, 2, 4,
    2, 5, 4,
    1, 4, 3,
    3, 4, 5,
  ]
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  return geometry
}

function buildRingSegmentSpecs(size) {
  const outerRadius = Math.min(size[0], size[2]) * 0.5
  const tubeRadius = Math.max(Math.min(size[1] * 0.5, outerRadius * 0.45), 0.05)
  const majorRadius = Math.max(outerRadius - tubeRadius, 0.05)
  const segments = 12
  const segmentLength = Math.max(2 * majorRadius * Math.tan(Math.PI / segments), tubeRadius * 1.5) * 1.08
  const segmentSize = [segmentLength, tubeRadius * 2, tubeRadius * 2]
  const out = []
  for (let index = 0; index < segments; index += 1) {
    const angle = (index / segments) * Math.PI * 2
    out.push({
      position: [Math.cos(angle) * majorRadius, 0, Math.sin(angle) * majorRadius],
      rotationY: -(angle + Math.PI / 2),
      size: segmentSize,
    })
  }
  return out
}

function addColliderDebugPrimitive(parent, geometry, position = [0, 0, 0], quaternion = null) {
  const fill = new THREE.Mesh(geometry, COLLIDER_DEBUG_FILL_MATERIAL)
  fill.renderOrder = 999
  fill.position.set(position[0], position[1], position[2])
  if (quaternion) fill.quaternion.copy(quaternion)
  parent.add(fill)

  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), COLLIDER_DEBUG_LINE_MATERIAL)
  edges.renderOrder = 1000
  edges.position.copy(fill.position)
  if (quaternion) edges.quaternion.copy(quaternion)
  parent.add(edges)
}

function buildColliderDebugKey(entity) {
  const size = Array.isArray(entity?.size) && entity.size.length >= 3 ? entity.size : null
  if (!size) return 'none'
  const shape = resolveColliderShape(entity)
  return `${shape}:${size.map((value) => Number(value).toFixed(3)).join(',')}`
}

function createColliderDebugVisual(entity) {
  const size = Array.isArray(entity?.size) && entity.size.length >= 3 ? entity.size : null
  if (!size) return null

  const shape = resolveColliderShape(entity)
  const group = new THREE.Group()
  group.userData.colliderDebugKey = buildColliderDebugKey(entity)

  if (shape === 'Ball') {
    addColliderDebugPrimitive(group, new THREE.SphereGeometry(size[0] * 0.5, 18, 12))
    return group
  }

  if (shape === 'Cylinder') {
    addColliderDebugPrimitive(group, new THREE.CylinderGeometry(size[0] * 0.5, size[0] * 0.5, size[1], 18, 1, false))
    return group
  }

  if (shape === 'Wedge') {
    addColliderDebugPrimitive(group, createWedgeGeometry(size))
    return group
  }

  if (shape === 'Ring') {
    for (const segment of buildRingSegmentSpecs(size)) {
      const rotation = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), segment.rotationY)
      addColliderDebugPrimitive(
        group,
        new THREE.BoxGeometry(segment.size[0], segment.size[1], segment.size[2]),
        segment.position,
        rotation,
      )
    }
    return group
  }

  addColliderDebugPrimitive(group, new THREE.BoxGeometry(size[0], size[1], size[2]))
  return group
}

function applyColorToMeshes(obj, colorHex) {
  obj.traverse((child) => {
    if (child.isMesh && child.material && child.userData?.preserveColor !== true) {
      child.material.color.setHex(colorHex)
    }
  })
}

function applyEntityAppearance(obj, entity) {
  if (!obj?.userData) return

  if (obj.userData.dynamicRole === 'Rock' && obj.material) {
    obj.material.color.copy(resolveEntityColor(entity))
  }

  if (obj.userData.dynamicRole === 'PickupObject' && obj.material) {
    obj.material.color.setHex(resolveEntityColorHex(entity))
  }

  if ((obj.userData.dynamicRole === 'Ball' || obj.userData.dynamicRole === 'Ring') && obj.userData.isStyledCarryable) {
    applyColorToMeshes(obj, resolveEntityColorHex(entity))
  }
}

function buildSky(scene) {
  const skyMat = new THREE.ShaderMaterial({
    uniforms: {
      topColor: { value: new THREE.Color(0x87ceeb) },
      bottomColor: { value: new THREE.Color(0xffecd2) },
    },
    vertexShader: `
      varying vec3 vWP;
      void main(){
        vWP = (modelMatrix * vec4(position, 1.0)).xyz;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      uniform vec3 topColor, bottomColor;
      varying vec3 vWP;
      void main(){
        float h = normalize(vWP).y;
        gl_FragColor = vec4(mix(bottomColor, topColor, max(h, 0.0)), 1.0);
      }
    `,
    side: THREE.BackSide,
    depthWrite: false,
  })
  scene.add(new THREE.Mesh(new THREE.SphereGeometry(1500, 32, 32), skyMat))
}

function buildClouds(scene) {
  const cloudList = []
  const cloudMat = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    transparent: true,
    opacity: 0.8,
    roughness: 1,
  })

  for (let i = 0; i < 20; i++) {
    const cg = new THREE.Group()
    for (let j = 0; j < 3 + Math.floor(Math.random() * 4); j++) {
      const p = new THREE.Mesh(new THREE.SphereGeometry(6 + Math.random() * 10, 8, 8), cloudMat)
      p.position.set(j * 8 - 16, Math.random() * 5, Math.random() * 6 - 3)
      p.scale.y = 0.6
      cg.add(p)
    }
    cg.position.set(Math.random() * 500 - 250, 50 + Math.random() * 50, Math.random() * 300 - 150)
    scene.add(cg)
    cloudList.push({ mesh: cg, speed: 0.5 + Math.random() * 1.5 })
  }

  return cloudList
}

function updateClouds(clouds, dt) {
  for (const c of clouds) {
    c.mesh.position.x += c.speed * dt
    if (c.mesh.position.x > 250) c.mesh.position.x = -250
  }
}

function nameColor(name) {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return new THREE.Color().setHSL((h % 360) / 360, 0.55, 0.55)
}

// Beach looks: the Beach bridge writes static/tints.json ({players: {name: {preset, hair, eyes,
// skin, outfit, trim, accessory, face}}, guest_face}), so each character is its participant's chibi
// in their own colors, wearing their own 2D face. Guests and players without a look get a plain
// chibi in a color picked from their name, with the Beach's plain guest face.
// Read from this same server, never pushed.
let tints = {}
let guestFace = null
let tintsVersion = 0
let tintTimer = null

async function refreshTints() {
  let next = {}
  try {
    const url = new URL('static/tints.json', document.baseURI)
    url.searchParams.set('t', String(Date.now()))
    const r = await fetch(url, { cache: 'no-store' })
    const data = r.ok ? await r.json() : {}
    next = data.players || {}
    guestFace = data.guest_face || null
  } catch (_) {
    next = {}
  }
  if (JSON.stringify(next) !== JSON.stringify(tints)) {
    tints = next
    tintsVersion++
  }
}

function startTints() {
  if (tintTimer) return
  refreshTints()
  tintTimer = setInterval(refreshTints, 10000)
}

function lookFor(name) {
  return tints[name] || guestLook('#' + nameColor(name).getHexString(), guestFace)
}

// Build (or rebuild) a player's chibi and name label when their name or look changes.
function syncPlayer(obj, name, size) {
  const u = obj.userData
  if (u.playerName === name && u.tintsVersion === tintsVersion) return
  u.tintsVersion = tintsVersion
  const look = lookFor(name)
  const lookKey = JSON.stringify(look)
  if (u.lookKey !== lookKey) {
    if (u.chibi) {
      obj.remove(u.chibi)
      disposeChibi(u.chibi)                   // its merged shapes; the colors are shared
    }
    u.chibi = buildChibi(look)
    obj.add(u.chibi)
    u.lookKey = lookKey
  }
  if (u.playerName !== name) {
    if (u.label) {
      obj.remove(u.label)
      u.label.material.map.dispose()
      u.label.material.dispose()
    }
    u.label = makeLabelSprite(name)
    u.label.position.set(0, size[1] / 2 + 0.9, 0)
    obj.add(u.label)
    u.playerName = name
  }
}

// Who's watching, written above the watch spot: "Watching" and up to five names.
function makeWatchSprite(names) {
  const shown = names.slice(0, 5)
  if (names.length > 5) shown[4] = '+' + (names.length - 4) + ' more'
  const canvas = document.createElement('canvas')
  canvas.width = 320
  canvas.height = 56 + 40 * Math.max(1, shown.length)
  const g = canvas.getContext('2d')
  g.fillStyle = '#b02626'
  g.fillRect(0, 0, canvas.width, canvas.height)
  g.strokeStyle = '#ffffff'
  g.lineWidth = 6
  g.strokeRect(3, 3, canvas.width - 6, canvas.height - 6)
  g.fillStyle = '#ffffff'
  g.textAlign = 'center'
  g.textBaseline = 'middle'
  g.font = 'bold 30px sans-serif'
  g.fillText('Watching', 160, 30)
  g.font = 'bold 30px sans-serif'
  shown.forEach((n, i) => g.fillText(n.slice(0, 18), 160, 76 + 40 * i))
  if (!shown.length) { g.font = 'italic 26px sans-serif'; g.fillText('nobody', 160, 76) }
  const map = new THREE.CanvasTexture(canvas)
  map.colorSpace = THREE.SRGBColorSpace
  // Not lit or tone-mapped: the board reads the same in any light.
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map, depthTest: false, toneMapped: false }))
  sprite.scale.set(6, 6 * canvas.height / canvas.width, 1)
  return sprite
}

function syncWatchSign(obj, text) {
  const u = obj.userData
  if (u.watchText === text) return
  if (u.label) {
    obj.remove(u.label)
    u.label.material.map.dispose()
    u.label.material.dispose()
  }
  const names = text ? text.split(', ').filter(Boolean) : []
  u.label = makeWatchSprite(names)
  u.label.position.set(0, 1.2 + u.label.scale.y / 2, 0)
  obj.add(u.label)
  u.watchText = text
}

function makeLabelSprite(text) {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 64
  const g = canvas.getContext('2d')
  g.fillStyle = 'rgba(0,0,0,0.45)'
  g.fillRect(0, 8, 256, 48)
  g.fillStyle = '#ffffff'
  g.font = 'bold 30px sans-serif'
  g.textAlign = 'center'
  g.textBaseline = 'middle'
  g.fillText(text.slice(0, 16), 128, 32)
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), depthTest: false }))
  sprite.scale.set(4, 1, 1)
  return sprite
}

function createEntityVisual(entity) {
  const role = (entity.render && entity.render.role) || entity.name || ''
  const size = entity.size || [1, 1, 1]
  const modelUrl = resolveEntityModelUrl(entity)
  const color = resolveEntityColorHex(entity)

  if (modelUrl) {
    const root = new THREE.Group()
    root.userData.isModelEntity = true
    root.userData.modelUrl = modelUrl
    const fallback = new THREE.Mesh(
      new THREE.CapsuleGeometry(0.35, 0.5, 8, 16),
      new THREE.MeshStandardMaterial({ color: 0xffa07a, roughness: 0.5, metalness: 0.05 }),
    )
    fallback.castShadow = true
    fallback.receiveShadow = true
    const scale = (size[1] || 5) / 1.3
    fallback.scale.setScalar(scale)
    root.add(fallback)
    return root
  }

  if (role === 'Ocean') {
    const geometry = new THREE.PlaneGeometry(size[0], size[2])
    // Bake rotation into geometry; per-frame updateScene resets object quaternion
    // when entity rotation is identity, which would otherwise flip the plane vertical.
    geometry.rotateX(-Math.PI / 2)
    const mesh = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({
        color: 0x4ab0d6,
        transparent: true,
        opacity: 0.72,
        roughness: 0.08,
        metalness: 0.18,
      }),
    )
    mesh.receiveShadow = true
    return mesh
  }

  if (role === 'Ground') {
    const group = new THREE.Group()
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(size[0], size[1], size[2]),
      new THREE.MeshStandardMaterial({ color: 0x55efC4, roughness: 0.5, metalness: 0.2 }),
    )
    mesh.receiveShadow = true
    mesh.castShadow = true
    group.add(mesh)
    return group
  }

  if (role === 'Mesa') {
    const group = new THREE.Group()
    const w = size[0], h = size[1], d = size[2]

    const layers = [
      { frac: 0.0,  hFrac: 0.40, color: 0x8b6940 },
      { frac: 0.40, hFrac: 0.40, color: 0xa57d50 },
      { frac: 0.80, hFrac: 0.20, color: 0x55cfb0 },
    ]

    for (const layer of layers) {
      const lh = h * layer.hFrac
      const ly = -h / 2 + h * layer.frac + lh / 2
      const mesh = new THREE.Mesh(
        new THREE.BoxGeometry(w, lh, d),
        new THREE.MeshStandardMaterial({ color: layer.color, roughness: 0.9, metalness: 0.0 }),
      )
      mesh.position.y = ly
      mesh.castShadow = true
      mesh.receiveShadow = true
      group.add(mesh)
    }

    return group
  }

  if (role === 'Rock') {
    const mesh = new THREE.Mesh(
      new THREE.DodecahedronGeometry(Math.max(size[0], size[1], size[2]) / 2, 0),
      createRockLikeMaterial(resolveEntityColor(entity)),
    )
    mesh.castShadow = true
    mesh.receiveShadow = true
    mesh.userData.dynamicRole = 'Rock'
    return mesh
  }

  if (role === 'Plank') {
    const group = new THREE.Group()

    const body = new THREE.Mesh(
      new THREE.BoxGeometry(size[0], size[1], size[2]),
      new THREE.MeshStandardMaterial({ color: 0x9c6e48, roughness: 0.92, metalness: 0.0 }),
    )
    body.castShadow = true
    body.receiveShadow = true
    group.add(body)

    const slatOffsets = [-0.28, 0, 0.28]
    for (const zFrac of slatOffsets) {
      const groove = new THREE.Mesh(
        new THREE.BoxGeometry(size[0] * 0.96, size[1] * 0.12, size[2] * 0.08),
        new THREE.MeshStandardMaterial({ color: 0x6f4a2c, roughness: 1.0, metalness: 0.0 }),
      )
      groove.position.set(0, size[1] * 0.18, size[2] * zFrac)
      groove.castShadow = true
      groove.receiveShadow = true
      groove.userData.preserveColor = true
      group.add(groove)
    }

    return group
  }

  if (role === 'Ring') {
    const group = new THREE.Group()
    const outerRadius = Math.min(size[0], size[2]) * 0.5
    const tubeRadius = Math.max(Math.min(size[1] * 0.5, outerRadius * 0.45), 0.05)
    const ringRadius = Math.max(outerRadius - tubeRadius, 0.05)

    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(ringRadius, tubeRadius, 18, 40),
      new THREE.MeshStandardMaterial({ color, roughness: 0.82, metalness: 0.12 }),
    )
    ring.rotation.x = Math.PI / 2
    ring.castShadow = true
    ring.receiveShadow = true
    group.add(ring)
    group.userData.dynamicRole = 'Ring'
    group.userData.isStyledCarryable = true
    return group
  }

  if (role === 'PickupObject') {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(size[0], size[1], size[2]),
      createRockLikeMaterial(resolveEntityColor(entity)),
    )
    mesh.castShadow = true
    mesh.receiveShadow = true
    mesh.userData.dynamicRole = 'PickupObject'
    return mesh
  }

  const attrs = entity.attributes || {}

  // The lighthouse: a white tower with red bands, and its lamp (lit, so it reads at any time of day).
  if (role === 'Lighthouse') {
    const group = new THREE.Group()
    const r = size[0] / 2
    const h = size[1]
    const bands = 6
    for (let i = 0; i < bands; i++) {
      const band = new THREE.Mesh(
        new THREE.CylinderGeometry(r * (1 - 0.06 * (i + 1) / bands), r * (1 - 0.06 * i / bands), h / bands, 32),
        new THREE.MeshStandardMaterial({ color: i % 2 ? 0xd8483a : 0xf5f2ec, roughness: 0.7 }),
      )
      band.position.y = -h / 2 + h / bands * (i + 0.5)
      band.castShadow = true
      band.receiveShadow = true
      group.add(band)
    }
    return group
  }
  if (role === 'LighthouseLamp') {
    return new THREE.Mesh(
      new THREE.CylinderGeometry(size[0] / 2, size[0] / 2, size[1], 24),
      new THREE.MeshStandardMaterial({ color: 0xffd65a, emissive: 0xffc23a, emissiveIntensity: 0.9, roughness: 0.3 }),
    )
  }
  // A signpost board: wood, with its area's name above it (a label that always faces you).
  if (role === 'SignBoard') {
    const group = new THREE.Group()
    const board = new THREE.Mesh(
      new THREE.BoxGeometry(size[0], size[1], size[2]),
      new THREE.MeshStandardMaterial({ color: 0xecdab0, roughness: 0.85 }),
    )
    board.castShadow = true
    group.add(board)
    const label = makeLabelSprite(String(attrs.SignText || ''))
    label.position.y = size[1] / 2 + 0.35
    label.scale.set(2.6, 0.65, 1)
    group.add(label)
    return group
  }

  // The watch spot's board: the names of whoever is watching, above the lifeguard chair.
  if (role === 'WatchSign') {
    const group = new THREE.Group()
    const board = new THREE.Mesh(
      new THREE.BoxGeometry(size[0], size[1], size[2]),
      new THREE.MeshStandardMaterial({ color: 0xfff4dc, roughness: 0.8 }),
    )
    board.castShadow = true
    group.add(board)
    group.userData.isWatchSign = true
    return group
  }

  if (attrs.PlayerName) {
    const group = new THREE.Group()
    group.userData.isPlayer = true
    syncPlayer(group, String(attrs.PlayerName), size)
    startTints()
    return group
  }

  if (role === 'Sand' || role === 'SeaFloor') {
    // The island's rounded corners and bumps are upright cylinders; the shallows read as water.
    const round = entity.render && entity.render.primitive === 'cylinder'
    const mesh = new THREE.Mesh(
      round ? new THREE.CylinderGeometry(size[0] / 2, size[0] / 2, size[1], 48)
        : new THREE.BoxGeometry(size[0], size[1], size[2]),
      new THREE.MeshStandardMaterial({ color: role === 'Sand' ? 0xecd6a0 : 0x6fbfd2, roughness: 0.95 }),
    )
    mesh.receiveShadow = true
    return mesh
  }

  // The Sand Gardens: the box's smooth sand, its frame, and the grooves (many: no shadows, cheap material).
  if (role === 'Groove' || role === 'GardenSand' || role === 'GardenFrame') {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(size[0], size[1], size[2]),
      new THREE.MeshLambertMaterial({ color: role === 'Groove' ? 0xb8955c : role === 'GardenSand' ? 0xf2e2b8 : 0x966c46 }),
    )
    mesh.receiveShadow = role !== 'Groove'
    return mesh
  }

  if (role === 'GoalPost') {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(size[0], size[1], size[2]),
      new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.4 }),
    )
    mesh.castShadow = true
    return mesh
  }

  if (role === 'PlotMarker') {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(size[0], size[1], size[2]),
      new THREE.MeshStandardMaterial({ color: 0x78aadc, transparent: true, opacity: 0.45, roughness: 0.9 }),
    )
    mesh.receiveShadow = true
    return mesh
  }

  if (role === 'Ball') {
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(size[0] / 2, 24, 18),
      new THREE.MeshStandardMaterial({ color, roughness: 0.45 }),
    )
    mesh.castShadow = true
    return mesh
  }

  if (role === 'SandPiece') {
    if (attrs.PieceKind === 'flag') {
      const group = new THREE.Group()
      const pole = new THREE.Mesh(
        new THREE.BoxGeometry(size[0], size[1], size[2]),
        new THREE.MeshStandardMaterial({ color: 0xd9c9a0, roughness: 0.9 }),
      )
      const cloth = new THREE.Mesh(
        new THREE.BoxGeometry(0.7, 0.45, 0.04),
        new THREE.MeshStandardMaterial({ color: 0xdc3c3c, roughness: 0.7 }),
      )
      cloth.position.set(0.35 + size[0] / 2, size[1] / 2 - 0.25, 0)
      group.add(pole)
      group.add(cloth)
      return group
    }
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(size[0], size[1], size[2]),
      createRockLikeMaterial(resolveEntityColor(entity)),
    )
    mesh.castShadow = true
    mesh.receiveShadow = true
    return mesh
  }

  // Default: box with entity color
  let geometry
  const primitive = entity.render && entity.render.primitive
  if (primitive === 'cylinder') geometry = new THREE.CylinderGeometry(size[0] / 2, size[0] / 2, size[1], 16)
  else if (primitive === 'sphere') geometry = new THREE.SphereGeometry(size[0] / 2, 16, 16)
  else geometry = new THREE.BoxGeometry(size[0], size[1], size[2])

  const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color, roughness: 0.5, metalness: 0.2 }))
  mesh.castShadow = true
  mesh.receiveShadow = true
  return mesh
}

// PLAYING WITH THE MOUSE (10-18). People who choose Play get a character but, until now, no way to move
// it. The Beach page that frames this viewer passes the character's session in a message (the same
// session it put in this viewer's address; the engine page takes that out of reach of the renderer).
//   click the sand (or a step, the pier, the dune)  -> your character walks there
//   click or right-click a person                   -> the camera follows them; again, or Esc, to stop
//   Space                                            -> jump (the dune's ledges)
//   D / R / 1-8 (in the Sand Gardens)               -> draw in the nearest box, rake it, draw a shape
// A drag still turns the camera: only a short, still click counts.
function createPlayControls(ctx, camera, scene, entityObjects) {
  const canvas = ctx.canvas
  const base = window.location.pathname.replace(/\/[^/]*$/, '')
  let session = null
  const raycaster = new THREE.Raycaster()
  const ndc = new THREE.Vector2()
  let down = null
  let marker = null
  let markerUntil = 0

  function onMessage (ev) {
    if (ev.source !== window.parent || !ev.data || ev.data.type !== 'beach-session') return
    session = typeof ev.data.session === 'string' && ev.data.session ? ev.data.session : null
  }

  async function send (type, data) {
    if (!session) return false
    try {
      const r = await fetch(base + '/input', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Session': session },
        body: JSON.stringify({ type, data: data || {} }),
      })
      return r.ok
    } catch (_) { return false }
  }

  function replay () { return ctx.runtime?.internal?.get ? ctx.runtime.internal.get('replay') : null }
  // People are followed by their player id (the engine's list may name them differently from the
  // Beach name on their label): the player whose character is this entity.
  let players = []
  function follow (entityId) {
    const api = replay()
    const p = players.find(x => x && x.root_part_id === entityId)
    if (!api || !p || p.id == null) return
    const id = String(p.id)
    const now = api.getSelectedPlayerId ? api.getSelectedPlayerId() : null
    if (now === id) api.clearSelectedPlayer ? api.clearSelectedPlayer() : api.selectPlayer(null)
    else api.selectPlayer(id)
  }
  function unfollow () {
    const api = replay()
    if (api) api.clearSelectedPlayer ? api.clearSelectedPlayer() : api.selectPlayer(null)
  }

  // What's under the pointer: a person (their name), or a spot to walk to.
  function pick (ev) {
    const rect = canvas.getBoundingClientRect()
    ndc.set(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1)
    raycaster.setFromCamera(ndc, camera)
    raycaster.camera = camera
    const targets = [...entityObjects.values()]
    for (const hit of raycaster.intersectObjects(targets, true)) {
      if (hit.object.isSprite || hit.point.y > 40) continue
      let o = hit.object
      while (o && !(o.userData && o.userData.isPlayer)) o = o.parent
      if (o) return { person: o.userData.entityId }
      if (hit.object.material && hit.object.material.transparent && hit.object.material.opacity < 0.05) continue
      // Chibis are small: a click on the sand right by someone counts as clicking them.
      for (const obj of entityObjects.values()) {
        if (!obj.userData.isPlayer) continue
        if (Math.hypot(obj.position.x - hit.point.x, obj.position.z - hit.point.z) < 1.6) return { person: obj.userData.entityId }
      }
      return { spot: hit.point }
    }
    return null
  }

  function showMarker (p) {
    if (!marker) {
      marker = new THREE.Mesh(new THREE.RingGeometry(0.5, 0.8, 24), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85, side: THREE.DoubleSide }))
      marker.rotation.x = -Math.PI / 2
      scene.add(marker)
    }
    marker.position.set(p.x, p.y + 0.08, p.z)
    marker.visible = true
    markerUntil = performance.now() + 1500
    setTimeout(() => { if (marker && performance.now() >= markerUntil) marker.visible = false }, 1600)
  }

  function onDown (ev) { down = { x: ev.clientX, y: ev.clientY, t: performance.now(), button: ev.button } }
  function onUp (ev) {
    const d = down
    down = null
    if (!d || ev.button !== d.button) return
    if (Math.hypot(ev.clientX - d.x, ev.clientY - d.y) > 6 || performance.now() - d.t > 450) return   // a drag
    const what = pick(ev)
    if (!what) return
    if (what.person != null) { follow(what.person); return }
    if (d.button !== 0 || !session) return
    const p = what.spot
    showMarker(p)
    void send('MoveTo', { position: [p.x, p.y, p.z] })
  }
  function onContext (ev) {
    const what = pick(ev)
    if (what && what.person != null) ev.preventDefault()
  }
  function onKey (ev) {
    const t = ev.target
    if (t instanceof HTMLElement && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
    if (ev.code === 'Space' && session) { ev.preventDefault(); void send('Jump') }
    else if (session && (ev.key === 'd' || ev.key === 'D')) void send('Draw', { toggle: true })
    else if (session && (ev.key === 'r' || ev.key === 'R')) void send('Rake')
    else if (session && /^[1-8]$/.test(ev.key)) {
      const shapes = ['circle', 'square', 'triangle', 'star', 'heart', 'spiral', 'wave', 'zigzag']
      void send('Draw', { shape: shapes[Number(ev.key) - 1] })
    }
    else if (ev.key === 'Escape') unfollow()
  }

  window.addEventListener('message', onMessage)
  canvas.addEventListener('pointerdown', onDown)
  canvas.addEventListener('pointerup', onUp)
  canvas.addEventListener('contextmenu', onContext)
  window.addEventListener('keydown', onKey)
  // Ask the page for the session (it also sends one when this viewer loads).
  try { if (window.parent !== window) window.parent.postMessage({ type: 'beach-session-please' }, '*') } catch (_) {}
  return {
    setPlayers (list) { players = Array.isArray(list) ? list : [] },
    dispose () {
      window.removeEventListener('message', onMessage)
      canvas.removeEventListener('pointerdown', onDown)
      canvas.removeEventListener('pointerup', onUp)
      canvas.removeEventListener('contextmenu', onContext)
      window.removeEventListener('keydown', onKey)
      if (marker) scene.remove(marker)
    },
  }
}

export function createRenderer(ctx) {
  const scene = new THREE.Scene()
  const captureConfig = globalThis.__mesaCaptureConfig && typeof globalThis.__mesaCaptureConfig === 'object'
    ? globalThis.__mesaCaptureConfig
    : {}
  const debugCollidersEnabled = Boolean(captureConfig.debugColliders) || readDebugFlag('debugColliders') || readDebugFlag('debugCollider')

  const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 3000)

  const renderer = new THREE.WebGLRenderer({ canvas: ctx.canvas, antialias: true })
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFSoftShadowMap
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.2
  renderer.outputColorSpace = THREE.SRGBColorSpace

  // Lights (matching fall-guys)
  scene.add(new THREE.AmbientLight(0xffffff, 0.6))
  scene.add(new THREE.HemisphereLight(0x87ceeb, 0x98fb98, 0.4))

  const dirLight = new THREE.DirectionalLight(0xffffff, 1.2)
  dirLight.position.set(30, 50, 20)
  dirLight.castShadow = true
  dirLight.shadow.mapSize.set(2048, 2048)
  dirLight.shadow.camera.left = -80
  dirLight.shadow.camera.right = 80
  dirLight.shadow.camera.top = 80
  dirLight.shadow.camera.bottom = -80
  dirLight.shadow.camera.near = 1
  dirLight.shadow.camera.far = 200
  dirLight.shadow.bias = -0.00005
  scene.add(dirLight)
  scene.add(dirLight.target)

  // Sky and clouds
  buildSky(scene)
  const clouds = buildClouds(scene)

  const interpolationDelayMs = Number.isFinite(captureConfig.interpolationDelayMs)
    ? Math.max(0, Number(captureConfig.interpolationDelayMs))
    : 100
  const followPositionSmoothing = Number.isFinite(captureConfig.followPositionSmoothing)
    ? Math.max(0, Number(captureConfig.followPositionSmoothing))
    : 10
  const followRotationSmoothing = Number.isFinite(captureConfig.followRotationSmoothing)
    ? Math.max(0, Number(captureConfig.followRotationSmoothing))
    : 14

  const stateBuffer = ctx.runtime.state.createSnapshotBuffer({ maxSnapshots: 8, interpolationDelayMs })
  const cameraModes = ctx.runtime.three.createCameraModeController(THREE, camera, {
    canvas: ctx.canvas,
    stateBuffer,
    debugCamera: false,
    follow: {
      followDistance: 20,
      followHeight: 6,
      shoulderOffset: 0,
      positionSmoothing: followPositionSmoothing,
      rotationSmoothing: followRotationSmoothing,
    },
    spectatorOffset: new THREE.Vector3(0, 18, -18),
    spectatorBoundsPadding: 8,
  })
  if (cameraModes?.api && ctx.runtime?.internal?.expose) {
    ctx.runtime.internal.expose('camera', cameraModes.api)
  }
  const entityObjects = new Map()
  const colliderDebugObjects = new Map()
  const controls = createPlayControls(ctx, camera, scene, entityObjects)
  const modelController = ctx.runtime.three.createModelEntityController(THREE, {
    onError(err, meta) {
      ctx.log('warn', 'Model entity load failed', { err: String(err), ...meta })
    },
  })

  // World announcements (goals, falling castles) arrive as "Announce" replicated events.
  const banner = document.createElement('div')
  banner.style.cssText = 'position:absolute;top:16px;left:50%;transform:translateX(-50%);padding:8px 16px;' +
    'border-radius:8px;background:rgba(0,0,0,0.6);color:#fff;font:600 18px sans-serif;display:none;pointer-events:none'
  if (ctx.canvas && ctx.canvas.parentElement) ctx.canvas.parentElement.appendChild(banner)
  let lastAnnounceId = -1
  let bannerUntil = 0
  function updateBanner(obs) {
    const events = (obs && obs.recent_events) || []
    for (const evt of events) {
      if (evt && evt.name === 'Announce' && evt.id > lastAnnounceId) {
        lastAnnounceId = evt.id
        const payload = Array.isArray(evt.payload) ? evt.payload[0] : evt.payload
        if (payload && payload.text) {
          banner.textContent = String(payload.text)
          banner.style.display = 'block'
          bannerUntil = performance.now() + 4000
        }
      }
    }
    if (bannerUntil && performance.now() > bannerUntil) {
      banner.style.display = 'none'
      bannerUntil = 0
    }
  }

  const tmpForward = new THREE.Vector3(0, 0, 1)
  const anchorPos = new THREE.Vector3(0, 4, 0)
  const clock = new THREE.Clock()

  function syncColliderDebug(entity, visible) {
    if (!debugCollidersEnabled) return

    const debugKey = buildColliderDebugKey(entity)
    let debugObj = colliderDebugObjects.get(entity.id)
    if (!debugObj || debugObj.userData.colliderDebugKey !== debugKey) {
      if (debugObj) {
        scene.remove(debugObj)
        colliderDebugObjects.delete(entity.id)
      }
      debugObj = createColliderDebugVisual(entity)
      if (debugObj) {
        colliderDebugObjects.set(entity.id, debugObj)
        scene.add(debugObj)
      }
    }

    if (!debugObj) return
    debugObj.position.set(entity.position[0], entity.position[1], entity.position[2])
    if (entity.rotation) debugObj.quaternion.copy(rotationToQuaternion(entity.rotation))
    else debugObj.quaternion.identity()
    debugObj.visible = visible
  }

  function computeAnchorPosition(obs) {
    let count = 0
    let sumX = 0
    let sumY = 0
    let sumZ = 0
    const pushPos = (pos) => {
      if (!Array.isArray(pos)) return
      const x = Number(pos[0])
      const y = Number(pos[1])
      const z = Number(pos[2])
      if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return
      sumX += x
      sumY += y
      sumZ += z
      count += 1
    }
    for (const player of obs.players || []) pushPos(player?.position)
    for (const entity of obs.entities || []) pushPos(entity?.position)
    if (count === 0) return anchorPos.clone()
    return new THREE.Vector3(sumX / count, sumY / count, sumZ / count)
  }

  function updateScene(obs, dt) {
    const activeIds = new Set()
    const stateByRootPartId = new Map()
    for (const player of obs.players || []) {
      if (typeof player.root_part_id === 'number' && typeof player.humanoid_state === 'string') {
        stateByRootPartId.set(player.root_part_id, player.humanoid_state)
      }
    }

    // A character whose player has left is never drawn, even if a live update hasn't said it's
    // gone (patches/clawblox-live-removals.patch fixes that in the engine; this guards older ones).
    const present = Array.isArray(obs.players) ? obs.players : []
    const roots = present.every(p => typeof p?.root_part_id === 'number') ? new Set(present.map(p => p.root_part_id)) : null

    for (const entity of obs.entities || []) {
      if (roots && entity.attributes && typeof entity.attributes.PlayerUserId === 'number' && !roots.has(entity.id)) continue
      activeIds.add(entity.id)
      let obj = entityObjects.get(entity.id)
      if (!obj) {
        obj = createEntityVisual(entity)
        obj.userData.entityId = entity.id
        entityObjects.set(entity.id, obj)
        scene.add(obj)
      }

      obj.position.set(entity.position[0], entity.position[1], entity.position[2])
      if (entity.rotation) obj.quaternion.copy(rotationToQuaternion(entity.rotation))
      else obj.quaternion.identity()
      obj.visible = !(entity.render && entity.render.visible === false)
      applyEntityAppearance(obj, entity)
      if (obj.userData.isWatchSign) syncWatchSign(obj, String((entity.attributes || {}).WatchNames || ''))
      if (obj.userData.isPlayer && entity.attributes && entity.attributes.PlayerName) {
        syncPlayer(obj, String(entity.attributes.PlayerName), entity.size || [2, 5, 2])
      }
      syncColliderDebug(entity, obj.visible)

      const prev = obj.userData.prevPos
      let speed = 0
      if (prev) {
        const dx = entity.position[0] - prev[0]
        const dz = entity.position[2] - prev[2]
        speed = Math.sqrt(dx * dx + dz * dz) / Math.max(dt, 0.001)
      }
      obj.userData.prevPos = [entity.position[0], entity.position[1], entity.position[2]]

      if (obj.userData && obj.userData.isModelEntity) {
        const modelUrl = resolveEntityModelUrl(entity)
        if (modelUrl) {
          void modelController.upsert({
            entityId: entity.id,
            root: obj,
            modelUrl,
            size: entity.size || [2, 5, 2],
            yawOffsetDeg: entity.model_yaw_offset_deg,
          })
          modelController.update(entity.id, {
            dt,
            speed,
            humanoidState: stateByRootPartId.get(entity.id) || null,
          })
        }
      }
    }

    for (const [id, obj] of entityObjects.entries()) {
      if (!activeIds.has(id)) {
        scene.remove(obj)
        modelController.remove(id)
        entityObjects.delete(id)
      }
    }
    for (const [id, obj] of colliderDebugObjects.entries()) {
      if (!activeIds.has(id)) {
        scene.remove(obj)
        colliderDebugObjects.delete(id)
      }
    }

    const players = obs.players || []
    controls.setPlayers(players)
    const selectedId = obs && obs.selected_player_id ? String(obs.selected_player_id) : null
    const selectedTarget = selectedId
      ? players.find((player) => String(player?.id || '') === selectedId)
      : null
    const followTarget = selectedTarget || null
    const cameraTarget = followTarget && Array.isArray(followTarget.position)
      ? new THREE.Vector3(followTarget.position[0], followTarget.position[1], followTarget.position[2])
      : computeAnchorPosition(obs)
    const cameraMode = followTarget ? 'follow' : 'spectator'

    anchorPos.copy(cameraTarget)
    cameraModes.update({
      mode: cameraMode,
      targetPosition: cameraTarget,
      targetForward: tmpForward,
      dt,
    })

    dirLight.position.set(cameraTarget.x + 30, 50, cameraTarget.z + 20)
    dirLight.target.position.copy(cameraTarget)
  }

  return {
    onResize({ width, height }) {
      camera.aspect = width / Math.max(1, height)
      camera.updateProjectionMatrix()
      renderer.setSize(width, height, false)
    },

    onState(state) {
      const captureMeta = state && typeof state === 'object' && state.__mesaCaptureMeta && typeof state.__mesaCaptureMeta === 'object'
        ? state.__mesaCaptureMeta
        : null
      const obsState = captureMeta ? { ...state } : state
      if (captureMeta) delete obsState.__mesaCaptureMeta

      if (captureMeta?.resetBuffer) stateBuffer.clear()
      if (captureMeta?.push !== false) {
        const pushNowMs = Number.isFinite(captureMeta?.pushNowMs)
          ? Number(captureMeta.pushNowMs)
          : undefined
        stateBuffer.push(obsState, pushNowMs)
      }
      const renderNowMs = Number.isFinite(captureMeta?.renderNowMs)
        ? Number(captureMeta.renderNowMs)
        : undefined
      const obs = stateBuffer.interpolated(renderNowMs) || obsState
      const dt = Number.isFinite(captureMeta?.dt)
        ? Math.max(0, Number(captureMeta.dt))
        : Math.min(clock.getDelta(), 0.05)
      updateClouds(clouds, dt)
      updateScene(obs, dt)
      updateBanner(obsState)
      renderer.render(scene, camera)
    },

    unmount() {
      controls.dispose()
      if (ctx.runtime?.internal?.remove) ctx.runtime.internal.remove('camera')
      if (cameraModes?.dispose) cameraModes.dispose()
      for (const obj of entityObjects.values()) scene.remove(obj)
      for (const obj of colliderDebugObjects.values()) scene.remove(obj)
      entityObjects.clear()
      colliderDebugObjects.clear()
      modelController.clear()
      renderer.dispose()
      banner.remove()
    },
  }
}
