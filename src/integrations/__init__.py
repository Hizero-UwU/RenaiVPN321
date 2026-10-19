from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class ProviderUnavailable(RuntimeError):
    """Raised when no verified provider adapter is configured."""


@dataclass(frozen=True, slots=True)
class ProvisionRequest:
    external_key: str
    telegram_id: int
    plan_code: str
    duration_days: int
    devices: int
    traffic_gb: int | None


@dataclass(frozen=True, slots=True)
class RemoteSubscription:
    remote_user_id: str
    connection_url: str
    expires_at: datetime
    plan_name: str
    devices: int
    traffic_gb: int | None
    old_link_invalidated: bool | None = None


class RemnawaveAdapter(Protocol):
    async def provision(self, request: ProvisionRequest) -> RemoteSubscription: ...
    async def get_subscription(self, remote_user_id: str) -> RemoteSubscription | None: ...
    async def reissue(self, remote_user_id: str, idempotency_key: str) -> RemoteSubscription: ...


class UnavailableRemnawave:
    """Fail-closed adapter until a deployment's API contract has been verified."""

    def __init__(self, reason: str = "Remnawave API contract not configured or verified") -> None:
        self.reason = reason

    async def provision(self, request: ProvisionRequest) -> RemoteSubscription:
        raise ProviderUnavailable(self.reason)

    async def get_subscription(self, remote_user_id: str) -> RemoteSubscription | None:
        raise ProviderUnavailable(self.reason)

    async def reissue(self, remote_user_id: str, idempotency_key: str) -> RemoteSubscription:
        raise ProviderUnavailable(self.reason)


@dataclass(frozen=True, slots=True)
class CheckoutRequest:
    order_reference: str
    amount_minor: int
    currency: str
    description: str
    return_url: str


@dataclass(frozen=True, slots=True)
class Checkout:
    provider_payment_id: str
    url: str
    amount_minor: int
    currency: str


@dataclass(frozen=True, slots=True)
class VerifiedPaymentEvent:
    event_id: str
    provider_payment_id: str
    order_reference: str
    amount_minor: int
    currency: str
    succeeded: bool


class PaymentAdapter(Protocol):
    name: str

    async def create_checkout(self, request: CheckoutRequest, idempotency_key: str) -> Checkout: ...
    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> VerifiedPaymentEvent: ...


class UnavailablePaymentAdapter:
    """Disabled adapter that can never fabricate a successful payment."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def create_checkout(self, request: CheckoutRequest, idempotency_key: str) -> Checkout:
        raise ProviderUnavailable(f"{self.name} is not configured for live payments")

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> VerifiedPaymentEvent:
        raise ProviderUnavailable(f"{self.name} webhook verification is not configured")


def verify_hmac_sha256(raw_body: bytes, secret: str, signature: str) -> bool:
    """Constant-time raw-body HMAC helper for providers documenting this scheme."""
    import hashlib
    import hmac

    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def validate_payment_event(
    event: VerifiedPaymentEvent, *, reference: str, amount_minor: int, currency: str
) -> None:
    if event.order_reference != reference:
        raise ValueError("Payment order reference mismatch")
    if event.amount_minor != amount_minor:
        raise ValueError("Payment amount mismatch")
    if event.currency.upper() != currency.upper():
        raise ValueError("Payment currency mismatch")
    if not event.succeeded:
        raise ValueError("Payment has not succeeded")


__all__ = [
    "Checkout",
    "CheckoutRequest",
    "PaymentAdapter",
    "ProviderUnavailable",
    "ProvisionRequest",
    "RemnawaveAdapter",
    "RemoteSubscription",
    "UnavailablePaymentAdapter",
    "UnavailableRemnawave",
    "VerifiedPaymentEvent",
    "validate_payment_event",
    "verify_hmac_sha256",
]
