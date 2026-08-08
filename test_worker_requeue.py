import asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from brain_farm.app.database.session import make_session_factory
from brain_farm.app.database.models import Simulation, Expression, Project
from brain_farm.app.services.worker import SimulationWorker
from brain_farm.app.services.brain_client import BrainClient

async def main():
    worker = SimulationWorker()
    db_factory = make_session_factory()
    async with db_factory() as db:
        res = await db.execute(select(Simulation).where(Simulation.status == "NEEDS_AUTH").limit(1))
        sim = res.scalar_one_or_none()
        if not sim:
            print("No NEEDS_AUTH simulations found in the DB to test with.")
            # Let's create one just to test
            return
        
        expr_res = await db.execute(select(Expression).where(Expression.id == sim.expression_id))
        expr = expr_res.scalar_one()
        proj_res = await db.execute(select(Project).where(Project.id == expr.project_id))
        proj = proj_res.scalar_one()
        user_id = proj.user_id
        print(f"Testing Simulation {sim.id}: status={sim.status}, belongs to Project {proj.id}, User {user_id}")
        
        # Test 1: Run poll_active_simulations WITHOUT injected client
        print("\n--- Test 1: Polling WITHOUT injected client ---")
        await worker.poll_active_simulations()
        await db.refresh(sim)
        print(f"Simulation status in DB: {sim.status} (expected: NEEDS_AUTH)")
        
        # Test 2: Run poll_active_simulations WITH injected client but is_authenticated=False
        print("\n--- Test 2: Polling WITH unauthenticated client ---")
        client = BrainClient("casperliam67@gmail.com", "dummy_pass", use_mock=True)
        client.is_authenticated = False
        worker.inject_client(user_id, client)
        await worker.poll_active_simulations()
        await db.refresh(sim)
        print(f"Simulation status in DB: {sim.status} (expected: NEEDS_AUTH)")
        
        # Test 3: Run poll_active_simulations WITH authenticated client
        print("\n--- Test 3: Polling WITH authenticated client ---")
        client.is_authenticated = True
        await worker.poll_active_simulations()
        
        # Query again to see if status updated in DB
        async with db_factory() as db2:
            res2 = await db2.execute(select(Simulation).where(Simulation.id == sim.id))
            sim2 = res2.scalar_one()
            print(f"Simulation status in DB: {sim2.status} (expected: QUEUED)")
            
            if sim2.status == "QUEUED":
                print("SUCCESS! Worker successfully re-queued NEEDS_AUTH simulation.")
                # Restore
                sim2.status = "NEEDS_AUTH"
                sim2.error_message = "Session expired during submission. Please re-authenticate."
                await db2.commit()
                print("Restored original NEEDS_AUTH status.")
            else:
                print("FAILED! Worker did not update simulation status.")

asyncio.run(main())
