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
        
        # Auto-migrate/inspect columns for sqlite
        def migrate_sqlite(connection):
            dbapi_conn = connection.connection
            cursor = dbapi_conn.cursor()
            
            # Expressions table cols
            cursor.execute("PRAGMA table_info(expressions)")
            expr_cols = {row[1] for row in cursor.fetchall()}
            
            expr_additions = [
                ("research_family", "VARCHAR(100)"),
                ("hypothesis", "TEXT"),
                ("lineage_id", "INTEGER"),
                ("complexity_score", "FLOAT"),
                ("parameter_sensitivity", "JSON"),
                ("regime_performance", "JSON")
            ]
            
            for col_name, col_type in expr_additions:
                if col_name not in expr_cols:
                    try:
                        cursor.execute(f"ALTER TABLE expressions ADD COLUMN {col_name} {col_type}")
                    except Exception:
                        pass
                        
            # Metrics table cols
            cursor.execute("PRAGMA table_info(metrics)")
            metrics_cols = {row[1] for row in cursor.fetchall()}
            
            metric_additions = [
                ("rank_ic", "FLOAT DEFAULT 0.0"),
                ("mean_ic", "FLOAT DEFAULT 0.0"),
                ("median_ic", "FLOAT DEFAULT 0.0"),
                ("ic_std_dev", "FLOAT DEFAULT 0.0"),
                ("ic_ir", "FLOAT DEFAULT 0.0"),
                ("positive_ic_ratio", "FLOAT DEFAULT 0.0"),
                ("walk_forward_score", "FLOAT DEFAULT 0.0"),
                ("regime_score", "FLOAT DEFAULT 0.0"),
                ("correlation_score", "FLOAT DEFAULT 0.0"),
                ("composite_research_score", "FLOAT DEFAULT 0.0")
            ]
            
            for col_name, col_type in metric_additions:
                if col_name not in metrics_cols:
                    try:
                        cursor.execute(f"ALTER TABLE metrics ADD COLUMN {col_name} {col_type}")
                    except Exception:
                        pass
                        
        await conn.run_sync(migrate_sqlite)
    await engine.dispose()
