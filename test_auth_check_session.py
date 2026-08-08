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
            print("--- AUTHENTICATION STEP (POST) ---")
            r_auth = await client.post(auth_url, auth=(email, password))
            print(f"Auth Response Code: {r_auth.status_code}")
            print(f"Auth Body: {r_auth.text[:200]}")
            
            print("\n--- GET /authentication (using same session) ---")
            r_check = await client.get(auth_url)
            print(f"Check Response Code: {r_check.status_code}")
            print(f"Check Body: {r_check.text[:300]}")

            print("\n--- GET /datafields or /data-fields/ ---")
            r_df = await client.get("https://api.worldquantbrain.com/datafields")
            print(f"/datafields Code: {r_df.status_code}")
            
            r_df2 = await client.get("https://api.worldquantbrain.com/data-fields/")
            print(f"/data-fields/ Code: {r_df2.status_code}")
            print(f"/data-fields/ Body: {r_df2.text[:200]}")

asyncio.run(run_test())
