// TITAN Ω — "TRUST THE ZERO" · deterministic frame renderer.
//
// Playwright's real-time video recording proved unusable here: it writes
// variable-rate output, this page drops frames unevenly under software GL, and
// the resulting drift between script time and video time is non-linear, so no
// single speed correction fixes it. Sync markers were lost at exactly the
// re-render boundaries where drift was worst.
//
// So nothing is recorded in real time. The film is rendered frame by frame:
// for frame f the scene is posed at t = f/FPS and screenshotted. Frame N IS
// time N/30, so picture and score cannot drift apart by construction, and a
// re-run reproduces the same file.
//
// The trade: the product's own ambient 3D motion advances in wall-clock time,
// so it reads slightly faster than life. On a 16-second cut that plays as
// energy, and it is the only thing given up for exact timing.
//
//   node marketing/render.mjs vertical|hero <outdir>

import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const MODE = process.argv[2] || 'vertical';
const OUT = process.argv[3] || `/tmp/frames-${MODE}`;
const FPS = 30;

const CFG = {
  vertical: { w: 540, h: 960, dur: 18.0, capPx: 23, dsf: 2 },
  hero: { w: 1280, h: 720, dur: 32.3, capPx: 38, dsf: 1 },
}[MODE];

fs.mkdirSync(OUT, { recursive: true });
for (const f of fs.readdirSync(OUT)) fs.unlinkSync(path.join(OUT, f));

const ease = (x) => 1 - Math.pow(1 - x, 3);                 // out-cubic
const lerp = (a, b, u) => a + (b - a) * Math.max(0, Math.min(1, u));
const ramp = (t, t0, t1) => (t <= t0 ? 0 : t >= t1 ? 1 : (t - t0) / (t1 - t0));

const browser = await chromium.launch({
  args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader', '--disable-dev-shm-usage',
         '--hide-scrollbars', '--mute-audio'],
});
const ctx = await browser.newContext({
  viewport: { width: CFG.w, height: CFG.h },
  deviceScaleFactor: CFG.dsf,
  isMobile: MODE === 'vertical',
  hasTouch: MODE === 'vertical',
  reducedMotion: 'no-preference',
  colorScheme: 'dark',
});
const page = await ctx.newPage();
await page.goto('http://127.0.0.1:3000/', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(4000);

// --- real refusals, fetched from the running backend ------------------------
const proof = await page.evaluate(async () => {
  const j = async (m, u, b) => {
    const r = await fetch(u, b
      ? { method: m, headers: { 'content-type': 'application/json' }, body: JSON.stringify(b) }
      : { method: m });
    return { status: r.status, body: await r.text() };
  };
  const s = JSON.parse((await j('POST', '/api/voice/sessions', {})).body);
  await j('POST', `/api/voice/sessions/${s.id}/state`, { state: 'speaking' });
  await j('POST', `/api/voice/sessions/${s.id}/state`, { state: 'ended' });
  return {
    illegal: await j('POST', `/api/voice/sessions/${s.id}/state`, { state: 'listening' }),
    selfSeo: await j('GET', '/api/self-seo'),
    apis: await j('GET', '/api/apis/stats'),
  };
});
console.log('409  :', proof.illegal.status, JSON.parse(proof.illegal.body).detail.slice(0, 90));
console.log('APIS :', JSON.parse(proof.apis.body).stats.total, 'catalogued,',
            JSON.parse(proof.apis.body).stats.adapters_written, 'registry adapters');

await page.addStyleTag({ content: `
  #tz { position:fixed; inset:0; z-index:2147483000; pointer-events:none; }
  #tz > div { position:fixed; inset:0; }
  #tz-black { background:#000; opacity:0; }
  #tz-flash { background:#dffaff; opacity:0; }
  #tz-vig { opacity:0; background:radial-gradient(ellipse at 50% 47%, transparent 32%, rgba(0,0,0,.85) 100%); }
  #tz-cap { inset:auto 0 ${MODE === 'vertical' ? '11%' : '9%'} 0 !important; text-align:center;
            padding:0 ${MODE === 'vertical' ? '8%' : '12%'};
            font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
            font-size:${CFG.capPx}px; line-height:1.42; color:#eaf6ff; opacity:0;
            text-shadow:0 2px 30px rgba(0,0,0,.98), 0 0 70px rgba(0,0,0,.9); }
  #tz-cap b { color:#22d3ee; font-weight:600; }
  #tz-proof { display:flex; align-items:center; justify-content:center; background:#05070d; opacity:0; }
  #tz-proof .box { width:min(${MODE === 'vertical' ? '86vw' : '1180px'},86vw);
                   border:1px solid #16203a; background:#0a0e1a; border-radius:14px;
                   padding:${MODE === 'vertical' ? '22px 24px' : '38px 44px'};
                   font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
  #tz-proof .req { font-size:${MODE === 'vertical' ? 12 : 19}px; color:#5b708f; letter-spacing:.08em; margin-bottom:${MODE === 'vertical' ? 12 : 20}px; }
  #tz-proof .st { font-size:${MODE === 'vertical' ? 46 : 74}px; font-weight:700; letter-spacing:-.02em; margin-bottom:${MODE === 'vertical' ? 14 : 22}px; }
  #tz-proof .st.refuse { color:#fb7185; }
  #tz-proof .st.honest { color:#fbbf24; }
  #tz-proof .body { font-size:${MODE === 'vertical' ? 16 : 25}px; line-height:1.55; color:#cfe3ff; }
  #tz-proof .body em { color:#22d3ee; font-style:normal; }
  #tz-proof .tag { margin-top:${MODE === 'vertical' ? 16 : 26}px; font-size:${MODE === 'vertical' ? 12 : 18}px;
                   letter-spacing:.2em; color:#34d399; text-transform:uppercase; }
  #tz-end { display:flex; flex-direction:column; gap:${MODE === 'vertical' ? 22 : 34}px;
            align-items:center; justify-content:center; background:#05070d; opacity:0;
            font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
  #tz-end .lock { font-size:${MODE === 'vertical' ? 52 : 104}px; letter-spacing:.30em; color:#fff; text-indent:.30em; }
  #tz-end .lock i { font-style:normal; color:#22d3ee; }
  #tz-end .line { font-size:${MODE === 'vertical' ? 22 : 34}px; color:#7fe9f7; letter-spacing:.20em; opacity:0; }
  #tz-end .url { font-size:${MODE === 'vertical' ? 15 : 24}px; color:#5b708f; letter-spacing:.16em; opacity:0; }
  body { will-change:transform; }
`});

await page.evaluate((p) => {
  const d = document.createElement('div');
  d.id = 'tz';
  d.innerHTML = `<div id="tz-vig"></div>
    <div id="tz-proof"><div class="box"><div class="req"></div><div class="st"></div>
      <div class="body"></div><div class="tag"></div></div></div>
    <div id="tz-cap"></div><div id="tz-flash"></div><div id="tz-black"></div>
    <div id="tz-end"><div class="lock">TITAN <i>Ω</i></div>
      <div class="line">TRUST THE ZERO</div><div class="url">titanomega-ai.com</div></div>`;
  document.documentElement.appendChild(d);
  window.P = p;
  window.$ = (id) => document.getElementById(id);

  // Pose the camera explicitly for this frame. No CSS transition anywhere —
  // every value is computed from t, which is what makes the render repeatable.
  window.pose = (scale, x, y) => {
    document.body.style.transformOrigin =
      `${window.innerWidth / 2}px ${window.scrollY + window.innerHeight / 2}px`;
    document.body.style.transition = 'none';
    document.body.style.transform = `scale(${scale}) translate(${x}px, ${y}px)`;
  };
  window.setCap = (html, op) => {
    const c = window.$('tz-cap');
    if (c.dataset.html !== html) { c.innerHTML = html; c.dataset.html = html; }
    c.style.opacity = String(op);
  };
  window.setProof = (req, status, cls, body, tag, op) => {
    const r = window.$('tz-proof');
    if (r.dataset.k !== req) {
      r.querySelector('.req').textContent = req;
      r.querySelector('.st').textContent = status;
      r.querySelector('.st').className = 'st ' + cls;
      r.querySelector('.body').innerHTML = body;
      r.querySelector('.tag').textContent = tag;
      r.dataset.k = req;
    }
    r.style.opacity = String(op);
  };
  window.tab = (label) => {
    const b = [...document.querySelectorAll('button')].find((n) => n.textContent.trim() === label);
    if (b) b.click();
    return !!b;
  };
  window.centre = (text) => {
    document.body.style.transition = 'none';
    document.body.style.transform = 'none';
    const el = [...document.querySelectorAll('div,section,article')]
      .filter((n) => n.textContent.includes(text))
      .filter((n) => { const h = n.getBoundingClientRect().height; return h > 60 && h < 520; }).pop();
    if (!el) return false;
    const r = el.getBoundingClientRect();
    window.scrollBy({ top: r.top - (window.innerHeight / 2 - r.height / 2), behavior: 'instant' });
    return true;
  };
  // The CHANNELS rail is six CONNECT tiles with no OAuth behind them — the one
  // element on screen promising something the product does not do.
  window.hideRail = () => {
    const l = [...document.querySelectorAll('.hud-label')]
      .find((n) => n.textContent.trim().toLowerCase() === 'channels');
    if (l && l.parentElement) { l.parentElement.style.visibility = 'hidden'; return true; }
    return false;
  };
}, proof);

// ---------------------------------------------------------------------------
// BEAT SHEET — seconds. Matches marketing/score.py exactly.
// ---------------------------------------------------------------------------
const B = MODE === 'vertical'
  ? { boot: 1.70, cut: 4.90, zero: 6.50, proof: 10.40, city: 12.40, black: 15.00, mark: 15.35, end: 18.00 }
  : { boot: 2.45, cut: 8.78, zero: 10.65, r1: 14.35, r2: 16.95, r3: 19.55, city: 21.90,
      black: 29.38, mark: 29.82, end: 32.30 };

const CAPS = MODE === 'vertical' ? [
  [0.40, 1.65, 'My AI company has made <b>$0</b>.'],
  [2.05, 4.60, '<b>102 agents.</b> 12 divisions. All awake.'],
  [3.45, 4.60, 'So I checked what it had earned.'],
  [6.60, 7.55, '<b>Zero.</b>'],
  [7.75, 9.10, 'It could have shown any number I wanted.'],
  [9.25, 10.25, 'It is <b>my own</b> dashboard.'],
  [10.60, 12.25, 'No number is shown unless it was <b>measured</b>.'],
  [12.60, 14.85, 'Every other number on here is real too.'],
] : [
  [0.60, 2.35, 'My AI company has made <b>$0</b>.'],
  [3.95, 6.30, '<b>102 digital employees.</b> 12 divisions.'],
  [6.55, 8.60, 'So I checked what it had earned.'],
  [10.80, 12.10, '<b>Zero.</b>'],
  [12.35, 14.20, 'It could have shown me any number I wanted.'],
  [22.10, 26.60, 'Twelve divisions. Every number on here was measured.'],
  [26.95, 28.20, 'It hasn’t earned anything yet.'],
  [28.40, 29.30, 'That’s the first true thing it told me.'],
];

// One-shot actions, fired the first time a frame's time passes them.
const ACTIONS = MODE === 'vertical' ? [
  [B.boot, 'boot'], [B.cut, 'cut'], [B.proof, 'proofpanel'], [B.city, 'city'],
] : [
  [B.boot, 'boot'], [B.cut, 'cut'], [B.r1, 'r1'], [B.r2, 'r2'], [B.r3, 'r3'], [B.city, 'city'],
];

const fired = new Set();
const N = Math.round(CFG.dur * FPS);
console.log(`rendering ${N} frames @ ${FPS}fps -> ${OUT}`);

for (let f = 0; f < N; f += 1) {
  const t = f / FPS;

  for (const [at, name] of ACTIONS) {
    if (t >= at && !fired.has(name)) {
      fired.add(name);
      await page.evaluate(async ({ name: n, mode }) => {
        const P = window.P;
        if (n === 'boot') { window.tab('ENTER SILENTLY ▸'); }
        if (n === 'cut') { window.centre('TOTAL REVENUE'); }
        if (n === 'proofpanel') { window.centre('All numbers are real'); }
        if (n === 'city') {
          window.tab('AI City');
          window.scrollTo({ top: mode === 'vertical' ? 620 : 420, behavior: 'instant' });
        }
        if (n === 'r1') {
          const d = JSON.parse(P.illegal.body).detail;
          window.setProof('POST /api/voice/sessions/{id}/state → "listening"', P.illegal.status,
            'refuse', d.replace('is not a legal transition', '<em>is not a legal transition</em>'),
            'it refuses illegal states', 0);
        }
        if (n === 'r2') {
          window.setProof('GET /api/self-seo', P.selfSeo.status, 'honest',
            JSON.parse(P.selfSeo.body).note.replace('has not audited itself yet',
              '<em>has not audited itself yet</em>'),
            'no score until it measured one', 0);
        }
        if (n === 'r3') {
          const s = JSON.parse(P.apis.body).stats;
          window.setProof('GET /api/apis/stats', s.total.toLocaleString() + ' catalogued', 'honest',
            'Every record is <em>METADATA_ONLY</em>. Registry adapters written: <em>' +
            s.adapters_written + '</em>. Five capabilities are wired by hand — and it says so.',
            'catalogued is not integrated', 0);
        }
      }, { name, mode: MODE });
      if (name === 'boot') {
        await page.waitForFunction(
          () => [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'AI City'),
          { timeout: 5000 }).catch(() => console.log('WARN: dashboard slow'));
        console.log('  rail hidden:', await page.evaluate(() => window.hideRail()));
      }
    }
  }

  // Camera, captions, overlays — all computed from t.
  await page.evaluate(({ t: tt, B: b, CAPS: caps, MODE: mode }) => {
    const ease3 = (x) => 1 - Math.pow(1 - x, 3);
    const rmp = (x, a, c) => (x <= a ? 0 : x >= c ? 1 : (x - a) / (c - a));
    const lp = (a, c, u) => a + (c - a) * Math.max(0, Math.min(1, u));

    let sc = 1, tx = 0, ty = 0, vig = 0;
    if (mode === 'vertical') {
      if (tt < b.boot) { sc = lp(1.35, 1.12, ease3(rmp(tt, 0, b.boot))); vig = 1; }
      else if (tt < b.cut) { sc = lp(1.12, 1.0, ease3(rmp(tt, b.boot, b.boot + 2.2))); vig = 0; }
      else if (tt < b.proof) { sc = lp(1.0, 1.14, ease3(rmp(tt, b.cut, b.cut + 1.5))); tx = 10; ty = 30; vig = 1; }
      else if (tt < b.city) { sc = lp(1.0, 1.10, ease3(rmp(tt, b.proof, b.proof + 2.0))); tx = 6; ty = 16; vig = 1; }
      else { sc = lp(1.0, 1.28, rmp(tt, b.city, b.city + 2.4)); ty = -10; vig = 0; }
    } else {
      if (tt < b.boot) { sc = lp(1.30, 1.10, ease3(rmp(tt, 0, b.boot))); vig = 1; }
      else if (tt < b.cut) { sc = lp(1.10, 1.0, ease3(rmp(tt, b.boot + 0.6, b.boot + 3.0))); vig = 0; }
      else if (tt < b.r1) { sc = lp(1.0, 1.42, ease3(rmp(tt, b.cut, b.cut + 1.7))); ty = 40; vig = 1; }
      else if (tt < b.city) { sc = 1; vig = 1; }
      else { sc = lp(1.0, 1.16, rmp(tt, b.city, b.city + 5.0)); ty = -20; vig = 0; }
    }
    window.pose(sc, tx, ty);
    window.$('tz-vig').style.opacity = String(vig);

    let html = '', op = 0;
    for (const [a, c, h] of caps) {
      if (tt >= a - 0.25 && tt <= c + 0.25) {
        html = h;
        op = Math.min(rmp(tt, a - 0.22, a + 0.06), 1 - rmp(tt, c - 0.06, c + 0.22));
      }
    }
    window.setCap(html, Math.max(0, op));

    // Proof cards (hero only): hard on, hard off.
    if (mode === 'hero') {
      const on = (tt >= b.r1 && tt < b.city) ? 1 : 0;
      window.$('tz-proof').style.opacity = String(on);
    }

    // Cut flashes.
    let fl = 0;
    for (const at of [b.cut, b.proof, b.city, b.r1, b.r2, b.r3]) {
      if (at != null && tt >= at && tt < at + 0.09) fl = Math.max(fl, 0.85 * (1 - (tt - at) / 0.09));
    }
    window.$('tz-flash').style.opacity = String(fl);

    // Black, then the mark.
    window.$('tz-black').style.opacity = String(rmp(tt, b.black, b.black + 0.26));
    const endOn = rmp(tt, b.mark, b.mark + 0.5);
    window.$('tz-end').style.opacity = String(endOn);
    document.querySelector('#tz-end .line').style.opacity =
      String(rmp(tt, b.mark + 0.65, b.mark + 1.1));
    document.querySelector('#tz-end .url').style.opacity =
      String(rmp(tt, b.mark + 1.35, b.mark + 1.8));
  }, { t, B, CAPS, MODE });

  await page.screenshot({ path: path.join(OUT, `f${String(f).padStart(5, '0')}.png`) });
  if (f % 60 === 0) console.log(`  frame ${f}/${N}  t=${t.toFixed(2)}s`);
}

await browser.close();
console.log(`DONE ${N} frames`);
