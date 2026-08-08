from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from brain_farm.app.core.config import settings


# Declarative base
class Base(DeclarativeBase):
    pass


def _make_engine():
    """Create a fresh async engine per call (NullPool = no cross-loop sharing)."""
    return create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        connect_args={"timeout": 30} if settings.DATABASE_URL.startswith("sqlite") else {},
        poolclass=NullPool,
    )


def make_session_factory():
    """Return a new async_sessionmaker bound to a fresh engine."""
    engine = _make_engine()
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


# A convenience alias used by non-UI code (worker, init_db).
# Because this runs only once at import time from the background worker thread,
# it is safe to be module-level there.
AsyncSessionLocal = make_session_factory()


async def init_db():
    """Initialises tables in the database."""
    engine = _make_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
