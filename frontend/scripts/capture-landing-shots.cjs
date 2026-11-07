/* Captures the real product screens shown on the landing page, from the app's own public demo gallery
 * (prerecorded investigations). Nothing is drawn or edited: each image is a clip of a rendered page.
 *
 *   1. API (demo routes only, no database, ignores .env):   see docs/design/prototypes/landing/README.md
 *        cd backend && .venv/bin/python -c "import uvicorn; from querycure.api.main import create_app; \
 *          from querycure.core.config import Settings; \
 *          uvicorn.run(create_app(Settings(_env_file=None, cors_origins=['http://localhost:3000']), engine=None), port=8000)"
 *   2. Web:   cd frontend && NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 pnpm dev
 *   3.        cd frontend && node scripts/capture-landing-shots.cjs
 *
 * Output: public/landing/product/<shot>-<dark|light>.png (2x). Prints each size in CSS pixels. */
const { chromium } = require("@playwright/test");
const path = require("node:path");

const BASE = process.env.SHOTS_BASE ?? "http://localhost:3000";
const OUT = path.join(__dirname, "..", "public", "landing", "product");
const PAD = 10;

/** Absolute page rect (x, y, w, h) of the element whose own text contains `text`, or of `selector`. */
const rectOf = (page, spec) =>
  page.evaluate((s) => {
    let el = null;
    if (s.selector && s.match) el = [...document.querySelectorAll(s.selector)].find((e) => e.innerText.includes(s.match)) ?? null;
    else if (s.selector) el = document.querySelector(s.selector);
    else {
      const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      while (w.nextNode()) if (w.currentNode.textContent.includes(s.text)) { el = w.currentNode.parentElement; break; }
    }
    if (!el) return null;
    if (s.up) for (const f of s.up) { const p = el.closest(f); if (p) el = p; }
    const r = el.getBoundingClientRect();
    return { x: r.left, y: r.top + scrollY, w: r.width, h: r.height };
  }, spec);

/** The bordered card that contains `text`: climb until the box is at least `minH` tall. */
const cardOf = (page, text, minH) =>
  page.evaluate(([t, h]) => {
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let el = null;
    while (w.nextNode()) if (w.currentNode.textContent.includes(t)) { el = w.currentNode.parentElement; break; }
    while (el && el.getBoundingClientRect().height < h) el = el.parentElement;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.left, y: r.top + scrollY, w: r.width, h: r.height };
  }, [text, minH]);

async function open(browser, scheme, slug, width = 1280) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 2, colorScheme: scheme });
  await ctx.addInitScript((t) => localStorage.setItem("theme", t), scheme); // next-themes' storage key
  const page = await ctx.newPage();
  await page.goto(`${BASE}/demo/${slug}`, { waitUntil: "networkidle" });
  await page.waitForSelector("#report-provenance-and-integrity", { timeout: 30000 });
  await page.waitForTimeout(800);
  return { ctx, page };
}

async function clip(page, name, scheme, { x, y, w, h }) {
  const c = { x: Math.max(0, x - PAD), y: Math.max(0, y - PAD), width: w + 2 * PAD, height: h + 2 * PAD };
  await page.screenshot({ path: path.join(OUT, `${name}-${scheme}.png`), clip: c, fullPage: true });
  console.log(`${name}-${scheme}`.padEnd(34), `${Math.round(c.width)}x${Math.round(c.height)}`);
}

const union = (a, b) => ({ x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.max(a.x + a.w, b.x + b.w) - Math.min(a.x, b.x), h: Math.max(a.y + a.h, b.y + b.h) - Math.min(a.y, b.y) });

(async () => {
  const browser = await chromium.launch();
  for (const scheme of ["dark", "light"]) {
    // Investigation: a plain EXPLAIN plan of the slow query, with the hottest node found.
    let { ctx, page } = await open(browser, scheme, "orders-missing-composite-index");
    const q = await rectOf(page, { selector: "#report-query h2" });
    const op = await rectOf(page, { selector: "#report-observed-problem" });
    await clip(page, "investigation", scheme, { x: 88, y: q.y - 4, w: 736, h: op.y + op.h - q.y + 4 });
    const hy = await rectOf(page, { selector: "#report-hypotheses" });
    const rec = await rectOf(page, { selector: "#report-recommendation" });
    await clip(page, "hypotheses", scheme, union(hy, rec));
    await ctx.close();

    // Approval, audit and report: a prerecorded sandbox investigation.
    ({ ctx, page } = await open(browser, scheme, "orders-sandbox-composite-index"));
    const round = await rectOf(page, { selector: "h3", match: "Round 1" });
    const details = await rectOf(page, { text: "Experiment details" });
    await clip(page, "approval", scheme, { x: 88, y: round.y, w: 736, h: details.y - round.y - 28 });
    const card = await cardOf(page, "rescore", 330);
    await clip(page, "audit", scheme, card);
    const lim = await rectOf(page, { selector: "#report-limitations" });
    const prov = await rectOf(page, { selector: "#report-provenance-and-integrity" });
    await clip(page, "report-body", scheme, union(lim, prov));
    await ctx.close();

    // The report header and the stored-digest check, at a width where the page is one column (no side rail).
    ({ ctx, page } = await open(browser, scheme, "orders-sandbox-composite-index", 900));
    await page.getByRole("button", { name: "Check stored digests" }).click();
    await page.waitForTimeout(1500);
    const manifest = await rectOf(page, { selector: "main section" });
    const head = await rectOf(page, { selector: "main article header" });
    await clip(page, "report-header", scheme, { x: manifest.x, y: manifest.y, w: manifest.w, h: head.y + head.h - manifest.y });
    await ctx.close();
  }
  await browser.close();
})();
