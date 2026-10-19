from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.config import Settings
from src.db.models import Base


async def main() -> None:
    settings = Settings.from_env()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(text("SELECT 1"))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
