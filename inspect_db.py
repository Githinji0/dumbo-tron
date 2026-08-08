import asyncio
from sqlalchemy import select
from brain_farm.app.database.session import make_session_factory
from brain_farm.app.database.models import User, Project, Expression, Simulation, ProjectLog

AsyncSessionLocal = make_session_factory()

async def inspect():
    async with AsyncSessionLocal() as db:
        # Users
        u_res = await db.execute(select(User))
        users = u_res.scalars().all()
        print(f"=== USERS: {len(users)} ===")
        for u in users:
            print(f"User ID: {u.id}, Email: {u.email}")

        # Projects
        p_res = await db.execute(select(Project))
        projects = p_res.scalars().all()
        print(f"\n=== PROJECTS: {len(projects)} ===")
        for p in projects:
            print(f"Proj ID: {p.id}, User ID: {p.user_id}, Name: {p.name}, Region: {p.region}, Universe: {p.universe}")

        # Simulation statuses
        s_res = await db.execute(select(Simulation.status, Simulation.error_message))
        sims = s_res.all()
        print(f"\n=== SIMULATIONS: {len(sims)} ===")
        statuses = {}
        for s in sims:
            statuses[s[0]] = statuses.get(s[0], 0) + 1
        print(f"Sim statuses breakdown: {statuses}")
        
        # Details of NEEDS_AUTH
        if "NEEDS_AUTH" in statuses:
            print("\n=== NEEDS_AUTH Details ===")
            na_res = await db.execute(
                select(Simulation.id, Expression.expression_text, Simulation.error_message)
                .join(Expression, Simulation.expression_id == Expression.id)
                .where(Simulation.status == "NEEDS_AUTH")
                .limit(5)
            )
            for raw in na_res.all():
                print(f"Sim ID: {raw[0]}, Expr: {raw[1][:40]}, Error: {raw[2]}")

        # Logs
        log_res = await db.execute(select(ProjectLog).order_by(ProjectLog.created_at.desc()).limit(10))
        logs = log_res.scalars().all()
        print(f"\n=== LATEST DB LOGS: {len(logs)} ===")
        for l in logs:
            print(f"[{l.created_at}] [{l.level}] {l.message}")

if __name__ == "__main__":
    asyncio.run(inspect())
