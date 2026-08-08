import asyncio
from sqlalchemy import select
from brain_farm.app.database.session import make_session_factory
from brain_farm.app.database.models import ProjectLog

async def main():
    db_factory = make_session_factory()
    async with db_factory() as db:
        res = await db.execute(select(ProjectLog).order_by(ProjectLog.created_at.desc()).limit(5))
        logs = res.scalars().all()
        print(f"Found {len(logs)} logs.")
        for l in logs:
            print(f"[{l.created_at}] [{l.level}] {l.message}")

asyncio.run(main())
