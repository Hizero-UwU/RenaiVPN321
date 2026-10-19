from __future__ import annotations

import hashlib
import hmac

import pytest
from src.bot.keyboards import buy_keyboard, main_menu, persistent_keyboard
from src.bot.locales import tr
from src.integrations import (
    ProviderUnavailable,
    UnavailablePaymentAdapter,
    UnavailableRemnawave,
    VerifiedPaymentEvent,
    validate_payment_event,
    verify_hmac_sha256,
)


def test_locales_cover_common_labels_and_keyboard_layout() -> None:
    assert tr("ru", "no_subscription") == "❌ У вас нет активной подписки!"
    assert (
        tr("en", "offer_acceptance") == "By continuing to use the bot, you accept the offer terms."
    )
    keyboard = persistent_keyboard("en")
    assert len(keyboard.keyboard) == 3
    assert len(keyboard.keyboard[0]) == 1
    assert len(keyboard.keyboard[1]) == 2
    assert len(keyboard.keyboard[2]) == 1
    menu = main_menu("ru")
    callbacks = [button.callback_data for row in menu.inline_keyboard for button in row]
    assert "menu:balance" in callbacks and "menu:trial" in callbacks
    assert "buy:starter" in [
        button.callback_data for row in buy_keyboard("en").inline_keyboard for button in row
    ]


def test_hmac_verification_uses_exact_raw_body() -> None:
    secret = "test-secret"
    raw = b'{"ok":true}'
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    assert verify_hmac_sha256(raw, secret, signature)
    assert not verify_hmac_sha256(raw + b" ", secret, signature)


def test_payment_event_validation_checks_all_order_fields() -> None:
    event = VerifiedPaymentEvent("evt-1", "pay-1", "topup:1", 1000, "RUB", True)
    validate_payment_event(event, reference="topup:1", amount_minor=1000, currency="RUB")
    with pytest.raises(ValueError, match="amount"):
        validate_payment_event(event, reference="topup:1", amount_minor=900, currency="RUB")
    with pytest.raises(ValueError, match="currency"):
        validate_payment_event(event, reference="topup:1", amount_minor=1000, currency="USD")


@pytest.mark.asyncio
async def test_unavailable_providers_cannot_claim_success() -> None:
    remnawave = UnavailableRemnawave()
    payment = UnavailablePaymentAdapter("Platega")
    with pytest.raises(ProviderUnavailable):
        await remnawave.get_subscription("tg-1")
    with pytest.raises(ProviderUnavailable):
        await payment.create_checkout(None, "idem")  # type: ignore[arg-type]
    with pytest.raises(ProviderUnavailable):
        payment.verify_webhook(b"{}", {})


def test_verified_payment_requires_success() -> None:
    failed = VerifiedPaymentEvent("evt", "p", "r", 100, "RUB", False)
    with pytest.raises(ValueError, match="not succeeded"):
        validate_payment_event(failed, reference="r", amount_minor=100, currency="RUB")
