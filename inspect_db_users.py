import asyncio
from sqlalchemy import select
from brain_farm.app.database.session import make_session_factory
from brain_farm.app.database.models import User

async def run():
    f = make_session_factory()
    async with f() as db:
        res = await db.execute(select(User))
        for u in res.scalars().all():
            print(f"ID: {u.id}, Email: '{u.email}'")

asyncio.run(run())
