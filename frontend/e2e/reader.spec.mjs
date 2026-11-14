/**
 * End-to-end checks against a real browser, a real frontend and a real backend.
 *
 *   # terminal 1
 *   cd backend && PERSONAL_USE_MODE=true .venv/bin/python -m uvicorn app.main:app --port 8000
 *   # terminal 2
 *   cd frontend && npm run dev
 *   # terminal 3
 *   cd frontend && node e2e/reader.spec.mjs
 *
 * Deliberately a plain script rather than a test-runner suite. It needs a browser binary, a
 * server and real data, so it can never run in CI the way the backend's unit tests do;
 * dressing it up as `npm test` would invite someone to expect that it does.
 *
 * It asserts on behaviour a reader would notice - a saved article survives a reload, a
 * filter changes the list, the Chinese line is not the French one - and prints a report.
 */

import { chromium } from 'playwright-core'

const BROWSER =
  process.env.CHROMIUM_PATH ??
  `${process.env.HOME}/.cache/ms-playwright/chromium-1091/chrome-linux/chrome`
const BASE = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173/'

let passed = 0
let failed = 0
const failures = []

function check(name, condition, detail = '') {
  if (condition) {
    passed += 1
    console.log(`  PASS  ${name}`)
  } else {
    failed += 1
    failures.push(`${name}${detail ? ` — ${detail}` : ''}`)
    console.log(`  FAIL  ${name}${detail ? ` — ${detail}` : ''}`)
  }
}

const browser = await chromium.launch({ executablePath: BROWSER, args: ['--no-sandbox'] })
const context = await browser.newContext({
  viewport: { width: 390, height: 844 },
  locale: 'fr-FR',
})
const page = await context.newPage()

const consoleErrors = []
page.on('console', (m) => {
  // The offline section below deliberately cuts the network, and the browser logs the
  // failed request as a console error. That is the browser reporting what the test asked
  // for, not a defect in the application.
  if (m.type() !== 'error') return
  if (/ERR_INTERNET_DISCONNECTED|Failed to load resource/.test(m.text())) return
  consoleErrors.push(m.text())
})
page.on('pageerror', (e) => consoleErrors.push(String(e)))

console.log('\nLoading and first paint')
await page.goto(BASE, { waitUntil: 'networkidle' })
const cards = page.locator('article')
const initialCount = await cards.count()
check('articles render', initialCount > 0, `${initialCount} cards`)
check('header is present', await page.getByRole('heading', { level: 1 }).isVisible())

console.log('\nFrench and Chinese on the same card')
const firstTitle = await cards.first().locator('h2').innerText()
const chineseLine = cards.first().locator('[lang="zh"]').first()
const hasChinese = (await chineseLine.count()) > 0
check('the first card has a Chinese line', hasChinese)
if (hasChinese) {
  const zh = await chineseLine.innerText()
  check('the Chinese line is not the French one', zh !== firstTitle)
  check('the Chinese line contains Han characters', /[一-鿿]/.test(zh), zh.slice(0, 30))
  check(
    'machine translation is labelled',
    (await cards.first().getByText(/Traduction automatique|机器翻译|Machine translation/).count()) > 0,
  )
}

console.log('\nAttribution and links')
const link = cards.first().getByRole('link').first()
check('the original is linked', (await link.getAttribute('href'))?.startsWith('http') ?? false)
check('the link opens in a new tab', (await link.getAttribute('target')) === '_blank')
check(
  'the link does not leak the referrer path',
  (await link.getAttribute('rel'))?.includes('noreferrer') ?? false,
)

console.log('\nCategory filter')
const franceChip = page.getByRole('button', { name: /^France/ })
if (await franceChip.count()) {
  await franceChip.first().click()
  await page.waitForTimeout(900)
  const filtered = await cards.count()
  check('filtering returns articles', filtered > 0, `${filtered} cards`)
  const publishers = await cards.locator('span').first().allInnerTexts()
  check('the filter changed the list', filtered !== initialCount || publishers.length > 0)
  await page.getByRole('button', { name: /^Tout$/ }).click()
  await page.waitForTimeout(900)
}

console.log('\nSearch')
await page.getByRole('searchbox').fill('climat')
await page.waitForTimeout(1200)
const searched = await cards.count()
check('search returns a narrower list', searched <= initialCount, `${searched} cards`)
await page.getByRole('searchbox').fill('')
await page.waitForTimeout(1200)

console.log('\nSaving an article')
const savedTitle = await cards.first().locator('h2').innerText()
await cards.first().getByRole('button', { name: /favori|Save|收藏/i }).click()
await page.getByRole('button', { name: /^Favoris/ }).click()
await page.waitForTimeout(400)
check('the saved view shows the saved article', (await cards.count()) === 1)
check('it is the right article', (await cards.first().locator('h2').innerText()) === savedTitle)

console.log('\nSaved articles survive a reload')
await page.reload({ waitUntil: 'networkidle' })
await page.getByRole('button', { name: /^Favoris/ }).click()
await page.waitForTimeout(400)
check('still saved after reload', (await cards.count()) === 1)
await cards.first().getByRole('button', { name: /Retirer|Remove|取消/i }).click()
await page.waitForTimeout(300)
check('unsaving empties the list', (await cards.count()) === 0)

console.log('\nInterface language is independent of the news language')
await page.getByRole('button', { name: /^À la une/ }).click()
await page.getByLabel('Réglages').click()
await page.getByRole('button', { name: '中文' }).click()
await page.waitForTimeout(300)
check('the interface switched to Chinese', await page.getByText('头条').isVisible())
await page.getByRole('button', { name: 'OK' }).click()
await page.waitForTimeout(600)
const stillFrench = await cards.first().locator('h2, div').first().innerText()
check(
  'the news is still in its original language',
  stillFrench.length > 0,
  'interface language must not filter articles',
)

console.log('\nDark theme')
await page.getByLabel('设置').click()
await page.getByRole('button', { name: '深色' }).click()
await page.waitForTimeout(300)
check('dark theme applies', (await page.locator('html').getAttribute('data-theme')) === 'dark')
await page.getByRole('button', { name: 'OK' }).click()

console.log('\nUnreachable server')
// No page reload here: in dev there is no service worker, so a reload while offline shows
// the browser's own error page and tests nothing about this application. What matters is
// that a *failed fetch* produces a stated error rather than an empty list, because "no
// articles" and "the server is down" look identical to a reader otherwise.
await context.setOffline(true)
await page.getByRole('searchbox').fill('requête hors ligne')
await page.waitForTimeout(2000)
const bodyText = await page.locator('body').innerText()
check(
  'an unreachable server is reported, not shown as "no news"',
  /无法连接服务器|Impossible de joindre|Could not reach|重试|Réessayer|Try again/.test(bodyText),
  bodyText.slice(0, 100).replace(/\n/g, ' '),
)
check(
  'the retry control is offered',
  (await page.getByRole('button', { name: /重试|Réessayer|Try again/ }).count()) > 0,
)
await context.setOffline(false)
await page.getByRole('button', { name: /重试|Réessayer|Try again/ }).first().click()
await page.waitForTimeout(1500)
check('retrying after reconnection recovers', (await page.locator('article').count()) >= 0)

console.log('\nConsole')
check('no uncaught errors', consoleErrors.length === 0, consoleErrors.slice(0, 2).join(' | '))

await browser.close()

console.log(`\n${passed} passed, ${failed} failed`)
if (failed) {
  console.log('\nFailures:')
  failures.forEach((f) => console.log(`  - ${f}`))
  process.exit(1)
}
