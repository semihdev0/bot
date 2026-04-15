"""User profile page for Betronix - extracts all profile data.

Betronix profile has 4 info cards:
- Temel Bilgiler: Kullanıcı Adı, İsim, E-posta, Telefon, Cinsiyet
- Hesap Bilgileri: Durum, Kayıt Tarihi, Son Giriş, Son Giriş IP, Ortak, BTag ID
- Yatırım Bilgileri: İlk Yatırım, Son Yatırım, Yatırım Sayısı, Çekim Sayısı, Son Kullanılan Bonus
- Finansal Bilgiler: Bakiye, Bonus, Toplam Yatırım, Toplam Çekim, Kar/Zarar

Plus tabs: Yatırımlar, Çekimler, Bonuslar, etc.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import structlog
from playwright.async_api import Page

from src.config.selectors import SelectorRegistry
from src.engine.models import (
    BonusHistory,
    BonusHistoryEntry,
    DepositEntry,
    DepositHistory,
    UserProfile,
    WithdrawalEntry,
    WithdrawalHistory,
)
from src.pages.base import BasePage

logger = structlog.get_logger()

# Successful deposit/withdrawal status keywords (English + Turkish)
_SUCCESS_KEYWORDS = (
    "completed", "success", "approved", "confirmed", "accepted", "paid",
    "tamamlan", "başarılı", "onaylan", "kabul",
)
_FAILED_KEYWORDS = (
    "rejected", "cancelled", "failed", "declined", "denied",
    "başarısız", "iptal", "reddedil",
)


class UserProfilePage(BasePage):
    page_name = "user_profile_page"

    async def navigate_to_profile(
        self, base_url: str, path_template: str, user_id: str
    ) -> None:
        """Navigate to a user's profile page.

        The backoffice is a Next.js SPA.  After navigation the shell
        loads immediately but profile data is fetched asynchronously.
        We must wait until the profile cards have rendered before
        attempting to extract values.
        """
        path = path_template.format(user_id=user_id)
        url = f"{base_url.rstrip('/')}{path}"
        await self.page.goto(url, wait_until="networkidle", timeout=60000)

        # Wait for profile content to render (Next.js hydration + data fetch)
        # Look for any element containing ₺ (balance/deposit values) as a
        # signal that profile data has loaded.
        for attempt in range(10):
            text_nodes = await self.page.evaluate(
                """() => {
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT
                );
                let count = 0;
                while (walker.nextNode()) {
                    const t = walker.currentNode.textContent;
                    if (t.includes('₺') || t.includes('Balance') || t.includes('Bakiye')) {
                        count++;
                    }
                }
                return count;
            }"""
            )
            if text_nodes > 2:
                logger.debug(
                    "profile_content_loaded",
                    user_id=user_id,
                    attempt=attempt,
                    indicators=text_nodes,
                )
                break
            await asyncio.sleep(1)
        else:
            logger.warning("profile_content_slow_load", user_id=user_id)
            await asyncio.sleep(3)  # Last resort extra wait

        logger.debug("user_profile_loaded", user_id=user_id)

    async def navigate_via_username_link(self, link_locator) -> None:
        """Navigate to profile by clicking the username link in bonus list."""
        await link_locator.click()
        await self.page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)
        logger.debug("user_profile_loaded_via_link")

    async def extract_profile(self, user_id: str, username: str = "") -> UserProfile:
        """Extract all relevant user data from the Betronix profile page.

        Extracts data from:
        1. Profile info cards (Financial, Deposit, Account info) via JS DOM traversal
        2. Deposits tab (deposit history)
        3. Withdrawals tab (withdrawal history)
        4. Bonuses tab (bonus history)

        Panel UI can be English or Turkish - handles both.
        """
        # --- Extract all card values in one shot via JavaScript ---
        card = await self._extract_all_card_values(user_id)

        bakiye = card.get("bakiye", "")
        bonus_bakiye = card.get("bonus_bakiye", "")
        toplam_yatirim = card.get("toplam_yatirim", "")
        toplam_cekim = card.get("toplam_cekim", "")
        kar_zarar = card.get("kar_zarar", "")
        ilk_yatirim_raw = card.get("ilk_yatirim", "")
        son_yatirim_raw = card.get("son_yatirim", "")
        yatirim_sayisi_raw = card.get("yatirim_sayisi", "")
        cekim_sayisi_raw = card.get("cekim_sayisi", "")
        son_kullanilan_bonus = card.get("son_kullanilan_bonus", "")
        durum = card.get("durum", "")
        kayit_tarihi_raw = card.get("kayit_tarihi", "")
        son_giris_raw = card.get("son_giris", "")
        aktif_bonus = card.get("aktif_bonus", "")

        # Clean up aktif_bonus
        if aktif_bonus.strip().lower() in ("", "-", "none", "no bonus", "no bonus used"):
            aktif_bonus = ""

        logger.info(
            "profile_raw_values",
            user_id=user_id,
            bakiye=bakiye[:30] if bakiye else "",
            toplam_yatirim=toplam_yatirim[:30] if toplam_yatirim else "",
            durum=durum[:30] if durum else "EMPTY",
            yatirim_sayisi=yatirim_sayisi_raw[:30] if yatirim_sayisi_raw else "",
            son_yatirim=son_yatirim_raw[:30] if son_yatirim_raw else "",
            aktif_bonus=aktif_bonus[:30] if aktif_bonus else "",
        )

        # --- Tab Data: Yatırımlar, Çekimler, Bonuslar ---
        deposits = await self._extract_deposit_history()
        son_yatirim_tutari = self._get_last_successful_amount(deposits)
        withdrawals = await self._extract_withdrawal_history()
        bonus_history = await self._extract_bonus_history()

        profile = UserProfile(
            user_id=user_id,
            username=username,
            bakiye=self._parse_decimal(bakiye),
            bonus_bakiye=self._parse_decimal(bonus_bakiye),
            toplam_yatirim=self._parse_decimal(toplam_yatirim),
            toplam_cekim=self._parse_decimal(toplam_cekim),
            kar_zarar=self._parse_decimal(kar_zarar),
            ilk_yatirim_tarihi=self._parse_date(ilk_yatirim_raw),
            son_yatirim_tarihi=self._parse_date(son_yatirim_raw),
            son_yatirim_tutari=son_yatirim_tutari,
            yatirim_sayisi=self._parse_int(yatirim_sayisi_raw),
            cekim_sayisi=self._parse_int(cekim_sayisi_raw),
            son_kullanilan_bonus=son_kullanilan_bonus,
            durum=durum,
            kayit_tarihi=self._parse_date(kayit_tarihi_raw),
            son_giris=self._parse_date(son_giris_raw),
            aktif_bonus=aktif_bonus,
            deposits=deposits,
            withdrawals=withdrawals,
            bonus_history=bonus_history,
        )

        logger.info(
            "profile_extracted",
            user_id=user_id,
            bakiye=str(profile.bakiye),
            toplam_yatirim=str(profile.toplam_yatirim),
            yatirim_sayisi=profile.yatirim_sayisi,
            son_yatirim_tutari=str(profile.son_yatirim_tutari),
            aktif_bonus=profile.aktif_bonus,
            durum=profile.durum,
            deposits_count=len(deposits.entries),
            withdrawals_count=len(withdrawals.entries),
            bonus_history_count=len(bonus_history.entries),
        )
        return profile

    # ------------------------------------------------------------------
    # Tab extractors
    # ------------------------------------------------------------------

    async def _extract_deposit_history(self) -> DepositHistory:
        """Extract deposit entries from the Yatırımlar tab.

        Table columns: REFERANS KODU | TUTAR | YÖNTEM | DURUM | TARİH
        Green rows = successful, Red rows = failed.
        """
        entries: list[DepositEntry] = []
        try:
            await self._click_tab("Deposits", "Yatırımlar")
            await self._select_time_filter("All", "All Time", "Tüm Zamanlar")

            rows = self.page.locator("table tbody tr")
            count = await rows.count()

            for i in range(min(count, 50)):
                try:
                    row = rows.nth(i)
                    row_text = (await row.text_content() or "").lower()

                    # Determine success status from row text/style
                    is_successful = self._is_successful_status(row_text)

                    # Extract columns
                    amount_text = await self._safe_cell_text(row, 2)
                    method_text = await self._safe_cell_text(row, 3)
                    status_text = await self._safe_cell_text(row, 4)
                    date_text = await self._safe_cell_text(row, 5)

                    entries.append(DepositEntry(
                        amount=self._parse_decimal(amount_text),
                        status=status_text,
                        method=method_text,
                        date=self._parse_date(date_text),
                        is_successful=is_successful,
                    ))
                except Exception as e:
                    logger.debug("deposit_row_parse_error", row=i, error=str(e))
                    continue

            logger.debug("deposit_history_extracted", count=len(entries))
        except Exception as e:
            logger.warning("deposit_history_extraction_failed", error=str(e))

        return DepositHistory(entries=entries)

    async def _extract_withdrawal_history(self) -> WithdrawalHistory:
        """Extract withdrawal entries from the Withdrawals tab."""
        entries: list[WithdrawalEntry] = []
        try:
            await self._click_tab("Withdrawals", "Çekimler")
            await self._select_time_filter("All", "All Time", "Tüm Zamanlar")

            rows = self.page.locator("table tbody tr")
            count = await rows.count()

            for i in range(min(count, 50)):
                try:
                    row = rows.nth(i)
                    row_text = (await row.text_content() or "").lower()

                    is_successful = self._is_successful_status(row_text)

                    amount_text = await self._safe_cell_text(row, 2)
                    status_text = await self._safe_cell_text(row, 4)
                    date_text = await self._safe_cell_text(row, 5)

                    entries.append(WithdrawalEntry(
                        amount=self._parse_decimal(amount_text),
                        status=status_text,
                        date=self._parse_date(date_text),
                        is_successful=is_successful,
                    ))
                except Exception as e:
                    logger.debug("withdrawal_row_parse_error", row=i, error=str(e))
                    continue

            logger.debug("withdrawal_history_extracted", count=len(entries))
        except Exception as e:
            logger.warning("withdrawal_history_extraction_failed", error=str(e))

        return WithdrawalHistory(entries=entries)

    async def _extract_bonus_history(self) -> BonusHistory:
        """Extract bonus entries from the Bonuslar tab.

        Table columns: BONUS ADI | BONUS TUTARI | ÇEVRİM İLERLEMESİ | ÇEVRİM HEDEFİ | DURUM | TARİH
        """
        entries: list[BonusHistoryEntry] = []
        try:
            await self._click_tab("Bonuses", "Bonuslar")
            await self._select_time_filter("All", "All Time", "Tüm Zamanlar")

            rows = self.page.locator("table tbody tr")
            count = await rows.count()

            for i in range(min(count, 50)):
                try:
                    row = rows.nth(i)

                    bonus_name = await self._safe_cell_text(row, 1)
                    amount_text = await self._safe_cell_text(row, 2)
                    status_text = await self._safe_cell_text(row, 5)
                    date_text = await self._safe_cell_text(row, 6)

                    entries.append(BonusHistoryEntry(
                        bonus_name=bonus_name,
                        amount=self._parse_decimal(amount_text),
                        status=status_text.strip(),
                        date=self._parse_date(date_text),
                    ))
                except Exception as e:
                    logger.debug("bonus_row_parse_error", row=i, error=str(e))
                    continue

            logger.debug("bonus_history_extracted", count=len(entries))
        except Exception as e:
            logger.warning("bonus_history_extraction_failed", error=str(e))

        return BonusHistory(entries=entries)

    # ------------------------------------------------------------------
    # Tab helpers
    # ------------------------------------------------------------------

    async def _click_tab(self, *tab_names: str) -> None:
        """Click a profile tab trying multiple names (English/Turkish).

        IMPORTANT: The sidebar also has links like "Deposits" and
        "Withdrawals".  We must click the PROFILE TAB, not the sidebar.
        Strategy order:
        1. [role='tab'] buttons (shadcn/Radix tab components)
        2. Buttons within a tablist
        3. Last resort: any text match (but try Turkish names first
           since sidebar uses English)
        """
        for name in tab_names:
            # Strategy 1: role=tab (most specific, avoids sidebar)
            try:
                tab = self.page.get_by_role("tab", name=name, exact=True)
                if await tab.count() > 0:
                    await tab.first.click()
                    await asyncio.sleep(1.5)
                    logger.debug("tab_clicked", name=name, strategy="role_tab")
                    return
            except Exception:
                pass

            # Strategy 2: button inside a tablist
            try:
                tab = self.page.locator("[role='tablist'] button").filter(
                    has_text=name
                )
                if await tab.count() > 0:
                    await tab.first.click()
                    await asyncio.sleep(1.5)
                    logger.debug("tab_clicked", name=name, strategy="tablist_button")
                    return
            except Exception:
                pass

        # Strategy 3: try Turkish names first (sidebar uses English)
        for name in reversed(tab_names):
            try:
                tab = self.page.get_by_text(name, exact=True).first
                if await tab.count() > 0:
                    await tab.click()
                    await asyncio.sleep(1.5)
                    logger.debug("tab_clicked", name=name, strategy="text_fallback")
                    return
            except Exception:
                pass

        logger.warning("tab_not_found", tried=tab_names)

    async def _select_time_filter(self, *filter_names: str) -> None:
        """Select a time filter trying multiple names (English/Turkish)."""
        for name in filter_names:
            try:
                time_filter = self.page.get_by_text(name, exact=True).first
                if await time_filter.count() > 0:
                    await time_filter.click()
                    await asyncio.sleep(1)
                    return
            except Exception:
                continue

    async def _safe_cell_text(self, row, col_index: int) -> str:
        """Safely get text from a table cell by column index."""
        try:
            cell = row.locator(f"td:nth-child({col_index})")
            if await cell.count() > 0:
                return (await cell.text_content() or "").strip()
        except Exception:
            pass
        return ""

    @staticmethod
    def _is_successful_status(row_text: str) -> bool:
        """Determine if a row represents a successful transaction."""
        text = row_text.lower()
        if any(kw in text for kw in _FAILED_KEYWORDS):
            return False
        return any(kw in text for kw in _SUCCESS_KEYWORDS)

    @staticmethod
    def _get_last_successful_amount(deposits: DepositHistory) -> Decimal:
        """Get the amount of the most recent successful deposit."""
        last = deposits.last_successful
        return last.amount if last else Decimal("0")

    # ------------------------------------------------------------------
    # Card value extraction via JavaScript DOM traversal
    # ------------------------------------------------------------------

    # Map of label text (as it appears on page) → canonical key
    _LABEL_ALIASES: dict[str, str] = {
        "Bakiye": "bakiye",
        "Balance": "bakiye",
        "Bonus": "bonus_bakiye",
        "Toplam Yatırım": "toplam_yatirim",
        "Total Deposits": "toplam_yatirim",
        "Total Deposit": "toplam_yatirim",
        "Toplam Çekim": "toplam_cekim",
        "Total Withdrawals": "toplam_cekim",
        "Total Withdrawal": "toplam_cekim",
        "Kar/Zarar": "kar_zarar",
        "Profit/Loss": "kar_zarar",
        "İlk Yatırım": "ilk_yatirim",
        "First Deposit": "ilk_yatirim",
        "Son Yatırım": "son_yatirim",
        "Last Deposit": "son_yatirim",
        "Yatırım Sayısı": "yatirim_sayisi",
        "Deposit Count": "yatirim_sayisi",
        "Çekim Sayısı": "cekim_sayisi",
        "Withdrawal Count": "cekim_sayisi",
        "Son Kullanılan Bonus": "son_kullanilan_bonus",
        "Last Bonus": "son_kullanilan_bonus",
        "Durum": "durum",
        "Status": "durum",
        "Account Status": "durum",
        "Hesap Durumu": "durum",
        "Kayıt Tarihi": "kayit_tarihi",
        "Registration Date": "kayit_tarihi",
        "Registered": "kayit_tarihi",
        "Son Giriş": "son_giris",
        "Last Login": "son_giris",
        "Last Sign In": "son_giris",
        "Aktif Bonus": "aktif_bonus",
        "Active Bonus": "aktif_bonus",
    }

    _EXTRACT_CARDS_JS = """(labels) => {
        const result = {};

        // ---- Strategy 1: DOM traversal ----
        // Walk all text nodes, find exact label matches,
        // then climb up to 5 parent levels looking for a sibling
        // element that contains the value.
        const walker = document.createTreeWalker(
            document.body, NodeFilter.SHOW_TEXT
        );
        const found = [];
        while (walker.nextNode()) {
            const t = walker.currentNode.textContent.trim();
            if (t && labels.includes(t)) {
                found.push({ text: t, el: walker.currentNode.parentElement });
            }
        }

        for (const { text, el } of found) {
            if (result[text]) continue;

            let current = el;
            for (let lvl = 0; lvl < 5; lvl++) {
                const sib = current.nextElementSibling;
                if (sib) {
                    const val = (sib.innerText || sib.textContent || '').trim();
                    // Accept if non-empty, different from label, and not another label
                    if (val && val !== text && !labels.includes(val)) {
                        result[text] = val.split('\\n')[0].trim();
                        break;
                    }
                }
                const parent = current.parentElement;
                if (!parent || parent === document.body) break;
                current = parent;
            }
        }

        // ---- Strategy 2: innerText line-by-line fallback ----
        // Label on one line, value on the next line.
        const lines = document.body.innerText
            .split('\\n')
            .map(l => l.trim())
            .filter(l => l.length > 0);

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            if (labels.includes(line) && !result[line] && i + 1 < lines.length) {
                const next = lines[i + 1];
                if (!labels.includes(next)) {
                    result[line] = next;
                }
            }
        }

        return result;
    }"""

    async def _extract_all_card_values(self, user_id: str) -> dict[str, str]:
        """Extract all profile card values using JavaScript DOM traversal.

        Two strategies run inside a single page.evaluate() call:
        1. DOM traversal – find exact label text nodes, walk up to 5
           parent levels checking for a next-sibling with the value.
        2. innerText fallback – label on one line, value on the next.

        Returns a dict mapping canonical keys (bakiye, durum, …) to
        raw string values.
        """
        label_list = list(self._LABEL_ALIASES.keys())

        try:
            js_result: dict[str, str] = await self.page.evaluate(
                self._EXTRACT_CARDS_JS, label_list
            )
        except Exception as e:
            logger.error("card_extraction_js_failed", error=str(e))
            js_result = {}

        # Also log page text for debugging
        try:
            page_text = await self.page.evaluate("() => document.body.innerText")
            logger.info(
                "profile_page_dump",
                user_id=user_id,
                text_length=len(page_text),
                first_500=page_text[:500],
            )
        except Exception:
            pass

        # Map label aliases → canonical keys
        canonical: dict[str, str] = {}
        for label_text, raw_value in js_result.items():
            key = self._LABEL_ALIASES.get(label_text)
            if key and key not in canonical and raw_value:
                canonical[key] = raw_value

        logger.info(
            "card_values_extracted",
            user_id=user_id,
            found_keys=list(canonical.keys()),
            values={k: v[:50] for k, v in canonical.items()},
        )
        return canonical

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_decimal(text: str) -> Decimal:
        """Parse a decimal value from Betronix text format.

        Handles Turkish number formatting:
          '13.915 ₺'      → 13915  (dot = thousands separator)
          '1.000.000 ₺'   → 1000000
          '2.500,50 ₺'    → 2500.50  (comma = decimal separator)
          '100 ₺'          → 100
          '+1.000 ₺'       → 1000
          '-500 ₺'         → -500
          '3.50'           → 3.50  (dot = decimal when not 3 digits)

        Rules:
        - If comma exists → dots are thousands, comma is decimal
        - If only dots → check if all parts after first have exactly
          3 digits (then dots are thousands separators)
        - Otherwise → dot is decimal separator
        """
        cleaned = (
            text.replace("₺", "")
            .replace("TL", "")
            .replace("+", "")
            .replace(" ", "")
            .strip()
        )
        if not cleaned or cleaned == "-":
            return Decimal("0")

        # Preserve negative sign
        negative = cleaned.startswith("-")
        if negative:
            cleaned = cleaned[1:]

        if "," in cleaned:
            # Turkish decimal format: 1.000.000,50 → 1000000.50
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            parts = cleaned.split(".")
            if len(parts) >= 2:
                # Check if ALL parts after the first have exactly 3 digits
                # e.g. "1.000.000" → ["1", "000", "000"] → all 3-digit → thousands
                # e.g. "3.50" → ["3", "50"] → "50" is 2 digits → decimal
                all_thousands = all(len(p) == 3 for p in parts[1:])
                if all_thousands:
                    cleaned = cleaned.replace(".", "")
                # else: single dot with non-3-digit part → it's a decimal point

        try:
            result = Decimal(cleaned)
            return -result if negative else result
        except (InvalidOperation, ValueError):
            return Decimal("0")

    @staticmethod
    def _parse_int(text: str) -> int:
        """Parse integer from text."""
        cleaned = re.sub(r"[^\d]", "", text)
        return int(cleaned) if cleaned else 0

    @staticmethod
    def _parse_date(text: str) -> datetime | None:
        """Parse date from Betronix format.

        Supports:
        - Relative: '8h ago', '2d ago', '30m ago', '1w ago'
        - Absolute: '15.04.2026 17:00'
        - Mixed:    '8h ago 15.04.2026 17:00'
        """
        if not text or text.strip() in ("", "-"):
            return None

        # --- Strategy 1: Absolute date pattern dd.mm.YYYY HH:MM ---
        date_match = re.search(r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})", text)
        if date_match:
            try:
                return datetime.strptime(date_match.group(1), "%d.%m.%Y %H:%M")
            except ValueError:
                pass

        # dd/mm/YYYY HH:MM pattern
        date_match = re.search(r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})", text)
        if date_match:
            try:
                return datetime.strptime(date_match.group(1), "%d/%m/%Y %H:%M")
            except ValueError:
                pass

        # --- Strategy 2: Relative time ("8h ago", "2d ago", "30m ago") ---
        rel_match = re.search(r"(\d+)\s*(m|h|d|w)\s*ago", text, re.IGNORECASE)
        if rel_match:
            amount = int(rel_match.group(1))
            unit = rel_match.group(2).lower()
            now = datetime.now()
            if unit == "m":
                return now - timedelta(minutes=amount)
            elif unit == "h":
                return now - timedelta(hours=amount)
            elif unit == "d":
                return now - timedelta(days=amount)
            elif unit == "w":
                return now - timedelta(weeks=amount)

        # --- Strategy 3: Try common date formats line by line ---
        for fmt in (
            "%d.%m.%Y %H:%M",
            "%d.%m.%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%d.%m.%Y",
            "%d/%m/%Y",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    return datetime.strptime(line, fmt)
                except ValueError:
                    continue

        return None
