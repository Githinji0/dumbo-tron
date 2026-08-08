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
        real_users = [u for u in users if u.email and not u.email.endswith("mock.com")]
        if not real_users:
            print("BRAIN AUTH TEST")
            print("---------------")
            print("Base URL: configured")
            print("Email: not configured in DB (register via UI first)")
            print("Password: not configured in DB")
            print("\nAuthentication: SKIPPED (No real user in DB)")
            return
        
        u = real_users[0]
        email = u.email
        password = u.get_password()
        
        # Test updated client logic using POST stream
        client = BrainClient(email, password, use_mock=False)
        
        # Temporary patch of client logic to use POST for testing
        # (We will modify client.stream method parameters)
        # But wait, let's verify if the client itself needs code changes.
        # We can implement a clean wrapper test:
        print("BRAIN AUTH TEST")
        print("---------------")
        print(f"Base URL: {client.base_url}")
        print(f"Email: {email}")
        
        # Initialize client
        HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        import httpx
        client.client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=120.0, write=10.0, pool=10.0),
            follow_redirects=True,
            headers=HEADERS,
        )
        
        try:
            # Send the stream authentication request using POST
            auth_url = f"{client.base_url}/authentication"
            client._auth_stream = client.client.stream(
                "POST", auth_url, auth=(client.email, client.password)
            )
            res = await client._auth_stream.__aenter__()
            
            print(f"HTTP Status: {res.status_code}")
            
            if res.status_code in (200, 201):
                client.is_authenticated = True
                await client._auth_stream.__aexit__(None, None, None)
                print("\nAuthentication: SUCCESS")
                print("Cookies retrieved:")
                for name, value in client.client.cookies.items():
                    print(f"  Cookie: name={name}")
            elif res.status_code == 202:
                print("OTP Required - Auth stream kept open.")
                print("\nAuthentication: OTP_SENT")
            else:
                body = ""
                async for chunk in res.aiter_text():
                    body += chunk
                    if len(body) > 300:
                        break
                print(f"Response: {body[:200]}")
                print("\nAuthentication: FAILED")
                await client._auth_stream.__aexit__(None, None, None)
        except Exception as e:
            print(f"Error: {e}")
            print("\nAuthentication: FAILED")
            if hasattr(client, "_auth_stream") and client._auth_stream:
                try:
                    await client._auth_stream.__aexit__(None, None, None)
                except Exception:
                    pass
        
        if client.client:
            await client.client.aclose()

asyncio.run(run_test())
