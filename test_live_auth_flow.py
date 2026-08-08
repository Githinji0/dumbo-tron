import asyncio
from sqlalchemy import select
from brain_farm.app.database.session import make_session_factory
from brain_farm.app.database.models import User
from brain_farm.app.services.brain_client import BrainClient

async def run_test():
    db_factory = make_session_factory()
    async with db_factory() as db:
        res = await db.execute(select(User))
        users = res.scalars().all()
        
        print("BRAIN AUTH TEST")
        print("---------------")
        
        if not users:
            print("No users found in database.")
            return

        real_users = [u for u in users if not u.email.endswith("mock.com")]
        if not real_users:
            print("No real (non-mock) users found in database to test.")
            return

        for u in real_users:
            print(f"Testing live credentials for user email: {u.email}")
            password = u.get_password()
            
            # Create a live client
            client = BrainClient(u.email, password, use_mock=False)
            success, msg = await client.authenticate_step1()
            
            print(f"Result success: {success}")
            print(f"Message: {msg}")
            
            if client.client:
                await client.client.aclose()

asyncio.run(run_test())
