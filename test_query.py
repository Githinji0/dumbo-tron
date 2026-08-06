import asyncio
from brain_farm.app.database.session import AsyncSessionLocal
from brain_farm.app.database.models import Project, Expression, Simulation, Metric
from sqlalchemy import select

async def run():
    async with AsyncSessionLocal() as db:
        # Get active project
        proj = (await db.execute(select(Project))).scalar_one_or_none()
        if not proj:
            print("No project found!")
            return
            
        print("Project ID:", proj.id)
        
        # Test Query 1 (get_all_metrics)
        q1 = (
            select(Metric.sharpe, Metric.fitness, Metric.turnover, Metric.returns, Metric.margin, Expression.generator_type)
            .select_from(Metric)
            .join(Simulation, Metric.simulation_id == Simulation.id)
            .join(Expression, Simulation.expression_id == Expression.id)
            .where(Expression.project_id == proj.id)
        )
        r1 = (await db.execute(q1)).all()
        print("get_all_metrics result count:", len(r1))
        
        # Test Query 2 (fetch_passed_alphas)
        q2 = (
            select(Expression.expression_text, Simulation.brain_alpha_id, Metric.sharpe, Metric.fitness, Metric.turnover, Metric.margin, Expression.generator_type, Expression.id)
            .select_from(Expression)
            .join(Simulation, Expression.id == Simulation.expression_id)
            .join(Metric, Simulation.id == Metric.simulation_id)
            .where(Expression.project_id == proj.id, Expression.status == "PASSED")
        )
        r2 = (await db.execute(q2)).all()
        print("fetch_passed_alphas result count:", len(r2))

asyncio.run(run())
