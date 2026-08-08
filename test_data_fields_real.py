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
            
            # Common parameters in some client implementations:
            params_options = [
                {"limit": 5},
                {"region": "USA", "universe": "TOP3000", "delay": 1},
                {"region": "USA", "universe": "TOP3000", "delay": "1", "limit": "5"},
                {"region": "USA", "universe": "TOP3000", "delay": 1, "instrumentType": "EQUITY"},
            ]
            
            for index, params in enumerate(params_options):
                print(f"\nOption {index}: GET /data-fields with {params}")
                r = await client.get("https://api.worldquantbrain.com/data-fields", params=params)
                print(f"Status Code: {r.status_code}")
                if r.status_code == 200:
                    print(f"SUCCESS! Result keys: {list(r.json().keys())}")
                    print(f"Results sample count: {len(r.json().get('results', []))}")
                    break
                else:
                    print(f"Error: {r.text[:200]}")

asyncio.run(run_test())
