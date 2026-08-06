import asyncio
from brain_farm.app.database.session import AsyncSessionLocal
from brain_farm.app.database.models import ProjectLog
from sqlalchemy import select

async def run():
    async with AsyncSessionLocal() as db:
        logs = (await db.execute(select(ProjectLog).order_by(ProjectLog.created_at.desc()).limit(20))).all()
        print("Latest 20 Logs:")
        for l in logs:
            print(f"[{l[0].created_at}] ({l[0].level}) {l[0].message}")

asyncio.run(run())
