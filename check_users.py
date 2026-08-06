import asyncio
from brain_farm.app.database.session import AsyncSessionLocal
from brain_farm.app.database.models import User, Project
from sqlalchemy import select

async def run():
    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User))).all()
        projects = (await db.execute(select(Project))).all()
        print("Users in DB:")
        for u in users:
            print(f"User ID: {u[0].id}, Email: {u[0].email}")
        print("\nProjects in DB:")
        for p in projects:
            print(f"Project ID: {p[0].id}, Name: {p[0].name}, User ID: {p[0].user_id}")

asyncio.run(run())
