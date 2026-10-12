"""
One-off bootstrap: create the very first member account and workspace.

There's no self-serve signup through this - it's for seeding an account
without exposing a fresh deployment publicly first. Creates a brand new
workspace (Organization) with its own mcp_token and join_code, same as the
real "Create account" flow does, then a member in it. Everyone after that
uses the Members page (to add a teammate to this workspace) or the
"Create account" tab (to make their own separate workspace, or join this one
with the join code this script prints).

Usage:
    python scripts/create_first_member.py "Your Name" you@example.com yourpassword "Workspace Name"
"""
import asyncio
import secrets
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select
from app.database.connection import AsyncSessionLocal
from app.models.database import User, Organization
from app.security import hash_password, verify_password



async def main():
    if len(sys.argv) != 5:
        print('Usage: python scripts/create_first_member.py "Your Name" you@example.com yourpassword "Workspace Name"')
        sys.exit(1)

    name, email, password, workspace_name = sys.argv[1], sys.argv[2].strip().lower(), sys.argv[3], sys.argv[4]
    if len(password) < 8:
        print("[ERROR] Password must be at least 8 characters.")
        sys.exit(1)

    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(User.id).where(User.email == email))).scalar_one_or_none()
        if existing:
            print(f"[ERROR] A member with email {email} already exists.")
            sys.exit(1)

        slug_base = workspace_name.strip().lower().replace(" ", "-")[:80] or "workspace"
        slug = slug_base
        suffix = 1
        while (await db.execute(select(Organization.id).where(Organization.slug == slug))).scalar_one_or_none():
            suffix += 1
            slug = f"{slug_base}-{suffix}"

        org = Organization(
            name=workspace_name.strip(),
            slug=slug,
            mcp_token=secrets.token_urlsafe(32),
            join_code=secrets.token_hex(4),
        )
        db.add(org)
        await db.flush()

        user = User(
            organization_id=org.id,
            email=email,
            name=name,
            password_hash=hash_password(password),
            is_active=True,
        )
        db.add(user)
        await db.commit()
        print(f"[OK] Created workspace '{workspace_name}' (join code: {org.join_code}) with member {name} <{email}>.")
        print("Sign in at your frontend URL, or share the join code so others can join this same workspace.")


if __name__ == "__main__":
    asyncio.run(main())
