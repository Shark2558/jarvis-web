import asyncio, sys, subprocess, time
from playwright.async_api import async_playwright
SHOTS = [
  ("01-reader-laptop-night", "v=reader&s=night", 1440, 900, False),
  ("01b-reader-flow-laptop-night", "v=reader&s=night&at=how", 1440, 900, False),
  ("02-reader-laptop-day", "v=reader&s=day", 1440, 900, False),
  ("03-search-laptop-night", "v=search&s=night", 1440, 900, False),
  ("04-player-laptop-night", "v=player&s=night", 1440, 900, False),
  ("05-player-laptop-day", "v=player&s=day", 1440, 900, False),
  ("06-reader-phone-night", "v=reader&s=night&p=1", 390, 844, True),
  ("06b-reader-flow-phone-night", "v=reader&s=night&p=1&at=how", 390, 844, True),
  ("07-contents-phone-night", "v=sheet&s=night&p=1", 390, 844, True),
  ("08-player-phone-night", "v=player&s=night&p=1", 390, 844, True),
  ("09-reader-phone-day", "v=reader&s=day&p=1", 390, 844, True),
]
async def main(out):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for name, qs, w, h, mob in SHOTS:
            ctx = await b.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if mob else 1, is_mobile=mob, has_touch=mob)
            pg = await ctx.new_page()
            errs = []
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(f"http://127.0.0.1:8765/mock.html?{qs}")
            await pg.wait_for_selector("html[data-ready='1']", timeout=10000)
            await pg.wait_for_timeout(900)
            if False:
                await pg.evaluate("document.getElementById('main').scrollTop = 0")
            await pg.screenshot(path=f"{out}/{name}.png")
            if errs: print(name, "ERRORS:", errs)
            await ctx.close()
        await b.close()
asyncio.run(main(sys.argv[1]))
