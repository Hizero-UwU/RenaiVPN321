from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from src.bot.locales import localized_keyboard_label, tr
from src.bot.view_models import main_menu


def persistent_keyboard(locale: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=localized_keyboard_label(locale, "👤", "profile"))],
            [
                KeyboardButton(text=localized_keyboard_label(locale, "🧭", "menu")),
                KeyboardButton(text=localized_keyboard_label(locale, "🔐", "my_vpn")),
            ],
            [KeyboardButton(text=localized_keyboard_label(locale, "💬", "offer"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="onb:lang:ru"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="onb:lang:en"),
            ]
        ]
    )


def currency_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="₽ RUB", callback_data="onb:currency:RUB"),
                InlineKeyboardButton(text="$ USD", callback_data="onb:currency:USD"),
            ]
        ]
    )


def buy_keyboard(locale: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🥉 Starter", callback_data="buy:starter"),
                InlineKeyboardButton(text="🥈 Standard", callback_data="buy:standard"),
            ],
            [InlineKeyboardButton(text="🥇 Company", callback_data="buy:company")],
            [InlineKeyboardButton(text=f"↩️ {tr(locale, 'back')}", callback_data="nav:menu")],
        ]
    )


def one_button(text: str, callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=callback_data)]]
    )


__all__ = [
    "buy_keyboard",
    "currency_keyboard",
    "language_keyboard",
    "main_menu",
    "one_button",
    "persistent_keyboard",
]
