"""User profile page for Betronix - extracts all profile data.

Betronix profile has 4 info cards:
- Temel Bilgiler: Kullanıcı Adı, İsim, E-posta, Telefon, Cinsiyet
- Hesap Bilgileri: Durum, Kayıt Tarihi, Son Giriş, Son Giriş IP, Ortak, BTag ID
- Yatırım Bilgileri: İlk Yatırım, Son Yatırım, Yatırım Sayısı, Çekim Sayısı, Son Kullanılan Bonus
- Finansal Bilgiler: Bakiye, Bonus, Toplam Yatırım, Toplam Çekim, Kar/Zarar

Plus an "Aktif Bonus" section and tabs (Yatırımlar, Çekimler, etc.)
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import structlog
from playwright.async_api import Page

from src.config.selectors import SelectorRegistry
from src.engine.models import UserProfile
from src.pages.base import BasePage

logger = structlog.get_logger()


class UserProfilePage(BasePage):
    page_name = "user_profile_page"

    async def navigate_to_profile(
        self, base_url: str, path_template: str, user_id: str
    ) -> None:
        """Navigate to a user's profile page."""
        path = path_template.format(user_id=user_id)
        url = f"{base_url.rstrip('/')}{path}"
        await self.navigate(url)
        await asyncio.sleep(2)  # Wait for profile data to load
        logger.debug("user_profile_loaded", user_id=user_id)

    async def navigate_via_username_link(self, link_locator) -> None:
        """Navigate to profile by clicking the username link in bonus list."""
        await link_locator.click()
        await self.page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)
        logger.debug("user_profile_loaded_via_link")

    async def extract_profile(self, user_id: str, username: str = "") -> UserProfile:
        """Extract all relevant user data from the Betronix profile page.

        Uses a label-based extraction approach: find the label text,
        then get the adjacent value.
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

        # --- Son yatırım tutarını yatırımlar tablosundan çek ---
        son_yatirim_tutari = await self._extract_last_deposit_amount()

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
        )
        return profile

    async def _extract_value_by_label(self, label: str) -> str:
        """Extract the value next to a label on the profile page.

        Betronix shows data as: "Label    Value" in cards.
        Strategy: find the element containing the label text,
        then get the sibling/adjacent element's text.
        """
        try:
            # Try finding the label and getting adjacent value
            # Approach 1: find text, get parent row, get last text element
            label_locator = self.page.get_by_text(label, exact=False).first
            if await label_locator.count() == 0:
                return ""

            # Get the parent container (likely a row/flex container)
            parent = label_locator.locator("..")
            parent_text = await parent.text_content() or ""

            # Remove the label from the full text to get the value
            value = parent_text.replace(label, "").strip()

            # Clean up common artifacts
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
                # Remove "Aktif Bonus" label and extract bonus name
                cleaned = text.replace("Aktif Bonus", "").strip()
                # Extract bonus name (e.g., "%25 ANLIK KAYIP BONUSU")
                if cleaned and cleaned != "-":
                    return cleaned.split("\n")[0].strip()
            return ""
        except Exception:
            return ""

    async def _extract_last_deposit_amount(self) -> Decimal:
        """Navigate to Yatırımlar tab and get the most recent deposit amount.

        The deposits table has: REFERANS KODU | TUTAR | YÖNTEM | DURUM | TARİH
        We want the TUTAR from the first completed (Tamamlandı) row.
        """
        try:
            # Click Yatırımlar tab
            yatirimlar_tab = self.page.get_by_text("Yatırımlar", exact=True).first
            if await yatirimlar_tab.count() > 0:
                await yatirimlar_tab.click()
                await asyncio.sleep(1)

            # Look for the first row with a completed status
            rows = self.page.locator("table tbody tr")
            count = await rows.count()

            for i in range(min(count, 10)):
                row = rows.nth(i)
                row_text = await row.text_content() or ""

                # Check for completed status
                if "tamamlan" in row_text.lower():
                    # Get the amount column (2nd column)
                    amount_cell = row.locator("td:nth-child(2)")
                    amount_text = await amount_cell.text_content() or "0"
                    return self._parse_decimal(amount_text)

            return Decimal("0")
        except Exception as e:
            logger.debug("last_deposit_extraction_failed", error=str(e))
            return Decimal("0")

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

        # Handle Turkish number format: 13.915 = 13915 (dot as thousands sep)
        # If there's a comma, it's the decimal separator: 13.915,50
        if "," in cleaned:
            # Has decimal comma: 1.234,56 -> 1234.56
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # No comma: could be 13.915 (thirteen thousand) or 3.50 (three and a half)
            # Heuristic: if dot is followed by exactly 3 digits, it's thousands separator
            parts = cleaned.split(".")
            if len(parts) == 2 and len(parts[1]) == 3:
                # 13.915 -> 13915 (thousands separator)
                cleaned = cleaned.replace(".", "")
            elif len(parts) > 2:
                # 1.234.567 -> 1234567 (multiple thousands separators)
                cleaned = cleaned.replace(".", "")
            # else: single dot with non-3 decimals, treat as decimal point

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

        # Try to find a full date pattern in the text
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
            # Try matching against different parts of the text
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    return datetime.strptime(line, fmt)
                except ValueError:
                    continue

        return None
