from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import (
    buy_keyboard,
    currency_keyboard,
    language_keyboard,
    one_button,
    persistent_keyboard,
)
from src.bot.locales import tr
from src.bot.view_models import active_subscription_text, main_menu, offer_keyboard
from src.config import Settings, format_money, parse_minor_units
from src.db.models import Plan, Subscription, User, Wallet
from src.domain.services import (
    apply_promo_code,
    BusinessRuleError,
    CurrencyNotConfigured,
    InsufficientBalance,
    ProvisioningPending,
    award_trial,
    create_purchase_order,
    fulfill_paid_order,
    plan_price,
    provision_registered_user,
    register_user,
)
from src.integrations import ProviderUnavailable, RemnawaveAdapter


def build_user_router(settings: Settings, remnawave: RemnawaveAdapter) -> Router:
    router = Router(name="user")

    async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
        return await session.scalar(select(User).where(User.telegram_id == telegram_id))

    @router.message(CommandStart())
    async def start(message: Message, session: AsyncSession) -> None:
        if message.from_user is None:
            return
        command_args = (message.text or "").split(maxsplit=1)
        referral_token = None
        if len(command_args) > 1 and command_args[1].startswith("ref_"):
            referral_token = command_args[1][4:]
        user, created = await register_user(
            session,
            message.from_user.id,
            message.from_user.first_name,
            message.from_user.username,
            referral_token,
        )
        if user.blocked:
            await message.answer("Access denied.")
            return
        if user.provisioning_state != "succeeded":
            try:
                await provision_registered_user(session, user, remnawave)
            except ProvisioningPending:
                await message.answer(tr(user.language, "provisioning_pending"))
        if user.language not in {"ru", "en"}:
            await message.answer(tr("en", "choose_language"), reply_markup=language_keyboard())
            return
        if user.currency not in {"RUB", "USD"}:
            await message.answer(
                tr(user.language, "choose_currency"), reply_markup=currency_keyboard()
            )
            return
        await message.answer(
            tr(user.language, "welcome"), reply_markup=persistent_keyboard(user.language)
        )
        if not created:
            await show_main_menu(message, user)

    @router.callback_query(F.data.startswith("onb:lang:"))
    async def choose_language(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        if callback.from_user is None or callback.data not in {"onb:lang:ru", "onb:lang:en"}:
            return
        user = await get_user(session, callback.from_user.id)
        if user is None:
            return
        user.language = callback.data.rsplit(":", 1)[1]
        await session.flush()
        if callback.message:
            await callback.message.edit_text(
                tr(user.language, "choose_currency"), reply_markup=currency_keyboard()
            )

    @router.callback_query(F.data.startswith("onb:currency:"))
    async def choose_currency(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        if callback.from_user is None or callback.data not in {
            "onb:currency:RUB",
            "onb:currency:USD",
        }:
            return
        user = await get_user(session, callback.from_user.id)
        if user is None or user.language not in {"ru", "en"}:
            return
        user.currency = callback.data.rsplit(":", 1)[1]
        await session.flush()
        if callback.message:
            await callback.message.edit_text(tr(user.language, "welcome"))
            await callback.message.answer(
                tr(user.language, "welcome"), reply_markup=persistent_keyboard(user.language)
            )

    @router.message(F.text)
    async def reply_keyboard(message: Message, session: AsyncSession) -> None:
        if message.from_user is None or message.text is None:
            return
        user = await get_user(session, message.from_user.id)
        if (
            user is None
            or user.blocked
            or user.language not in {"ru", "en"}
            or user.currency not in {"RUB", "USD"}
        ):
            return
        locale = user.language
        normalized = message.text.split(" ", 1)[-1]
        if normalized in {tr(locale, "menu"), "Menu", "Меню"}:
            await show_main_menu(message, user)
        elif normalized in {tr(locale, "my_vpn"), "My VPN", "Мой VPN"}:
            await show_vpn(message, session, user, settings)
        elif normalized in {tr(locale, "profile"), "Profile", "Профиль"}:
            await show_profile(message, session, user)
        elif normalized in {tr(locale, "offer"), "Our offer", "Наше предложение"}:
            await show_offer(message, settings, user)

    @router.callback_query(F.data == "nav:menu")
    @router.callback_query(F.data == "menu:home")
    async def menu_home(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if user and user.language:
            await edit_or_send(callback, tr(user.language, "menu"), main_menu(user.language))

    @router.callback_query(F.data == "menu:balance")
    async def balance(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if not user or not user.currency or not user.language:
            return
        wallet = await session.scalar(
            select(Wallet).where(Wallet.user_id == user.id, Wallet.currency == user.currency)
        )
        amount = 0 if wallet is None else wallet.balance_minor
        text = (
            f"{tr(user.language, 'balance')}: {format_money(amount, user.currency, user.language)}"
        )
        await edit_or_send(
            callback, text, one_button(f"💸 {tr(user.language, 'topup')}", "topup:start")
        )

    @router.callback_query(F.data == "menu:buy")
    async def buy(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if not user or not user.language or not user.currency:
            return
        lines = []
        for plan in settings.plans:
            try:
                _, amount = await plan_price(session, plan.code, user.currency)
                lines.append(
                    f"{plan.name} · {plan.devices} devices · {plan.traffic_gb if plan.traffic_gb is not None else 'unlimited'} GB · {format_money(amount, user.currency, user.language)}"
                )
            except CurrencyNotConfigured:
                lines.append(f"{plan.name} · {tr(user.language, 'not_configured_currency')}")
        await edit_or_send(callback, "\n".join(lines), buy_keyboard(user.language))

    @router.callback_query(F.data.startswith("buy:"))
    async def buy_plan(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        if callback.from_user is None or callback.data not in {
            "buy:starter",
            "buy:standard",
            "buy:company",
        }:
            return
        user = await get_user(session, callback.from_user.id)
        if not user or not user.language or not user.currency:
            return
        code = callback.data.split(":", 1)[1]
        key = f"tg:{callback.from_user.id}:{callback.id}"
        try:
            result = await create_purchase_order(
                session,
                user=user,
                plan_code=code,
                currency=user.currency,
                idempotency_key=key,
                paid_via_wallet=True,
            )
        except InsufficientBalance:
            await edit_or_send(
                callback,
                tr(user.language, "insufficient"),
                one_button(f"💸 {tr(user.language, 'topup')}", "topup:start"),
            )
            return
        except CurrencyNotConfigured:
            await edit_or_send(
                callback, tr(user.language, "not_configured_currency"), buy_keyboard(user.language)
            )
            return
        if result.state == "paid":
            try:
                subscription = await fulfill_paid_order(
                    session, order_public_id=result.public_id, adapter=remnawave, settings=settings
                )
            except ProvisioningPending:
                await edit_or_send(
                    callback, tr(user.language, "provisioning_pending"), main_menu(user.language)
                )
                return
            await edit_or_send(
                callback,
                f"✅ {result.public_id}\n{subscription.expires_at}",
                main_menu(user.language),
            )

    @router.callback_query(F.data == "menu:vpn")
    @router.callback_query(F.data == "menu:profile")
    async def menu_profile_vpn(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if user is None:
            return
        if callback.data == "menu:vpn":
            await show_vpn(callback, session, user, settings)
        else:
            await show_profile(callback, session, user)

    @router.callback_query(F.data == "menu:trial")
    async def trial(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if not user or not user.language:
            return
        try:
            subscription = await award_trial(
                session, user=user, adapter=remnawave, settings=settings
            )
        except (BusinessRuleError, ProvisioningPending) as exc:
            await edit_or_send(
                callback, f"{tr(user.language, 'trial')}: {exc}", main_menu(user.language)
            )
            return
        await edit_or_send(
            callback,
            f"{tr(user.language, 'trial')}\n{subscription.connection_url_encrypted or ''}",
            main_menu(user.language),
        )

    @router.callback_query(F.data == "menu:referral")
    async def referral(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if not user or not user.language:
            return
        bot_username = getattr(callback.bot, "username", None)
        text = tr(user.language, "trial_reward")
        if bot_username:
            text += f"\nhttps://t.me/{bot_username}?start=ref_{user.referral_token}"
        await edit_or_send(callback, text, one_button(f"↩️ {tr(user.language, 'back')}", "nav:menu"))

    @router.callback_query(F.data == "menu:support")
    async def support(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if not user or not user.language:
            return
        if settings.support_url:
            await edit_or_send(
                callback,
                tr(user.language, "support"),
                one_button(f"❓ {tr(user.language, 'support')}", "nav:menu"),
            )
            if callback.message:
                await callback.message.answer(settings.support_url)
        elif settings.support_username:
            if callback.message:
                await callback.message.answer(f"https://t.me/{settings.support_username}")
        else:
            await edit_or_send(
                callback,
                tr(user.language, "support_unconfigured"),
                one_button(f"↩️ {tr(user.language, 'back')}", "nav:menu"),
            )

    @router.callback_query(F.data == "menu:settings")
    async def settings_view(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if not user or not user.language:
            return
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🇷🇺 Русский", callback_data="settings:lang:ru"),
                    InlineKeyboardButton(text="🇬🇧 English", callback_data="settings:lang:en"),
                ],
                [
                    InlineKeyboardButton(text="₽ RUB", callback_data="settings:currency:RUB"),
                    InlineKeyboardButton(text="$ USD", callback_data="settings:currency:USD"),
                ],
                [
                    InlineKeyboardButton(
                        text=f"↩️ {tr(user.language, 'back')}", callback_data="nav:menu"
                    )
                ],
            ]
        )
        await edit_or_send(callback, tr(user.language, "settings"), keyboard)

    @router.callback_query(F.data.startswith("settings:lang:"))
    async def change_language(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        if callback.data not in {"settings:lang:ru", "settings:lang:en"}:
            return
        user = await get_user(session, callback.from_user.id)
        if user:
            user.language = callback.data.rsplit(":", 1)[1]
            await session.flush()
            await edit_or_send(callback, tr(user.language, "settings"), main_menu(user.language))

    @router.callback_query(F.data.startswith("settings:currency:"))
    async def change_currency(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        if callback.data not in {"settings:currency:RUB", "settings:currency:USD"}:
            return
        user = await get_user(session, callback.from_user.id)
        if user:
            old_currency = user.currency
            user.currency = callback.data.rsplit(":", 1)[1]
            wallet = await session.scalar(
                select(Wallet).where(Wallet.user_id == user.id, Wallet.currency == user.currency)
            )
            await session.flush()
            note = (
                ""
                if old_currency == user.currency or wallet is None or wallet.balance_minor == 0
                else f"\n{format_money(wallet.balance_minor, user.currency, user.language or 'en')}"
            )
            await edit_or_send(
                callback,
                f"{tr(user.language, 'settings')} · {user.currency}{note}",
                main_menu(user.language or "en"),
            )

    @router.callback_query(F.data == "menu:promo")
    async def promo_prompt(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if user and callback.message:
            await callback.message.answer(
                "🏷️ Send your promo code to apply it to your next order."
                if user.language == "en"
                else "🏷️ Отправьте промокод, чтобы применить его к следующему заказу."
            )

    @router.message(F.text)
    async def apply_promo_message(message: Message, session: AsyncSession) -> None:
        if not message.from_user or not message.text:
            return
        user = await get_user(session, message.from_user.id)
        if not user or user.blocked or user.language not in {"ru", "en"}:
            return
        if message.text.startswith("/"):
            return
        try:
            orders = await session.scalars(
                select(Order)
                .where(Order.user_id == user.id, Order.state == "created")
                .order_by(Order.created_at.desc())
                .limit(1)
            )
            order = orders.first()
            if order is None:
                return
            await apply_promo_code(session, order=order, user=user, promo_code=message.text)
            await message.answer(
                tr(user.language, "promo_applied", amount=format_money(order.amount_minor, order.currency, user.language))
            )
        except BusinessRuleError:
            await message.answer(tr(user.language, "promo_invalid"))

    @router.callback_query(F.data == "menu:reissue")
    async def request_reissue(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if not user or not user.language:
            return
        await edit_or_send(
            callback,
            tr(user.language, "confirm_reissue"),
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=tr(user.language, "confirm"), callback_data="vpn:reissue:confirm"
                        ),
                        InlineKeyboardButton(
                            text=tr(user.language, "cancel"), callback_data="vpn:reissue:cancel"
                        ),
                    ]
                ]
            ),
        )

    @router.callback_query(F.data.startswith("vpn:reissue:"))
    async def reissue_subscription(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if not user or not user.language:
            return
        if callback.data == "vpn:reissue:cancel":
            await edit_or_send(callback, tr(user.language, "menu"), main_menu(user.language))
            return
        if callback.data != "vpn:reissue:confirm":
            return
        subscription = await session.scalar(
            select(Subscription)
            .where(Subscription.user_id == user.id, Subscription.status == "active")
            .order_by(Subscription.expires_at.desc())
            .limit(1)
            .with_for_update()
        )
        if not subscription or not subscription.provider_user_id:
            await edit_or_send(callback, tr(user.language, "no_subscription"), main_menu(user.language))
            return
        try:
            remote = await remnawave.reissue(subscription.provider_user_id, f"reissue:{subscription.id}:{callback.id}")
        except ProviderUnavailable:
            await edit_or_send(callback, tr(user.language, "provisioning_pending"), main_menu(user.language))
            return
        subscription.connection_url_encrypted = remote.connection_url
        await session.flush()
        disclosure = tr(user.language, "old_link_invalidated") if remote.old_link_invalidated is True else tr(user.language, "old_link_not_guaranteed")
        await edit_or_send(callback, f"{disclosure}\n{remote.connection_url}", main_menu(user.language))

    @router.callback_query(F.data == "topup:start")
    async def topup_start(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if not user or not user.language or not user.currency:
            return
        amounts = settings.topup_presets_minor.get(user.currency, ())
        rows = [
            [InlineKeyboardButton(text=format_money(value, user.currency, user.language), callback_data=f"topup:amount:{value}")]
            for value in amounts
        ]
        rows.append([InlineKeyboardButton(text=tr(user.language, "other"), callback_data="topup:other")])
        rows.append([InlineKeyboardButton(text=tr(user.language, "back"), callback_data="menu:balance")])
        if not amounts:
            await edit_or_send(callback, tr(user.language, "topup_unconfigured"), main_menu(user.language))
            return
        await edit_or_send(callback, tr(user.language, "topup_prompt"), InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data.startswith("topup:amount:"))
    async def topup_select(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if not user or not user.currency or not user.language:
            return
        try:
            amount = int(callback.data.rsplit(":", 1)[1])
        except (ValueError, AttributeError):
            return
        if amount not in settings.topup_presets_minor.get(user.currency, ()):
            return
        support = settings.support_url or (f"https://t.me/{settings.support_username}" if settings.support_username else None)
        rows = []
        if settings.platega_configured:
            rows.append([InlineKeyboardButton(text="💳 Platega", callback_data=f"topup:pay:platega:{amount}")])
        if settings.cryptobot_configured:
            rows.append([InlineKeyboardButton(text="🪙 CryptoBot", callback_data=f"topup:pay:cryptobot:{amount}")])
        if support:
            rows.append([InlineKeyboardButton(text=f"📞 {tr(user.language, 'support')}", url=support)])
        if not rows:
            await edit_or_send(callback, tr(user.language, "payment_methods_unavailable"), main_menu(user.language))
            return
        await edit_or_send(callback, tr(user.language, "payment_choose", amount=format_money(amount, user.currency, user.language)), InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data.startswith("topup:pay:"))
    async def topup_unavailable_provider(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if user and user.language:
            await edit_or_send(callback, tr(user.language, "payment_methods_unavailable"), main_menu(user.language))

    @router.callback_query(F.data == "topup:other")
    async def topup_other(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        user = await get_user(session, callback.from_user.id)
        if user and user.language and callback.message:
            await callback.message.answer(tr(user.language, "topup_enter_amount"))

    @router.message(F.text.regexp(r"^\\d+(?:[.,]\\d+)?$"))
    async def topup_custom_amount(message: Message, session: AsyncSession) -> None:
        if not message.from_user or not message.text:
            return
        user = await get_user(session, message.from_user.id)
        if not user or user.blocked or not user.currency or not user.language:
            return
        try:
            amount = parse_minor_units(message.text.replace(",", "."), user.currency)
        except ValueError:
            await message.answer(tr(user.language, "topup_invalid_amount"))
            return
        minimum = settings.topup_min_minor.get(user.currency)
        maximum = settings.topup_max_minor.get(user.currency)
        if minimum is None or maximum is None or not minimum <= amount <= maximum:
            await message.answer(tr(user.language, "topup_invalid_amount"))
            return
        await message.answer(tr(user.language, "payment_methods_unavailable"))

    @router.message(Command("admin"))
    async def admin_entry(message: Message) -> None:
        if message.from_user is None or message.from_user.id not in settings.admin_ids:
            await message.answer("Access denied.")
            return
        from src.admin.handlers import admin_keyboard

        await message.answer("Admin panel", reply_markup=admin_keyboard())

    return router


async def show_main_menu(message: Message, user: User) -> None:
    await message.answer(tr(user.language, "menu"), reply_markup=main_menu(user.language))


async def show_vpn(
    target: Message | CallbackQuery,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    if not user.language:
        return
    subscription = await session.scalar(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status == "active")
        .order_by(Subscription.expires_at.desc())
        .limit(1)
    )
    if subscription is None:
        markup = one_button(f"💸 {tr(user.language, 'buy')}", "menu:buy")
        await answer_or_edit(target, tr(user.language, "no_subscription"), markup)
        return
    plan = await session.get(Plan, subscription.plan_id) if subscription.plan_id else None
    plan_label = plan.name if plan else ("Пробный" if user.language == "ru" else "Trial")
    details = active_subscription_text(
        user.language,
        plan=plan_label,
        expires_at=subscription.expires_at,
        timezone_name=settings.timezone,
        connection_url=subscription.connection_url_encrypted or "",
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"💸 {tr(user.language, 'renew')}", callback_data="menu:buy"
                ),
                InlineKeyboardButton(
                    text=f"🌐 {tr(user.language, 'reissue')}", callback_data="vpn:reissue:confirm"
                ),
            ],
            [InlineKeyboardButton(text=f"↩️ {tr(user.language, 'back')}", callback_data="nav:menu")],
        ]
    )
    await answer_or_edit(target, details, keyboard)


async def show_profile(target: Message | CallbackQuery, session: AsyncSession, user: User) -> None:
    if not user.language:
        return
    active = await session.scalar(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status == "active")
        .order_by(Subscription.expires_at.desc())
        .limit(1)
    )
    status = "Active" if active else ("Активна" if user.language == "ru" else "Inactive")
    plan_text = ""
    if active and active.plan_id:
        from src.db.models import Plan

        plan = await session.get(Plan, active.plan_id)
        if plan:
            plan_text = f"\nPlan: {plan.name}"
    safe_name = user.first_name.replace("<", "&lt;").replace(">", "&gt;")
    text = f"👤 {safe_name}\nTelegram ID: {user.telegram_id}\nSubscription: {status}{plan_text}"
    await answer_or_edit(target, text, one_button(f"🔐 {tr(user.language, 'my_vpn')}", "menu:vpn"))


async def show_offer(target: Message, settings: Settings, user: User) -> None:
    await target.answer(
        tr(user.language, "offer_acceptance"),
        reply_markup=offer_keyboard(settings.offer_url, user.language),
    )


async def edit_or_send(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest:
            await callback.message.answer(text, reply_markup=keyboard)


async def answer_or_edit(
    target: Message | CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, text, keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)


__all__ = ["build_user_router", "show_offer", "show_profile", "show_vpn"]
