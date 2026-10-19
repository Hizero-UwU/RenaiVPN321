from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.config import Settings
from src.db.models import (
    AdminAuditEvent,
    Order,
    PaymentAttempt,
    PaymentState,
    Subscription,
    User,
    Wallet,
)
from src.domain.services import BusinessRuleError, change_wallet_balance


class AdminAuthorizationError(PermissionError):
    pass


async def require_admin(
    session: AsyncSession, *, admin_telegram_id: int, settings: Settings
) -> None:
    if admin_telegram_id not in settings.admin_ids:
        raise AdminAuthorizationError("Access denied")
    await session.flush()


async def audit_admin_action(
    session: AsyncSession,
    *,
    admin_telegram_id: int,
    action: str,
    target_ref: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AdminAuditEvent(
            admin_telegram_id=admin_telegram_id,
            action=action,
            target_ref=target_ref,
            details=details,
        )
    )
    await session.flush()


async def grant_balance(
    session: AsyncSession,
    *,
    admin_telegram_id: int,
    user: User,
    currency: str,
    amount_minor: int,
    idempotency_key: str,
) -> Wallet:
    if amount_minor <= 0:
        raise BusinessRuleError("Admin balance grant must be positive")
    wallet = await change_wallet_balance(
        session,
        user_id=user.id,
        currency=currency,
        amount_minor=amount_minor,
        kind="admin_adjustment",
        idempotency_key=idempotency_key,
        reference=f"admin:{admin_telegram_id}",
    )
    await audit_admin_action(
        session,
        admin_telegram_id=admin_telegram_id,
        action="grant_balance",
        target_ref=str(user.telegram_id),
        details={"currency": currency.upper(), "amount_minor": amount_minor},
    )
    return wallet


async def set_user_blocked(
    session: AsyncSession, *, admin_telegram_id: int, user: User, blocked: bool
) -> None:
    user.blocked = blocked
    await audit_admin_action(
        session,
        admin_telegram_id=admin_telegram_id,
        action="block_user" if blocked else "unblock_user",
        target_ref=str(user.telegram_id),
    )
    await session.flush()


async def statistics(session: AsyncSession) -> dict[str, Any]:
    from sqlalchemy import func

    users = await session.scalar(select(func.count()).select_from(User)) or 0
    active = (
        await session.scalar(
            select(func.count()).select_from(Subscription).where(Subscription.status == "active")
        )
        or 0
    )
    orders = await session.scalar(select(func.count()).select_from(Order)) or 0
    payments = await session.execute(
        select(
            PaymentAttempt.currency, PaymentAttempt.state, func.sum(PaymentAttempt.amount_minor)
        ).group_by(PaymentAttempt.currency, PaymentAttempt.state)
    )
    payment_totals = {
        f"{currency}:{state}": int(total or 0) for currency, state, total in payments.all()
    }
    sales = await session.execute(
        select(Order.currency, Order.state, func.sum(Order.amount_minor)).group_by(
            Order.currency, Order.state
        )
    )
    order_totals = {
        f"{currency}:{state}": int(total or 0) for currency, state, total in sales.all()
    }
    return {
        "period": "all time",
        "registered_users": users,
        "active_subscriptions": active,
        "orders": orders,
        "payment_totals_by_currency_state": payment_totals,
        "sales_totals_by_currency_state": order_totals,
    }


async def ensure_admin_user(session: AsyncSession, telegram_id: int) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        raise BusinessRuleError("Target user not found")
    return user


async def create_manual_payment_request(
    session: AsyncSession,
    *,
    user: User,
    amount_minor: int,
    currency: str,
    provider: str,
    reference: str,
) -> PaymentAttempt:
    if amount_minor <= 0:
        raise BusinessRuleError("Payment request amount must be positive")
    attempt = PaymentAttempt(
        user_id=user.id,
        provider=provider,
        amount_minor=amount_minor,
        currency=currency.upper(),
        support_request=True,
        state=PaymentState.PENDING,
        provider_payment_id=reference,
    )
    session.add(attempt)
    await session.flush()
    return attempt


__all__ = [
    "AdminAuthorizationError",
    "audit_admin_action",
    "create_manual_payment_request",
    "ensure_admin_user",
    "grant_balance",
    "require_admin",
    "set_user_blocked",
    "statistics",
]
