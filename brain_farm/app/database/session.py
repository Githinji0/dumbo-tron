from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from brain_farm.app.core.config import settings

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"timeout": 30} if settings.DATABASE_URL.startswith("sqlite") else {}
)

# Create session maker
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Declarative base
class Base(DeclarativeBase):
    pass

async def init_db():
    """Initializes tables in the database."""
    async with engine.begin() as conn:
        # Create all tables if they don't exist
        await conn.run_sync(Base.metadata.create_all)
