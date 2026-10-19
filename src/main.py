from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import text

from src.admin.router import register_admin_handlers
from src.bot.handlers import build_user_router
from src.config import ConfigurationError, Settings
from src.db.session import make_engine, make_session_factory
from src.domain.health import initialize_catalog
from src.integrations import UnavailableRemnawave
from src.logging_config import configure_logging

logger = logging.getLogger(__name__)


async def run() -> None:
    configure_logging()
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    engine = make_engine(settings)
    session_factory = make_session_factory(engine)
    remnawave = UnavailableRemnawave()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.include_router(build_user_router(settings, remnawave))
    register_admin_handlers(dispatcher, settings, remnawave)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SELECT 1"))
        async with session_factory() as session:
            await initialize_catalog(session, settings)
        logger.info("Database ready; starting Telegram polling")
        await dispatcher.start_polling(bot, session=session_factory)
    except TelegramAPIError:
        logger.exception("Telegram polling failed")
        raise
    finally:
        with suppress(Exception):
            await bot.session.close()
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Shutdown requested")


if __name__ == "__main__":
    main()
