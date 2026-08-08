"""
Diagnostic: tests the real WorldQuant BRAIN authentication endpoint
and prints the exact response so we can see what's going wrong.

Usage:
    python debug_auth.py YOUR_EMAIL YOUR_PASSWORD
"""
import sys
import asyncio
import httpx

BASE_URL = "https://api.worldquantbrain.com"

async def test_auth(email: str, password: str):
    print(f"\n--- Testing BRAIN Authentication ---")
    print(f"URL : {BASE_URL}/authentication")
    print(f"User: {email}")
    print()

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            res = await client.post(
                f"{BASE_URL}/authentication",
                auth=(email, password),
            )
            print(f"HTTP Status : {res.status_code}")
            print(f"Headers     : {dict(res.headers)}")
            print(f"Body        : {res.text[:500]}")

            if res.status_code == 201:
                print("\n[SUCCESS] Authentication succeeded on the real API!")
                print("Cookies:", dict(res.cookies))
            elif res.status_code == 401:
                print("\n[FAIL] 401 Unauthorized - wrong credentials OR 2FA required.")
            elif res.status_code == 403:
                print("\n[FAIL] 403 Forbidden - account may require OTP/2FA challenge.")
            elif res.status_code == 202:
                print("\n[INFO] 202 Accepted - check if a 2FA OTP was sent to your email.")
            else:
                print(f"\n[UNKNOWN] Unexpected status {res.status_code}")
        except httpx.ConnectError as e:
            print(f"[ERROR] Could not reach {BASE_URL}: {e}")
        except Exception as e:
            print(f"[ERROR] Unexpected: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python debug_auth.py <email> <password>")
        sys.exit(1)
    asyncio.run(test_auth(sys.argv[1], sys.argv[2]))
