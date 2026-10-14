#!/usr/bin/env python3
"""Browser checks for the built site with Playwright.

    python site/browser_checks.py http://127.0.0.1:8765 [--engines chromium,firefox,webkit] [--require]
                                  [--shots DIR] [--axe PATH_TO_axe.min.js] [--quick]

Route inventory: every <loc> in the served sitemap.xml plus /404.html.

Tiered coverage (what ran is printed at the end; an engine that is not installed is reported NOT RUN,
never as a pass; with --require a missing engine fails the run):

  chromium  every route x 320/390/768/1024/1280/1440 CSS px x light/dark: no console errors or failed
            requests; no document-level horizontal overflow; no element wider than the viewport outside a
            deliberate scroller (pre[tabindex], .table-wrap, .doc table); clipped text (overflow hidden/clip
            with scrollWidth > clientWidth) is a failure; command blocks: the rendered code text never shares
            space with the Copy button in ANY label state (Copy / Copied / Select and copy); the diagram's
            labels stay inside their cards and the gateway box; the external SVG's text boxes stay inside the
            gateway rectangle (measured with getBBox, i.e. in SVG user units, under whatever font the browser
            falls back to).
            shared components at breakpoint boundaries 759/760/761, 859/860/861, 899/900/901.
            200 % text enlargement (html{font-size:200%}) and the WCAG reflow case: a 320 CSS px viewport at
            device scale 4, i.e. 400 % browser zoom from a 1280 px window (DPR alone is not zoom - the CSS
            viewport is what changes).
            font fallback (web fonts blocked), JavaScript disabled, all <details> expanded.
            clipboard: the value written by every Copy button equals the code's exact text; the install
            one-liner equals facts.INSTALL_ONE_LINER byte for byte.
            keyboard: first Tab = skip link; visible focus ring on nav links and Copy buttons; scrollers are
            focusable; walkthrough tabs switch with arrow keys; the copy button announces in the live region.
  firefox,  one representative page per template (home, get-started, how-it-works, integrations, benchmarks,
  webkit    roadmap, thanks, docs index, a rendered doc, 404) at 390 and 1280: overflow, clipping, command
            block and diagram geometry. Playwright WebKit is not Safari; it is reported as "webkit".

--axe runs axe-core (serious/critical) in chromium at 1280. --shots saves component screenshots.
--quick: chromium at 390/1280 only (local smoke). Exit 1 on failures.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import urllib.request
from pathlib import Path

from playwright.async_api import Error as PwError
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import facts  # noqa: E402

WIDTHS = [320, 390, 768, 1024, 1280, 1440]
BOUNDARIES = [759, 760, 761, 859, 860, 861, 899, 900, 901]
COMPONENT_PAGES = ["/", "/get-started/", "/how-it-works/"]
REPRESENTATIVE = ["/", "/get-started/", "/how-it-works/", "/integrations/", "/benchmarks/", "/roadmap/", "/thanks/", "/docs/", "/docs/routing/", "/404.html"]

# Geometry probes -------------------------------------------------------------------------------------
JS_OVERFLOW = """
() => {
  const vw = document.documentElement.clientWidth;
  const out = {doc: document.documentElement.scrollWidth > vw, wide: [], clipped: []};
  const scroller = el => el.closest('pre[tabindex], .table-wrap, .doc table, .cmd-scroll pre');
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.position === 'fixed') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0) continue;
    if (r.right > vw + 1 && !scroller(el) && !el.classList.contains('skip')) out.wide.push(el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ')[0] : '') + ' right=' + Math.round(r.right));
    if ((cs.overflowX === 'hidden' || cs.overflowX === 'clip') && el.scrollWidth > el.clientWidth + 1 && !el.classList.contains('sr-only') && el.tagName !== 'HTML')
      out.clipped.push(el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ')[0] : '') + ' ' + el.scrollWidth + '>' + el.clientWidth);
  }
  out.wide = out.wide.slice(0, 5); out.clipped = out.clipped.slice(0, 5);
  return out;
}
"""

JS_CMD = """
(labels) => {
  const res = [];
  document.querySelectorAll('.cmd').forEach((box, i) => {
    const pre = box.querySelector('pre'); const btn = box.querySelector('.copy'); const bar = box.querySelector('.cmd-bar');
    const textRects = () => { const r = document.createRange(); r.selectNodeContents(pre); return Array.from(r.getClientRects()).filter(t => t.width > 0); };
    const item = {i, text: pre.textContent.slice(0, 32), hasBar: !!bar, overlaps: [], barOverflow: false, preClips: false};
    if (!btn) { res.push(item); return; }
    const orig = btn.textContent;
    for (const label of labels) {
      btn.textContent = label;
      const b = btn.getBoundingClientRect();
      const rects = textRects();  // re-measured per label: a longer label may reflow the toolbar row
      const hit = rects.some(t => t.left < b.right && t.right > b.left && t.top < b.bottom && t.bottom > b.top);
      if (hit) item.overlaps.push(label);
      const bb = box.getBoundingClientRect();
      if (b.right > bb.right + 0.5 || b.left < bb.left - 0.5) item.barOverflow = true;
    }
    btn.textContent = orig;
    const cs = getComputedStyle(pre);
    if ((cs.overflowX === 'hidden' || cs.overflowX === 'clip' || cs.overflowX === 'visible') && pre.scrollWidth > pre.clientWidth + 1) item.preClips = true;
    res.push(item);
  });
  return res;
}
"""

JS_DIAGRAM = """
() => {
  const fits = document.querySelector('.fits'); if (!fits) return null;
  const out = {cards: 0, outside: []};
  const inside = (inner, outer, pad) => inner.left >= outer.left - pad && inner.right <= outer.right + pad && inner.top >= outer.top - pad && inner.bottom <= outer.bottom + pad;
  const textRects = el => { const r = document.createRange(); r.selectNodeContents(el); return Array.from(r.getClientRects()).filter(t => t.width > 0); };
  for (const card of fits.querySelectorAll('.fits-cards li, .fits-gw, .fits-chip code')) {
    out.cards++;
    const cb = card.getBoundingClientRect();
    for (const t of textRects(card)) if (!inside(t, cb, 0.5)) out.outside.push(card.className + ': ' + card.textContent.trim().slice(0, 30));
  }
  const fb = fits.getBoundingClientRect();
  for (const el of fits.querySelectorAll('*')) { const r = el.getBoundingClientRect(); if (r.width && !inside(r, fb, 0.5)) out.outside.push('escapes figure: ' + el.tagName + '.' + el.className); }
  return out;
}
"""

JS_SVG = """
() => {
  const s = document.querySelector('svg'); const gw = Array.from(s.querySelectorAll('rect')).find(r => r.getAttribute('fill') === '#0f5c50');
  const gb = gw.getBBox(); const out = {font: getComputedStyle(s).fontFamily, outside: [], n: 0};
  const vb = s.viewBox.baseVal;
  s.querySelectorAll('text').forEach(t => {
    const b = t.getBBox(); const x = parseFloat(t.getAttribute('x'));
    if (b.x + b.width > vb.width - 8) out.outside.push('viewBox: ' + t.textContent);
    if (x >= gb.x && x <= gb.x + gb.width) { out.n++; if (b.x + b.width > gb.x + gb.width - 12 || b.y + b.height > gb.y + gb.height) out.outside.push('gateway box: ' + t.textContent + ' right=' + Math.round(b.x + b.width) + ' box=' + (gb.x + gb.width)); }
  });
  return out;
}
"""


class Run:
    def __init__(self, base: str, args: argparse.Namespace) -> None:
        self.base = base
        self.args = args
        self.failures: list[str] = []
        self.ran: list[str] = []
        self.not_run: list[str] = []

    def fail(self, msg: str) -> None:
        self.failures.append(msg)

    # ---- helpers -----------------------------------------------------------------------------------
    async def open(self, browser, path: str, width: int, scheme: str = "light", **ctx_kw):  # type: ignore[no-untyped-def]
        ctx = await browser.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme, reduced_motion="reduce", **ctx_kw)
        page = await ctx.new_page()
        console: list[str] = []
        page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console.append(str(e)))
        page.on("requestfailed", lambda r: console.append(f"request failed: {r.url}") if "/assets/fonts/" not in r.url else None)
        resp = await page.goto(self.base + path)
        if resp is None or (resp.status != 200 and not path.endswith("404.html")):
            self.fail(f"{path}: HTTP {resp.status if resp else '?'}")
        await page.wait_for_timeout(150)
        return ctx, page, console

    async def geometry(self, page, tag: str, diagram: bool = True) -> None:  # type: ignore[no-untyped-def]
        ov = await page.evaluate(JS_OVERFLOW)
        if ov["doc"]:
            self.fail(f"{tag}: document-level horizontal overflow")
        if ov["wide"]:
            self.fail(f"{tag}: elements wider than the viewport outside a scroller: {ov['wide']}")
        if ov["clipped"]:
            self.fail(f"{tag}: clipped content (overflow hidden with wider scrollWidth): {ov['clipped']}")
        cmds = await page.evaluate(JS_CMD, ["Copy", "Copied", "Select and copy"])
        for c in cmds:
            if not c["hasBar"]:
                self.fail(f"{tag}: command block {c['i']} has no toolbar row")
            if c["overlaps"]:
                self.fail(f"{tag}: Copy button covers the code text in state(s) {c['overlaps']} (block {c['i']}: {c['text']!r})")
            if c["barOverflow"]:
                self.fail(f"{tag}: Copy button escapes its block (block {c['i']})")
            if c["preClips"]:
                self.fail(f"{tag}: code is clipped instead of wrapped or scrolled (block {c['i']}: {c['text']!r})")
        if diagram:
            d = await page.evaluate(JS_DIAGRAM)
            if d and d["outside"]:
                self.fail(f"{tag}: diagram text leaves its container: {d['outside'][:4]}")

    # ---- tiers -------------------------------------------------------------------------------------
    async def chromium_full(self, p, routes: list[str]) -> None:  # type: ignore[no-untyped-def]
        browser = await p.chromium.launch()
        widths = [390, 1280] if self.args.quick else WIDTHS
        schemes = ["light", "dark"]
        count = 0
        for path in routes:
            for width in widths:
                for scheme in schemes:
                    ctx, page, console = await self.open(browser, path, width, scheme)
                    await ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=self.base)
                    tag = f"{path} @{width}/{scheme}"
                    if console:
                        self.fail(f"{tag}: console/requests: {console[:3]}")
                    await self.geometry(page, tag)
                    count += 1
                    if self.args.shots and path in COMPONENT_PAGES and width in (390, 1280) and scheme == "light":
                        await self.shots(page, path, width)
                    if width == 1280 and scheme == "light":
                        await self.keyboard(page, path)
                        if self.args.axe:
                            await self.axe(page, path)
                    if path == "/" and width == 1280 and scheme == "light":
                        await self.tabs(page)
                    if path in ("/", "/get-started/") and width in (390, 1280) and scheme == "light":
                        await self.clipboard(page, path, width)
                    await ctx.close()
        self.ran.append(f"chromium: {len(routes)} routes x {len(widths)} widths {widths} x {schemes} = {count} page loads (geometry, console, keyboard, clipboard)")
        # breakpoint boundaries on the shared components
        if not self.args.quick:
            n = 0
            for path in COMPONENT_PAGES:
                for width in BOUNDARIES:
                    ctx, page, _ = await self.open(browser, path, width)
                    await self.geometry(page, f"{path} @{width} (breakpoint boundary)")
                    await ctx.close()
                    n += 1
            self.ran.append(f"chromium: breakpoint boundaries {BOUNDARIES} on {COMPONENT_PAGES} = {n} loads")
            # 200 % text enlargement
            n = 0
            for path in routes:
                for width in (390, 1280):
                    ctx, page, _ = await self.open(browser, path, width)
                    await page.add_style_tag(content="html{font-size:200%}")
                    await page.wait_for_timeout(100)
                    await self.geometry(page, f"{path} @{width} text 200%")
                    await ctx.close()
                    n += 1
            self.ran.append(f"chromium: 200% text enlargement on {len(routes)} routes x 390/1280 = {n} loads")
            # reflow: 320 CSS px at device scale 4 (= 400 % zoom from 1280)
            n = 0
            for path in routes:
                ctx, page, _ = await self.open(browser, path, 320, device_scale_factor=4)
                await self.geometry(page, f"{path} @320 css px, dpr 4 (400% zoom from 1280)")
                await ctx.close()
                n += 1
            self.ran.append(f"chromium: reflow at 320 CSS px / device scale 4 on {len(routes)} routes = {n} loads")
            # expanded content
            n = 0
            for path in routes:
                ctx, page, _ = await self.open(browser, path, 320)
                await page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
                await page.wait_for_timeout(100)
                await self.geometry(page, f"{path} @320 all <details> open")
                await ctx.close()
                n += 1
            self.ran.append(f"chromium: all <details> expanded at 320 on {len(routes)} routes = {n} loads")
            # font fallback (web fonts blocked)
            n = 0
            for path in COMPONENT_PAGES:
                for width in (320, 390, 1280):
                    ctx = await browser.new_context(viewport={"width": width, "height": 900}, reduced_motion="reduce")
                    await ctx.route("**/assets/fonts/*", lambda route: asyncio.ensure_future(route.abort()))
                    page = await ctx.new_page()
                    await page.goto(self.base + path)
                    await page.wait_for_timeout(200)
                    fam = await page.evaluate("document.fonts.check('16px \"IBM Plex Sans\"')")
                    await self.geometry(page, f"{path} @{width} fallback fonts (web fonts blocked; plex loaded={fam})")
                    await ctx.close()
                    n += 1
            self.ran.append(f"chromium: fallback fonts (web fonts blocked) on {COMPONENT_PAGES} x 320/390/1280 = {n} loads")
            # JavaScript disabled
            n = 0
            for path in COMPONENT_PAGES:
                ctx, page, _ = await self.open(browser, path, 390, java_script_enabled=False)
                if await page.locator(".copy").count():
                    self.fail(f"{path} no-JS: a Copy button exists without JavaScript")
                if path == "/" and await page.locator("details.scenario").count() < 2:
                    self.fail("home no-JS: walkthrough scenarios are not readable without JavaScript")
                if await page.locator(".cmd-bar").count() and not await page.locator(".cmd-label").first.is_visible():
                    self.fail(f"{path} no-JS: command toolbar label not visible")
                await self.geometry(page, f"{path} @390 JavaScript disabled")
                await ctx.close()
                n += 1
            self.ran.append(f"chromium: JavaScript disabled on {COMPONENT_PAGES} at 390 = {n} loads")
            # the external SVG asset's own geometry (fallback font, no page stylesheet)
            ctx = await browser.new_context(viewport={"width": 1200, "height": 500})
            page = await ctx.new_page()
            await page.goto(self.base + "/assets/where-it-fits.svg")
            await page.wait_for_timeout(200)
            svg = await page.evaluate(JS_SVG)
            if svg["outside"]:
                self.fail(f"where-it-fits.svg: text leaves its box under font {svg['font']!r}: {svg['outside']}")
            self.ran.append(f"chromium: where-it-fits.svg text boxes ({svg['n']} gateway labels) measured under font {svg['font']}")
            await ctx.close()
        await browser.close()

    async def other_engine(self, p, name: str) -> None:  # type: ignore[no-untyped-def]
        try:
            browser = await getattr(p, name).launch()
        except PwError as e:  # not installed here
            self.not_run.append(f"{name}: NOT RUN ({str(e).splitlines()[0][:100]})")
            if self.args.require:
                self.fail(f"{name} required but not available")
            return
        n = 0
        for path in REPRESENTATIVE:
            for width in (390, 1280):
                ctx, page, console = await self.open(browser, path, width)
                if console:
                    self.fail(f"{name} {path} @{width}: console/requests: {console[:3]}")
                await self.geometry(page, f"{name} {path} @{width}")
                await ctx.close()
                n += 1
        await browser.close()
        self.ran.append(f"{name}: {len(REPRESENTATIVE)} representative routes x 390/1280 = {n} loads (overflow, clipping, command block + diagram geometry)")

    # ---- behaviour ---------------------------------------------------------------------------------
    async def keyboard(self, page, path: str) -> None:  # type: ignore[no-untyped-def]
        await page.keyboard.press("Tab")
        first = await page.evaluate("document.activeElement.className")
        if "skip" not in first:
            self.fail(f"{path}: first Tab focuses '{first}', not the skip link")
        await page.keyboard.press("Tab")
        await page.keyboard.press("Tab")
        ring = await page.evaluate("getComputedStyle(document.activeElement).outlineStyle + ' ' + getComputedStyle(document.activeElement).outlineWidth")
        if "none" in ring or ring.endswith(" 0px"):
            self.fail(f"{path}: no visible focus ring on keyboard focus ({ring})")
        btn = page.locator(".cmd .copy").first
        if await btn.count():
            await btn.focus()
            ring = await page.evaluate("getComputedStyle(document.activeElement).outlineStyle + ' ' + getComputedStyle(document.activeElement).outlineWidth")
            if "none" in ring or ring.endswith(" 0px"):
                self.fail(f"{path}: Copy button has no visible focus ring ({ring})")
        sc = page.locator("pre[tabindex='0']").first
        if await sc.count():
            await sc.focus()
            if await page.evaluate("document.activeElement.tagName") != "PRE":
                self.fail(f"{path}: scrollable code block is not keyboard focusable")

    async def clipboard(self, page, path: str, width: int) -> None:  # type: ignore[no-untyped-def]
        boxes = page.locator(".cmd")
        n = await boxes.count()
        for i in range(n):
            box = boxes.nth(i)
            expected = (await box.locator("pre code").text_content() or "").rstrip("\n")
            await box.locator(".copy").click()
            await page.wait_for_timeout(120)
            got = await page.evaluate("navigator.clipboard.readText()")
            if i == 0:
                live = await page.locator("[aria-live=polite]").text_content()
                if "copied" not in (live or "").lower():
                    self.fail(f"{path}: copy button did not announce through the live region")
            if got != expected:
                self.fail(f"{path} @{width}: clipboard value differs from the code text for block {i}: {got!r} != {expected!r}")
            if i == 0 and path in ("/", "/get-started/") and got != facts.INSTALL_ONE_LINER:
                self.fail(f"{path}: install one-liner copied as {got!r}, canonical is {facts.INSTALL_ONE_LINER!r}")
            if got.count("\n") != expected.count("\n"):
                self.fail(f"{path}: visual wrapping changed the number of newlines in the copied value (block {i})")
            label = await box.locator(".copy").text_content()
            if label != "Copied":
                self.fail(f"{path}: button label after copy is {label!r}")

    async def tabs(self, page) -> None:  # type: ignore[no-untyped-def]
        tabs = page.locator(".scenario-tabs [role=tab]")
        n = await tabs.count()
        if n < 2:
            self.fail("home: walkthrough tabs not built")
            return
        await tabs.nth(0).focus()
        await page.keyboard.press("ArrowRight")
        sel = await page.evaluate("document.querySelector('.scenario-tabs [aria-selected=true]').id")
        if sel != "tab-1":
            self.fail(f"home: ArrowRight did not move the tab selection (selected {sel})")
        open_count = await page.evaluate("document.querySelectorAll('details.scenario[open]').length")
        if open_count != 1:
            self.fail(f"home: {open_count} scenario panels open (want 1)")

    async def axe(self, page, path: str) -> None:  # type: ignore[no-untyped-def]
        await page.add_script_tag(path=str(self.args.axe))
        res = await page.evaluate("axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag22aa', 'best-practice']}})")
        for v in res["violations"]:
            if v["impact"] in ("serious", "critical"):
                self.fail(f"{path}: axe {v['impact']} {v['id']}: {v['help']} ({len(v['nodes'])} nodes; e.g. {v['nodes'][0]['target']})")

    async def shots(self, page, path: str, width: int) -> None:  # type: ignore[no-untyped-def]
        out = Path(self.args.shots)
        out.mkdir(parents=True, exist_ok=True)
        slug = path.strip("/").replace("/", "-") or "home"
        await page.screenshot(path=str(out / f"{slug}-{width}.png"), full_page=True)
        boxes = page.locator(".cmd")
        for i in range(await boxes.count()):
            await boxes.nth(i).screenshot(path=str(out / f"{slug}-{width}-cmd{i}.png"))
        if await page.locator(".fits-figure").count():
            await page.locator(".fits-figure").screenshot(path=str(out / f"{slug}-{width}-diagram.png"))


def routes_from_sitemap(base: str) -> list[str]:
    xml = urllib.request.urlopen(base + "/sitemap.xml", timeout=10).read().decode()  # noqa: S310 - local server
    locs = re.findall(r"<loc>([^<]+)</loc>", xml)
    paths = sorted({re.sub(r"^https?://[^/]+", "", u) or "/" for u in locs})
    return paths + ["/404.html"]


async def main(args: argparse.Namespace) -> int:
    base = args.base.rstrip("/")
    run = Run(base, args)
    routes = routes_from_sitemap(base)
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    async with async_playwright() as p:
        if "chromium" in engines:
            await run.chromium_full(p, routes)
        for name in engines:
            if name != "chromium":
                await run.other_engine(p, name)
    print("ran:")
    for r in run.ran:
        print("  " + r)
    for r in run.not_run:
        print("  " + r)
    if run.failures:
        print("\n".join("FAIL " + f for f in run.failures))
        print(f"{len(run.failures)} failure(s)")
        return 1
    print(f"ok: {len(routes)} routes; no failures")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default="http://127.0.0.1:8765")
    ap.add_argument("--engines", default="chromium")
    ap.add_argument("--require", action="store_true", help="fail when a requested engine is not installed")
    ap.add_argument("--shots", default="")
    ap.add_argument("--axe", default="")
    ap.add_argument("--quick", action="store_true")
    sys.exit(asyncio.run(main(ap.parse_args())))
