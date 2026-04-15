"""Dump profile page - full text content and screenshot."""

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
        await page.goto(
            os.environ["BACKOFFICE_URL"] + "/players/TUTurgut0101",
            wait_until="commit",
            timeout=60000,
        )
        await asyncio.sleep(5)

        # Take screenshot
        await page.screenshot(path="/home/user/bot/profile_screenshot.png", full_page=True)
        print("Screenshot saved: /home/user/bot/profile_screenshot.png")

        # Get current URL
        print(f"\nCurrent URL: {page.url}")

        # Dump ALL visible text on the page (structured)
        all_text = await page.evaluate("""() => {
            const lines = [];
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            while (walker.nextNode()) {
                const text = walker.currentNode.textContent.trim();
                if (text.length > 0 && text.length < 100) {
                    const parent = walker.currentNode.parentElement;
                    const tag = parent ? parent.tagName : '?';
                    const cls = parent ? (parent.className||'').toString().substring(0,50) : '';
                    lines.push(tag + '|' + cls + '|' + text);
                }
            }
            return lines;
        }""")

        print(f"\n=== ALL TEXT NODES ({len(all_text)} total) ===")
        for line in all_text:
            parts = line.split("|", 2)
            tag, cls, text = parts[0], parts[1], parts[2] if len(parts) > 2 else ""
            # Filter: show only text that looks like profile data
            keywords = ["balance", "deposit", "withdraw", "bonus", "status",
                       "active", "profit", "loss", "bakiye", "yatırım", "çekim",
                       "durum", "kayıt", "giriş", "registered", "login",
                       "₺", "tl", "count", "total", "last", "first",
                       "aktif", "pasif", "player", "user"]
            if any(kw in text.lower() for kw in keywords) or "₺" in text:
                print(f"  <{tag:6s} cls={cls[:40]:40s}> {text}")

        # Also dump all content with financial patterns (numbers with ₺ or TL)
        print("\n=== FINANCIAL VALUES ===")
        for line in all_text:
            parts = line.split("|", 2)
            text = parts[2] if len(parts) > 2 else ""
            if "₺" in text or "TL" in text or ("." in text and any(c.isdigit() for c in text)):
                tag, cls = parts[0], parts[1]
                print(f"  <{tag:6s} cls={cls[:40]:40s}> {text}")

        # Check the main content area HTML structure
        main_html = await page.evaluate("""() => {
            // Try to find the main content area
            const main = document.querySelector('main') ||
                         document.querySelector('[role=main]') ||
                         document.querySelector('.content') ||
                         document.querySelector('#content');
            if (main) return main.innerHTML.substring(0, 3000);

            // Fallback: get body's direct children structure
            const body = document.body;
            const result = [];
            for (const child of body.children) {
                result.push('<' + child.tagName + ' class="' + (child.className||'').toString().substring(0,60) + '">' +
                           child.textContent.substring(0, 100).trim() + '...');
            }
            return result.join('\\n');
        }""")

        print(f"\n=== MAIN CONTENT HTML (first 3000 chars) ===")
        print(main_html[:3000])

        await b.close()


asyncio.run(main())
