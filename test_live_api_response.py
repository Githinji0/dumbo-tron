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
            print("No real users found to test.")
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
        
        client = httpx.AsyncClient(follow_redirects=True, headers=HEADERS)
        auth_url = "https://api.worldquantbrain.com/authentication"
        
        print(f"Requesting: {auth_url}")
        print(f"Email: {email}")
        
        try:
            async with client.stream("GET", auth_url, auth=(email, password)) as res:
                print(f"Status Code: {res.status_code}")
                print("Safe Headers:")
                for k, v in res.headers.items():
                    if k.lower() in ("set-cookie", "authorization", "www-authenticate"):
                        print(f"  {k}: <redacted>")
                    else:
                        print(f"  {k}: {v}")
                
                body = ""
                async for chunk in res.aiter_text():
                    body += chunk
                    if len(body) > 300:
                        break
                print(f"Body (first 300 chars): {body[:300]}")
        except Exception as e:
            print(f"Exception during GET: {e}")

        await client.aclose()

asyncio.run(run_test())
