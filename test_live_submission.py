import asyncio
import os
import sys
from sqlalchemy import select

from brain_farm.app.database.session import make_session_factory
from brain_farm.app.database.models import User, Project
from brain_farm.app.core.security import decrypt_data
from brain_farm.app.services.brain_client import BrainClient

AsyncSessionLocal = make_session_factory()

async def main():
    print("=== LIVE SIMULATION TRIGGER UNIT ===")
    async with AsyncSessionLocal() as db:
        # Load the user and project
        u_res = await db.execute(select(User).where(User.id == 2))
        user = u_res.scalars().first()
        if not user:
            print("No user found in database.")
            return

        p_res = await db.execute(select(Project).where(Project.user_id == user.id))
        proj = p_res.scalars().first()
        if not proj:
            print("No project found for user.")
            return

        print(f"Loaded User ID: {user.id}, Email: {user.email}")
        print(f"Loaded Project: {proj.name}, Region: {proj.region}, Universe: {proj.universe}")

        # Decrypt password
        try:
            password = decrypt_data(user.encrypted_password)
        except Exception as e:
            print(f"Error decrypting password: {e}")
            return

        # Initialize BrainClient (use_mock=False)
        print("Authenticating with WorldQuant BRAIN API...")
        async with BrainClient(user.email, password, use_mock=False) as client:
            # Recheck check_session or authenticate
            # If server has an active session files, the client can check session.
            # But let's authenticate from scratch or reuse the existing session files if loaded.
            # Let's perform step 1
            print("Running authentication...")
            step1_ok, state = await client.authenticate_step1()
            if not step1_ok:
                print(f"Auth step 1 failed: {state}")
                # Check check_session
                alive, info = await client.check_session()
                if alive:
                    print("Existing session is alive! Proceeding...")
                    client.is_authenticated = True
                else:
                    print("Could not authenticate. Missing credentials or OTP required.")
                    return
            else:
                print(f"Auth step 1 state: {state}")
                if state == "OTP_REQUIRED":
                    print("OTP is required to authenticate. Please log in first via frontend dashboard so the session is injected.")
                    # Let's see if we can check session
                    alive, info = await client.check_session()
                    if alive:
                        print("Existing session is alive! Proceeding...")
                        client.is_authenticated = True
                    else:
                        print("Session is not alive. Please login via GUI first.")
                        return
                    
            if not client.is_authenticated:
                print("Client not authenticated.")
                return

            print("Client authenticated successfully.")
            
            # Submit test simulation
            expression = "rank(close)"
            settings = {
                "region": proj.region,
                "universe": proj.universe,
                "neutralization": proj.neutralization,
                "delay": proj.delay,
                "decay": proj.decay
            }
            print(f"Submitting simulation for formula: '{expression}' with settings: {settings}")
            sim_id, err = await client.submit_simulation(expression, settings)
            if err:
                print(f"Submission failed: {err}")
                return
            
            print(f"SUCCESS! Simulation ID returned: {sim_id}")
            print("Starting polling...")
            
            # Poll status
            for idx in range(10):
                await asyncio.sleep(5)
                data, err = await client.get_simulation_status(sim_id)
                if err:
                    print(f"Polling error: {err}")
                    break
                status = data.get("status", "UNKNOWN") if data else "UNKNOWN"
                print(f"Poll #{idx+1}: Status = {status} | Data keys: {list(data.keys()) if data else []}")
                if status in ("COMPLETE", "ERROR", "REJECTED"):
                    print(f"Final state reached. Status: {status}")
                    if data:
                        print(f"Metrics/data: {data}")
                    break

if __name__ == "__main__":
    asyncio.run(main())
