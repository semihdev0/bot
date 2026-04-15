"""Try different profile URL patterns and check Players search."""

import asyncio
import os

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        page = await (
            await b.new_context(viewport={"width": 1920, "height": 1080})
        ).new_page()
        await page.goto(
            os.environ["BACKOFFICE_URL"] + "/login",
            wait_until="commit",
            timeout=60000,
        )
        await page.wait_for_selector(
            "input[name='companyId']", state="visible", timeout=30000
        )
        await asyncio.sleep(1)
        await page.fill("input[name='companyId']", os.environ["BACKOFFICE_COMPANY_CODE"])
        await page.fill("input[name='username']", os.environ["BACKOFFICE_USERNAME"])
        await page.fill("input[name='password']", os.environ["BACKOFFICE_PASSWORD"])
        await page.get_by_text("Sign In").click()
        await asyncio.sleep(5)

        base = os.environ["BACKOFFICE_URL"]

        # First: go to bonus requests and try clicking username
        print("=== BONUS REQUESTS - CLICK USERNAME ===")
        await page.goto(base + "/bonus-requests", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3)

        rows = page.locator("table tbody tr")
        count = await rows.count()
        print(f"Found {count} rows")

        if count > 0:
            first_row = rows.first
            # Get all cells in the row
            cells = first_row.locator("td")
            cell_count = await cells.count()
            print(f"Cells in first row: {cell_count}")
            for i in range(cell_count):
                cell = cells.nth(i)
                cell_text = (await cell.text_content() or "").strip()[:50]
                # Check for clickable children
                clickables = cell.locator("span, button, div, p, a")
                cc = await clickables.count()
                print(f"  Cell {i}: text='{cell_text}' clickable_children={cc}")

            # Try to find and click the username text
            # Username format: @Turgut0101 or Turgut0101
            for username_text in ["Turgut0101", "@Turgut0101", "TUTurgut0101", "Tm8189", "@Tm8189"]:
                el = first_row.get_by_text(username_text, exact=False).first
                if await el.count() > 0:
                    print(f"\nFound username text: '{username_text}'")
                    tag = await el.evaluate("e => e.tagName")
                    cls = await el.evaluate("e => (e.className||'').toString().substring(0,80)")
                    cursor = await el.evaluate("e => getComputedStyle(e).cursor")
                    print(f"  Tag: {tag}, Class: {cls}, Cursor: {cursor}")

                    # Click it
                    print(f"  Clicking...")
                    before_url = page.url
                    await el.click()
                    await asyncio.sleep(5)
                    after_url = page.url
                    print(f"  Before: {before_url}")
                    print(f"  After:  {after_url}")

                    if before_url != after_url:
                        print(f"  NAVIGATED! Profile URL pattern found!")
                        # Check page content
                        text_with_lira = await page.evaluate("""() => {
                            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                            let c = 0;
                            while (walker.nextNode()) { if (walker.currentNode.textContent.includes('₺')) c++; }
                            return c;
                        }""")
                        print(f"  Text nodes with ₺: {text_with_lira}")

                        # Dump relevant text
                        texts = await page.evaluate("""() => {
                            const r = [];
                            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                            while (walker.nextNode()) {
                                const t = walker.currentNode.textContent.trim();
                                if (t.length > 0 && t.length < 80) r.push(t);
                            }
                            return r;
                        }""")
                        print(f"  Total text nodes: {len(texts)}")
                        for t in texts:
                            kw = ["balance","deposit","withdraw","status","₺","bonus","total","profit","loss","active","count","registered","login","first","last","player"]
                            if any(k in t.lower() for k in kw) or "₺" in t:
                                print(f"    {t}")
                    else:
                        print(f"  URL did not change. Maybe it opened a modal?")
                        # Check for modals
                        modals = page.locator("[role='dialog'], [data-state='open']")
                        mc = await modals.count()
                        print(f"  Modals found: {mc}")
                    break

        print("\n\n=== TRYING URL PATTERNS ===")
        # Try different URL patterns
        patterns = [
            "/players/TUTurgut0101",
            "/players/Turgut0101",
            "/player/TUTurgut0101",
            "/player/Turgut0101",
            "/users/TUTurgut0101",
            "/user/TUTurgut0101",
            "/players?search=Turgut0101",
            "/players?q=Turgut0101",
        ]

        for pattern in patterns:
            url = base + pattern
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
            text = await page.evaluate("() => document.body.innerText.substring(0, 500)")
            has_no_players = "no players" in text.lower() or "not found" in text.lower()
            has_currency = "₺" in text
            print(f"\n{'OK' if not has_no_players else 'FAIL'} {pattern}")
            print(f"  URL: {page.url}")
            print(f"  Has ₺: {has_currency}, No Players: {has_no_players}")
            if not has_no_players and has_currency:
                print(f"  TEXT: {text[:200]}")
                break

        # Now try the Players list page with search
        print("\n\n=== PLAYERS LIST PAGE ===")
        await page.goto(base + "/players", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)
        print(f"Players page URL: {page.url}")

        # Look for search input
        inputs = page.locator("input")
        input_count = await inputs.count()
        print(f"Input elements: {input_count}")
        for i in range(input_count):
            inp = inputs.nth(i)
            name = await inp.get_attribute("name") or ""
            placeholder = await inp.get_attribute("placeholder") or ""
            inp_type = await inp.get_attribute("type") or ""
            if name or placeholder:
                print(f"  Input {i}: name='{name}' placeholder='{placeholder}' type='{inp_type}'")

        # Try searching
        search_input = page.locator("input[placeholder*='Search'], input[placeholder*='search'], input[name*='search'], input[name*='query']").first
        if await search_input.count() > 0:
            print("\nSearch input found! Typing 'Turgut0101'...")
            await search_input.fill("Turgut0101")
            await asyncio.sleep(3)

            # Check results
            links = page.locator("table tbody tr a, table tbody tr td")
            link_count = await links.count()
            print(f"Result elements: {link_count}")

            rows = page.locator("table tbody tr")
            row_count = await rows.count()
            print(f"Result rows: {row_count}")
            for i in range(min(row_count, 3)):
                row = rows.nth(i)
                row_text = (await row.text_content() or "").strip()[:150]
                print(f"  Row {i}: {row_text}")

                # Find links in row
                row_links = row.locator("a")
                rl_count = await row_links.count()
                for j in range(rl_count):
                    href = await row_links.nth(j).get_attribute("href") or ""
                    lt = (await row_links.nth(j).text_content() or "").strip()
                    print(f"    Link: text='{lt}' href='{href}'")
        else:
            print("No search input found!")
            # Try just looking at the players table
            rows = page.locator("table tbody tr")
            row_count = await rows.count()
            print(f"Table rows: {row_count}")
            for i in range(min(row_count, 3)):
                row = rows.nth(i)
                text = (await row.text_content() or "").strip()[:150]
                print(f"  Row {i}: {text}")
                links = row.locator("a")
                lc = await links.count()
                for j in range(lc):
                    href = await links.nth(j).get_attribute("href") or ""
                    lt = (await links.nth(j).text_content() or "").strip()
                    print(f"    Link: text='{lt}' href='{href}'")

        await b.close()


asyncio.run(main())
