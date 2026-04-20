"""Inspect Comm100 login and console pages to discover DOM elements."""

import asyncio
import os
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

LOGIN_URL = "https://secure.comm100.io/signin"
CONSOLE_URL = (
    "https://dash15.lively-chat.com/agentconsole/auth.html"
    f"?siteId={os.environ.get('COMM100_SITE_ID', '90008526')}"
)
EMAIL = os.environ.get("COMM100_EMAIL", "")
PASSWORD = os.environ.get("COMM100_PASSWORD", "")


async def dump_elements(page, label: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  URL: {page.url}")
    print(f"{'='*60}")

    # Inputs
    inputs = page.locator("input")
    count = await inputs.count()
    print(f"\n--- INPUTS ({count}) ---")
    for i in range(count):
        el = inputs.nth(i)
        attrs = {}
        for attr in ["type", "name", "id", "placeholder", "class", "value"]:
            val = await el.get_attribute(attr)
            if val:
                attrs[attr] = val
        visible = await el.is_visible()
        print(f"  [{i}] visible={visible} {attrs}")

    # Buttons
    buttons = page.locator("button")
    count = await buttons.count()
    print(f"\n--- BUTTONS ({count}) ---")
    for i in range(count):
        el = buttons.nth(i)
        text = (await el.inner_text()).strip()
        attrs = {}
        for attr in ["type", "id", "class", "name", "data-testid"]:
            val = await el.get_attribute(attr)
            if val:
                attrs[attr] = val
        visible = await el.is_visible()
        print(f"  [{i}] visible={visible} text='{text}' {attrs}")

    # Links (a tags)
    links = page.locator("a")
    count = await links.count()
    print(f"\n--- LINKS ({count}) ---")
    for i in range(min(count, 20)):
        el = links.nth(i)
        text = (await el.inner_text()).strip()
        href = await el.get_attribute("href") or ""
        cls = await el.get_attribute("class") or ""
        visible = await el.is_visible()
        if text or visible:
            print(f"  [{i}] visible={visible} text='{text}' href='{href}' class='{cls}'")

    # Iframes
    iframes = page.locator("iframe")
    count = await iframes.count()
    print(f"\n--- IFRAMES ({count}) ---")
    for i in range(count):
        el = iframes.nth(i)
        src = await el.get_attribute("src") or ""
        fid = await el.get_attribute("id") or ""
        print(f"  [{i}] id='{fid}' src='{src}'")

    # Divs with role=button or clickable look
    role_btns = page.locator("[role='button'], [onclick], [class*='btn']")
    count = await role_btns.count()
    print(f"\n--- ROLE BUTTONS / BTN CLASS ({count}) ---")
    for i in range(min(count, 20)):
        el = role_btns.nth(i)
        text = (await el.inner_text()).strip()[:60]
        tag = await el.evaluate("el => el.tagName")
        cls = await el.get_attribute("class") or ""
        visible = await el.is_visible()
        if visible:
            print(f"  [{i}] <{tag}> visible={visible} text='{text}' class='{cls}'")


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # === STEP 1: Login Page ===
        print("\n>>> Opening login page...")
        await page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3)
        await page.screenshot(path="/tmp/inspect_01_login.png", full_page=True)
        await dump_elements(page, "LOGIN PAGE")

        # Save full HTML
        html = await page.content()
        with open("/tmp/inspect_01_login.html", "w") as f:
            f.write(html)
        print("\n  >> HTML saved to /tmp/inspect_01_login.html")

        # === STEP 2: Fill and submit login ===
        if EMAIL and PASSWORD:
            print("\n>>> Filling login form...")
            try:
                email_input = page.locator("input").first
                inputs = page.locator("input")
                count = await inputs.count()

                email_filled = False
                pass_filled = False
                for i in range(count):
                    inp = inputs.nth(i)
                    inp_type = (await inp.get_attribute("type") or "").lower()
                    if inp_type in ("email", "text") and not email_filled:
                        await inp.fill(EMAIL)
                        email_filled = True
                        print(f"  >> Email filled in input[{i}]")
                    elif inp_type == "password" and not pass_filled:
                        await inp.fill(PASSWORD)
                        pass_filled = True
                        print(f"  >> Password filled in input[{i}]")

                await page.screenshot(path="/tmp/inspect_02_filled.png")

                # Try clicking any visible button
                buttons = page.locator("button")
                btn_count = await buttons.count()
                for i in range(btn_count):
                    btn = buttons.nth(i)
                    if await btn.is_visible():
                        text = (await btn.inner_text()).strip()
                        print(f"  >> Clicking button[{i}]: '{text}'")
                        await btn.click()
                        break

                await asyncio.sleep(8)
                await page.screenshot(path="/tmp/inspect_03_after_login.png")
                print(f"\n>>> After login URL: {page.url}")
                await dump_elements(page, "AFTER LOGIN")

                html = await page.content()
                with open("/tmp/inspect_03_after_login.html", "w") as f:
                    f.write(html)

            except Exception as e:
                print(f"  !! Login error: {e}")
                await page.screenshot(path="/tmp/inspect_error.png")

        # === STEP 3: Navigate to Agent Console ===
        print(f"\n>>> Opening agent console: {CONSOLE_URL}")
        await page.goto(CONSOLE_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)
        await page.screenshot(path="/tmp/inspect_04_console.png", full_page=True)
        await dump_elements(page, "AGENT CONSOLE")

        html = await page.content()
        with open("/tmp/inspect_04_console.html", "w") as f:
            f.write(html)
        print("\n  >> HTML saved to /tmp/inspect_04_console.html")

        # Check for forced login
        print("\n>>> Checking for forced login prompt...")
        await asyncio.sleep(3)
        await page.screenshot(path="/tmp/inspect_05_console_after.png")
        await dump_elements(page, "CONSOLE AFTER WAIT")

        await context.close()
        await browser.close()

    print("\n\n=== SCREENSHOTS SAVED ===")
    print("  /tmp/inspect_01_login.png")
    print("  /tmp/inspect_02_filled.png")
    print("  /tmp/inspect_03_after_login.png")
    print("  /tmp/inspect_04_console.png")
    print("  /tmp/inspect_05_console_after.png")
    print("\nRun: cat /tmp/inspect_01_login.html | head -200")


if __name__ == "__main__":
    asyncio.run(main())
