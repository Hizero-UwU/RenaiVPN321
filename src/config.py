from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Final

CURRENCY_MINOR_UNITS: Final[dict[str, int]] = {"RUB": 2, "USD": 2}


class ConfigurationError(ValueError):
    """Raised when required application settings are missing or invalid."""


class CurrencyPriceUnavailable(ValueError):
    """Raised when a plan or amount is not configured for the selected currency."""


def parse_positive_int(value: str | None, name: str, default: int | None = None) -> int:
    if value is None or value.strip() == "":
        if default is not None:
            return default
        raise ConfigurationError(f"{name} must be configured")
    try:
        result = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if result <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return result


def parse_optional_positive_int(value: str | None, name: str) -> int | None:
    if value is None or value.strip() == "":
        return None
    return parse_positive_int(value, name)


def parse_minor_units(value: str, currency: str) -> int:
    """Parse a decimal user amount exactly into integer minor units."""
    currency = currency.upper()
    if currency not in CURRENCY_MINOR_UNITS:
        raise ValueError("Unsupported currency")
    try:
        amount = Decimal(value.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("Enter a valid amount") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Amount must be greater than zero")
    scale = 10 ** CURRENCY_MINOR_UNITS[currency]
    minor = amount * scale
    if minor != minor.to_integral_value():
        raise ValueError("Amount has too many decimal places")
    return int(minor)


def format_money(minor: int, currency: str, locale: str = "en") -> str:
    if currency.upper() not in CURRENCY_MINOR_UNITS:
        raise ValueError("Unsupported currency")
    value = Decimal(minor) / (10 ** CURRENCY_MINOR_UNITS[currency.upper()])
    formatted = f"{value:,.2f}"
    if locale == "ru":
        formatted = formatted.replace(",", " ").replace(".", ",")
    return f"{formatted} {currency.upper()}"


@dataclass(frozen=True, slots=True)
class PlanConfig:
    code: str
    name: str
    devices: int
    traffic_gb: int | None
    prices_minor: dict[str, int | None]
    duration: timedelta

    def price_for(self, currency: str) -> int:
        amount = self.prices_minor.get(currency.upper())
        if amount is None:
            raise CurrencyPriceUnavailable(f"{self.code} is not priced in {currency.upper()}")
        return amount


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_url: str
    admin_ids: frozenset[int]
    timezone: str
    offer_url: str
    support_url: str | None
    support_username: str | None
    remnawave_base_url: str | None
    remnawave_api_token: str | None
    remnawave_api_version: str | None
    channel_gate_enabled: bool
    required_channel_id: str | None
    required_channel_url: str | None
    default_plan_days: int
    trial_days: int
    trial_cooldown_days: int
    referral_reward_days: int
    max_promo_discount_percent: int
    plans: tuple[PlanConfig, ...]
    topup_presets_minor: dict[str, tuple[int, ...]]
    topup_min_minor: dict[str, int | None]
    topup_max_minor: dict[str, int | None]
    platega_configured: bool
    cryptobot_configured: bool

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        import os
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        source = os.environ if env is None else env
        bot_token = source.get("BOT_TOKEN", "").strip()
        if not bot_token:
            raise ConfigurationError("BOT_TOKEN is required")
        database_url = source.get("DATABASE_URL", "").strip()
        if not database_url.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite://")):
            raise ConfigurationError("DATABASE_URL must use postgresql+asyncpg or sqlite+aiosqlite")
        timezone = source.get("TIMEZONE", "UTC").strip()
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError("TIMEZONE must be a valid IANA timezone") from exc
        offer_url = source.get("OFFER_URL", "").strip()
        if not offer_url.startswith(("https://", "http://")):
            raise ConfigurationError("OFFER_URL must be an HTTP(S) URL")

        admin_ids: set[int] = set()
        for item in filter(None, (x.strip() for x in source.get("ADMIN_IDS", "").split(","))):
            try:
                admin_id = int(item)
            except ValueError as exc:
                raise ConfigurationError(
                    "ADMIN_IDS must be comma-separated Telegram numeric IDs"
                ) from exc
            if admin_id <= 0:
                raise ConfigurationError("ADMIN_IDS must contain positive Telegram IDs")
            admin_ids.add(admin_id)

        default_days = parse_positive_int(source.get("DEFAULT_PLAN_DAYS"), "DEFAULT_PLAN_DAYS", 30)
        prices = {
            "starter": source.get("RUB_STARTER_PRICE_MINOR", "9900"),
            "standard": source.get("RUB_STANDARD_PRICE_MINOR", "17900"),
            "company": source.get("RUB_COMPANY_PRICE_MINOR", "34900"),
        }
        plan_specs = (
            ("starter", "🥉 Starter", 2, 50),
            ("standard", "🥈 Standard", 5, 250),
            ("company", "🥇 Company", 15, None),
        )
        plans = tuple(
            PlanConfig(
                code=code,
                name=name,
                devices=devices,
                traffic_gb=traffic,
                prices_minor={
                    "RUB": _optional_amount(prices[code], f"RUB_{code.upper()}_PRICE_MINOR"),
                    "USD": _optional_amount(
                        source.get(f"USD_{code.upper()}_PRICE_MINOR"),
                        f"USD_{code.upper()}_PRICE_MINOR",
                    ),
                },
                duration=timedelta(
                    days=parse_positive_int(
                        source.get(f"{code.upper()}_DURATION_DAYS"),
                        f"{code.upper()}_DURATION_DAYS",
                        default_days,
                    )
                ),
            )
            for code, name, devices, traffic in plan_specs
        )

        presets = {
            "RUB": _parse_amount_list(
                source.get("RUB_TOPUP_PRESETS_MINOR", "10000,30000,50000,100000"),
                "RUB_TOPUP_PRESETS_MINOR",
            ),
            "USD": _parse_amount_list(
                source.get("USD_TOPUP_PRESETS_MINOR", ""), "USD_TOPUP_PRESETS_MINOR"
            ),
        }
        gate = source.get("CHANNEL_GATE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
        channel_id = source.get("REQUIRED_CHANNEL_ID", "").strip() or None
        channel_url = source.get("REQUIRED_CHANNEL_URL", "").strip() or None
        if gate and not (channel_id and channel_url):
            raise ConfigurationError(
                "Required channel ID and URL must be set when channel gate is enabled"
            )
        return cls(
            bot_token=bot_token,
            database_url=database_url,
            admin_ids=frozenset(admin_ids),
            timezone=timezone,
            offer_url=offer_url,
            support_url=source.get("SUPPORT_URL", "").strip() or None,
            support_username=source.get("SUPPORT_USERNAME", "").strip().lstrip("@") or None,
            remnawave_base_url=source.get("REMWAVE_BASE_URL", "").strip().rstrip("/") or None,
            remnawave_api_token=source.get("REMWAVE_API_TOKEN", "").strip() or None,
            remnawave_api_version=source.get("REMWAVE_API_VERSION", "").strip() or None,
            channel_gate_enabled=gate,
            required_channel_id=channel_id,
            required_channel_url=channel_url,
            default_plan_days=default_days,
            trial_days=parse_positive_int(source.get("TRIAL_DAYS"), "TRIAL_DAYS", 2),
            trial_cooldown_days=parse_positive_int(
                source.get("TRIAL_COOLDOWN_DAYS"), "TRIAL_COOLDOWN_DAYS", 60
            ),
            referral_reward_days=parse_positive_int(
                source.get("REFERRAL_REWARD_DAYS"), "REFERRAL_REWARD_DAYS", 3
            ),
            max_promo_discount_percent=parse_positive_int(
                source.get("MAX_PROMO_DISCOUNT_PERCENT"), "MAX_PROMO_DISCOUNT_PERCENT", 50
            ),
            plans=plans,
            topup_presets_minor=presets,
            topup_min_minor={
                currency: _optional_amount(
                    source.get(f"{currency}_TOPUP_MIN_MINOR"), f"{currency}_TOPUP_MIN_MINOR"
                )
                for currency in ("RUB", "USD")
            },
            topup_max_minor={
                currency: _optional_amount(
                    source.get(f"{currency}_TOPUP_MAX_MINOR"), f"{currency}_TOPUP_MAX_MINOR"
                )
                for currency in ("RUB", "USD")
            },
            platega_configured=all(
                source.get(key, "").strip()
                for key in ("PLATEGA_MERCHANT_ID", "PLATEGA_SECRET", "PLATEGA_WEBHOOK_SECRET")
            ),
            cryptobot_configured=all(
                source.get(k, "").strip() for k in ("CRYPTOBOT_TOKEN", "CRYPTOBOT_WEBHOOK_SECRET")
            ),
        )


def _optional_amount(value: str | None, name: str) -> int | None:
    if value is None or value.strip() == "":
        return None
    try:
        amount = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer in minor currency units") from exc
    if amount <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return amount


def _parse_amount_list(value: str, name: str) -> tuple[int, ...]:
    if not value.strip():
        return ()
    amounts: list[int] = []
    for item in value.split(","):
        amount = _optional_amount(item.strip(), name)
        assert amount is not None
        amounts.append(amount)
    return tuple(amounts)
