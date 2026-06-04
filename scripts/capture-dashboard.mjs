/**
 * Capture a clean PNG of the Daily Picks dashboard for the README hero.
 *
 * Run from the repo root:
 *   cd SecureStats
 *   npx -y -p playwright@1.49 node scripts/capture-dashboard.mjs
 *
 * Output: docs/dashboard-screenshot.png
 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const BASE = process.env.BASE_URL ?? 'http://localhost:8080'
const API = `${BASE}/api/v1`
const USERNAME = process.env.DASH_USER ?? 'josephhcoonn'
const PASSWORD = process.env.DASH_PASS ?? 'ChangeMe123!'
const TARGET = process.env.TARGET_PATH ?? '/picks'
const OUT = path.resolve('docs/dashboard-screenshot.png')

async function login() {
  const resp = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USERNAME, password: PASSWORD }),
  })
  if (!resp.ok) throw new Error(`login failed: ${resp.status} ${await resp.text()}`)
  const body = await resp.json()
  return body.access_token
}

async function main() {
  const token = await login()
  console.log(`✓ logged in as ${USERNAME}`)

  const browser = await chromium.launch({ headless: true })
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      deviceScaleFactor: 1,
    })
    const page = await context.newPage()

    // Seed the SPA's auth state via localStorage. Visiting the BASE
    // first is necessary because storage is per-origin.
    await page.goto(BASE, { waitUntil: 'domcontentloaded' })
    await page.evaluate((t) => localStorage.setItem('securestats.token', t), token)

    await page.goto(`${BASE}${TARGET}`, { waitUntil: 'networkidle' })
    // Give the picks board a beat to render the radial bar charts
    await page.waitForTimeout(2500)

    // On /picks, click the History sub-tab so the screenshot shows
    // accumulated accuracy data instead of "no games today" when the
    // current slate hasn't been loaded yet.
    if (process.env.CLICK_HISTORY === '1') {
      const historyBtn = page.locator('button:has-text("History")').first()
      if (await historyBtn.count()) {
        await historyBtn.click()
        await page.waitForTimeout(2500)
      }
    }

    fs.mkdirSync(path.dirname(OUT), { recursive: true })
    await page.screenshot({ path: OUT, fullPage: false })
    console.log(`✓ saved ${OUT}`)
  } finally {
    await browser.close()
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
