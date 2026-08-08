import asyncio
from sqlalchemy import select
from brain_farm.app.database.session import make_session_factory
from brain_farm.app.database.models import Simulation, Expression, Project, User

async def main():
    db_factory = make_session_factory()
    async with db_factory() as db:
        res = await db.execute(
            select(Simulation.id, Project.id, Project.name, User.id, User.email, Simulation.status)
            .join(Expression, Simulation.expression_id == Expression.id)
            .join(Project, Expression.project_id == Project.id)
            .join(User, Project.user_id == User.id)
            .where(Simulation.status == "NEEDS_AUTH")
        )
        rows = res.all()
        print(f"Found {len(rows)} simulations in NEEDS_AUTH state.")
        for row in rows[:10]:
            print(f"Sim ID: {row[0]} | Project ID: {row[1]} ({row[2]}) | User ID: {row[3]} ({row[4]})")

asyncio.run(main())
