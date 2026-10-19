# Remnawave Telegram VPN bot

A Python 3.12+ Telegram bot foundation for selling VPN subscriptions through Remnawave. The bot includes bilingual RU/EN interaction, per-currency wallets, payment/provider boundaries, order idempotency records, trials, referrals, promo persistence, admin authorization entry, migrations, and local container configuration.

> **Provider safety:** this repository does not include a live Remnawave adapter. No instance/version-specific OpenAPI contract or credentials were provided, so provisioning, trial, paid fulfillment, and reissue fail safely and remain pending rather than creating local entitlements or claiming success. Payment adapters are disabled unless implemented against verified provider documentation; a payment redirect or client callback is never accepted as payment evidence.

## Requirements and local setup

- Python 3.12 or later
- Docker Engine with Compose (or a reachable PostgreSQL 16 service)
- Telegram bot token from BotFather

Copy `.env.example` to `.env` and fill in required values. `BOT_TOKEN`, `DATABASE_URL`, and `OFFER_URL` are required. Never commit `.env` or production credentials.

```bash
python -m venv .venv
```

```bash
. .venv/Scripts/activate
```

```bash
python -m pip install -e ".[dev]"
```

```bash
docker compose up -d db
```

```bash
python -m alembic upgrade head
```

```bash
python -m src.main
```

The Compose service starts the bot after Postgres health-check. The bot refuses to start when required configuration is invalid or Telegram credentials are missing.

## Configuration

- `BOT_TOKEN`: Telegram bot token. Keep secret.
- `ADMIN_IDS`: comma-separated numeric Telegram IDs. Admin entry is denied to other users.
- `DATABASE_URL`: async PostgreSQL URL (Compose default is `postgresql+asyncpg://bot:bot@db:5432/vpn_bot`). SQLite async URLs are permitted for unit-level local testing only.
- `REDIS_URL`: reserved optional setting; current workflows do not require Redis.
- `TIMEZONE`: IANA timezone for display, default `UTC`.
- `OFFER_URL`: configured offer link. The bot displays the localized notice “By continuing to use the bot, you accept the offer terms”; it does not make legal-compliance claims.
- `SUPPORT_URL` / `SUPPORT_USERNAME`: support destination; absent values produce a localized not-configured message.
- `CHANNEL_GATE_ENABLED`, `REQUIRED_CHANNEL_ID`, `REQUIRED_CHANNEL_URL`: mandatory channel settings. A Telegram bot must be able to call `getChatMember` (for reliable member checks, make it an administrator in the channel). UI entry points are present; channel membership enforcement is not yet wired into dispatcher middleware and must not be considered deployed until that is implemented and tested.
- `REMWAVE_BASE_URL`, `REMWAVE_API_TOKEN`, `REMWAVE_API_VERSION`: reserved credentials/metadata. No API route is assumed. Obtain the deployed Remnawave version's official OpenAPI specification, verify authentication and user/subscription/reissue operations, then implement and contract-test `RemnawaveAdapter` in `src/integrations/`.
- `PLATEGA_MERCHANT_ID`, `PLATEGA_SECRET`, `PLATEGA_WEBHOOK_SECRET`, `CRYPTOBOT_*`: reserved provider secrets. Live checkout/webhooks are not implemented. Credentials alone do not enable success; verify Platega's official API and signature scheme before adding an adapter and HTTPS webhook endpoint.

### Prices, durations, currencies

Prices are integer minor units and currency-specific. RUB defaults match the brief: Starter 99 RUB (2 devices, 50 GB), Standard 179 RUB (5 devices, 250 GB), Company 349 RUB (15 devices, unlimited traffic). USD prices and presets are intentionally unset; no FX conversion is performed. Set `USD_STARTER_PRICE_MINOR`, `USD_STANDARD_PRICE_MINOR`, and `USD_COMPANY_PRICE_MINOR` explicitly to enable those catalog prices. Configure per-currency top-up presets/min/max with the corresponding environment variables; top-up UI is not yet connected to provider adapters.

`DEFAULT_PLAN_DAYS` is provisionally 30; per-plan `STARTER_DURATION_DAYS`, `STANDARD_DURATION_DAYS`, and `COMPANY_DURATION_DAYS` override it. Trial duration defaults to 2 days, cooldown to 60 days since successful grant, and referral reward to 3 days. `MAX_PROMO_DISCOUNT_PERCENT` bounds promo configuration. Amount precision is validated per currency; all current supported currencies use two decimal places.

## Database and operations

Alembic migrations are under `alembic/`. Apply with `python -m alembic upgrade head`. PostgreSQL is the source of truth for wallet ledgers, orders, provider attempts, and entitlements. `ProviderOperation` and pending states are designed for safe reconciliation after provider timeouts, but an automated scheduler/worker and admin reconciliation command are still outstanding.

Use PostgreSQL backups appropriate to the deployment, encrypt backups at rest, and test restoring a backup in a non-production environment. Do not delete pending provider/payment records during recovery. Check provider dashboards by internal order/payment reference and reconcile through verified APIs before any manual adjustment. Manual balance adjustments must be represented as ledger entries and audited; never treat them as revenue.

## Tests and checks

Install dev dependencies, then run:

```bash
pytest
```

```bash
ruff check .
```

```bash
mypy src
```

Provider integrations require sandbox credentials and contract tests against the exact provider versions. Do not use production customers for smoke testing. The initial repository has no live credentials, Remnawave OpenAPI file, Telegram token, or payment-provider verification data; external services are therefore unverified.

## Security and deployment notes

- Use HTTPS for any payment webhook endpoint and validate documented provider signatures against the exact raw request body.
- Persist webhook event IDs and reject replay/duplicates; validate payment reference, amount, currency, and success state before crediting exactly once.
- Keep bot tokens, provider credentials, webhook secrets, and complete subscription links out of logs. Connection URLs are sensitive account credentials; currently the model field is named `connection_url_encrypted` but encryption/key management has not yet been implemented, so do not persist production links until encryption-at-rest is added.
- Configure PostgreSQL strong credentials and a private network in production; rotate leaked or expired tokens promptly.
- Avoid enabling real checkout until the checkout and webhook adapter, HTTPS ingress, idempotency, reconciliation, and failure-mode tests are complete.
- The current admin UI is an authorized entry point only. Grant/block/broadcast/statistics/admin callback actions need their service handlers and audit-confirmation flows before production use.
