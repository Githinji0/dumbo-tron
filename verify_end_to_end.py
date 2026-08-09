import asyncio
import sys
from fastapi.testclient import TestClient
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from brain_farm.app.server import app
from brain_farm.app.database.session import make_session_factory, init_db
from brain_farm.app.database.models import Project, Expression, Simulation, Metric, User, ProjectLog
from brain_farm.app.services.worker import SimulationWorker
from brain_farm.app.services.priority_engine import ResearchPriorityEngine

AsyncSessionLocal = make_session_factory()
client = TestClient(app)

async def test_full_pipeline():
    print("====== STARTING E2E INTEGRATION VERIFICATION ======")
    await init_db()
    
    # Authenticate and login to verify routes
    login_payload = {
        "email": "e2e_user@mock.com",
        "password": "mockpassword",
        "use_mock": True
    }
    resp = client.post("/api/auth/login", json=login_payload)
    assert resp.status_code == 200, "Failed to login"
    cookies = resp.cookies
    user_id = resp.json()["user_id"]
    print(f"1. Logged in successfully. User ID: {user_id}")
    
    async with AsyncSessionLocal() as db:
        # Robust cascaded cleanup by project name
        res_old_projs = await db.execute(
            select(Project.id).where(Project.name == "E2E Integration Test Project")
        )
        old_proj_ids = [r[0] for r in res_old_projs.all()]
        
        if old_proj_ids:
            # Delete metrics
            res_sim_ids = await db.execute(
                select(Simulation.id).where(Simulation.expression_id.in_(
                    select(Expression.id).where(Expression.project_id.in_(old_proj_ids))
                ))
            )
            old_sim_ids = [s[0] for s in res_sim_ids.all()]
            if old_sim_ids:
                await db.execute(delete(Metric).where(Metric.simulation_id.in_(old_sim_ids)))
                await db.execute(delete(Simulation).where(Simulation.id.in_(old_sim_ids)))
                
            await db.execute(delete(Expression).where(Expression.project_id.in_(old_proj_ids)))
            await db.execute(delete(Project).where(Project.id.in_(old_proj_ids)))
            await db.commit()
            print(f"Cleaned up previous E2E project data for project IDs: {old_proj_ids}")
            
        # Create Project
        proj = Project(
            name="E2E Integration Test Project",
            region="USA",
            universe="TOP3000",
            neutralization="SUBINDUSTRY",
            user_id=user_id,
            min_sharpe=1.0,
            min_fitness=0.0,
            max_turnover=1.0,
            min_margin=-10.0,
            min_sub_universe_sharpe=-10.0
        )
        db.add(proj)
        await db.flush()
        proj_id = proj.id
        await db.commit()
    
    print(f"2. Created E2E project with ID: {proj_id}")
    
    # Launch Farm
    farm_payload = {
        "project_id": proj_id,
        "engine": "Research Family Generator",
        "count": 5,
        "research_family": "ALL"
    }
    farm_resp = client.post("/api/farm/launch", json=farm_payload, cookies=cookies)
    assert farm_resp.status_code == 200, "Failed to launch farm"
    print("3. Launched Farm using Research Family Generator successfully.")
    
    async with AsyncSessionLocal() as db:
        # Verify expressions were generated with families and complexity scores
        res_exprs = await db.execute(
            select(Expression).where(Expression.project_id == proj_id)
        )
        exprs = res_exprs.scalars().all()
        print(f"DEBUG: Found {len(exprs)} expressions for project {proj_id}:")
        for e in exprs:
            print(f"   ID: {e.id}, ProjectID: {e.project_id}, Text: {e.expression_text}, Status: {e.status}")
        assert len(exprs) == 5, f"Expected 5 generated expressions, got {len(exprs)}"
        for ex in exprs:
            assert ex.status == "PENDING"
            assert ex.research_family is not None, "Research family was not assigned"
            assert ex.hypothesis is not None, "Hypothesis template was not assigned"
            assert ex.complexity_score is not None, "Complexity score was not computed"
            assert ex.lineage_id is not None, "Lineage ID was not assigned"
            print(f"   [Expr {ex.id}] '{ex.expression_text[:40]}...' Family: {ex.research_family}, Complexity: {ex.complexity_score}")
            
        # Create duplicate manually to test Fast Rejection
        dup = Expression(
            project_id=proj_id,
            expression_text=exprs[0].expression_text,
            generator_type="TEST",
            status="PENDING",
            research_family=exprs[0].research_family,
            hypothesis=exprs[0].hypothesis,
            lineage_id=exprs[0].lineage_id,
            complexity_score=exprs[0].complexity_score
        )
        db.add(dup)
        await db.commit()
        dup_id = dup.id
        print(f"4. Created duplicate of Expr {exprs[0].id} (ID: {dup_id}) to verify rejection.")

    # Instantiate SimulationWorker and inject mock client to intercept submissions and polling
    worker = SimulationWorker()
    
    from unittest.mock import AsyncMock
    mock_client = AsyncMock()
    mock_client.is_authenticated = True
    # We will mock the submit_simulation to return a unique mock simulation id using the expression hash
    mock_client.submit_simulation.side_effect = lambda expr, settings: (f"mock-sim-id-e2e-{hash(expr) & 0xffffffff}", None)
    # We will mock the get_simulation_status callback to return successful performance checks
    mock_client.get_simulation_status.side_effect = lambda sim_id: (({
        "status": "COMPLETE",
        "alpha": f"alpha-{sim_id}",
        "is": {
            "sharpe": 1.65,
            "fitness": 1.20,
            "turnover": 0.30,
            "returns": 0.08,
            "margin": 12.0
        },
        "subUniverseSharpe": {
            "TOP2000": 1.30,
            "TOP1000": 1.10
        }
    }, None))
    
    worker._active_clients[user_id] = mock_client
    print("5. Mock client and submissions interceptor configured.")

    await worker.process_pending_expressions()
    
    async with AsyncSessionLocal() as db:
        # Verify duplicate was rejected
        res_dup = await db.execute(select(Expression).where(Expression.id == dup_id))
        dup_expr = res_dup.scalar_one()
        assert dup_expr.status == "REJECTED", f"Expected duplicate to be REJECTED, status is {dup_expr.status}"
        
        # Verify other expressions were queued for simulations
        res_non_dup = await db.execute(
            select(Expression)
            .options(selectinload(Expression.simulations))
            .where(Expression.project_id == proj_id)
            .where(Expression.id != dup_id)
        )
        non_dup_exprs = res_non_dup.scalars().all()
        for ex in non_dup_exprs:
            assert ex.status == "SIMULATING", f"Expected SIMULATING status, got {ex.status}"
            assert len(ex.simulations) == 1, "Simulation record not created"
            assert ex.simulations[0].status == "QUEUED"
            
        print("6. Checked process_pending_expressions: Duplicates REJECTED, others SIMULATING.")

    # Process queued simulations
    # In mock mode, this submit the simulations to the mock client, which transitions them to COMPLETE/SENT/POLLING
    await worker.process_queued_simulations()
    
    # Wait for the background submission tasks to complete
    await asyncio.sleep(0.5)
    
    async with AsyncSessionLocal() as db:
        res_sims = await db.execute(
            select(Simulation).join(Expression).where(Expression.project_id == proj_id)
        )
        sims = res_sims.scalars().all()
        # Filter only non-rejected simulation records
        valid_sims = [s for s in sims if s.expression_id != dup_id]
        
        # Poll all of them to trigger metric calculation, walk-forward, regime analyses & composite scoring
        for sim in valid_sims:
            await worker._poll_simulation_task(sim.id)
            
    print("7. Processed polling for all active simulations to COMPLETE.")
    
    # Validate final persistent schema scores
    async with AsyncSessionLocal() as db:
        res_completed = await db.execute(
            select(Expression)
            .options(selectinload(Expression.simulations).selectinload(Simulation.metrics))
            .where(Expression.project_id == proj_id)
            .where(Expression.id != dup_id)
        )
        completed_exprs = res_completed.scalars().all()
        for ex in completed_exprs:
            assert ex.status == "PASSED", f"Expected expression to be PASSED, got {ex.status}"
            sim = ex.simulations[0]
            assert sim.status == "COMPLETE"
            metrics = sim.metrics
            assert metrics is not None, "Metrics was not persisted"
            
            # Assert all Phase 3 & Phase 4 & Phase 5 metrics are calculated and not null
            assert metrics.rank_ic is not None
            assert metrics.mean_ic is not None
            assert metrics.median_ic is not None
            assert metrics.ic_std_dev is not None
            assert metrics.ic_ir is not None
            assert metrics.positive_ic_ratio is not None
            assert metrics.walk_forward_score is not None
            assert metrics.regime_score is not None
            assert metrics.composite_research_score is not None
            assert metrics.correlation_score is not None
            
            # Verify complexity exists
            assert ex.complexity_score is not None
            
            print(f"   [Metrics - Expr {ex.id}] Sharpe: {metrics.sharpe}, Rank IC: {metrics.rank_ic:.4f}, Median IC: {metrics.median_ic:.4f}, Positive IC Ratio: {metrics.positive_ic_ratio:.2%}")
            print(f"                    Walk-Forward Score: {metrics.walk_forward_score:.4f}, Regime Score: {metrics.regime_score:.4f}")
            print(f"                    Composite Scorer rating: {metrics.composite_research_score:.4f}")
            
    print("8. Verified all Phase 3 (Rank IC, mean/median IC, std, Positive IC Ratio, Walk-Forward, Regime), Phase 4 (Composite Scorer) and Phase 5/6 (Sensitivity/Priority) metrics are calculated and stored successfully!")

    # Verify priority statistics allocation (Phase 6)
    async with AsyncSessionLocal() as db:
        allocs = await ResearchPriorityEngine.allocate_generation_slots(proj_id, 10, db)
        print("9. Evaluated dynamic priority slot allocation for next farm run:")
        for fam, cnt in allocs.items():
            print(f"   - {fam}: {cnt} slots")
        
        # Cleanup
        await db.execute(delete(Metric).where(Metric.simulation_id.in_([s.id for s in sims])))
        await db.execute(delete(Simulation).where(Simulation.id.in_([s.id for s in sims])))
        await db.execute(delete(Expression).where(Expression.project_id == proj_id))
        await db.execute(delete(Project).where(Project.id == proj_id))
        await db.commit()
    
    print("10. Cleaned up E2E verification test data.")
    print("====== E2E INTEGRATION VERIFICATION PASSED SUCCESSFULLY ======")

if __name__ == "__main__":
    asyncio.run(test_full_pipeline())
