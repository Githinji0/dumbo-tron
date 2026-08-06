import asyncio
from brain_farm.app.database.session import AsyncSessionLocal
from brain_farm.app.database.models import Project, Expression, Simulation, Metric
from sqlalchemy import select

async def run():
    async with AsyncSessionLocal() as db:
        # Fetch all passed expressions and trace their simulations/metrics
        result = await db.execute(
            select(Expression.id, Expression.expression_text, Expression.status, Simulation.id, Metric.id, Metric.sharpe, Metric.fitness, Metric.turnover, Metric.margin)
            .select_from(Expression)
            .outerjoin(Simulation, Expression.id == Simulation.expression_id)
            .outerjoin(Metric, Simulation.id == Metric.simulation_id)
            .where(Expression.project_id == 1)
        )
        rows = result.all()
        print("Total expressions checked:", len(rows))
        for r in rows:
            print(f"Expr ID: {r[0]}, Status: {r[2]}, Sim ID: {r[3]}, Met ID: {r[4]}, Sharpe: {r[5]}, Fitness: {r[6]}, Turn: {r[7]}, Margin: {r[8]}")

asyncio.run(run())
