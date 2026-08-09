import pytest
import asyncio
from sqlalchemy import select, delete
from brain_farm.app.database.models import Expression, Metric, Simulation, Project
from brain_farm.app.database.session import make_session_factory, init_db
from brain_farm.app.services.composite_scorer import WeightedCompositeScorer
from brain_farm.app.services.worker import SimulationWorker

AsyncSessionLocal = make_session_factory()

def test_composite_scorer_components():
    # Test research score calculation
    r_score = WeightedCompositeScorer.calculate_research_score(1.5, 1.2)
    assert 0.0 <= r_score <= 1.0
    
    # Test robustness score
    rob_score = WeightedCompositeScorer.calculate_robustness_score(0.8, 0.7)
    assert 0.0 <= rob_score <= 1.0
    
    # Test simplicity score
    simp_1 = WeightedCompositeScorer.calculate_simplicity_score(1.0)
    simp_heavy = WeightedCompositeScorer.calculate_simplicity_score(25.0)
    assert simp_1 == 1.0
    assert simp_heavy == 0.05


def test_composite_scorer_full():
    async def _run_test():
        await init_db()
        
        async with AsyncSessionLocal() as db:
            # Clean up leftover test data if any
            await db.execute(delete(Simulation).where(Simulation.brain_simulation_id == "mock-sim-id-phase-4"))
            await db.commit()
            
        async with AsyncSessionLocal() as db:
            # Create a mock project
            proj = Project(
                name="Test Phase 4 Project",
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
            
            # Setup pre-existing passed alpha to verify diversity calculations
            passed_expr = Expression(
                project_id=proj.id,
                expression_text="rank(close)",
                generator_type="TEST",
                status="PASSED",
                complexity_score=1.0,
                lineage_id=1
            )
            db.add(passed_expr)
            await db.flush()
            
            # Create the candidate expression
            expr = Expression(
                project_id=proj.id,
                expression_text="rank(open)",
                generator_type="TEST",
                status="SIMULATING",
                complexity_score=2.0,
                lineage_id=2
            )
            db.add(expr)
            await db.flush()
            
            sim = Simulation(
                expression_id=expr.id,
                status="POLLING",
                brain_simulation_id="mock-sim-id-phase-4",
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
                "alpha": "alpha-654321",
                "is": {
                    "sharpe": 1.70,
                    "fitness": 1.40,
                    "turnover": 0.25,
                    "returns": 0.09,
                    "margin": 18.0,
                    "drawdown": 0.04
                },
                "subUniverseSharpe": {
                    "TOP2000": 1.40,
                    "TOP1000": 1.20
                }
            }, None)
            
            worker._active_clients[proj.user_id] = mock_client
            
            # Poll specific simulation
            await worker._poll_simulation_task(sim.id)
            
            # Check results
            async with AsyncSessionLocal() as db2:
                res_metric = await db2.execute(
                    select(Metric)
                    .where(Metric.simulation_id == sim.id)
                )
                m = res_metric.scalar_one_or_none()
                
                assert m is not None
                assert m.composite_research_score is not None
                assert m.composite_research_score != 0.0
                assert m.correlation_score is not None
                assert 0.0 <= m.correlation_score <= 1.0 # diversity score
                
                # Cleanup
                await db2.execute(delete(Metric).where(Metric.simulation_id == sim.id))
                await db2.execute(delete(Simulation).where(Simulation.id == sim.id))
                await db2.execute(delete(Expression).where(Expression.id.in_([expr.id, passed_expr.id])))
                await db2.execute(delete(Project).where(Project.id == proj.id))
                await db2.commit()
                
    asyncio.run(_run_test())
