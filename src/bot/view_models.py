from __future__ import annotations

from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.locales import tr
from src.config import Settings, format_money


def main_menu(locale: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"💵 {tr(locale, 'balance')}", callback_data="menu:balance"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"👤 {tr(locale, 'profile')}", callback_data="menu:profile"
                ),
                InlineKeyboardButton(text=f"🔐 {tr(locale, 'my_vpn')}", callback_data="menu:vpn"),
            ],
            [InlineKeyboardButton(text=f"💸 {tr(locale, 'buy')}", callback_data="menu:buy")],
            [
                InlineKeyboardButton(
                    text=f"🌐 {tr(locale, 'reissue')}", callback_data="menu:reissue"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"👥 {tr(locale, 'referral')}", callback_data="menu:referral"
                )
            ],
            [InlineKeyboardButton(text=f"🎁 {tr(locale, 'trial')}", callback_data="menu:trial")],
            [
                InlineKeyboardButton(
                    text=f"🛠️ {tr(locale, 'settings')}", callback_data="menu:settings"
                ),
                InlineKeyboardButton(
                    text=f"❓ {tr(locale, 'support')}", callback_data="menu:support"
                ),
            ],
            [InlineKeyboardButton(text=f"🏷️ {tr(locale, 'promo')}", callback_data="menu:promo")],
        ]
    )


def admin_keyboard(locale: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔊 Statistics", callback_data="admin:stats")],
            [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin:broadcast")],
            [InlineKeyboardButton(text="🛑 Mandatory subscription", callback_data="admin:channel")],
            [
                InlineKeyboardButton(
                    text="🧿 Grant subscription", callback_data="admin:grant_subscription"
                )
            ],
            [InlineKeyboardButton(text="💵 Grant balance", callback_data="admin:grant_balance")],
            [InlineKeyboardButton(text="🛠 Block user", callback_data="admin:block")],
            [InlineKeyboardButton(text="🏷 Create promo code", callback_data="admin:create_promo")],
        ]
    )


def currency_label(currency: str) -> str:
    return {"RUB": "₽ RUB", "USD": "$ USD"}.get(currency.upper(), currency.upper())


def plan_label(name: str, devices: int, traffic_gb: int | None, duration_days: int) -> str:
    traffic = "unlimited" if traffic_gb is None else f"{traffic_gb} GB"
    return f"{name} · {devices} devices · {traffic} · {duration_days} days"


def active_subscription_text(
    locale: str,
    *,
    plan: str,
    expires_at: datetime,
    timezone_name: str,
    connection_url: str,
) -> str:
    from zoneinfo import ZoneInfo

    expiry = expires_at.astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M %Z")
    if locale == "ru":
        return f"✅ Активна\nТариф: {plan}\nИстекает: {expiry}\n🔗 Connect: {connection_url}"
    return f"✅ Active\nPlan: {plan}\nExpires: {expiry}\n🔗 Connect: {connection_url}"


def plan_price_text(
    settings: Settings, *, plan_code: str, currency: str, locale: str
) -> str | None:
    plan = next((item for item in settings.plans if item.code == plan_code), None)
    if plan is None:
        return None
    amount = plan.prices_minor.get(currency.upper())
    if amount is None:
        return None
    return format_money(amount, currency, locale)


def offer_keyboard(offer_url: str, locale: str) -> InlineKeyboardMarkup:
    label = "Оферта" if locale == "ru" else "Offer"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"💬 {label}", url=offer_url)]]
    )


def support_keyboard(url: str, locale: str) -> InlineKeyboardMarkup:
    label = tr(locale, "support")
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"❓ {label}", url=url)]]
    )


__all__ = [
    "active_subscription_text",
    "admin_keyboard",
    "currency_label",
    "main_menu",
    "offer_keyboard",
    "plan_label",
    "plan_price_text",
    "support_keyboard",
]
