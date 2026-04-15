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

# Successful deposit/withdrawal status keywords (Turkish)
_SUCCESS_KEYWORDS = ("tamamlan", "başarılı", "onaylan", "completed", "success")
_FAILED_KEYWORDS = ("başarısız", "iptal", "reddedil", "failed", "cancelled")


class UserProfilePage(BasePage):
    page_name = "user_profile_page"

    async def navigate_to_profile(
        self, base_url: str, path_template: str, user_id: str
    ) -> None:
        """Navigate to a user's profile page."""
        path = path_template.format(user_id=user_id)
        url = f"{base_url.rstrip('/')}{path}"
        await self.navigate(url)
        await asyncio.sleep(2)
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
        1. Profile info cards (Finansal, Yatırım, Hesap bilgileri)
        2. Yatırımlar tab (deposit history)
        3. Çekimler tab (withdrawal history)
        4. Bonuslar tab (bonus history)
        """
        # --- Finansal Bilgiler ---
        bakiye = await self._extract_value_by_label("Bakiye")
        bonus_bakiye = await self._extract_value_by_label("Bonus")
        toplam_yatirim = await self._extract_value_by_label("Toplam Yatırım")
        toplam_cekim = await self._extract_value_by_label("Toplam Çekim")
        kar_zarar = await self._extract_value_by_label("Kar/Zarar")

        # --- Yatırım Bilgileri ---
        ilk_yatirim_raw = await self._extract_value_by_label("İlk Yatırım")
        son_yatirim_raw = await self._extract_value_by_label("Son Yatırım")
        yatirim_sayisi_raw = await self._extract_value_by_label("Yatırım Sayısı")
        cekim_sayisi_raw = await self._extract_value_by_label("Çekim Sayısı")
        son_kullanilan_bonus = await self._extract_value_by_label("Son Kullanılan Bonus")

        # --- Hesap Bilgileri ---
        durum = await self._extract_value_by_label("Durum")
        kayit_tarihi_raw = await self._extract_value_by_label("Kayıt Tarihi")
        son_giris_raw = await self._extract_value_by_label("Son Giriş")

        # --- Aktif Bonus ---
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
            await self._click_tab("Yatırımlar")
            await self._select_time_filter("Tüm Zamanlar")

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
        """Extract withdrawal entries from the Çekimler tab.

        Table columns: REFERANS KODU | TUTAR | YÖNTEM | DURUM | TARİH
        """
        entries: list[WithdrawalEntry] = []
        try:
            await self._click_tab("Çekimler")
            await self._select_time_filter("Tüm Zamanlar")

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
            await self._click_tab("Bonuslar")
            await self._select_time_filter("Tüm Zamanlar")

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

    async def _click_tab(self, tab_name: str) -> None:
        """Click a tab on the profile page (Yatırımlar, Çekimler, Bonuslar, etc.)."""
        tab = self.page.get_by_text(tab_name, exact=True).first
        if await tab.count() > 0:
            await tab.click()
            await asyncio.sleep(1.5)

    async def _select_time_filter(self, filter_name: str) -> None:
        """Select a time filter (Tüm Zamanlar, Son 7 Gün, etc.)."""
        try:
            time_filter = self.page.get_by_text(filter_name, exact=True).first
            if await time_filter.count() > 0:
                await time_filter.click()
                await asyncio.sleep(1)
        except Exception:
            pass

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
        """Extract active bonus name from the Aktif Bonus section."""
        try:
            section = self.page.get_by_text("Aktif Bonus", exact=False).first
            if await section.count() > 0:
                parent = section.locator("..")
                text = await parent.text_content() or ""
                cleaned = text.replace("Aktif Bonus", "").strip()
                if cleaned and cleaned != "-":
                    return cleaned.split("\n")[0].strip()
            return ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_decimal(text: str) -> Decimal:
        """Parse a decimal value from Betronix text format.

        Handles: '13.915 ₺', '100 ₺', '2.000 ₺', '+1.000 ₺', '3.000₺'
        Turkish format uses dots as thousands separator: 13.915 = 13915
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

        if "," in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            parts = cleaned.split(".")
            if len(parts) == 2 and len(parts[1]) == 3:
                cleaned = cleaned.replace(".", "")
            elif len(parts) > 2:
                cleaned = cleaned.replace(".", "")

        try:
            return Decimal(cleaned)
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

        Formats seen: '07/01 14:31\\n07.01.2026 14:31', '25/03 12:09\\n25.03.2026 12:09'
        Also: '07/01/2026 14:31', '07.01.2026 14:31'
        """
        if not text or text.strip() in ("", "-"):
            return None

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
