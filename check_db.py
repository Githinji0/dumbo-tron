import asyncio
from brain_farm.app.database.session import AsyncSessionLocal
from brain_farm.app.database.models import Project, Expression, Simulation, Metric
from sqlalchemy import select

async def run():
    async with AsyncSessionLocal() as db:
        projects = (await db.execute(select(Project))).all()
        expressions = (await db.execute(select(Expression))).all()
        simulations = (await db.execute(select(Simulation))).all()
        metrics = (await db.execute(select(Metric))).all()
        print(f"Projects count: {len(projects)}")
        print(f"Expressions count: {len(expressions)}")
        if expressions:
            print("Expression statuses:", [e[0].status for e in expressions])
        print(f"Simulations count: {len(simulations)}")
        if simulations:
            print("Simulation statuses:", [s[0].status for s in simulations])
        print(f"Metrics count: {len(metrics)}")

asyncio.run(run())
