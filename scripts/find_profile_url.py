"""Find the correct profile URL by clicking username in bonus list."""

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
        await page.fill(
            "input[name='companyId']", os.environ["BACKOFFICE_COMPANY_CODE"]
        )
        await page.fill("input[name='username']", os.environ["BACKOFFICE_USERNAME"])
        await page.fill("input[name='password']", os.environ["BACKOFFICE_PASSWORD"])
        await page.get_by_text("Sign In").click()
        await asyncio.sleep(5)

        # Go to bonus requests
        await page.goto(
            os.environ["BACKOFFICE_URL"] + "/bonus-requests",
            wait_until="networkidle",
            timeout=60000,
        )
        await asyncio.sleep(3)

        # Find all links in the first few table rows
        print("=== LINKS IN BONUS REQUEST TABLE ===")
        rows = page.locator("table tbody tr")
        count = await rows.count()
        print(f"Found {count} rows")

        for i in range(min(count, 3)):
            row = rows.nth(i)
            row_text = (await row.text_content() or "").strip()[:100]
            print(f"\nRow {i}: {row_text}")

            # Find all links in the row
            links = row.locator("a")
            link_count = await links.count()
            print(f"  Links in row: {link_count}")
            for j in range(link_count):
                link = links.nth(j)
                href = await link.get_attribute("href") or "NO HREF"
                text = (await link.text_content() or "").strip()
                print(f"  Link {j}: text='{text}' href='{href}'")

            # Find all clickable elements
            buttons = row.locator("button, [role='button'], [onclick]")
            btn_count = await buttons.count()
            print(f"  Buttons/clickables: {btn_count}")
            for j in range(min(btn_count, 5)):
                btn = buttons.nth(j)
                text = (await btn.text_content() or "").strip()[:50]
                cls = await btn.get_attribute("class") or ""
                print(f"  Button {j}: text='{text}' class='{cls[:60]}'")

        # Try clicking the first username link and see where it goes
        if count > 0:
            print("\n=== CLICKING FIRST ROW USERNAME ===")
            first_row = rows.first
            first_link = first_row.locator("a").first

            if await first_link.count() > 0:
                href = await first_link.get_attribute("href") or ""
                text = (await first_link.text_content() or "").strip()
                print(f"Clicking link: text='{text}' href='{href}'")

                await first_link.click()
                await asyncio.sleep(5)

                print(f"Navigated to: {page.url}")

                # Take screenshot of the profile page
                await page.screenshot(
                    path="/home/user/bot/profile_after_click.png", full_page=True
                )
                print("Screenshot saved: profile_after_click.png")

                # Check text nodes count
                count = await page.evaluate("""() => {
                    const walker = document.createTreeWalker(
                        document.body, NodeFilter.SHOW_TEXT
                    );
                    let c = 0;
                    while (walker.nextNode()) {
                        const t = walker.currentNode.textContent;
                        if (t.includes('₺')) c++;
                    }
                    return c;
                }""")
                print(f"Text nodes with ₺: {count}")

                # Wait more and check again
                await asyncio.sleep(5)
                count2 = await page.evaluate("""() => {
                    const walker = document.createTreeWalker(
                        document.body, NodeFilter.SHOW_TEXT
                    );
                    let c = 0;
                    while (walker.nextNode()) {
                        const t = walker.currentNode.textContent;
                        if (t.includes('₺')) c++;
                    }
                    return c;
                }""")
                print(f"Text nodes with ₺ (after 5s more): {count2}")

                # Dump profile text
                texts = await page.evaluate("""() => {
                    const results = [];
                    const walker = document.createTreeWalker(
                        document.body, NodeFilter.SHOW_TEXT
                    );
                    while (walker.nextNode()) {
                        const t = walker.currentNode.textContent.trim();
                        if (t.length > 0 && t.length < 80) {
                            const p = walker.currentNode.parentElement;
                            const tag = p ? p.tagName : '?';
                            const cls = p ? (p.className||'').toString().substring(0,50) : '';
                            results.push(tag + '|' + cls + '|' + t);
                        }
                    }
                    return results;
                }""")

                print(f"\n=== PROFILE PAGE TEXT NODES ({len(texts)}) ===")
                for line in texts:
                    parts = line.split("|", 2)
                    text = parts[2] if len(parts) > 2 else ""
                    tag = parts[0]
                    cls = parts[1][:40] if len(parts) > 1 else ""
                    # Show profile-relevant items
                    keywords = [
                        "balance", "deposit", "withdraw", "bonus",
                        "status", "active", "profit", "loss", "₺",
                        "count", "total", "last", "first", "registered",
                        "login", "player", "user", "bakiye", "yatırım",
                        "durum", "aktif",
                    ]
                    if any(kw in text.lower() for kw in keywords) or "₺" in text:
                        print(f"  <{tag:6s} cls={cls:40s}> {text}")
            else:
                print("No links found in first row!")

        await b.close()


asyncio.run(main())
