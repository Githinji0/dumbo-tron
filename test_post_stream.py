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
            print("No real users found.")
            return
        
        email = real_users[0].email
        password = real_users[0].get_password()
        
        HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        
        client = httpx.AsyncClient(follow_redirects=True, headers=HEADERS)
        try:
            async with client.stream("POST", "https://api.worldquantbrain.com/authentication", auth=(email, password)) as r:
                print(f"POST Stream Status: {r.status_code}")
                print("Cookies in client after stream open:")
                for name, value in client.cookies.items():
                    print(f"  Cookie: name={name}")
                print("Headers:")
                for k, v in r.headers.items():
                    if k.lower() in ("set-cookie", "authorization"):
                        print(f"  {k}: [redacted-cookie/auth]")
                    else:
                        print(f"  {k}: {v}")
        except Exception as e:
            print(f"POST Stream Error: {e}")
        await client.aclose()

asyncio.run(run_test())
