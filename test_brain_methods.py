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
        
        # Test 1: GET stream (what client does)
        print("\n=== Test 1: GET stream ===")
        client1 = httpx.AsyncClient(follow_redirects=True, headers=HEADERS)
        try:
            async with client1.stream("GET", "https://api.worldquantbrain.com/authentication", auth=(email, password)) as r1:
                print(f"GET Status: {r1.status_code}")
                print("Cookies:")
                for name, value in client1.cookies.items():
                    print(f"  Cookie: name={name}, value=[redacted]")
                print("Headers:")
                for k, v in r1.headers.items():
                    if k.lower() in ("set-cookie", "authorization"):
                        print(f"  {k}: [redacted-cookie/auth]")
                    else:
                        print(f"  {k}: {v}")
        except Exception as e:
            print(f"GET Error: {e}")
        await client1.aclose()
        
        # Test 2: POST (the standard alternative)
        print("\n=== Test 2: POST ===")
        client2 = httpx.AsyncClient(follow_redirects=True, headers=HEADERS)
        try:
            r2 = await client2.post("https://api.worldquantbrain.com/authentication", auth=(email, password))
            print(f"POST Status: {r2.status_code}")
            print("Cookies:")
            for name, value in client2.cookies.items():
                print(f"  Cookie: name={name}, value=[redacted]")
            print("Headers:")
            for k, v in r2.headers.items():
                if k.lower() in ("set-cookie", "authorization"):
                    print(f"  {k}: [redacted-cookie/auth]")
                else:
                    print(f"  {k}: {v}")
            print(f"POST Body (first 300 chars): {r2.text[:300]}")
        except Exception as e:
            print(f"POST Error: {e}")
        await client2.aclose()

asyncio.run(run_test())
