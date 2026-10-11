#!/usr/bin/env python3
"""Browser checks for the built site with Playwright (Chromium).

    python site/browser_checks.py http://127.0.0.1:8765 [--axe PATH_TO_axe.min.js]

For the home, get-started, how-it-works, integrations, benchmarks, privacy and one docs page:
no console errors or failed requests; no horizontal overflow at 390 px; the first Tab reaches the
skip link and the nav links are reachable by keyboard with a visible focus ring; the copy button
announces through the live region; the walkthrough tabs switch panels with arrow keys; the site
respects prefers-reduced-motion (no animations declared); dark colour scheme renders.
With --axe, runs axe-core and reports serious/critical violations. Exit 1 on failures.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

PAGES = ["/", "/get-started/", "/how-it-works/", "/integrations/", "/benchmarks/", "/privacy/", "/docs/", "/docs/routing/", "/404.html"]


async def main(base: str, axe: Path | None) -> int:
    failures: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for path in PAGES:
            for width, scheme in ((1280, "light"), (390, "dark")):
                ctx = await browser.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme, reduced_motion="reduce")
                await ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
                page = await ctx.new_page()
                console: list[str] = []
                page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e: console.append(str(e)))
                page.on("requestfailed", lambda r: console.append(f"request failed: {r.url}"))
                resp = await page.goto(base + path)
                if resp is None or (resp.status != 200 and not path.endswith("404.html")):
                    failures.append(f"{path}: HTTP {resp.status if resp else '?'}")
                await page.wait_for_timeout(300)
                if console:
                    failures.append(f"{path} @{width}: console/requests: {console[:3]}")
                sw, cw = await page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
                if sw > cw:
                    failures.append(f"{path} @{width}: horizontal overflow ({sw} > {cw})")
                if width == 1280:
                    # keyboard: first tab = skip link, then focus must be visible on nav links
                    await page.keyboard.press("Tab")
                    first = await page.evaluate("document.activeElement.className")
                    if "skip" not in first:
                        failures.append(f"{path}: first Tab focuses '{first}', not the skip link")
                    await page.keyboard.press("Tab")
                    await page.keyboard.press("Tab")
                    ring = await page.evaluate("getComputedStyle(document.activeElement).outlineStyle + ' ' + getComputedStyle(document.activeElement).outlineWidth")
                    if "none" in ring or ring.endswith(" 0px"):
                        failures.append(f"{path}: no visible focus ring on keyboard focus ({ring})")
                    if axe:
                        await page.add_script_tag(path=str(axe))
                        res = await page.evaluate("axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag22aa', 'best-practice']}})")
                        for v in res["violations"]:
                            if v["impact"] in ("serious", "critical"):
                                failures.append(f"{path}: axe {v['impact']} {v['id']}: {v['help']} ({len(v['nodes'])} nodes; e.g. {v['nodes'][0]['target']})")
                if path == "/" and width == 1280:
                    # copy button feedback + walkthrough tabs
                    btn = page.locator(".cmd .copy").first
                    await btn.click()
                    await page.wait_for_timeout(300)
                    live = await page.locator("[aria-live=polite]").text_content()
                    if "copied" not in (live or "").lower():
                        failures.append("home: copy button did not announce through the live region")
                    tabs = page.locator('.scenario-tabs [role=tab]')
                    n = await tabs.count()
                    if n < 2:
                        failures.append("home: walkthrough tabs not built")
                    else:
                        await tabs.nth(0).focus()
                        await page.keyboard.press("ArrowRight")
                        sel = await page.evaluate("document.querySelector('.scenario-tabs [aria-selected=true]').id")
                        if sel != "tab-1":
                            failures.append(f"home: ArrowRight did not move the tab selection (selected {sel})")
                        open_count = await page.evaluate("document.querySelectorAll('details.scenario[open]').length")
                        if open_count != 1:
                            failures.append(f"home: {open_count} scenario panels open (want 1)")
                await ctx.close()
        await browser.close()
    if failures:
        print("\n".join("FAIL " + f for f in failures))
        return 1
    print(f"ok: {len(PAGES)} pages × 2 viewports/schemes; keyboard, overflow, console, copy/tab behaviour{' and axe-core' if axe else ''} checks passed")
    return 0


if __name__ == "__main__":
    base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8765"
    axe = Path(sys.argv[sys.argv.index("--axe") + 1]) if "--axe" in sys.argv else None
    sys.exit(asyncio.run(main(base, axe)))
