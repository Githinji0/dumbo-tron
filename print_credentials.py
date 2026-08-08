import asyncio
from sqlalchemy import select
from brain_farm.app.database.session import make_session_factory
from brain_farm.app.database.models import User
from brain_farm.app.core.security import decrypt_data

AsyncSessionLocal = make_session_factory()

async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User))
        for u in res.scalars().all():
            pw = decrypt_data(u.encrypted_password)
            print(f"ID: {u.id} | Email: '{u.email}' | PW: '{pw}'")

if __name__ == "__main__":
    asyncio.run(main())
