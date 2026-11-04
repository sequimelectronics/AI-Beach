// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
// The in-browser projector (the keeper, 11-03: "so we don't have to run 2 different browsers"). It runs on this
// computer only (http://127.0.0.1, which browsers treat as a secure page, so tab sharing works without HTTPS). It shares
// ONE tab's sound through the browser's own picker, turns it into raw 16 kHz mono samples, and hands them to the
// projector program beside it, which does everything else. The page holds no Beach sign-in.
'use strict'
;(() => {
  // The session key comes in the address's # part (never sent to any server), then is tidied away.
  const key = new URLSearchParams(location.hash.slice(1)).get('k') || ''
  history.replaceState(null, '', location.pathname)
  const button = document.getElementById('share')
  const status = document.getElementById('status')
  let stream = null
  let ctx = null
  let queue = []
  let sending = false
  let timer = null
  const say = (t) => { status.textContent = t }

  function post (path, body) {
    return fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Key': key }, body })
  }

  async function flush () {
    if (sending || !queue.length) return
    sending = true
    const parts = queue
    queue = []
    let n = 0
    for (const p of parts) n += p.byteLength
    const out = new Uint8Array(n)
    let at = 0
    for (const p of parts) { out.set(new Uint8Array(p), at); at += p.byteLength }
    try {
      const r = await post('/pcm', out)
      if (r.status === 410) stopAll('The projector has ended the show. You can close this tab.')
    } catch (e) { /* the projector may be busy for a moment; the next flush tries again */ }
    sending = false
  }

  // Pictures (step 2): with the projector's describer on, one picture of the shared tab every few seconds, drawn from
  // its video into a canvas no bigger than 768 px, sent as one JPEG. The projector keeps only the latest, in memory.
  let frameTimer = null
  let frameBusy = false
  function startPictures (videoTrack) {
    const v = document.createElement('video')
    v.muted = true
    v.playsInline = true
    v.srcObject = new MediaStream([videoTrack])
    v.play().catch(() => {})
    const canvas = document.createElement('canvas')
    frameTimer = setInterval(() => {
      if (frameBusy || !v.videoWidth) return
      const scale = Math.min(1, 768 / Math.max(v.videoWidth, v.videoHeight))
      canvas.width = Math.round(v.videoWidth * scale)
      canvas.height = Math.round(v.videoHeight * scale)
      canvas.getContext('2d').drawImage(v, 0, 0, canvas.width, canvas.height)
      frameBusy = true
      canvas.toBlob((blob) => {
        if (!blob) { frameBusy = false; return }
        fetch('/frame', { method: 'POST', headers: { 'Content-Type': 'image/jpeg', 'X-Key': key }, body: blob })
          .catch(() => {})
          .finally(() => { frameBusy = false })
      }, 'image/jpeg', 0.85)
    }, 3000)
  }

  function stopAll (why) {
    if (frameTimer) { clearInterval(frameTimer); frameTimer = null }
    if (timer) { clearInterval(timer); timer = null }
    if (stream) stream.getTracks().forEach(t => t.stop())
    if (ctx) ctx.close()
    stream = null
    ctx = null
    post('/stop', new Uint8Array(0)).catch(() => {})
    button.disabled = true
    say(why || 'Stopped. The show ends; you can close this tab.')
  }

  button.addEventListener('click', async () => {
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({
        video: { displaySurface: 'browser' }, // the picker opens on tabs
        audio: true,
        preferCurrentTab: false,
        selfBrowserSurface: 'exclude', // not this page itself
        systemAudio: 'exclude', // never the whole computer's sound
        surfaceSwitching: 'exclude', // one tab per show: no 'share this tab instead' mid-show (Pharos)
        monitorTypeSurfaces: 'exclude' // no whole screens
      })
    } catch (e) {
      say('Nothing was shared.')
      return
    }
    const video = stream.getVideoTracks()[0]
    const surface = video && video.getSettings().displaySurface
    if (surface && surface !== 'browser') {
      stream.getTracks().forEach(t => t.stop())
      stream = null
      say('Please share a browser tab, not a window or a screen.')
      return
    }
    const audio = stream.getAudioTracks()[0]
    if (!audio) {
      stream.getTracks().forEach(t => t.stop())
      stream = null
      say('That tab was shared without its sound: share it again with "Also share tab audio" on.')
      return
    }
    ctx = new AudioContext({ sampleRate: 16000 })
    await ctx.audioWorklet.addModule('/tabpage-worklet.js')
    const node = new AudioWorkletNode(ctx, 'pcm16')
    node.port.onmessage = (e) => { queue.push(e.data) }
    ctx.createMediaStreamSource(new MediaStream([audio])).connect(node) // not to the speakers: the tab plays itself
    const r = await post('/start', new Uint8Array(0)).catch(() => null)
    if (!r || !r.ok) { stopAll('The projector didn\'t answer. Start the Drive-In Projector again, then this page.'); return }
    timer = setInterval(flush, 500)
    const started = await r.json().catch(() => ({}))
    if (started.pictures) startPictures(video)
    audio.addEventListener('ended', () => stopAll())
    video.addEventListener('ended', () => stopAll())
    button.disabled = true
    say('ON AIR: this tab\'s sound' + (started.pictures ? ' and picture go' : ' goes') +
        ' to the projector. Press Play in it. Stop sharing to end the show.')
  })

  window.addEventListener('pagehide', () => { if (stream) post('/stop', new Uint8Array(0)).catch(() => {}) })
})()
