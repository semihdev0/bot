"""Examine username cell structure and find the link icon."""

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
        ctx = await b.new_context(viewport={"width": 1920, "height": 1080})
        page = await ctx.new_page()
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
        await page.goto(
            os.environ["BACKOFFICE_URL"] + "/bonus-requests",
            wait_until="networkidle",
            timeout=60000,
        )
        await asyncio.sleep(3)

        rows = page.locator("table tbody tr")
        count = await rows.count()
        if count == 0:
            print("No rows found!")
            await b.close()
            return

        # Examine Cell 1 (username cell) in detail
        first_row = rows.first
        cell1 = first_row.locator("td").nth(1)
        cell1_html = await cell1.evaluate("e => e.innerHTML")
        print("=== USERNAME CELL (Cell 1) HTML ===")
        print(cell1_html)
        print()

        # Find ALL children in the username cell
        children = cell1.locator("*")
        child_count = await children.count()
        print(f"=== ALL CHILDREN IN USERNAME CELL ({child_count}) ===")
        for i in range(child_count):
            child = children.nth(i)
            tag = await child.evaluate("e => e.tagName")
            cls = await child.evaluate("e => (e.className||'').toString().substring(0,100)")
            text = await child.evaluate("e => e.textContent.trim().substring(0,50)")
            href = await child.evaluate("e => e.getAttribute('href') || ''")
            onclick = await child.evaluate("e => e.getAttribute('onclick') || ''")
            cursor = await child.evaluate("e => getComputedStyle(e).cursor")
            is_svg = await child.evaluate("e => e.tagName === 'svg' || e.tagName === 'SVG' || e.closest('svg') !== null")
            print(f"  [{i}] <{tag}> cls='{cls[:60]}' text='{text[:30]}' href='{href}' cursor={cursor} svg={is_svg}")

        # Find the link icon - look for SVG, anchor, or external link element
        print("\n=== LOOKING FOR LINK ICON ===")
        # Try: any element with href
        links = cell1.locator("[href]")
        lc = await links.count()
        print(f"Elements with href: {lc}")
        for i in range(lc):
            href = await links.nth(i).get_attribute("href") or ""
            tag = await links.nth(i).evaluate("e => e.tagName")
            print(f"  [{i}] <{tag}> href='{href}'")

        # Try: SVG elements (icons)
        svgs = cell1.locator("svg")
        sc = await svgs.count()
        print(f"SVG icons: {sc}")

        # Try clicking the link icon (if it's an anchor or opens new tab)
        # Listen for new pages (tabs) opening
        print("\n=== TRYING TO CLICK LINK ICON ===")

        # Setup listener for new pages
        new_page_url = None

        def on_page(new_page):
            nonlocal new_page_url
            new_page_url = new_page.url
            print(f"  NEW TAB OPENED: {new_page.url}")

        ctx.on("page", on_page)

        # Try clicking the icon/link next to username
        # The external link icon is likely the last clickable element in the cell
        # or an SVG/anchor element
        if lc > 0:
            link = links.first
            print("Clicking first [href] element...")
            await link.click()
            await asyncio.sleep(3)
        elif sc > 0:
            svg = svgs.first
            print("Clicking first SVG icon...")
            await svg.click()
            await asyncio.sleep(3)
        else:
            # Try clicking each child that has cursor:pointer
            for i in range(child_count):
                child = children.nth(i)
                cursor = await child.evaluate("e => getComputedStyle(e).cursor")
                if cursor == "pointer":
                    tag = await child.evaluate("e => e.tagName")
                    text = await child.evaluate("e => e.textContent.trim()[:30]")
                    print(f"Clicking pointer element [{i}] <{tag}> '{text}'...")
                    await child.click()
                    await asyncio.sleep(3)

                    if new_page_url:
                        break
                    if page.url != os.environ["BACKOFFICE_URL"] + "/bonus-requests":
                        print(f"  URL changed to: {page.url}")
                        break

        # Check result
        if new_page_url:
            print(f"\nSUCCESS! New tab URL: {new_page_url}")
            # Get the new page and extract info
            pages = ctx.pages
            print(f"Total pages/tabs: {len(pages)}")
            if len(pages) > 1:
                new_pg = pages[-1]
                await asyncio.sleep(5)
                print(f"New tab final URL: {new_pg.url}")
                nt = await new_pg.evaluate("""() => {
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    let c = 0;
                    while (walker.nextNode()) { if (walker.currentNode.textContent.includes('₺')) c++; }
                    return c;
                }""")
                print(f"New tab text nodes with ₺: {nt}")
        else:
            print(f"\nCurrent page URL: {page.url}")
            print("No new tab detected.")

        await b.close()


asyncio.run(main())
