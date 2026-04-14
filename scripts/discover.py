"""Discovery script - Betronix paneline bağlanıp gerçek DOM yapısını çeker.

Bu scripti kendi bilgisayarınızda veya VPS'inizde çalıştırın:
  python scripts/discover.py

Sonuç logs/discovery_output.txt dosyasına kaydedilir.
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

URL = os.environ.get("BACKOFFICE_URL", "https://bo.betronix.net")
USERNAME = os.environ.get("BACKOFFICE_USERNAME", "")
PASSWORD = os.environ.get("BACKOFFICE_PASSWORD", "")
COMPANY_CODE = os.environ.get("BACKOFFICE_COMPANY_CODE", "")

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
OUTPUT = LOG_DIR / "discovery_output.txt"


def log(msg: str):
    print(msg)
    with open(OUTPUT, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


async def main():
    # Clear previous output
    OUTPUT.write_text("", encoding="utf-8")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # Visible mode
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        # ========== STEP 1: LOGIN ==========
        log("=" * 60)
        log("STEP 1: LOGIN")
        log("=" * 60)
        await page.goto(f"{URL}/login", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Get all inputs
        inputs = await page.query_selector_all("input")
        log(f"\nInput sayisi: {len(inputs)}")
        for i, inp in enumerate(inputs):
            attrs = {}
            for attr in ["type", "name", "id", "placeholder", "class"]:
                val = await inp.get_attribute(attr) or ""
                if val:
                    attrs[attr] = val[:80]
            log(f"  input[{i}]: {attrs}")

        # Fill form
        if len(inputs) >= 3:
            await inputs[0].fill(COMPANY_CODE)
            await inputs[1].fill(USERNAME)
            await inputs[2].fill(PASSWORD)
            log("Form dolduruldu")

        # Click Sign In
        await page.get_by_text("Sign In").click()
        await asyncio.sleep(5)
        log(f"Login sonrasi URL: {page.url}")

        # ========== STEP 2: BONUS LIST ==========
        log("\n" + "=" * 60)
        log("STEP 2: BONUS TALEPLERI SAYFASI")
        log("=" * 60)
        await page.goto(f"{URL}/bonus-requests", wait_until="domcontentloaded")
        await asyncio.sleep(5)

        # Table headers
        headers = await page.query_selector_all("th")
        header_info = []
        for h in headers:
            txt = (await h.text_content() or "").strip()
            cls = await h.get_attribute("class") or ""
            header_info.append(f"'{txt}' class={cls[:60]}")
        log(f"\nTablo basliklari ({len(headers)}):")
        for hi in header_info:
            log(f"  {hi}")

        # Table rows
        rows = await page.query_selector_all("table tbody tr")
        log(f"\nSatir sayisi: {len(rows)}")

        if rows:
            # Analyze first 2 rows in detail
            for ri in range(min(2, len(rows))):
                row = rows[ri]
                row_cls = await row.get_attribute("class") or ""
                cells = await row.query_selector_all("td")
                log(f"\n  Satir[{ri}] class='{row_cls[:60]}' | {len(cells)} hucre:")
                for ci, cell in enumerate(cells):
                    txt = (await cell.text_content() or "").strip()[:60]
                    cls = await cell.get_attribute("class") or ""
                    log(f"    td[{ci}]: '{txt}' class='{cls[:60]}'")

                # Action buttons in last cell
                last_cell = cells[-1] if cells else None
                if last_cell:
                    btns = await last_cell.query_selector_all("button, svg, a, span[role='button']")
                    log(f"    Son hucredeki butonlar ({len(btns)}):")
                    for bi, btn in enumerate(btns):
                        html = await btn.evaluate("el => el.outerHTML")
                        log(f"      btn[{bi}]: {html[:200]}")

        # ========== STEP 3: APPROVE MODAL ==========
        log("\n" + "=" * 60)
        log("STEP 3: ONAY MODALI")
        log("=" * 60)

        if rows:
            first_row = rows[0]
            btns = await first_row.query_selector_all("button")
            if btns:
                log(f"Ilk satirdaki buton tiklaniyor...")
                await btns[0].click()
                await asyncio.sleep(2)

                # Find modal
                modals = await page.query_selector_all(
                    "[class*='modal'], [class*='dialog'], [role='dialog'], "
                    "[class*='Modal'], [class*='Dialog'], [class*='overlay']"
                )
                log(f"Modal sayisi: {len(modals)}")
                for mi, modal in enumerate(modals):
                    html = await modal.inner_html()
                    log(f"\n  Modal[{mi}] HTML (ilk 2000 karakter):")
                    log(f"  {html[:2000]}")

                    # Inputs
                    m_inputs = await modal.query_selector_all("input, textarea, select")
                    for inp in m_inputs:
                        attrs = {}
                        for attr in ["type", "name", "id", "placeholder", "class"]:
                            val = await inp.get_attribute(attr) or ""
                            if val:
                                attrs[attr] = val[:60]
                        log(f"    Input: {attrs}")

                    # Buttons
                    m_btns = await modal.query_selector_all("button")
                    for btn in m_btns:
                        txt = (await btn.text_content() or "").strip()
                        cls = await btn.get_attribute("class") or ""
                        log(f"    Button: '{txt}' class='{cls[:60]}'")

                    # Checkboxes
                    cbs = await modal.query_selector_all(
                        "input[type='checkbox'], [role='checkbox']"
                    )
                    for cb in cbs:
                        cb_html = await cb.evaluate("el => el.outerHTML")
                        log(f"    Checkbox: {cb_html[:150]}")

                # Close modal
                await page.keyboard.press("Escape")
                await asyncio.sleep(1)

        # ========== STEP 4: USER PROFILE ==========
        log("\n" + "=" * 60)
        log("STEP 4: KULLANICI PROFILI")
        log("=" * 60)

        # Find username links
        user_links = await page.query_selector_all(
            "a[href*='player'], a[href*='user'], a[href*='oyuncu']"
        )
        log(f"Kullanici linkleri: {len(user_links)}")
        for ul in user_links[:3]:
            href = await ul.get_attribute("href") or ""
            txt = (await ul.text_content() or "").strip()[:30]
            log(f"  '{txt}' -> {href}")

        if user_links:
            href = await user_links[0].get_attribute("href") or ""
            profile_url = href if href.startswith("http") else f"{URL}{href}"
            log(f"\nProfil aciliyor: {profile_url}")
            await page.goto(profile_url, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            # Find label-value pairs
            labels = [
                "Bakiye", "Bonus", "Toplam Yatırım", "Toplam Çekim", "Kar/Zarar",
                "İlk Yatırım", "Son Yatırım", "Yatırım Sayısı", "Çekim Sayısı",
                "Son Kullanılan Bonus", "Durum", "Kayıt Tarihi", "Son Giriş",
                "Aktif Bonus",
            ]
            log("\nProfil verileri:")
            for label in labels:
                els = await page.get_by_text(label, exact=False).all()
                for el in els[:1]:
                    parent = await el.evaluate_handle("el => el.parentElement")
                    p_text = await parent.evaluate("el => el.textContent || ''")
                    p_class = await parent.evaluate("el => el.className || ''")
                    p_tag = await parent.evaluate("el => el.tagName")
                    clean = " ".join(p_text.split())[:120]
                    log(f"  [{label}] <{p_tag}> class='{str(p_class)[:50]}' -> {clean}")

            # Full page screenshot
            await page.screenshot(path=str(LOG_DIR / "profile_page.png"), full_page=True)
            log("Profil ekran goruntusu: logs/profile_page.png")

        # ========== DONE ==========
        log("\n" + "=" * 60)
        log("KESFET TAMAMLANDI!")
        log(f"Sonuclar: {OUTPUT}")
        log("=" * 60)

        input("\nTarayiciyi kapatmak icin Enter'a basin...")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
