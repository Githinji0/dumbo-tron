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
                ("regime_performance", "JSON"),
                ("expected_horizon", "VARCHAR(50)"),
                ("selected_fields", "TEXT"),
                ("selected_operators", "TEXT"),
                ("operator_parameters", "JSON"),
                ("expected_turnover_category", "VARCHAR(50)"),
                ("parent_alpha_id", "VARCHAR(100)"),
                ("generation_number", "INTEGER DEFAULT 1"),
                ("mutation_type", "VARCHAR(100)"),
                ("mutation_parameters", "JSON"),
                ("expression_depth", "INTEGER DEFAULT 1"),
                ("operator_count", "INTEGER DEFAULT 0"),
                ("field_count", "INTEGER DEFAULT 0"),
                ("transformation_parent", "INTEGER"),
                ("transformation_type", "VARCHAR(50)"),
                ("ai_generated", "BOOLEAN DEFAULT 0"),
                ("ai_analyzed", "BOOLEAN DEFAULT 0"),
                ("ai_analysis_type", "VARCHAR(50)"),
                ("ai_recommendation", "TEXT"),
                ("ai_confidence", "FLOAT"),
                ("ai_research_reason", "TEXT"),
                ("signal_type", "VARCHAR(50) DEFAULT 'RAW_SIGNAL'"),
                ("generation_reason", "TEXT"),
                ("diagnostic_category", "VARCHAR(50)"),
                ("research_quality_score", "FLOAT DEFAULT 0.0"),
                ("evaluation_status", "VARCHAR(50) DEFAULT 'PENDING'"),
                ("portfolio_status", "VARCHAR(50)"),
                ("metrics_status", "VARCHAR(50)"),
                ("raw_response_structure", "JSON"),
                ("parser_status", "VARCHAR(50)"),
                ("failure_reason", "TEXT")
            ]
            
            for col_name, col_type in expr_additions:
                if col_name not in expr_cols:
                    try:
                        cursor.execute(f"ALTER TABLE expressions ADD COLUMN {col_name} {col_type}")
                    except Exception:
                        pass

            # Simulations table cols
            cursor.execute("PRAGMA table_info(simulations)")
            sim_cols = {row[1] for row in cursor.fetchall()}
            
            sim_additions = [
                ("diagnostic_details", "JSON"),
                ("remote_status", "VARCHAR(50)"),
                ("raw_response_structure", "JSON")
            ]
            for col_name, col_type in sim_additions:
                if col_name not in sim_cols:
                    try:
                        cursor.execute(f"ALTER TABLE simulations ADD COLUMN {col_name} {col_type}")
                    except Exception:
                        pass
                        
            # Metrics table cols
            cursor.execute("PRAGMA table_info(metrics)")
            metrics_cols = {row[1] for row in cursor.fetchall()}
            
            metric_additions = [
                ("has_valid_metrics", "BOOLEAN DEFAULT 1"),
                ("rank_ic", "FLOAT DEFAULT 0.0"),
                ("mean_ic", "FLOAT DEFAULT 0.0"),
                ("median_ic", "FLOAT DEFAULT 0.0"),
                ("ic_std_dev", "FLOAT DEFAULT 0.0"),
                ("ic_ir", "FLOAT DEFAULT 0.0"),
                ("positive_ic_ratio", "FLOAT DEFAULT 0.0"),
                ("walk_forward_score", "FLOAT DEFAULT 0.0"),
                ("regime_score", "FLOAT DEFAULT 0.0"),
                ("correlation_score", "FLOAT DEFAULT 0.0"),
                ("composite_research_score", "FLOAT DEFAULT 0.0"),
                ("stability_score", "FLOAT DEFAULT 0.0"),
                ("robustness_score", "FLOAT DEFAULT 0.0"),
                ("diversity_score", "FLOAT DEFAULT 0.0"),
                ("simplicity_score", "FLOAT DEFAULT 0.0"),
                ("alpha_research_score", "FLOAT DEFAULT 0.0"),
                ("walk_forward_mean_sharpe", "FLOAT DEFAULT 0.0"),
                ("walk_forward_median_sharpe", "FLOAT DEFAULT 0.0"),
                ("walk_forward_min_sharpe", "FLOAT DEFAULT 0.0"),
                ("walk_forward_variance", "FLOAT DEFAULT 0.0"),
                ("parameter_stability_score", "FLOAT DEFAULT 0.0"),
                ("experiment_count", "INTEGER DEFAULT 1"),
                ("family_experiment_count", "INTEGER DEFAULT 1"),
                ("lineage_experiment_count", "INTEGER DEFAULT 1"),
                ("pareto_optimal", "BOOLEAN DEFAULT 0"),
                ("candidate_tier", "INTEGER DEFAULT 0"),
                ("multiple_testing_adjusted_score", "FLOAT DEFAULT 0.0"),
                ("ai_critic_risk_level", "VARCHAR(50)"),
                ("ai_critic_review", "JSON")
            ]
            
            for col_name, col_type in metric_additions:
                if col_name not in metrics_cols:
                    try:
                        cursor.execute(f"ALTER TABLE metrics ADD COLUMN {col_name} {col_type}")
                    except Exception:
                        pass
                        
        await conn.run_sync(migrate_sqlite)
    await engine.dispose()
