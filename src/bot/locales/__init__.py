from __future__ import annotations

from typing import Final

Locale = str

TRANSLATIONS: Final[dict[str, dict[str, str]]] = {
    "ru": {
        "choose_language": "Выберите язык / Choose a language",
        "choose_currency": "Выберите валюту для цен и оплаты:",
        "welcome": "Добро пожаловать!",
        "menu": "Меню",
        "profile": "Профиль",
        "my_vpn": "Мой VPN",
        "offer": "Наше предложение",
        "balance": "Баланс",
        "buy": "Купить подписку",
        "renew": "Продлить подписку",
        "reissue": "Перевыпустить подписку",
        "referral": "Пригласить друга",
        "trial": "Пробный период",
        "settings": "Настройки",
        "support": "Поддержка",
        "promo": "Промокод",
        "topup": "Пополнить баланс",
        "no_subscription": "❌ У вас нет активной подписки!",
        "insufficient": "❌ Недостаточно средств!",
        "offer_acceptance": "Продолжая пользоваться ботом, вы принимаете условия оферты.",
        "offer_not_configured": "Ссылка на оферту не настроена.",
        "support_unconfigured": "Поддержка пока не настроена.",
        "not_configured_currency": "Для этой валюты цена или способ оплаты не настроены.",
        "provisioning_pending": "Операция ожидает подтверждения VPN-провайдера. Повторите попытку позже.",
        "channel_required": "Для работы с ботом подпишитесь на канал и нажмите «Проверить подписку».",
        "subscribe": "Подписаться",
        "check_subscription": "Проверить подписку",
        "back": "Назад",
        "cancel": "Отмена",
        "trial_reward": "🎁 После покупки другом вы получите 3 бесплатных дня VPN.",
    },
    "en": {
        "choose_language": "Выберите язык / Choose a language",
        "choose_currency": "Choose a currency for prices and payments:",
        "welcome": "Welcome!",
        "menu": "Menu",
        "profile": "Profile",
        "my_vpn": "My VPN",
        "offer": "Our offer",
        "balance": "Balance",
        "buy": "Buy subscription",
        "renew": "Renew subscription",
        "reissue": "Reissue subscription",
        "referral": "Invite a friend",
        "trial": "Trial period",
        "settings": "Settings",
        "support": "Support",
        "promo": "Promo code",
        "topup": "Top up balance",
        "no_subscription": "❌ You do not have an active subscription!",
        "insufficient": "❌ Insufficient funds!",
        "offer_acceptance": "By continuing to use the bot, you accept the offer terms.",
        "offer_not_configured": "The offer link is not configured.",
        "support_unconfigured": "Support is not configured yet.",
        "not_configured_currency": "No price or payment method is configured for this currency.",
        "provisioning_pending": "The VPN provider has not confirmed this operation yet. Please retry later.",
        "promo_applied": "Promo code applied. Discounted total: {amount}.",
        "promo_invalid": "Promo code is invalid, exhausted, already used, or not applicable.",
        "confirm_reissue": "Reissue the VPN link? The old link may stop working.",
        "confirm": "Confirm",
        "old_link_invalidated": "✅ The old connection link was invalidated by the provider.",
        "old_link_not_guaranteed": "⚠️ The provider does not confirm invalidation of the old link.",
        "other": "Other amount",
        "topup_prompt": "Choose a top-up amount:",
        "topup_unconfigured": "No top-up amounts are configured for this currency.",
        "topup_enter_amount": "Enter an amount in your selected currency:",
        "topup_invalid_amount": "Invalid amount or outside configured limits.",
        "payment_choose": "Choose a payment method for {amount}:",
        "payment_methods_unavailable": "Payment methods are not configured for this currency yet.",
        "channel_required": "Subscribe to the channel and press “Check subscription” to use the bot.",
        "subscribe": "Subscribe",
        "check_subscription": "Check subscription",
        "back": "Back",
        "cancel": "Cancel",
        "trial_reward": "🎁 After your friend makes a purchase, you receive 3 free VPN days.",
    },
}


def tr(locale: str | None, key: str, **values: object) -> str:
    language = "ru" if locale == "ru" else "en"
    template = TRANSLATIONS[language].get(key, TRANSLATIONS["en"].get(key, key))
    return template.format(**values)


def localized_keyboard_label(locale: str, emoji: str, key: str) -> str:
    return f"{emoji} {tr(locale, key)}"


__all__ = ["TRANSLATIONS", "tr", "localized_keyboard_label"]
