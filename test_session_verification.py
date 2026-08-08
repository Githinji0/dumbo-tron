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
            print("No real user credentials in DB. Please sign in via UI first.")
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
            print("--- AUTHENTICATION STEP ---")
            print(f"Sending POST to {auth_url} for {email}...")
            
            res_auth = await client.post(auth_url, auth=(email, password))
            print(f"Auth Response Code: {res_auth.status_code}")
            
            if res_auth.status_code not in (200, 201):
                print(f"Authentication failed! Code: {res_auth.status_code}, Body: {res_auth.text[:150]}")
                return

            print("\n--- AUTHENTICATED REQUEST STEP ---")
            fields_url = "https://api.worldquantbrain.com/data-fields"
            params = {"region": "USA", "universe": "TOP3000", "limit": 2}
            print(f"Sending GET to {fields_url} with params {params} using same session...")
            
            res_fields = await client.get(fields_url, params=params)
            print(f"Fields Response Code: {res_fields.status_code}")
            
            if res_fields.status_code == 200:
                data = res_fields.json()
                print(f"Successfully fetched fields! Count returned: {len(data.get('results', []))}")
                print("Result fields:")
                for index, item in enumerate(data.get('results', [])):
                    print(f"  [{index}] ID: {item.get('id')}, Category: {item.get('category')}")
            else:
                print(f"Failed to fetch fields! Code: {res_fields.status_code}, Body: {res_fields.text[:200]}")

asyncio.run(run_test())
