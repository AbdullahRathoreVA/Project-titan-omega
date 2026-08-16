// Capture the REAL Titan Omega UI on a phone-sized viewport.
// Runs against the app booted locally in this container (the public host is
// blocked by session egress policy), so every pixel is the actual product.

import { chromium, devices } from 'playwright';
import fs from 'node:fs';

const OUT = process.env.OUT || '/tmp/claude-0/-home-user-Project-titan-omega/125cb865-0e1b-58b5-9b51-a24a462e7a39/scratchpad/shots';
fs.mkdirSync(OUT, { recursive: true });

const TABS = [
  ['Universe', 'universe'],
  ['Dashboard', 'dashboard'],
  ['Mission', 'mission'],
  ['Clients', 'clients'],
  ['SEO', 'seo'],
  ['Executive', 'executive'],
  ['Voice', 'voice'],
  ['Graph', 'graph'],
  ['AI City', 'city'],
  ['War Room', 'warroom'],
  ['Telegram', 'telegram'],
  ['Job Radar', 'jobs'],
  ['Finance', 'finance'],
  ['CRM', 'crm'],
  ['APIs', 'apis'],
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch({
  args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader', '--disable-dev-shm-usage'],
});

const ctx = await browser.newContext({
  ...devices['iPhone 14 Pro'],
  // The device preset reserves space for browser chrome; we want the full
  // 393x852 logical screen so the shots match a real full-bleed phone frame.
  viewport: { width: 393, height: 852 },
  reducedMotion: 'no-preference',
  colorScheme: 'dark',
});

const page = await ctx.newPage();
const errors = [];
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

console.log('viewport', JSON.stringify(page.viewportSize()));

// `networkidle` never fires: the dashboard polls every 5s and holds an SSE
// stream open. Wait for the document, then give the client render time.
await page.goto('http://127.0.0.1:3000/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await sleep(6000);

// The boot sequence plays on every load. Capture it first — it is the single
// most cinematic thing the product already does — then skip out of it.
await sleep(1800);
await page.screenshot({ path: `${OUT}/00-boot.png` });
await sleep(1500);
await page.screenshot({ path: `${OUT}/01-boot-late.png` });

for (const label of ['SKIP ▸', 'ENTER SILENTLY ▸']) {
  const b = page.getByRole('button', { name: label });
  if (await b.count()) { await b.first().click({ timeout: 5000 }).catch(() => {}); break; }
}
await sleep(2500);

let i = 2;
for (const [label, key] of TABS) {
  const btn = page.getByRole('button', { name: label, exact: true });
  if (!(await btn.count())) { console.log(`MISSING TAB: ${label}`); continue; }
  await btn.first().click({ timeout: 10000 }).catch((e) => console.log(`click fail ${label}: ${e.message}`));
  // 3D views need real frames on the software rasteriser.
  await sleep(['universe', 'city', 'graph', 'warroom'].includes(key) ? 5000 : 2200);
  const n = String(i).padStart(2, '0');
  await page.screenshot({ path: `${OUT}/${n}-${key}.png` });
  // A second frame further down the page, where the panels live.
  await page.evaluate(() => window.scrollTo({ top: 700, behavior: 'instant' }));
  await sleep(900);
  await page.screenshot({ path: `${OUT}/${n}-${key}-scroll.png` });
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await sleep(400);
  console.log(`captured ${label}`);
  i++;
}

// Full-page tall capture of the dashboard — shows the mobile IA fix (revenue
// first, rail collapsed) that the handoff doc measured.
await page.getByRole('button', { name: 'Dashboard', exact: true }).first().click().catch(() => {});
await sleep(2500);
await page.screenshot({ path: `${OUT}/99-dashboard-full.png`, fullPage: true });

const h = await page.evaluate(() => ({
  docH: document.documentElement.scrollHeight,
  bodyW: document.body.scrollWidth,
  vw: window.innerWidth,
}));
console.log('metrics', JSON.stringify(h));
console.log('console errors:', errors.length);
errors.slice(0, 8).forEach((e) => console.log('  ERR', e.slice(0, 160)));

await browser.close();
console.log('DONE');
