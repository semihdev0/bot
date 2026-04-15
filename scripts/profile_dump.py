"""Dump profile page structure to understand label-value extraction."""

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
        await asyncio.sleep(3)

        # Dump all label-value pairs from the page
        data = await page.evaluate(
            """() => {
            const results = [];
            const allEls = document.querySelectorAll('*');
            for (const el of allEls) {
                const children = el.children;
                if (children.length === 2) {
                    const c1 = children[0].textContent.trim();
                    const c2 = children[1].textContent.trim();
                    if (c1.length > 1 && c1.length < 35 && c2.length > 0 && c2.length < 60) {
                        results.push({label: c1, value: c2, tag: el.tagName, cls: (el.className||'').toString().substring(0,80)});
                    }
                }
            }
            return results;
        }"""
        )

        print("=== LABEL-VALUE PAIRS (2-child pattern) ===")
        seen = set()
        for d in data:
            key = d["label"] + "|" + d["value"]
            if key not in seen:
                seen.add(key)
                print(
                    f'  {d["label"]:30s} => {d["value"][:50]:50s}  [{d["tag"]}.{d["cls"][:40]}]'
                )

        # Also try: find all text elements and their next siblings
        data2 = await page.evaluate(
            """() => {
            const results = [];
            const labels = ['Balance','Bonus','Total Deposit','Total Withdrawal','Profit','Status','Registered','Last Login','First Deposit','Last Deposit','Deposit Count','Withdrawal Count','Last Bonus','Active Bonus','Bakiye','Durum','Toplam','GGR','NGR','Deposit','Withdrawal'];
            for (const label of labels) {
                const els = document.querySelectorAll('*');
                for (const el of els) {
                    if (el.children.length === 0 && el.textContent.trim() === label) {
                        const parent = el.parentElement;
                        const grandparent = parent ? parent.parentElement : null;
                        results.push({
                            label: label,
                            elTag: el.tagName,
                            parentText: (parent ? parent.textContent.trim() : '').substring(0,80),
                            parentTag: parent ? parent.tagName : '',
                            parentCls: parent ? (parent.className||'').toString().substring(0,80) : '',
                            gpText: (grandparent ? grandparent.textContent.trim() : '').substring(0,120),
                            gpTag: grandparent ? grandparent.tagName : '',
                            nextSibling: el.nextElementSibling ? el.nextElementSibling.textContent.trim().substring(0,60) : 'NONE',
                            parentNextSib: parent && parent.nextElementSibling ? parent.nextElementSibling.textContent.trim().substring(0,60) : 'NONE',
                        });
                    }
                }
            }
            return results;
        }"""
        )

        print()
        print("=== KNOWN LABELS LOOKUP ===")
        for d in data2:
            print(f'Label: "{d["label"]}" (in <{d["elTag"]}>)')
            print(f'  parent: <{d["parentTag"]}> cls={d["parentCls"][:60]}')
            print(f'  parentText: {d["parentText"]}')
            print(f'  nextSibling: {d["nextSibling"]}')
            print(f'  parentNextSib: {d["parentNextSib"]}')
            print(f'  gpText: {d["gpText"]}')
            print()

        await b.close()


asyncio.run(main())
