from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession
from src.admin.services import (
    AdminAuthorizationError,
    audit_admin_action,
    require_admin,
    statistics,
)
from src.bot.view_models import admin_keyboard
from src.config import Settings
from src.integrations import RemnawaveAdapter

router = Router(name="admin")


def register_admin_handlers(
    router: Router, settings: Settings, remnawave: RemnawaveAdapter
) -> None:
    @router.message(Command("admin"))
    async def entry(message: Message, session: AsyncSession) -> None:
        if message.from_user is None or message.from_user.id not in settings.admin_ids:
            await message.answer("Access denied.")
            return
        await message.answer("Admin panel", reply_markup=admin_keyboard())

    @router.callback_query(F.data.startswith("admin:"))
    async def actions(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        actor_id = callback.from_user.id
        try:
            await require_admin(session, admin_telegram_id=actor_id, settings=settings)
        except AdminAuthorizationError:
            if callback.message:
                await callback.message.answer("Access denied.")
            return
        action = callback.data.removeprefix("admin:")
        if action == "stats" and callback.message:
            totals = await statistics(session)
            await audit_admin_action(session, admin_telegram_id=actor_id, action="view_statistics")
            await callback.message.answer(f"Statistics · {totals['period']}\n{totals}")
            return
        await audit_admin_action(session, admin_telegram_id=actor_id, action=f"open_{action}")
        messages = {
            "broadcast": "Broadcast flow is not configured yet.",
            "channel": "Configure required channel environment variables and restart.",
            "grant_subscription": "Subscription grants require verified Remnawave API contract.",
            "grant_balance": "Use the audited grant service after explicit target/amount confirmation.",
            "block": "Block flow requires target selection and explicit confirmation.",
            "create_promo": "Promo creation requires validated input and explicit confirmation.",
        }
        if callback.message:
            await callback.message.answer(messages.get(action, "Unknown admin action."))

    @router.callback_query(F.data.startswith("admin:confirm:"))
    async def confirmation(callback: CallbackQuery, session: AsyncSession) -> None:
        await callback.answer()
        try:
            await require_admin(session, admin_telegram_id=callback.from_user.id, settings=settings)
        except AdminAuthorizationError:
            if callback.message:
                await callback.message.answer("Access denied.")
            return
        # Confirmation tokens must be backed by a persisted, expiring FSM operation.
        if callback.message:
            await callback.message.answer("No pending confirmed admin operation.")

    @router.message(Command("admin_stats"))
    async def stats_command(message: Message, session: AsyncSession) -> None:
        if message.from_user is None or message.from_user.id not in settings.admin_ids:
            await message.answer("Access denied.")
            return
        totals = await statistics(session)
        await audit_admin_action(
            session, admin_telegram_id=message.from_user.id, action="view_statistics"
        )
        await message.answer(f"Statistics · {totals['period']}\n{totals}")


__all__ = ["register_admin_handlers", "router"]
