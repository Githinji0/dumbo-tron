import asyncio
from sqlalchemy import select
from brain_farm.app.database.session import make_session_factory
from brain_farm.app.database.models import Expression

async def main():
    db_factory = make_session_factory()
    async with db_factory() as db:
        res = await db.execute(select(Expression.status))
        exprs = res.scalars().all()
        statuses = {}
        for e in exprs:
            statuses[e] = statuses.get(e, 0) + 1
        print(f"Expression statuses breakdown: {statuses}")

asyncio.run(main())
