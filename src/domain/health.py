from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.domain.services import seed_catalog


async def readiness(session: AsyncSession) -> bool:
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def initialize_catalog(session: AsyncSession, settings: Settings) -> None:
    async with session.begin():
        await seed_catalog(session, settings)
