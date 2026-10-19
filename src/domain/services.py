from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.db.models import (
    Order,
    OrderState,
    PaymentAttempt,
    PaymentState,
    Plan,
    PlanPrice,
    PromoCode,
    PromoRedemption,
    PromoReservation,
    ProviderOperation,
    ReferralReward,
    Subscription,
    TrialGrant,
    User,
    Wallet,
    WalletLedger,
)
from src.integrations import (
    CheckoutRequest,
    PaymentAdapter,
    ProviderUnavailable,
    ProvisionRequest,
    RemnawaveAdapter,
    validate_payment_event,
)


class BusinessRuleError(ValueError):
    pass


class InsufficientBalance(BusinessRuleError):
    pass


class CurrencyNotConfigured(BusinessRuleError):
    pass


class ProvisioningPending(RuntimeError):
    """Provider operation was durably recorded but could not be completed yet."""


@dataclass(frozen=True, slots=True)
class OrderResult:
    public_id: str
    state: str
    amount_minor: int
    currency: str


async def register_user(
    session: AsyncSession,
    telegram_id: int,
    first_name: str,
    username: str | None,
    referral_token: str | None = None,
) -> tuple[User, bool]:
    user = await session.scalar(
        select(User).where(User.telegram_id == telegram_id).with_for_update()
    )
    if user:
        return user, False
    inviter = None
    if referral_token:
        inviter = await session.scalar(select(User).where(User.referral_token == referral_token))
        if inviter is not None and inviter.telegram_id == telegram_id:
            inviter = None
    user = User(
        telegram_id=telegram_id,
        first_name=first_name[:128],
        username=username,
        referral_token=uuid4().hex,
    )
    if inviter is not None:
        user.referred_by_id = inviter.id
    session.add(user)
    await session.flush()
    return user, True


async def provision_registered_user(
    session: AsyncSession, user: User, adapter: RemnawaveAdapter
) -> User:
    """Reconcile existing accounts only; don't create a planless provider account speculatively."""
    if user.provisioning_state == "succeeded" and user.remnawave_user_id:
        return user
    operation_key = f"user-provision:{user.telegram_id}"
    operation = await session.scalar(
        select(ProviderOperation)
        .where(ProviderOperation.idempotency_key == operation_key)
        .with_for_update()
    )
    if operation is None:
        operation = ProviderOperation(
            provider="remnawave",
            operation="provision_user",
            idempotency_key=operation_key,
            entity_ref=str(user.id),
            state="pending",
        )
        session.add(operation)
        await session.flush()
    try:
        remote = await adapter.get_subscription(operation_key)
    except ProviderUnavailable as exc:
        operation.attempt_count += 1
        operation.last_error_code = type(exc).__name__
        await session.flush()
        raise ProvisioningPending("Remnawave registration is pending retry") from exc
    if remote is None:
        return user
    user.remnawave_user_id = remote.remote_user_id
    user.provisioning_state = "succeeded"
    operation.state = "succeeded"
    operation.attempt_count += 1
    operation.response_metadata = {"remote_user_id": remote.remote_user_id}
    await session.flush()
    return user


async def ensure_wallet(session: AsyncSession, user_id: int, currency: str) -> Wallet:
    currency = currency.upper()
    wallet = await session.scalar(
        select(Wallet).where(Wallet.user_id == user_id, Wallet.currency == currency).with_for_update()
    )
    if wallet is None:
        wallet = Wallet(user_id=user_id, currency=currency, balance_minor=0)
        session.add(wallet)
        await session.flush()
    return wallet


async def change_wallet_balance(
    session: AsyncSession,
    *,
    user_id: int,
    currency: str,
    amount_minor: int,
    kind: str,
    idempotency_key: str,
    reference: str | None = None,
    memo: str | None = None,
) -> Wallet:
    if amount_minor == 0:
        raise BusinessRuleError("Ledger entries cannot be zero")
    existing = await session.scalar(
        select(WalletLedger).where(WalletLedger.idempotency_key == idempotency_key)
    )
    if existing is not None:
        wallet = await session.get(Wallet, existing.wallet_id)
        if wallet is None:
            raise RuntimeError("Ledger references missing wallet")
        return wallet
    wallet = await ensure_wallet(session, user_id, currency)
    if wallet.currency != currency.upper():
        raise BusinessRuleError("Currency mismatch")
    updated = wallet.balance_minor + amount_minor
    if updated < 0:
        raise InsufficientBalance("Insufficient balance")
    wallet.balance_minor = updated
    session.add(
        WalletLedger(
            user_id=user_id,
            wallet_id=wallet.id,
            currency=currency.upper(),
            amount_minor=amount_minor,
            kind=kind,
            idempotency_key=idempotency_key,
            reference=reference,
            memo=memo,
        )
    )
    await session.flush()
    return wallet


async def seed_catalog(session: AsyncSession, settings: Settings) -> None:
    for config in settings.plans:
        plan = await session.scalar(select(Plan).where(Plan.code == config.code).with_for_update())
        if plan is None:
            plan = Plan(
                code=config.code,
                name=config.name,
                devices=config.devices,
                traffic_gb=config.traffic_gb,
                duration_days=config.duration.days,
                active=True,
            )
            session.add(plan)
            await session.flush()
        else:
            plan.name = config.name
            plan.devices = config.devices
            plan.traffic_gb = config.traffic_gb
            plan.duration_days = config.duration.days
        for currency, amount in config.prices_minor.items():
            price = await session.scalar(
                select(PlanPrice)
                .where(PlanPrice.plan_id == plan.id, PlanPrice.currency == currency)
                .with_for_update()
            )
            if amount is None:
                if price is not None:
                    await session.delete(price)
            elif price is None:
                session.add(PlanPrice(plan_id=plan.id, currency=currency, amount_minor=amount))
            else:
                price.amount_minor = amount
    await session.flush()


async def plan_price(session: AsyncSession, plan_code: str, currency: str) -> tuple[Plan, int]:
    plan = await session.scalar(select(Plan).where(Plan.code == plan_code, Plan.active.is_(True)))
    if plan is None:
        raise BusinessRuleError("Plan is unavailable")
    price = await session.scalar(
        select(PlanPrice).where(
            PlanPrice.plan_id == plan.id,
            PlanPrice.currency == currency.upper(),
        )
    )
    if price is None:
        raise CurrencyNotConfigured(f"No configured {currency.upper()} price for {plan_code}")
    return plan, price.amount_minor


async def create_purchase_order(
    session: AsyncSession,
    *,
    user: User,
    plan_code: str,
    currency: str,
    idempotency_key: str,
    promo_code: str | None = None,
    paid_via_wallet: bool = True,
) -> OrderResult:
    current = await session.scalar(
        select(Order).where(Order.idempotency_key == idempotency_key).with_for_update()
    )
    if current is not None:
        return OrderResult(current.public_id, current.state, current.amount_minor, current.currency)
    plan, amount = await plan_price(session, plan_code, currency)
    promo: PromoCode | None = None
    if promo_code:
        promo = await _reserve_promo(session, user=user, code=promo_code)
        amount = amount * (100 - promo.discount_percent) // 100
    order = Order(
        public_id=uuid4().hex[:16],
        user_id=user.id,
        plan_id=plan.id,
        state=OrderState.CREATED,
        currency=currency.upper(),
        amount_minor=amount,
        idempotency_key=idempotency_key,
        paid_via_wallet=paid_via_wallet,
    )
    session.add(order)
    await session.flush()
    if promo is not None:
        session.add(
            PromoReservation(
                promo_id=promo.id,
                user_id=user.id,
                order_id=order.id,
                state="reserved",
            )
        )
    if paid_via_wallet:
        wallet = await ensure_wallet(session, user.id, currency)
        if wallet.balance_minor < amount:
            raise InsufficientBalance("Insufficient balance")
        order.state = OrderState.PAID
    await session.flush()
    return OrderResult(order.public_id, order.state, order.amount_minor, order.currency)


async def _reserve_promo(session: AsyncSession, *, user: User, code: str) -> PromoCode:
    promo = await session.scalar(
        select(PromoCode)
        .where(PromoCode.code_normalized == code.strip().upper(), PromoCode.active.is_(True))
        .with_for_update()
    )
    if promo is None or not 0 < promo.discount_percent <= 100:
        raise BusinessRuleError("Promo code is invalid or inactive")
    if await session.scalar(
        select(PromoRedemption).where(
            PromoRedemption.promo_id == promo.id,
            PromoRedemption.user_id == user.id,
        )
    ):
        raise BusinessRuleError("Promo code was already used")
    reservation = await session.scalar(
        select(PromoReservation).where(
            PromoReservation.promo_id == promo.id,
            PromoReservation.user_id == user.id,
            PromoReservation.state == "reserved",
        )
    )
    if reservation is not None:
        raise BusinessRuleError("Promo code is already reserved by this user")
    reserved_count = (
        await session.scalar(
            select(func.count())
            .select_from(PromoReservation)
            .where(PromoReservation.promo_id == promo.id, PromoReservation.state == "reserved")
        )
        or 0
    )
    if promo.used_count + reserved_count >= promo.max_uses:
        raise BusinessRuleError("Promo code has no uses remaining")
    return promo


async def apply_promo_code(
    session: AsyncSession, *, order: Order, user: User, promo_code: str
) -> Order:
    if order.user_id != user.id or order.state != OrderState.CREATED:
        raise BusinessRuleError("Promo code cannot be applied to this order")
    if await session.scalar(
        select(PromoReservation).where(
            PromoReservation.user_id == user.id,
            PromoReservation.state == "reserved",
        )
    ):
        raise BusinessRuleError("Another promo code is already reserved")
    promo = await _reserve_promo(session, user=user, code=promo_code)
    plan = await session.get(Plan, order.plan_id)
    if plan is None:
        raise BusinessRuleError("Plan is unavailable")
    price = await session.scalar(
        select(PlanPrice).where(
            PlanPrice.plan_id == plan.id,
            PlanPrice.currency == order.currency,
        )
    )
    if price is None:
        raise CurrencyNotConfigured("Price is not configured")
    order.amount_minor = price.amount_minor * (100 - promo.discount_percent) // 100
    session.add(
        PromoReservation(
            promo_id=promo.id,
            user_id=user.id,
            order_id=order.id,
            state="reserved",
        )
    )
    await session.flush()
    return order


async def fulfill_paid_order(
    session: AsyncSession, *, order_public_id: str, adapter: RemnawaveAdapter, settings: Settings
) -> Subscription:
    order = await session.scalar(
        select(Order).where(Order.public_id == order_public_id).with_for_update()
    )
    if order is None:
        raise BusinessRuleError("Order not found")
    if order.state == OrderState.FULFILLED:
        subscription = await session.scalar(
            select(Subscription).where(Subscription.idempotency_key == f"order:{order.id}")
        )
        if subscription is None:
            raise RuntimeError("Fulfilled order is missing its subscription")
        return subscription
    if order.state not in (OrderState.PAID, OrderState.PROVISIONING):
        raise BusinessRuleError("Order is not paid")
    plan = await session.get(Plan, order.plan_id)
    user = await session.get(User, order.user_id)
    if plan is None or user is None:
        raise RuntimeError("Order references missing plan or user")
    operation_key = f"subscription-order:{order.id}"
    operation = await session.scalar(
        select(ProviderOperation)
        .where(ProviderOperation.idempotency_key == operation_key)
        .with_for_update()
    )
    if operation is None:
        operation = ProviderOperation(
            provider="remnawave",
            operation="provision_subscription",
            idempotency_key=operation_key,
            entity_ref=order.public_id,
        )
        session.add(operation)
        await session.flush()
    if order.paid_via_wallet and operation.attempt_count == 0:
        await change_wallet_balance(
            session,
            user_id=order.user_id,
            currency=order.currency,
            amount_minor=-order.amount_minor,
            kind="subscription_purchase",
            idempotency_key=f"order-debit:{order.idempotency_key}",
            reference=order.public_id,
        )
    order.state = OrderState.PROVISIONING
    await session.flush()
    try:
        remote = await adapter.provision(
            ProvisionRequest(
                external_key=operation_key,
                telegram_id=user.telegram_id,
                plan_code=plan.code,
                duration_days=plan.duration_days,
                devices=plan.devices,
                traffic_gb=plan.traffic_gb,
            )
        )
    except ProviderUnavailable as exc:
        operation.attempt_count += 1
        operation.last_error_code = type(exc).__name__
        operation.state = "pending"
        await session.flush()
        raise ProvisioningPending(
            "Order payment is confirmed; provisioning is pending retry"
        ) from exc
    subscription = await session.scalar(
        select(Subscription).where(Subscription.idempotency_key == f"order:{order.id}")
    )
    if subscription is None:
        subscription = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            provider_user_id=remote.remote_user_id,
            connection_url_encrypted=remote.connection_url,
            expires_at=remote.expires_at,
            status="active",
            source="purchase",
            idempotency_key=f"order:{order.id}",
        )
        session.add(subscription)
    else:
        subscription.provider_user_id = remote.remote_user_id
        subscription.connection_url_encrypted = remote.connection_url
        subscription.expires_at = remote.expires_at
        subscription.status = "active"
    user.remnawave_user_id = remote.remote_user_id
    user.provisioning_state = "succeeded"
    order.state = OrderState.FULFILLED
    operation.state = "succeeded"
    operation.attempt_count += 1
    operation.response_metadata = {
        "remote_user_id": remote.remote_user_id,
        "expiry": remote.expires_at.isoformat(),
    }
    await _consume_promo_reservation(session, order)
    await _award_referral(session, order, user, settings.referral_reward_days)
    await session.flush()
    return subscription


async def _consume_promo_reservation(session: AsyncSession, order: Order) -> None:
    reservation = await session.scalar(
        select(PromoReservation)
        .where(PromoReservation.order_id == order.id, PromoReservation.state == "reserved")
        .with_for_update()
    )
    if reservation is None:
        return
    promo = await session.scalar(
        select(PromoCode).where(PromoCode.id == reservation.promo_id).with_for_update()
    )
    if promo is None:
        raise RuntimeError("Promo reservation references missing code")
    if promo.used_count >= promo.max_uses:
        raise BusinessRuleError("Promo code usage limit reached before fulfillment")
    reservation.state = "consumed"
    promo.used_count += 1
    session.add(PromoRedemption(promo_id=promo.id, user_id=order.user_id, order_id=order.id))


async def release_promo_reservation(session: AsyncSession, order_id: int) -> None:
    reservation = await session.scalar(
        select(PromoReservation)
        .where(PromoReservation.order_id == order_id, PromoReservation.state == "reserved")
        .with_for_update()
    )
    if reservation is not None:
        reservation.state = "released"


async def _award_referral(
    session: AsyncSession, order: Order, user: User, reward_days: int
) -> ReferralReward | None:
    if order.qualification_source != "purchase" or not user.referred_by_id:
        return None
    if order.state != OrderState.FULFILLED:
        return None
    existing = await session.scalar(
        select(ReferralReward).where(ReferralReward.referred_user_id == user.id)
    )
    if existing:
        return existing
    reward = ReferralReward(
        inviter_user_id=user.referred_by_id,
        referred_user_id=user.id,
        order_id=order.id,
        reward_days=reward_days,
        state="pending",
    )
    session.add(reward)
    await session.flush()
    return reward


async def award_trial(
    session: AsyncSession, *, user: User, adapter: RemnawaveAdapter, settings: Settings
) -> Subscription:
    now = datetime.now(UTC)
    locked = await session.scalar(select(User).where(User.id == user.id).with_for_update())
    if locked is None:
        raise BusinessRuleError("User not found")
    if locked.trial_next_eligible_at is not None and locked.trial_next_eligible_at > now:
        raise BusinessRuleError(f"Trial available after {locked.trial_next_eligible_at.isoformat()}")
    if await session.scalar(
        select(TrialGrant).where(TrialGrant.user_id == locked.id, TrialGrant.state == "pending")
    ):
        raise BusinessRuleError("A trial grant is already pending")
    grant_key = f"trial:{locked.id}:{uuid4().hex}"
    grant = TrialGrant(user_id=locked.id, grant_key=grant_key, state="pending")
    session.add(grant)
    await session.flush()
    plan = next((p for p in settings.plans if p.code == "starter"), None)
    if plan is None:
        raise BusinessRuleError("Trial plan is not configured")
    try:
        remote = await adapter.provision(
            ProvisionRequest(
                external_key=grant_key,
                telegram_id=locked.telegram_id,
                plan_code=plan.code,
                duration_days=settings.trial_days,
                devices=plan.devices,
                traffic_gb=plan.traffic_gb,
            )
        )
    except ProviderUnavailable as exc:
        grant.state = "failed"
        await session.flush()
        raise ProvisioningPending(
            "Trial provisioning is pending; no trial entitlement was recorded"
        ) from exc
    grant.state = "succeeded"
    grant.provider_subscription_id = remote.remote_user_id
    grant.expires_at = remote.expires_at
    locked.trial_next_eligible_at = now + timedelta(days=settings.trial_cooldown_days)
    subscription = Subscription(
        user_id=locked.id,
        plan_id=None,
        provider_user_id=remote.remote_user_id,
        connection_url_encrypted=remote.connection_url,
        expires_at=remote.expires_at,
        status="active",
        source="trial",
        idempotency_key=grant_key,
    )
    session.add(subscription)
    await session.flush()
    return subscription


async def create_topup_checkout(
    session: AsyncSession,
    *,
    user: User,
    amount_minor: int,
    currency: str,
    provider: PaymentAdapter,
    return_url: str,
    minimum_minor: int,
    maximum_minor: int,
    idempotency_key: str,
) -> PaymentAttempt:
    currency = currency.upper()
    if amount_minor < minimum_minor or amount_minor > maximum_minor:
        raise BusinessRuleError("Top-up amount is outside the configured range")
    if provider.name not in {"platega", "cryptobot"}:
        raise BusinessRuleError("Unsupported payment provider")
    attempt = PaymentAttempt(
        user_id=user.id,
        provider=provider.name,
        amount_minor=amount_minor,
        currency=currency,
        state=PaymentState.PENDING,
    )
    session.add(attempt)
    await session.flush()
    checkout = await provider.create_checkout(
        CheckoutRequest(
            order_reference=f"topup:{attempt.id}",
            amount_minor=amount_minor,
            currency=currency,
            description="VPN wallet top-up",
            return_url=return_url,
        ),
        idempotency_key,
    )
    attempt.provider_payment_id = checkout.provider_payment_id
    attempt.checkout_url = checkout.url
    await session.flush()
    return attempt


async def apply_verified_payment(
    session: AsyncSession,
    *,
    attempt: PaymentAttempt,
    event_body: bytes,
    headers: dict[str, str],
    provider: PaymentAdapter,
) -> bool:
    attempt = await session.scalar(
        select(PaymentAttempt).where(PaymentAttempt.id == attempt.id).with_for_update()
    )
    if attempt is None or attempt.state == PaymentState.SUCCEEDED:
        return False
    event = provider.verify_webhook(event_body, headers)
    if (
        attempt.provider_payment_id is None
        or event.provider_payment_id != attempt.provider_payment_id
    ):
        raise BusinessRuleError("Payment reference mismatch")
    validate_payment_event(
        event,
        reference=f"topup:{attempt.id}",
        amount_minor=attempt.amount_minor,
        currency=attempt.currency,
    )
    previous = await session.scalar(
        select(PaymentAttempt).where(
            PaymentAttempt.provider == provider.name,
            PaymentAttempt.provider_event_id == event.event_id,
        )
    )
    if previous is not None:
        return False
    attempt.provider_event_id = event.event_id
    attempt.state = PaymentState.SUCCEEDED
    await change_wallet_balance(
        session,
        user_id=attempt.user_id,
        currency=attempt.currency,
        amount_minor=attempt.amount_minor,
        kind="verified_topup",
        idempotency_key=f"payment-credit:{provider.name}:{event.provider_payment_id}",
        reference=event.provider_payment_id,
    )
    await session.flush()
    return True


def trial_next_eligible(user: User) -> datetime | None:
    return user.trial_next_eligible_at


__all__ = [
    "BusinessRuleError",
    "CurrencyNotConfigured",
    "InsufficientBalance",
    "OrderResult",
    "ProvisioningPending",
    "apply_promo_code",
    "apply_verified_payment",
    "award_trial",
    "change_wallet_balance",
    "create_purchase_order",
    "create_topup_checkout",
    "ensure_wallet",
    "fulfill_paid_order",
    "plan_price",
    "provision_registered_user",
    "register_user",
    "release_promo_reservation",
    "seed_catalog",
    "trial_next_eligible",
]
