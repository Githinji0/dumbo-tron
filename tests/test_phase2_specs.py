import pytest
import asyncio
from sqlalchemy import select
from brain_farm.app.database.models import Expression, Metric, Simulation, ProjectLog
from brain_farm.app.database.session import make_session_factory, init_db
from brain_farm.app.server import calculate_complexity_score
from brain_farm.app.services.worker import SimulationWorker

# Use the test sqlite DB
AsyncSessionLocal = make_session_factory()

def test_complexity_scoring():
    # Test typical operations
    expr1 = "ts_zscore(close, 20)"
    score1 = calculate_complexity_score(expr1)
    
    expr2 = "group_neutralize(ts_decay_linear(rank(close), 10), subindustry) - rank(volume)"
    score2 = calculate_complexity_score(expr2)
    
    assert score2 > score1
    assert score1 >= 1.0
    assert score2 >= 1.0


def test_duplicate_rejection_worker():
    async def _run_test():
        # Auto-migrate database structure for the test context
        await init_db()
        
        async with AsyncSessionLocal() as db:
            # Create a mock project id
            project_id = 9999
            
            # Insert first expression as PENDING
            expr1 = Expression(
                project_id=project_id,
                expression_text="rank(close)",
                generator_type="TEST",
                status="PENDING",
                complexity_score=1.0,
                lineage_id=1
            )
            db.add(expr1)
            
            # Insert exact duplicate expression as PENDING
            expr2 = Expression(
                project_id=project_id,
                expression_text="rank(close)",
                generator_type="TEST",
                status="PENDING",
                complexity_score=1.0,
                lineage_id=2
            )
            db.add(expr2)
            
            await db.commit()
            
            # Fire worker to process pending expressions
            worker = SimulationWorker()
            await worker.process_pending_expressions()
            
            # Query statuses
            async with AsyncSessionLocal() as db2:
                res1 = await db2.execute(select(Expression).where(Expression.id == expr1.id))
                e1 = res1.scalar_one()
                res2 = await db2.execute(select(Expression).where(Expression.id == expr2.id))
                e2 = res2.scalar_one()
                
                # The first one should be SIMULATING (as it has no prior duplicate), the second one should be REJECTED
                assert e1.status == "SIMULATING"
                assert e2.status == "REJECTED"
                
                # Check ProjectLog warnings are recorded
                logs_res = await db2.execute(
                    select(ProjectLog)
                    .where(ProjectLog.project_id == project_id)
                    .where(ProjectLog.level == "WARNING")
                )
                logs = logs_res.scalars().all()
                assert len(logs) >= 1
                assert "Duplicate Checker: Rejected" in logs[0].message
                
                # Cleanup
                await db2.delete(e1)
                await db2.delete(e2)
                for l in logs:
                    await db2.delete(l)
                # Find and delete queued simulation for e1
                sim_res = await db2.execute(select(Simulation).where(Simulation.expression_id == e1.id))
                sims = sim_res.scalars().all()
                for s in sims:
                    await db2.delete(s)
                    
                await db2.commit()

    asyncio.run(_run_test())
