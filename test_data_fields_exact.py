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
            
            # Probe combinations
            probes = [
                {"region": "USA", "delay": 1, "universe": "TOP3000", "instrumentType": "EQUITY"},
                {"region": "USA", "delay": "1", "universe": "TOP3000", "instrumentType": "EQUITY", "limit": 5},
                {"region": "USA", "delay": 1, "universe": "TOP3000", "limit": 5},
            ]
            
            for p in probes:
                print(f"\nQuery params: {p}")
                r = await client.get("https://api.worldquantbrain.com/data-fields", params=p)
                print(f"Status Code: {r.status_code}")
                if r.status_code == 200:
                    print(f"Success! Keys: {list(r.json().keys())}")
                    print(f"Count: {len(r.json().get('results', []))}")
                    print(f"First field: {r.json().get('results', [])[0] if r.json().get('results') else 'None'}")
                else:
                    print(f"Body: {r.text[:200]}")

asyncio.run(run_test())
