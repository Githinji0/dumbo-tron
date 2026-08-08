import asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from brain_farm.app.database.session import make_session_factory
from brain_farm.app.database.models import Simulation, Expression, Project

async def main():
    db_factory = make_session_factory()
    async with db_factory() as db:
        try:
            result = await db.execute(
                select(Simulation)
                .join(Expression)
                .join(Project)
                .options(selectinload(Simulation.expression).selectinload(Expression.project))
                .where(Simulation.status.in_(["POLLING", "NEEDS_AUTH"]))
                .limit(20)
            )
            sims = result.scalars().all()
            print(f"Successfully loaded {len(sims)} simulations.")
            for sim in sims:
                print(f"Sim ID: {sim.id}")
                print(f"  Expression text: {sim.expression.expression_text}")
                print(f"  Project ID: {sim.expression.project_id}")
                # Accessing project
                proj = sim.expression.project
                print(f"  Project User ID: {proj.user_id}")
        except Exception as e:
            print(f"Query failed with exception: {e}")
            import traceback
            traceback.print_exc()

asyncio.run(main())
