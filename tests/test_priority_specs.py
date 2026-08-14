import pytest
import asyncio
from sqlalchemy import delete, select
from brain_farm.app.database.models import Expression, Metric, Simulation, Project
from brain_farm.app.database.session import make_session_factory, init_db
from brain_farm.app.services.priority_engine import ResearchPriorityEngine

AsyncSessionLocal = make_session_factory()

def test_priority_allocation():
    async def _run_test():
        await init_db()
        
        async with AsyncSessionLocal() as db:
            # Clean up leftover test data if any
            await db.execute(delete(Project).where(Project.name == "Test Phase 6 Project"))
            await db.commit()
            
        async with AsyncSessionLocal() as db:
            # Create a mock project
            proj = Project(
                name="Test Phase 6 Project",
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
            
            # Setup pre-existing passed and failed expressions for various families
            # Family MOMENTUM: 2 PASSED (exploitation candidate)
            # Family VALUE: 1 REJECTED (count = 1)
            # All other families: 0 experiments (neglected candidates)
            
            e1 = Expression(project_id=proj.id, expression_text="close / delay(close, 2)", generator_type="TEST", status="PASSED", research_family="MOMENTUM")
            e2 = Expression(project_id=proj.id, expression_text="close / delay(close, 5)", generator_type="TEST", status="PASSED", research_family="MOMENTUM")
            e3 = Expression(project_id=proj.id, expression_text="book_value / market_cap", generator_type="TEST", status="REJECTED", research_family="VALUE")
            db.add_all([e1, e2, e3])
            await db.flush()
            
            # Add simulations and metrics for MOMENTUM
            sim1 = Simulation(expression_id=e1.id, status="COMPLETE", brain_simulation_id="mock-sim-p6-1")
            sim2 = Simulation(expression_id=e2.id, status="COMPLETE", brain_simulation_id="mock-sim-p6-2")
            db.add_all([sim1, sim2])
            await db.flush()
            
            m1 = Metric(simulation_id=sim1.id, sharpe=2.5, fitness=2.0, turnover=0.25, returns=0.15, margin=5.0)
            m2 = Metric(simulation_id=sim2.id, sharpe=3.1, fitness=2.4, turnover=0.20, returns=0.18, margin=6.0)
            db.add_all([m1, m2])
            await db.commit()
            
        async with AsyncSessionLocal() as db:
            # Test group stats fetching
            stats = await ResearchPriorityEngine.get_family_performance_stats(proj.id, db)
            
            assert stats["MOMENTUM"]["count"] == 2
            assert stats["MOMENTUM"]["success_rate"] == 1.0
            assert stats["MOMENTUM"]["mean_sharpe"] == 2.8
            assert stats["VALUE"]["count"] == 1
            assert stats["VALUE"]["success_rate"] == 0.0
            assert stats["VALUE"]["mean_sharpe"] == 0.0
            assert stats["QUALITY"]["count"] == 0
            
            # Test allocations distribution
            allocs = await ResearchPriorityEngine.allocate_generation_slots(proj.id, 100, db)
            
            # Since MOMENTUM has a 2.8 mean Sharpe and is the only successful family,
            # it should be picked heavily via the 70% exploitation mechanism
            assert "MOMENTUM" in allocs
            assert allocs["MOMENTUM"] > 30 # Exploitation target should allocate a significant portion to MOMENTUM
            
            # Verify clean final dataset deletion
            await db.execute(delete(Metric).where(Metric.simulation_id.in_([sim1.id, sim2.id])))
            await db.execute(delete(Simulation).where(Simulation.id.in_([sim1.id, sim2.id])))
            await db.execute(delete(Expression).where(Expression.project_id == proj.id))
            await db.execute(delete(Project).where(Project.id == proj.id))
            await db.commit()
            
    asyncio.run(_run_test())
