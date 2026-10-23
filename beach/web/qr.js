// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// A small QR code maker for the keeper page (the keeper, 10-23: getting an invite link from the PC's browser onto
// a phone was "a pain"; now the phone scans it). Byte mode, error correction level M, versions 1-10 (up to 213
// bytes, plenty for an invite link). It draws on a canvas in the page itself: nothing is fetched or sent anywhere.
// Written from the QR specification (ISO/IEC 18004); tests/test_qr.py checks it module for module against the
// Python qrcode package.
'use strict'
;(function (root) {
  // Per version (level M): [error-correction codewords per block, [[block count, data codewords per block], ...]].
  const BLOCKS = [null,
    [10, [[1, 16]]], [16, [[1, 28]]], [26, [[1, 44]]], [18, [[2, 32]]], [24, [[2, 43]]],
    [16, [[4, 27]]], [18, [[4, 31]]], [22, [[2, 38], [2, 39]]], [22, [[3, 36], [2, 37]]], [26, [[4, 43], [1, 44]]]]
  const ALIGN = [null, [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]]

  // Arithmetic in GF(256), polynomial 0x11D.
  const EXP = new Array(512)
  const LOG = new Array(256)
  ;(function () {
    let x = 1
    for (let i = 0; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d }
    for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255]
  })()
  const gmul = (a, b) => (a === 0 || b === 0) ? 0 : EXP[LOG[a] + LOG[b]]

  function generator (n) {
    let g = [1]
    for (let i = 0; i < n; i++) {
      const next = new Array(g.length + 1).fill(0)
      for (let j = 0; j < g.length; j++) { next[j] ^= g[j]; next[j + 1] ^= gmul(g[j], EXP[i]) }
      g = next
    }
    return g
  }

  function ecBytes (data, n) {
    const gen = generator(n)
    const ecc = new Array(n).fill(0)
    for (const b of data) {
      const f = b ^ ecc[0]
      ecc.shift(); ecc.push(0)
      for (let i = 0; i < n; i++) ecc[i] ^= gmul(gen[i + 1], f)
    }
    return ecc
  }

  function utf8 (text) {
    if (typeof TextEncoder !== 'undefined') return Array.from(new TextEncoder().encode(text))
    return Array.from(Buffer.from(text, 'utf8'))   // node, for the tests
  }

  function dataCodewords (version) { return BLOCKS[version][1].reduce((n, [c, d]) => n + c * d, 0) }

  function codewords (bytes, version) {
    const bits = []
    const put = (v, n) => { for (let i = n - 1; i >= 0; i--) bits.push((v >>> i) & 1) }
    put(4, 4)                                   // byte mode
    put(bytes.length, version < 10 ? 8 : 16)
    for (const b of bytes) put(b, 8)
    const limit = dataCodewords(version) * 8
    for (let i = 0; i < 4 && bits.length < limit; i++) bits.push(0)   // terminator
    while (bits.length % 8) bits.push(0)
    const data = []
    for (let i = 0; i < bits.length; i += 8) data.push(parseInt(bits.slice(i, i + 8).join(''), 2))
    for (let i = 0; data.length < limit / 8; i++) data.push(i % 2 ? 0x11 : 0xec)
    // Split into blocks, add error correction, interleave.
    const [ecn, groups] = BLOCKS[version]
    const blocks = []
    let at = 0
    for (const [count, size] of groups) {
      for (let k = 0; k < count; k++) { const d = data.slice(at, at + size); at += size; blocks.push([d, ecBytes(d, ecn)]) }
    }
    const out = []
    const maxD = Math.max(...blocks.map(b => b[0].length))
    for (let i = 0; i < maxD; i++) for (const [d] of blocks) if (i < d.length) out.push(d[i])
    for (let i = 0; i < ecn; i++) for (const [, e] of blocks) out.push(e[i])
    return out
  }

  const MASKS = [
    (i, j) => (i + j) % 2 === 0, (i, j) => i % 2 === 0, (i, j) => j % 3 === 0, (i, j) => (i + j) % 3 === 0,
    (i, j) => (Math.floor(i / 2) + Math.floor(j / 3)) % 2 === 0, (i, j) => (i * j) % 2 + (i * j) % 3 === 0,
    (i, j) => ((i * j) % 2 + (i * j) % 3) % 2 === 0, (i, j) => ((i * j) % 3 + (i + j) % 2) % 2 === 0]

  function bchDigit (d) { let n = 0; while (d) { n++; d >>>= 1 } return n }
  function bch (data, g, shift) {
    let d = data << shift
    while (bchDigit(d) - bchDigit(g) >= 0) d ^= g << (bchDigit(d) - bchDigit(g))
    return (data << shift) | d
  }

  function build (cw, version, mask) {
    const n = version * 4 + 17
    const m = Array.from({ length: n }, () => new Array(n).fill(null))
    const probe = (row, col) => {
      for (let r = -1; r <= 7; r++) {
        for (let c = -1; c <= 7; c++) {
          if (row + r < 0 || row + r >= n || col + c < 0 || col + c >= n) continue
          m[row + r][col + c] = (r >= 0 && r <= 6 && (c === 0 || c === 6)) || (c >= 0 && c <= 6 && (r === 0 || r === 6)) ||
            (r >= 2 && r <= 4 && c >= 2 && c <= 4)
        }
      }
    }
    probe(0, 0); probe(n - 7, 0); probe(0, n - 7)
    for (const row of ALIGN[version]) {
      for (const col of ALIGN[version]) {
        if (m[row][col] !== null) continue
        for (let r = -2; r <= 2; r++) for (let c = -2; c <= 2; c++) m[row + r][col + c] = Math.abs(r) === 2 || Math.abs(c) === 2 || (r === 0 && c === 0)
      }
    }
    for (let r = 8; r < n - 8; r++) if (m[r][6] === null) m[r][6] = r % 2 === 0
    for (let c = 8; c < n - 8; c++) if (m[6][c] === null) m[6][c] = c % 2 === 0
    // Format information: level M (00) and the mask, with its error correction.
    const fmt = bch(mask, 0x537, 10) ^ 0x5412
    for (let i = 0; i < 15; i++) {
      const bit = ((fmt >> i) & 1) === 1
      if (i < 6) m[i][8] = bit; else if (i < 8) m[i + 1][8] = bit; else m[n - 15 + i][8] = bit
      if (i < 8) m[8][n - i - 1] = bit; else if (i < 9) m[8][15 - i] = bit; else m[8][14 - i] = bit
    }
    m[n - 8][8] = true
    if (version >= 7) {
      const v = bch(version, 0x1f25, 12)
      for (let i = 0; i < 18; i++) {
        const bit = ((v >> i) & 1) === 1
        m[Math.floor(i / 3)][i % 3 + n - 11] = bit
        m[i % 3 + n - 11][Math.floor(i / 3)] = bit
      }
    }
    // The data, in the zigzag order, masked.
    const fn = MASKS[mask]
    let inc = -1
    let row = n - 1
    let bitIndex = 7
    let byteIndex = 0
    for (let col = n - 1; col > 0; col -= 2) {
      if (col === 6) col -= 1
      for (;;) {
        for (const c of [col, col - 1]) {
          if (m[row][c] === null) {
            let dark = byteIndex < cw.length && ((cw[byteIndex] >>> bitIndex) & 1) === 1
            if (fn(row, c)) dark = !dark
            m[row][c] = dark
            if (--bitIndex === -1) { byteIndex++; bitIndex = 7 }
          }
        }
        row += inc
        if (row < 0 || row >= n) { row -= inc; inc = -inc; break }
      }
    }
    return m
  }

  // The usual four penalty rules, to pick the mask that reads most easily.
  function penalty (m) {
    const n = m.length
    let p = 0
    for (let pass = 0; pass < 2; pass++) {
      for (let a = 0; a < n; a++) {
        let run = 1
        for (let b = 1; b < n; b++) {
          const cur = pass ? m[b][a] : m[a][b]
          const prev = pass ? m[b - 1][a] : m[a][b - 1]
          if (cur === prev) { run++ } else { if (run >= 5) p += run - 2; run = 1 }
        }
        if (run >= 5) p += run - 2
      }
    }
    for (let r = 0; r < n - 1; r++) {
      for (let c = 0; c < n - 1; c++) {
        const v = m[r][c]
        if (v === m[r][c + 1] && v === m[r + 1][c] && v === m[r + 1][c + 1]) p += 3
      }
    }
    const pat = [true, false, true, true, true, false, true, false, false, false, false]
    const rev = pat.slice().reverse()
    for (let a = 0; a < n; a++) {
      for (let b = 0; b <= n - 11; b++) {
        for (const want of [pat, rev]) {
          if (want.every((w, k) => m[a][b + k] === w)) p += 40
          if (want.every((w, k) => m[b + k][a] === w)) p += 40
        }
      }
    }
    let dark = 0
    for (const r of m) for (const v of r) if (v) dark++
    p += Math.floor(Math.abs(dark * 100 / (n * n) - 50) / 5) * 10
    return p
  }

  function matrix (text, mask) {
    const bytes = utf8(String(text))
    let version = 1
    while (version <= 10 && 4 + (version < 10 ? 8 : 16) + bytes.length * 8 > dataCodewords(version) * 8) version++
    if (version > 10) throw new Error('too long for a QR code here')
    const cw = codewords(bytes, version)
    if (mask !== undefined) return { version, mask, modules: build(cw, version, mask) }
    let best = null
    for (let k = 0; k < 8; k++) {
      const mods = build(cw, version, k)
      const p = penalty(mods)
      if (!best || p < best.p) best = { version, mask: k, modules: mods, p }
    }
    return { version: best.version, mask: best.mask, modules: best.modules }
  }

  // A canvas with the code, dark on white with the quiet zone it needs, whatever the page's theme.
  function canvas (text, scale = 5) {
    const { modules } = matrix(text)
    const n = modules.length
    const q = 4
    const c = document.createElement('canvas')
    c.width = c.height = (n + 2 * q) * scale
    const g = c.getContext('2d')
    g.fillStyle = '#ffffff'
    g.fillRect(0, 0, c.width, c.height)
    g.fillStyle = '#000000'
    for (let r = 0; r < n; r++) for (let k = 0; k < n; k++) if (modules[r][k]) g.fillRect((k + q) * scale, (r + q) * scale, scale, scale)
    return c
  }

  const api = { matrix, canvas }
  if (typeof module !== 'undefined' && module.exports) module.exports = api
  else root.BeachQR = api
})(typeof window !== 'undefined' ? window : globalThis)
