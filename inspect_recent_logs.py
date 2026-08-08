import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select
from brain_farm.app.database.session import make_session_factory
from brain_farm.app.database.models import ProjectLog

async def main():
    db_factory = make_session_factory()
    async with db_factory() as db:
        ten_mins_ago = datetime.utcnow() - timedelta(minutes=10)
        res = await db.execute(
            select(ProjectLog)
            .where(ProjectLog.created_at >= ten_mins_ago)
            .order_by(ProjectLog.created_at.desc())
        )
        logs = res.scalars().all()
        print(f"Found {len(logs)} logs in the last 10 minutes.")
        for l in logs:
            print(f"[{l.created_at}] [{l.level}] {l.message}")

asyncio.run(main())
