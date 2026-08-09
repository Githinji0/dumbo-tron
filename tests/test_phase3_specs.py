import pytest
import asyncio
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from brain_farm.app.database.models import Expression, Metric, Simulation, Project
from brain_farm.app.database.session import make_session_factory, init_db
from brain_farm.app.services.ic_calculator import ICCalculator
from brain_farm.app.services.walk_forward import WalkForwardTester
from brain_farm.app.services.regime_analyzer import RegimeAnalyzer
from brain_farm.app.services.worker import SimulationWorker

# Use the test sqlite DB
AsyncSessionLocal = make_session_factory()

def test_ic_calculator():
    expr = "ts_zscore(close, 20)"
    sharpe = 1.6
    res = ICCalculator.calculate_ic_metrics(expr, sharpe)
    
    assert "rank_ic" in res
    assert "mean_ic" in res
    assert "median_ic" in res
    assert "ic_std_dev" in res
    assert "ic_ir" in res
    assert "positive_ic_ratio" in res
    
    assert res["ic_std_dev"] > 0
    assert 0.0 <= res["positive_ic_ratio"] <= 1.0


def test_walk_forward_evaluator():
    expr = "ts_zscore(close, 20)"
    sharpe = 1.6
    res = WalkForwardTester.evaluate_walk_forward(expr, sharpe)
    
    assert "walk_forward_score" in res
    assert 0.0 <= res["walk_forward_score"] <= 1.0


def test_regime_analyzer():
    expr = "ts_zscore(close, 20)"
    sharpe = 1.6
    res = RegimeAnalyzer.evaluate_regimes(expr, sharpe)
    
    assert "regime_score" in res
    assert "sharpe_run_low" in res
    assert "sharpe_run_high" in res
    assert 0.0 <= res["regime_score"] <= 1.0


def test_worker_advanced_metrics():
    async def _run_test():
        await init_db()
        
        async with AsyncSessionLocal() as db:
            # Clean up any leftover metrics/sims for this mock sim ID or orphans
            stmt = select(Simulation.id).where(Simulation.brain_simulation_id == "mock-sim-id-phase-3")
            sim_ids = (await db.execute(stmt)).scalars().all()
            if sim_ids:
                await db.execute(delete(Metric).where(Metric.simulation_id.in_(sim_ids)))
                await db.execute(delete(Simulation).where(Simulation.id.in_(sim_ids)))
            # Also clean up any orphaned metrics in general to prevent uniqueness conflicts
            await db.execute(delete(Metric).where(~Metric.simulation_id.in_(select(Simulation.id))))
            await db.commit()
            
        async with AsyncSessionLocal() as db:
            # Create a mock project
            proj = Project(
                name="Test Phase 3 Project",
                region="USA",
                universe="TOP3000",
                neutralization="SUBINDUSTRY",
                user_id=1,
                min_sharpe=1.0,
                min_fitness=0.0,
                max_turnover=1.0,
                min_margin=-10.0,
                min_sub_universe_sharpe=-10.0
            )
            db.add(proj)
            await db.flush()
            
            # Create an expression
            expr = Expression(
                project_id=proj.id,
                expression_text="rank(close)",
                generator_type="TEST",
                status="SIMULATING",
                complexity_score=1.0,
                lineage_id=1
            )
            db.add(expr)
            await db.flush()
            
            # Create simulation record in POLLING status
            sim = Simulation(
                expression_id=expr.id,
                status="POLLING",
                brain_simulation_id="mock-sim-id-phase-3",
                retry_count=0
            )
            db.add(sim)
            await db.commit()
            
            # Use worker client in mock mode
            worker = SimulationWorker()
            
            # Mock the BrainClient simulation status payload
            from unittest.mock import AsyncMock
            mock_client = AsyncMock()
            mock_client.is_authenticated = True
            mock_client.get_simulation_status.return_value = ({
                "status": "COMPLETE",
                "alpha": "alpha-123456",
                "is": {
                    "sharpe": 1.45,
                    "fitness": 1.20,
                    "turnover": 0.35,
                    "returns": 0.08,
                    "margin": 15.0,
                    "drawdown": 0.05
                },
                "subUniverseSharpe": {
                    "TOP2000": 1.22,
                    "TOP1000": 1.10
                }
            }, None)
            
            worker._active_clients[proj.user_id] = mock_client
            
            # Poll specific simulation
            await worker._poll_simulation_task(sim.id)
            
            # Check results
            async with AsyncSessionLocal() as db2:
                res_expr = await db2.execute(select(Expression).where(Expression.id == expr.id))
                e = res_expr.scalar_one()
                
                res_metric = await db2.execute(
                    select(Metric)
                    .where(Metric.simulation_id == sim.id)
                )
                m = res_metric.scalar_one_or_none()
                
                assert e.status == "PASSED"
                assert m is not None
                assert m.sharpe == 1.45
                assert m.rank_ic is not None
                assert m.rank_ic != 0.0
                assert m.walk_forward_score is not None
                assert m.regime_score is not None
                
                # Safe cleanup using bulk delete
                await db2.execute(delete(Metric).where(Metric.simulation_id == sim.id))
                await db2.execute(delete(Simulation).where(Simulation.id == sim.id))
                await db2.execute(delete(Expression).where(Expression.id == expr.id))
                await db2.execute(delete(Project).where(Project.id == proj.id))
                await db2.commit()
                
    asyncio.run(_run_test())
