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
from datetime import datetime
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
_SUCCESS_KEYWORDS = ("completed", "success", "tamamlan", "başarılı", "onaylan")
_FAILED_KEYWORDS = ("rejected", "cancelled", "failed", "başarısız", "iptal", "reddedil")


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
        1. Profile info cards (Financial, Deposit, Account info)
        2. Deposits tab (deposit history)
        3. Withdrawals tab (withdrawal history)
        4. Bonuses tab (bonus history)

        Panel UI can be English or Turkish - tries both.
        """
        # --- DEBUG: Dump page text to understand structure ---
        all_texts = await self.page.evaluate(
            """() => {
            const results = [];
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT
            );
            while (walker.nextNode()) {
                const t = walker.currentNode.textContent.trim();
                if (t.length > 1 && t.length < 80) {
                    results.push(t);
                }
            }
            return results;
        }"""
        )
        logger.info(
            "profile_page_texts",
            user_id=user_id,
            total=len(all_texts),
            texts=str(all_texts[:40]),
        )

        # --- Financial Information card ---
        bakiye = await self._extract_value_by_labels("Balance", "Bakiye")
        bonus_bakiye = await self._extract_value_by_labels("Bonus")
        toplam_yatirim = await self._extract_value_by_labels(
            "Total Deposits", "Total Deposit", "Toplam Yatırım"
        )
        toplam_cekim = await self._extract_value_by_labels(
            "Total Withdrawals", "Total Withdrawal", "Toplam Çekim"
        )
        kar_zarar = await self._extract_value_by_labels("Profit/Loss", "Kar/Zarar")

        # --- Deposit Info card ---
        ilk_yatirim_raw = await self._extract_value_by_labels(
            "First Deposit", "İlk Yatırım"
        )
        son_yatirim_raw = await self._extract_value_by_labels(
            "Last Deposit", "Son Yatırım"
        )
        yatirim_sayisi_raw = await self._extract_value_by_labels(
            "Deposit Count", "Yatırım Sayısı"
        )
        cekim_sayisi_raw = await self._extract_value_by_labels(
            "Withdrawal Count", "Çekim Sayısı"
        )
        son_kullanilan_bonus = await self._extract_value_by_labels(
            "Last Bonus", "Son Kullanılan Bonus"
        )

        # --- Account Information card ---
        durum = await self._extract_value_by_labels(
            "Status", "Account Status", "Durum", "Hesap Durumu"
        )
        kayit_tarihi_raw = await self._extract_value_by_labels(
            "Registered", "Registration Date", "Kayıt Tarihi"
        )
        son_giris_raw = await self._extract_value_by_labels(
            "Last Login", "Last Sign In", "Son Giriş"
        )

        # Debug: log all extracted raw values
        logger.info(
            "profile_raw_values",
            user_id=user_id,
            bakiye=bakiye[:30] if bakiye else "",
            toplam_yatirim=toplam_yatirim[:30] if toplam_yatirim else "",
            durum=durum[:30] if durum else "EMPTY",
            yatirim_sayisi=yatirim_sayisi_raw[:30] if yatirim_sayisi_raw else "",
            son_yatirim=son_yatirim_raw[:30] if son_yatirim_raw else "",
            aktif_bonus=(await self._extract_aktif_bonus())[:30],
        )

        # --- Active Bonus ---
        aktif_bonus = await self._extract_aktif_bonus()

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
        """Click a tab trying multiple names (English/Turkish)."""
        for name in tab_names:
            tab = self.page.get_by_text(name, exact=True).first
            if await tab.count() > 0:
                await tab.click()
                await asyncio.sleep(1.5)
                logger.debug("tab_clicked", name=name)
                return
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
    # Label-based extraction (profile cards)
    # ------------------------------------------------------------------

    async def _extract_value_by_labels(self, *labels: str) -> str:
        """Try multiple labels (English/Turkish) and return first match."""
        for label in labels:
            value = await self._extract_value_by_label(label)
            if value and value != "-" and value != "0":
                return value
        # Second pass: accept "0" or "-" if nothing better
        for label in labels:
            value = await self._extract_value_by_label(label)
            if value:
                return value
        return ""

    async def _extract_value_by_label(self, label: str) -> str:
        """Extract the value next to a label on the profile page."""
        try:
            label_locator = self.page.get_by_text(label, exact=False).first
            if await label_locator.count() == 0:
                return ""

            parent = label_locator.locator("..")
            parent_text = await parent.text_content() or ""
            value = parent_text.replace(label, "").strip()
            value = re.sub(r"\s+", " ", value).strip()

            logger.debug("label_value_extracted", label=label, value=value[:50])
            return value
        except Exception as e:
            logger.debug("label_extraction_failed", label=label, error=str(e))
            return ""

    async def _extract_aktif_bonus(self) -> str:
        """Extract active bonus name from the Active Bonus section."""
        for label in ("Active Bonus", "Aktif Bonus"):
            try:
                section = self.page.get_by_text(label, exact=False).first
                if await section.count() > 0:
                    parent = section.locator("..")
                    text = await parent.text_content() or ""
                    cleaned = text.replace(label, "").strip()
                    if cleaned and cleaned not in ("-", "None", "No bonus"):
                        return cleaned.split("\n")[0].strip()
            except Exception:
                continue
        return ""

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

        Profile cards show: '6h ago 15.04.2026 17:00' or '03/25, 03:17 PM 25.03.2026 15:17'
        We extract the dd.mm.YYYY HH:MM pattern wherever it appears.
        """
        if not text or text.strip() in ("", "-"):
            return None

        # Try to find a dd.mm.YYYY HH:MM pattern anywhere in the text
        date_match = re.search(r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})", text)
        if date_match:
            try:
                return datetime.strptime(date_match.group(1), "%d.%m.%Y %H:%M")
            except ValueError:
                pass

        # Try to find dd/mm/YYYY HH:MM pattern
        date_match = re.search(r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})", text)
        if date_match:
            try:
                return datetime.strptime(date_match.group(1), "%d/%m/%Y %H:%M")
            except ValueError:
                pass

        # Fallback: try each line with multiple formats
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
