// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// Runs in the browser's audio thread: the shared tab's sound (already at 16 kHz, the page's AudioContext rate) mixed
// to mono and turned into 16-bit samples, handed to the page in small pieces.
'use strict'

class Pcm16 extends AudioWorkletProcessor {
  process (inputs) {
    const chans = inputs[0]
    if (chans && chans.length) {
      const n = chans[0].length
      const out = new Int16Array(n)
      for (let i = 0; i < n; i++) {
        let s = 0
        for (let c = 0; c < chans.length; c++) s += chans[c][i]
        s = Math.max(-1, Math.min(1, s / chans.length))
        out[i] = s < 0 ? s * 0x8000 : s * 0x7fff
      }
      this.port.postMessage(out.buffer, [out.buffer])
    }
    return true
  }
}

registerProcessor('pcm16', Pcm16)
