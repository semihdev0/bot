"""Unit tests for the rule engine with Betronix-specific models."""

from datetime import datetime, timedelta
from decimal import Decimal

from src.config.models import (
    BonusCalculation,
    BonusRulesConfig,
    BonusTypeConfig,
    Condition,
    Rule,
)
from src.engine.models import (
    BonusHistory,
    BonusHistoryEntry,
    BonusRequest,
    DepositEntry,
    DepositHistory,
    UserProfile,
    WithdrawalHistory,
)
from src.engine.rule_engine import evaluate


def _make_profile(**kwargs) -> UserProfile:
    defaults = {
        "user_id": "testuser",
        "username": "Test User",
        "bakiye": Decimal("50"),
        "bonus_bakiye": Decimal("0"),
        "son_yatirim_tutari": Decimal("200"),
        "toplam_yatirim": Decimal("500"),
        "toplam_cekim": Decimal("100"),
        "kar_zarar": Decimal("-100"),
        "yatirim_sayisi": 5,
        "cekim_sayisi": 1,
        "durum": "Aktif",
        "kayit_tarihi": datetime.now() - timedelta(days=3),
        "son_yatirim_tarihi": datetime.now() - timedelta(hours=2),
        "son_kullanilan_bonus": "",
        "aktif_bonus": "",
    }
    defaults.update(kwargs)
    return UserProfile(**defaults)


def _make_request(**kwargs) -> BonusRequest:
    defaults = {
        "request_id": "BR001",
        "user_id": "testuser",
        "bonus_type": "kripto_yatirim_bonusu",
    }
    defaults.update(kwargs)
    return BonusRequest(**defaults)


def _make_rules_config() -> BonusRulesConfig:
    return BonusRulesConfig(
        bonus_types={
            "kripto_yatirim_bonusu": BonusTypeConfig(
                display_name="%15 Kripto Yatırım",
                default_action="reject",
                default_reject_message_key="genel_uygun_degil",
                rules=[
                    Rule(
                        name="Kripto yatırım aktif kullanıcı",
                        conditions=[
                            Condition(field="hesap_aktif", operator="==", value=True),
                            Condition(field="kripto_yatirim_var", operator="==", value=True),
                        ],
                        action="approve",
                        bonus_calculation=BonusCalculation(
                            method="percentage",
                            base_field="son_kripto_yatirim_tutari",
                            percentage=Decimal("15"),
                            turnover=1,
                        ),
                    ),
                    Rule(
                        name="Kripto yatırımı yok",
                        conditions=[
                            Condition(field="kripto_yatirim_var", operator="==", value=False),
                        ],
                        action="reject",
                        reject_message_key="kripto_yatirim_yok",
                    ),
                ],
            ),
            "ilk_kaybiniza_ozel_nakit_iade_bonusu": BonusTypeConfig(
                display_name="İlk Yatırıma Özel %100 Kayıp",
                default_action="reject",
                default_reject_message_key="ilk_kayip_genel_ret",
                rules=[
                    Rule(
                        name="Hesap pasif",
                        conditions=[
                            Condition(field="hesap_aktif", operator="==", value=False),
                        ],
                        action="reject",
                        reject_message_key="hesap_pasif",
                    ),
                    Rule(
                        name="Aktif bonus mevcut",
                        conditions=[
                            Condition(field="aktif_bonus_var", operator="==", value=True),
                        ],
                        action="reject",
                        reject_message_key="aktif_bonus_mevcut",
                    ),
                    Rule(
                        name="Birden fazla yatırım",
                        conditions=[
                            Condition(field="yatirim_sayisi", operator=">", value=1),
                        ],
                        action="reject",
                        reject_message_key="ilk_kayip_yatirim_yok",
                    ),
                    Rule(
                        name="Bakiye yüksek",
                        conditions=[
                            Condition(field="bakiye", operator=">=", value=5),
                        ],
                        action="reject",
                        reject_message_key="ilk_kayip_bakiye_yuksek",
                    ),
                    Rule(
                        name="İlk yatırım kayıp - onay",
                        conditions=[
                            Condition(field="hesap_aktif", operator="==", value=True),
                            Condition(field="aktif_bonus_var", operator="==", value=False),
                            Condition(field="yatirim_sayisi", operator="==", value=1),
                            Condition(field="bakiye", operator="<", value=5),
                            Condition(field="son_yatirim_gunu_farki", operator="<=", value=1),
                            Condition(field="son_yatirim_tutari", operator=">=", value=100),
                            Condition(field="son_yatirim_tutari", operator="<=", value=1000),
                        ],
                        action="approve",
                        bonus_calculation=BonusCalculation(
                            method="percentage",
                            base_field="son_yatirim_tutari",
                            percentage=Decimal("100"),
                            min_amount=Decimal("100"),
                            max_amount=Decimal("1000"),
                            turnover=5,
                        ),
                    ),
                ],
            ),
            "anlik_kayip_bonusu": BonusTypeConfig(
                display_name="%25 Anlık Kayıp",
                default_action="reject",
                default_reject_message_key="anlik_kayip_genel_ret",
                rules=[
                    Rule(
                        name="Hiç yatırım yok",
                        conditions=[
                            Condition(field="basarili_yatirim_var", operator="==", value=False),
                        ],
                        action="reject",
                        reject_message_key="anlik_kayip_yatirim_yok",
                    ),
                    Rule(
                        name="Yatırım 24 saatten eski",
                        conditions=[
                            Condition(field="son_24_saat_yatirim_var", operator="==", value=False),
                        ],
                        action="reject",
                        reject_message_key="anlik_kayip_tarih_gecmis",
                    ),
                    Rule(
                        name="Bakiye yüksek",
                        conditions=[
                            Condition(field="bakiye", operator=">=", value=5),
                        ],
                        action="reject",
                        reject_message_key="anlik_kayip_bakiye_yuksek",
                    ),
                    Rule(
                        name="İlk kayıp bonusu almış",
                        conditions=[
                            Condition(field="son_yatirimdan_sonra_ilk_kayip_var", operator="==", value=True),
                        ],
                        action="reject",
                        reject_message_key="anlik_kayip_ilk_kayip_almis",
                    ),
                    Rule(
                        name="Anlık kayıp onay",
                        conditions=[
                            Condition(field="son_24_saat_yatirim_var", operator="==", value=True),
                            Condition(field="bakiye", operator="<", value=5),
                            Condition(field="son_yatirimdan_sonra_ilk_kayip_var", operator="==", value=False),
                        ],
                        action="approve",
                        bonus_calculation=BonusCalculation(
                            method="percentage",
                            base_field="son_yatirim_tutari",
                            percentage=Decimal("25"),
                            turnover=1,
                        ),
                    ),
                ],
            ),
        }
    )


MESSAGES = {
    "genel_uygun_degil": "Uygun değil.",
    "aktif_bonus_mevcut": "Aktif bonus mevcut.",
    "hesap_pasif": "Hesap pasif.",
    "kripto_yatirim_yok": "Kripto yatırımı yok.",
    "ilk_kayip_genel_ret": "İlk kayıp genel ret.",
    "ilk_kayip_yatirim_yok": "İlk yatırım yapılmamış.",
    "ilk_kayip_bakiye_yuksek": "Bakiye yüksek.",
    "anlik_kayip_genel_ret": "Anlık kayıp genel ret.",
    "anlik_kayip_yatirim_yok": "Yatırım yok.",
    "anlik_kayip_tarih_gecmis": "Tarih geçmiş.",
    "anlik_kayip_bakiye_yuksek": "Bakiye yüksek.",
    "anlik_kayip_ilk_kayip_almis": "İlk kayıp almış.",
}


# --- Kripto Yatırım Bonusu Tests ---


def test_kripto_approve_with_crypto_deposit():
    """User with crypto deposit -> approve with 15%."""
    profile = _make_profile(
        durum="Aktif",
        aktif_bonus="",
        deposits=DepositHistory(entries=[
            DepositEntry(
                amount=Decimal("1000"),
                method="Kripto",
                is_successful=True,
                date=datetime.now() - timedelta(hours=1),
            ),
        ]),
    )
    request = _make_request(bonus_type="kripto_yatirim_bonusu")
    rules = _make_rules_config()
    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "approve"
    assert decision.bonus_amount == Decimal("150")  # 1000 * 15%
    assert decision.bonus_turnover == 1


def test_kripto_reject_no_crypto():
    """User without crypto deposit -> reject."""
    profile = _make_profile(
        durum="Aktif",
        deposits=DepositHistory(entries=[
            DepositEntry(
                amount=Decimal("1000"),
                method="Havale",
                is_successful=True,
                date=datetime.now(),
            ),
        ]),
    )
    request = _make_request(bonus_type="kripto_yatirim_bonusu")
    rules = _make_rules_config()
    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "reject"
    assert decision.matched_rule_name == "Kripto yatırımı yok"


# --- İlk Yatırım %100 Kayıp Tests ---

ILK_KAYIP_TYPE = "ilk_kaybiniza_ozel_nakit_iade_bonusu"


def test_ilk_kayip_approve_happy_path():
    """Single deposit, lost all, within time -> approve 100% with 5x turnover."""
    profile = _make_profile(
        son_yatirim_tutari=Decimal("500"),
        bakiye=Decimal("0"),
        yatirim_sayisi=1,
        durum="Aktif",
        aktif_bonus="",
        son_yatirim_tarihi=datetime.now(),
    )
    request = _make_request(bonus_type=ILK_KAYIP_TYPE)
    rules = _make_rules_config()
    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "approve"
    assert decision.bonus_amount == Decimal("500")
    assert decision.bonus_turnover == 5


def test_ilk_kayip_reject_inactive():
    """Inactive account -> reject."""
    profile = _make_profile(durum="Pasif", yatirim_sayisi=1, bakiye=Decimal("0"))
    request = _make_request(bonus_type=ILK_KAYIP_TYPE)
    rules = _make_rules_config()
    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "reject"
    assert decision.matched_rule_name == "Hesap pasif"


def test_ilk_kayip_reject_active_bonus():
    """Active bonus exists -> reject."""
    profile = _make_profile(
        aktif_bonus="%25 ANLIK KAYIP",
        yatirim_sayisi=1,
        bakiye=Decimal("0"),
    )
    request = _make_request(bonus_type=ILK_KAYIP_TYPE)
    rules = _make_rules_config()
    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "reject"
    assert decision.matched_rule_name == "Aktif bonus mevcut"


def test_ilk_kayip_reject_multiple_deposits():
    """More than 1 deposit -> reject."""
    profile = _make_profile(
        yatirim_sayisi=3,
        bakiye=Decimal("0"),
        aktif_bonus="",
    )
    request = _make_request(bonus_type=ILK_KAYIP_TYPE)
    rules = _make_rules_config()
    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "reject"
    assert decision.matched_rule_name == "Birden fazla yatırım"


def test_ilk_kayip_reject_balance_too_high():
    """Balance >= 5 TL -> reject."""
    profile = _make_profile(
        yatirim_sayisi=1,
        bakiye=Decimal("50"),
        aktif_bonus="",
    )
    request = _make_request(bonus_type=ILK_KAYIP_TYPE)
    rules = _make_rules_config()
    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "reject"
    assert decision.matched_rule_name == "Bakiye yüksek"


# --- %25 Anlık Kayıp Tests ---

ANLIK_KAYIP_TYPE = "anlik_kayip_bonusu"


def test_anlik_kayip_approve():
    """Recent deposit, low balance, no prior ilk kayip -> approve 25%."""
    profile = _make_profile(
        son_yatirim_tutari=Decimal("400"),
        bakiye=Decimal("2"),
        durum="Aktif",
        aktif_bonus="",
        son_yatirim_tarihi=datetime.now() - timedelta(hours=2),
        deposits=DepositHistory(entries=[
            DepositEntry(
                amount=Decimal("400"),
                method="Havale",
                is_successful=True,
                date=datetime.now() - timedelta(hours=2),
            ),
        ]),
        bonus_history=BonusHistory(entries=[]),
    )
    request = _make_request(bonus_type=ANLIK_KAYIP_TYPE)
    rules = _make_rules_config()
    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "approve"
    assert decision.bonus_amount == Decimal("100")  # 400 * 25%
    assert decision.bonus_turnover == 1


def test_anlik_kayip_reject_no_deposits():
    """No successful deposits -> reject."""
    profile = _make_profile(
        bakiye=Decimal("0"),
        deposits=DepositHistory(entries=[]),
    )
    request = _make_request(bonus_type=ANLIK_KAYIP_TYPE)
    rules = _make_rules_config()
    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "reject"
    assert decision.matched_rule_name == "Hiç yatırım yok"


def test_anlik_kayip_reject_old_deposit():
    """Deposit older than 24 hours -> reject."""
    profile = _make_profile(
        bakiye=Decimal("0"),
        son_yatirim_tarihi=datetime.now() - timedelta(hours=30),
        deposits=DepositHistory(entries=[
            DepositEntry(
                amount=Decimal("200"),
                method="Havale",
                is_successful=True,
                date=datetime.now() - timedelta(hours=30),
            ),
        ]),
    )
    request = _make_request(bonus_type=ANLIK_KAYIP_TYPE)
    rules = _make_rules_config()
    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "reject"
    assert decision.matched_rule_name == "Yatırım 24 saatten eski"


def test_anlik_kayip_reject_ilk_kayip_already_received():
    """Already received İlk Kayıp bonus after last deposit -> reject."""
    now = datetime.now()
    profile = _make_profile(
        bakiye=Decimal("0"),
        son_yatirim_tarihi=now - timedelta(hours=5),
        deposits=DepositHistory(entries=[
            DepositEntry(
                amount=Decimal("200"),
                method="Havale",
                is_successful=True,
                date=now - timedelta(hours=5),
            ),
        ]),
        bonus_history=BonusHistory(entries=[
            BonusHistoryEntry(
                bonus_name="İLK KAYBINIZA ÖZEL %100 NAKİT İADE BONUSU",
                amount=Decimal("200"),
                status="Aktif",
                date=now - timedelta(hours=3),
            ),
        ]),
    )
    request = _make_request(bonus_type=ANLIK_KAYIP_TYPE)
    rules = _make_rules_config()
    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "reject"
    assert decision.matched_rule_name == "İlk kayıp bonusu almış"


# --- Computed Field Tests ---


def test_computed_fields():
    """Test that computed profile fields work correctly."""
    profile = _make_profile(
        durum="Aktif",
        aktif_bonus="%25 ANLIK KAYIP BONUSU",
        kayit_tarihi=datetime.now() - timedelta(days=5),
        son_yatirim_tarihi=datetime.now() - timedelta(days=2),
    )
    assert profile.hesap_aktif is True
    assert profile.aktif_bonus_var is True
    assert profile.kayit_gunu_farki == 5
    assert profile.son_yatirim_gunu_farki == 2


def test_computed_hour_fields():
    """Test hour-based computed fields."""
    profile = _make_profile(
        son_yatirim_tarihi=datetime.now() - timedelta(hours=3),
        deposits=DepositHistory(entries=[
            DepositEntry(
                amount=Decimal("100"),
                method="Havale",
                is_successful=True,
                date=datetime.now() - timedelta(hours=3),
            ),
        ]),
    )
    assert profile.son_yatirim_saat_farki == 3
    assert profile.son_24_saat_yatirim_var is True
    assert profile.son_5_saat_yatirim_var is True


def test_crypto_computed_fields():
    """Test crypto-related computed fields."""
    profile = _make_profile(
        deposits=DepositHistory(entries=[
            DepositEntry(
                amount=Decimal("500"),
                method="Kripto Bitcoin",
                is_successful=True,
                date=datetime.now(),
            ),
            DepositEntry(
                amount=Decimal("200"),
                method="Havale",
                is_successful=True,
                date=datetime.now(),
            ),
        ]),
    )
    assert profile.kripto_yatirim_var is True
    assert profile.son_kripto_yatirim_tutari == Decimal("500")


def test_inactive_account():
    """Inactive account computed field."""
    profile = _make_profile(durum="Pasif")
    assert profile.hesap_aktif is False


def test_unknown_bonus_type_rejected():
    """Unknown bonus type should be rejected."""
    profile = _make_profile()
    request = _make_request(bonus_type="nonexistent_bonus")
    rules = _make_rules_config()
    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "reject"


def test_normalize_bonus_type():
    """Test bonus type normalization strips internal %number patterns."""
    from src.pages.bonus_list_page import BonusListPage

    assert BonusListPage._normalize_bonus_type("%15 KRİPTO YATIRIM BONUSU") == "kripto_yatirim_bonusu"
    assert BonusListPage._normalize_bonus_type("İLK KAYBINIZA ÖZEL %100 NAKİT İADE BONUSU") == "ilk_kaybiniza_ozel_nakit_iade_bonusu"
    assert BonusListPage._normalize_bonus_type("%25 ANLIK KAYIP BONUSU") == "anlik_kayip_bonusu"
    assert BonusListPage._normalize_bonus_type("%300 HOŞGELDİN BONUSU") == "hosgeldin_bonusu"
    assert BonusListPage._normalize_bonus_type("ÇEVRİMSİZ 2X YAP 5X ÇEK") == "cevrimsiz_2x_yap_5x_cek"
