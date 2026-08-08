import asyncio
from sqlalchemy import select
from brain_farm.app.database.session import make_session_factory
from brain_farm.app.database.models import User
import httpx

async def run_test():
    db_factory = make_session_factory()
    async with db_factory() as db:
        res = await db.execute(select(User))
        users = res.scalars().all()
        real_users = [u for u in users if u.email and not u.email.endswith("mock.com")]
        if not real_users:
            print("No real user credentials in DB.")
            return

        u = real_users[0]
        email = u.email
        password = u.get_password()

        HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

        async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS) as client:
            auth_url = "https://api.worldquantbrain.com/authentication"
            await client.post(auth_url, auth=(email, password))
            
            endpoints = [
                ("GET /users/self", "https://api.worldquantbrain.com/users/self", {}),
                ("GET /data-fields (no params)", "https://api.worldquantbrain.com/data-fields", {}),
                ("GET /data-fields (limit=1)", "https://api.worldquantbrain.com/data-fields", {"limit": 1}),
                ("GET /api/v2/data-fields", "https://api.worldquantbrain.com/api/v2/data-fields", {}),
                ("GET /api/v2/data-fields/", "https://api.worldquantbrain.com/api/v2/data-fields/", {}),
                ("GET /api/v2/data-fields (limit=1)", "https://api.worldquantbrain.com/api/v2/data-fields", {"limit": 1}),
            ]
            
            for name, url, params in endpoints:
                try:
                    r = await client.get(url, params=params)
                    print(f"\n{name}:")
                    print(f"  Status Code: {r.status_code}")
                    print(f"  Body: {r.text[:200]}")
                except Exception as e:
                    print(f"\n{name} Exception: {e}")

asyncio.run(run_test())
