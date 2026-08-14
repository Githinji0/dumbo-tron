import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select

from brain_farm.app.database.models import Base, Project, Expression, Simulation, Metric, User
from brain_farm.app.server import app, active_sessions
from brain_farm.app.services.worker import SimulationWorker

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture
async def test_env():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # Seed user & project
    async with async_session() as session:
        user = User(
            id=999,
            email="test_user_masking@example.com",
            encrypted_password="enc"
        )
        session.add(user)
        await session.flush()
        
        project = Project(
            id=101,
            user_id=999,
            name="Diagnostic Farm",
            min_sharpe=1.25,
            min_fitness=1.00,
            max_turnover=0.70,
            min_margin=4.0
        )
        session.add(project)
        
        # Valid alpha
        expr1 = Expression(
            id=1,
            project_id=101,
            expression_text="ts_decay_linear(rank(ts_delta(close, 5)), 10)",
            generator_type="TEMPLATE",
            status="PASSED",
            signal_type="PREDICTIVE_SIGNAL",
            diagnostic_category="HIGH_QUALITY"
        )
        session.add(expr1)
        await session.flush()

        sim1 = Simulation(
            id=1,
            expression_id=1,
            status="COMPLETE",
            brain_simulation_id="sim-valid-01",
            brain_alpha_id="alpha-valid-01"
        )
        session.add(sim1)
        await session.flush()

        m1 = Metric(
            simulation_id=1,
            has_valid_metrics=True,
            sharpe=1.65,
            fitness=1.20,
            turnover=0.35,
            returns=0.22,
            margin=5.5
        )
        session.add(m1)

        # Simulation with empty IS block (NO_VALID_METRICS)
        expr2 = Expression(
            id=2,
            project_id=101,
            expression_text="group_neutralize(vwap, subindustry)",
            generator_type="AST",
            status="NO_VALID_METRICS",
            signal_type="RAW_SIGNAL",
            diagnostic_category="NO_VALID_METRICS"
        )
        session.add(expr2)
        await session.flush()

        sim2 = Simulation(
            id=2,
            expression_id=2,
            status="NO_VALID_METRICS",
            brain_simulation_id="sim-empty-02",
            diagnostic_details={
                "simulation_status": "COMPLETED",
                "brain_response_status": "COMPLETE",
                "parser_status": "FAILED_TO_EXTRACT_METRICS",
                "result_availability": True,
                "portfolio_availability": False,
                "metric_availability": False,
                "message": "Empty IS block returned from BRAIN"
            }
        )
        session.add(sim2)

        await session.commit()

    import brain_farm.app.server as srv
    srv.AsyncSessionLocal = async_session
    active_sessions[999] = {"token": "dummy_tok", "device_id": "dummy_dev"}

    yield {"session": async_session, "user_id": 999}
    await engine.dispose()


@pytest.mark.asyncio
async def test_analytics_excludes_uncalculated_zero_metrics(test_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/analytics?project_id=101")
        assert res.status_code == 200
        data = res.json()
        
        # Only sim1 with valid metrics should be returned in analytics calculation
        assert len(data) == 1
        assert data[0]["sharpe"] == 1.65
        assert data[0]["fitness"] == 1.20


@pytest.mark.asyncio
async def test_passed_alphas_flags_no_valid_metrics(test_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/passed?project_id=101")
        assert res.status_code == 200
        data = res.json()
        
        assert len(data) == 2
        valid_item = next(x for x in data if x["expression"] == "ts_decay_linear(rank(ts_delta(close, 5)), 10)")
        assert valid_item["sharpe"] == 1.65
        assert valid_item["has_valid_metrics"] is True

        empty_item = next(x for x in data if x["expression"] == "group_neutralize(vwap, subindustry)")
        assert empty_item["sharpe"] is None
        assert empty_item["has_valid_metrics"] is False
        assert empty_item["diagnostic_category"] == "NO_VALID_METRICS"


@pytest.mark.asyncio
async def test_simulation_diagnostics_endpoint(test_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/simulations/2/diagnostics")
        assert res.status_code == 200
        diag = res.json()
        
        assert diag["simulation_id"] == 2
        assert diag["simulation_status"] == "NO_VALID_METRICS"
        assert diag["has_valid_metrics"] is False
        assert diag["diagnostics"]["parser_status"] == "FAILED_TO_EXTRACT_METRICS"
        assert diag["diagnostics"]["metric_availability"] is False
