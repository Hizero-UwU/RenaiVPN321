from __future__ import annotations

import pytest
from src.config import (
    ConfigurationError,
    CurrencyPriceUnavailable,
    Settings,
    format_money,
    parse_minor_units,
)


def base_env(**changes: str) -> dict[str, str]:
    result = {
        "BOT_TOKEN": "123456:placeholder",
        "DATABASE_URL": "sqlite+aiosqlite:///./test.db",
        "OFFER_URL": "https://example.test/offer",
    }
    result.update(changes)
    return result


def test_settings_defaults_rub_and_unset_usd() -> None:
    settings = Settings.from_env(base_env())
    assert [plan.prices_minor["RUB"] for plan in settings.plans] == [9900, 17900, 34900]
    assert [plan.prices_minor["USD"] for plan in settings.plans] == [None, None, None]
    assert settings.default_plan_days == 30
    assert settings.trial_days == 2
    assert settings.trial_cooldown_days == 60


def test_unconfigured_currency_does_not_convert() -> None:
    settings = Settings.from_env(base_env())
    with pytest.raises(CurrencyPriceUnavailable):
        settings.plans[0].price_for("USD")


def test_invalid_required_settings_fail_fast() -> None:
    with pytest.raises(ConfigurationError, match="BOT_TOKEN"):
        Settings.from_env(
            {"DATABASE_URL": "sqlite+aiosqlite:///./test.db", "OFFER_URL": "https://example.test"}
        )
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        Settings.from_env(base_env(DATABASE_URL="mysql://invalid"))


def test_minor_units_exact_and_currency_formatting() -> None:
    assert parse_minor_units("100.50", "RUB") == 10050
    assert format_money(9900, "RUB", "ru") == "99,00 RUB"
    with pytest.raises(ValueError):
        parse_minor_units("1.001", "USD")
    with pytest.raises(ValueError):
        parse_minor_units("-5", "RUB")
    with pytest.raises(ValueError):
        parse_minor_units("NaN", "RUB")


def test_channel_gate_requires_configuration() -> None:
    with pytest.raises(ConfigurationError, match="Required channel"):
        Settings.from_env(base_env(CHANNEL_GATE_ENABLED="true"))
