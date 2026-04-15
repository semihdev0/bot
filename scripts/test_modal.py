#!/usr/bin/env python3
"""Discover the actual modal structure on Betronix backoffice.

This script:
1. Logs into the panel
2. Navigates to bonus-requests
3. Finds a pending ("Beklemede") row
4. Clicks the REJECT button (red) on that row
5. Waits for the modal and dumps ALL visible elements
6. Takes a screenshot
7. Tries to find the confirm button
8. Closes the modal WITHOUT confirming (presses Escape)

Run on VPS:
    cd /home/user/bot
    .venv/bin/python scripts/test_modal.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

URL = os.environ.get("BACKOFFICE_URL", "https://bo.betronix.net")
USERNAME = os.environ.get("BACKOFFICE_USERNAME", "")
PASSWORD = os.environ.get("BACKOFFICE_PASSWORD", "")
COMPANY_CODE = os.environ.get("BACKOFFICE_COMPANY_CODE", "")


async def main():
    print("=" * 60)
    print("BETRONIX MODAL DISCOVERY SCRIPT")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        # --- LOGIN ---
        print("\n[1] Logging in...")
        await page.goto(f"{URL}/login", wait_until="commit", timeout=60000)
        await page.wait_for_selector("input[name='companyId']", state="visible", timeout=30000)
        await asyncio.sleep(1)
        await page.fill("input[name='companyId']", COMPANY_CODE)
        await page.fill("input[name='username']", USERNAME)
        await page.fill("input[name='password']", PASSWORD)
        await page.get_by_text("Sign In").click()

        try:
            await page.wait_for_url(lambda u: "login" not in u.lower(), timeout=15000)
        except Exception:
            await asyncio.sleep(3)

        print(f"    Current URL: {page.url}")
        if "login" in page.url.lower():
            print("    ERROR: Still on login page!")
            await browser.close()
            return

        print("    Login successful!")

        # --- NAVIGATE TO BONUS REQUESTS ---
        print("\n[2] Navigating to bonus-requests...")
        await page.goto(f"{URL}/bonus-requests", wait_until="commit", timeout=60000)
        await asyncio.sleep(3)
        print(f"    Current URL: {page.url}")

        # --- CLICK BEKLEMEDE TAB ---
        print("\n[3] Clicking 'Beklemede' filter tab...")
        try:
            beklemede_tab = page.get_by_text("Beklemede")
            if await beklemede_tab.count() > 0:
                await beklemede_tab.first.click()
                await asyncio.sleep(2)
                print("    Beklemede tab clicked!")
            else:
                print("    Beklemede tab not found, continuing with current view")
        except Exception as e:
            print(f"    Tab click error: {e}")

        # --- FIND A ROW (all rows are pending on Beklemede tab) ---
        print("\n[4] Looking for rows...")
        rows = page.locator("table tbody tr")
        row_count = await rows.count()
        print(f"    Total rows: {row_count}")

        # Dump first 3 rows to see structure
        for i in range(min(row_count, 3)):
            row = rows.nth(i)
            cols = row.locator("td")
            col_count = await cols.count()
            print(f"    Row {i} has {col_count} columns:")
            for j in range(col_count):
                t = (await cols.nth(j).text_content() or "").strip()
                print(f"      td[{j}]: {t[:80]}")

        target_row = rows.first if row_count > 0 else None

        if target_row is None or row_count == 0:
            print("    No rows found! Cannot test modal.")
            await page.screenshot(path="scripts/no_rows.png")
            await browser.close()
            return

        # --- DUMP ACTION BUTTONS ON THE ROW ---
        print("\n[4] Inspecting action buttons on the row...")
        action_buttons = target_row.locator("td:last-child button")
        btn_count = await action_buttons.count()
        print(f"    Buttons in last cell: {btn_count}")

        for i in range(btn_count):
            btn = action_buttons.nth(i)
            btn_text = (await btn.text_content() or "").strip()
            btn_class = (await btn.get_attribute("class") or "")
            btn_type = (await btn.get_attribute("type") or "")
            btn_aria = (await btn.get_attribute("aria-label") or "")
            print(f"    Button {i}: text='{btn_text}' type='{btn_type}' "
                  f"aria='{btn_aria}' class='{btn_class[:80]}'")

        # --- CLICK REJECT BUTTON ---
        print("\n[5] Clicking REJECT button (red)...")
        reject_btn = target_row.locator("td:last-child button[class*='red']").first
        if await reject_btn.count() == 0:
            # Try alternative: second button (typically reject)
            reject_btn = action_buttons.nth(1) if btn_count >= 2 else None
            if reject_btn is None:
                print("    ERROR: No reject button found!")
                await browser.close()
                return
            print("    Using fallback: second button in action cell")
        else:
            print("    Found red button")

        await reject_btn.click()
        print("    Clicked! Waiting for modal...")
        await asyncio.sleep(2)

        # --- SCREENSHOT ---
        await page.screenshot(path="scripts/modal_screenshot.png", full_page=True)
        print("    Screenshot saved: scripts/modal_screenshot.png")

        # --- DUMP MODAL STRUCTURE ---
        print("\n[6] Inspecting modal structure...")

        # Check various modal selectors
        modal_selectors = [
            "[role='dialog']",
            "[aria-modal='true']",
            "dialog[open]",
            "[data-state='open']",
            "[class*='modal']",
            "[class*='Modal']",
            "[class*='dialog']",
            "[class*='Dialog']",
            "[class*='overlay']",
            "[class*='Overlay']",
            "div.fixed",
        ]

        for sel in modal_selectors:
            try:
                loc = page.locator(sel)
                cnt = await loc.count()
                if cnt > 0:
                    for j in range(min(cnt, 3)):
                        el = loc.nth(j)
                        vis = await el.is_visible()
                        tag = await el.evaluate("el => el.tagName")
                        cls = (await el.get_attribute("class") or "")[:100]
                        text_preview = (await el.text_content() or "").strip()[:100]
                        print(f"    {sel} [{j}]: visible={vis} tag={tag} "
                              f"class='{cls}' text='{text_preview}'")
            except Exception as e:
                pass

        # --- DUMP ALL VISIBLE BUTTONS ---
        print("\n[7] All visible buttons on page:")
        all_buttons = page.locator("button:visible")
        visible_count = await all_buttons.count()
        print(f"    Total visible buttons: {visible_count}")

        for i in range(min(visible_count, 30)):
            btn = all_buttons.nth(i)
            btn_text = (await btn.text_content() or "").strip()
            btn_class = (await btn.get_attribute("class") or "")[:100]
            btn_type = (await btn.get_attribute("type") or "")
            btn_aria = (await btn.get_attribute("aria-label") or "")
            btn_role = (await btn.get_attribute("role") or "")
            print(f"    [{i}] text='{btn_text}' type='{btn_type}' "
                  f"role='{btn_role}' aria='{btn_aria}' class='{btn_class}'")

        # --- CHECK FOR TEXTAREA/INPUTS ---
        print("\n[8] Visible textareas and text inputs:")
        for sel, label in [
            ("textarea:visible", "textarea"),
            ("input[type='text']:visible", "text input"),
            ("input:visible", "any input"),
        ]:
            loc = page.locator(sel)
            cnt = await loc.count()
            if cnt > 0:
                for i in range(min(cnt, 5)):
                    el = loc.nth(i)
                    name = (await el.get_attribute("name") or "")
                    placeholder = (await el.get_attribute("placeholder") or "")
                    inp_type = (await el.get_attribute("type") or "")
                    cls = (await el.get_attribute("class") or "")[:80]
                    print(f"    {label} [{i}]: name='{name}' placeholder='{placeholder}' "
                          f"type='{inp_type}' class='{cls}'")

        # --- TRY SPECIFIC BUTTON TEXTS ---
        print("\n[9] Searching for specific button texts:")
        test_texts = [
            "Reddet", "reddet", "REDDET",
            "Onayla", "Evet", "Tamam", "Kaydet",
            "İptal", "Kapat", "Vazgeç",
            "Confirm", "Reject", "Cancel",
            "Talebi Reddet", "Evet, Reddet",
        ]
        for text in test_texts:
            try:
                exact = await page.get_by_text(text, exact=True).count()
                partial = await page.get_by_text(text, exact=False).count()
                role = await page.get_by_role("button", name=text).count()
                if exact > 0 or partial > 0 or role > 0:
                    print(f"    '{text}': exact={exact} partial={partial} role_button={role}")
            except Exception:
                pass

        # --- DUMP FULL MODAL HTML ---
        print("\n[10] Full modal/dialog HTML (if found):")
        for sel in ["[role='dialog']", "[aria-modal='true']", "[class*='modal']:visible"]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    html = await el.evaluate("el => el.outerHTML")
                    # Truncate for readability
                    if len(html) > 3000:
                        html = html[:3000] + "\n... [TRUNCATED]"
                    print(f"\n    --- {sel} HTML ---")
                    print(f"    {html}")
                    break
            except Exception:
                pass

        # --- CLOSE MODAL WITHOUT CONFIRMING ---
        print("\n[11] Closing modal (Escape)...")
        await page.keyboard.press("Escape")
        await asyncio.sleep(1)

        # --- NOW TEST APPROVE MODAL ---
        print("\n" + "=" * 60)
        print("TESTING APPROVE MODAL")
        print("=" * 60)

        # Re-find the row (may have changed)
        rows = page.locator("table tbody tr")
        target_row = None
        for i in range(await rows.count()):
            row = rows.nth(i)
            text = (await row.text_content() or "").lower()
            if "beklemede" in text:
                target_row = row
                break

        if target_row:
            print("\n[12] Clicking APPROVE button (green/emerald)...")
            approve_btn = target_row.locator("td:last-child button[class*='emerald']").first
            if await approve_btn.count() == 0:
                approve_btn = target_row.locator("td:last-child button").first
                print("    Using fallback: first button")
            else:
                print("    Found emerald button")

            await approve_btn.click()
            await asyncio.sleep(2)

            await page.screenshot(path="scripts/approve_modal_screenshot.png", full_page=True)
            print("    Screenshot saved: scripts/approve_modal_screenshot.png")

            # Dump all visible buttons
            print("\n[13] All visible buttons after approve click:")
            all_buttons = page.locator("button:visible")
            for i in range(min(await all_buttons.count(), 30)):
                btn = all_buttons.nth(i)
                btn_text = (await btn.text_content() or "").strip()
                btn_class = (await btn.get_attribute("class") or "")[:100]
                print(f"    [{i}] text='{btn_text}' class='{btn_class}'")

            # Search specific texts
            print("\n[14] Searching for approve button texts:")
            for text in test_texts:
                try:
                    exact = await page.get_by_text(text, exact=True).count()
                    if exact > 0:
                        print(f"    '{text}': found {exact} match(es)")
                except Exception:
                    pass

            # Dump modal HTML
            for sel in ["[role='dialog']", "[aria-modal='true']", "[class*='modal']:visible"]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        html = await el.evaluate("el => el.outerHTML")
                        if len(html) > 3000:
                            html = html[:3000] + "\n... [TRUNCATED]"
                        print(f"\n    --- APPROVE {sel} HTML ---")
                        print(f"    {html}")
                        break
                except Exception:
                    pass

            # Close
            await page.keyboard.press("Escape")
            await asyncio.sleep(1)

        print("\n" + "=" * 60)
        print("DISCOVERY COMPLETE")
        print("=" * 60)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
