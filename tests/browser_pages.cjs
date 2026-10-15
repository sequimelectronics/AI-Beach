// Drives the Beach's pages in a real browser for tests/test_pages_browser.py and prints what it saw
// as JSON. Args: <playwright module dir> <chromium path or ""> <beach url> <token>.
'use strict'
const { chromium } = require(process.argv[2])
const [exe, base, tok] = process.argv.slice(3)

;(async () => {
  const b = await chromium.launch({ ...(exe ? { executablePath: exe } : {}), args: ['--disable-background-networking'] })
  const ctx = await b.newContext({ viewport: { width: 1280, height: 800 } })
  await ctx.addInitScript(t => localStorage.setItem('beach_token', t), tok)
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', e => errors.push(e.message))
  const out = {}

  // The bar: every zone, a pin where you are, your picture opens My look and Sign out.
  await p.goto(base + '/'); await p.waitForSelector('.topbar nav a'); await p.waitForTimeout(500)
  out.bar = await p.$$eval('.topbar nav a', as => as.map(a => ({ text: a.childNodes[0].textContent.trim(), pin: !!a.querySelector('.pin'), sr: (a.querySelector('.sr-only') || {}).textContent || '', href: a.getAttribute('href') })))
  out.menuHiddenAtFirst = await p.$eval('.me-menu', m => m.hidden)
  await p.click('.me-chip')
  out.menu = await p.$$eval('.me-menu [role=menuitem]', ms => ms.map(m => m.textContent.trim()))
  out.menuShown = await p.$eval('.me-menu', m => !m.hidden)

  // SandChat: the target box is grayed out for an action that isn't aimed at anyone.
  await p.goto(base + '/chat?zone=sandchat'); await p.waitForSelector('select[aria-label="Action"] option', { state: 'attached' }); await p.waitForTimeout(800)
  await p.selectOption('select[aria-label="Action"]', 'wave')
  out.targetForWave = await p.$eval('select[aria-label="Aim it at"]', s => s.disabled)
  await p.selectOption('select[aria-label="Action"]', 'greet')
  out.targetForGreet = await p.$eval('select[aria-label="Aim it at"]', s => s.disabled)
  out.bell = await p.$$eval('button', bs => bs.map(x => x.textContent).filter(t => /Bell/.test(t)))

  // A finished table: Leave table, and Leave The Boardwalk.
  await p.goto(base + '/boardwalk?zone=boardwalk&table=1'); await p.waitForSelector('.turn-banner'); await p.waitForTimeout(500)
  out.tableButtons = await p.$$eval('main button, main a.button', bs => bs.map(x => x.textContent.trim()))
  await p.click('text=Leave table'); await p.waitForURL(u => !String(u).includes('table='))
  out.afterLeaveTable = new URL(p.url()).search

  // The world's own page keeps the bar, and offers Play and Watch.
  await p.goto(base + '/world?zone=beachblox'); await p.waitForSelector('.world-buttons button'); await p.waitForTimeout(300)
  out.worldBar = await p.$$eval('.topbar nav a', as => as.length)
  out.worldButtons = await p.$$eval('.world-buttons button', bs => bs.map(x => x.textContent.trim()))

  // My look: the new labels, in pairs.
  await p.goto(base + '/avatar'); await p.waitForSelector('.look-pair'); await p.waitForTimeout(300)
  out.lookPairs = await p.$$eval('.look-pair', ps => ps.map(x => [...x.querySelectorAll('h2')].map(h => h.textContent.trim())))

  out.errors = errors
  console.log(JSON.stringify(out))
  await b.close()
})().catch(e => { console.log(JSON.stringify({ fatal: String(e) })); process.exit(1) })
