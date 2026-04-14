"""User profile page - extracts balance, deposits, registration data."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

import structlog

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
        logger.debug("user_profile_loaded", user_id=user_id)

    async def extract_profile(self, user_id: str, username: str = "") -> UserProfile:
        """Extract all relevant user data from the profile page."""
        bakiye = await self._extract_decimal("balance")
        son_yatirim = await self._extract_decimal("last_deposit_amount")
        son_yatirim_tarihi = await self._extract_date("last_deposit_date")
        toplam_yatirim = await self._extract_decimal("total_deposits")
        toplam_cekim = await self._extract_decimal("total_withdrawals")
        kayit_tarihi = await self._extract_date("registration_date")

        profile = UserProfile(
            user_id=user_id,
            username=username,
            bakiye=bakiye,
            son_yatirim_tutari=son_yatirim,
            son_yatirim_tarihi=son_yatirim_tarihi,
            toplam_yatirim=toplam_yatirim,
            toplam_cekim=toplam_cekim,
            kayit_tarihi=kayit_tarihi,
        )

        logger.info(
            "profile_extracted",
            user_id=user_id,
            bakiye=str(bakiye),
            son_yatirim=str(son_yatirim),
            toplam_yatirim=str(toplam_yatirim),
        )
        return profile

    async def _extract_decimal(self, element_name: str) -> Decimal:
        """Extract a decimal value from an element, with error handling."""
        try:
            text = await self.extract_text(element_name)
            # Clean common formatting: remove currency symbols, spaces, etc.
            cleaned = (
                text.replace("₺", "")
                .replace("TL", "")
                .replace("$", "")
                .replace("€", "")
                .replace(",", ".")
                .replace(" ", "")
                .strip()
            )
            return Decimal(cleaned) if cleaned else Decimal("0")
        except (InvalidOperation, ValueError, KeyError) as e:
            logger.debug(
                "decimal_extraction_failed",
                element=element_name,
                error=str(e),
            )
            return Decimal("0")

    async def _extract_date(self, element_name: str) -> datetime | None:
        """Extract a datetime value from an element."""
        try:
            text = await self.extract_text(element_name)
            if not text:
                return None
            # Try common date formats
            for fmt in (
                "%d.%m.%Y %H:%M:%S",
                "%d.%m.%Y %H:%M",
                "%d.%m.%Y",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y",
            ):
                try:
                    return datetime.strptime(text.strip(), fmt)
                except ValueError:
                    continue
            logger.debug(
                "date_parse_failed", element=element_name, raw_text=text
            )
            return None
        except (KeyError, Exception) as e:
            logger.debug(
                "date_extraction_failed",
                element=element_name,
                error=str(e),
            )
            return None
