"""
Set a member's password from the machine running the server.

    python scripts/reset_password.py alice@example.com
    python scripts/reset_password.py alice@example.com --password 'new one'
    python scripts/reset_password.py --list

The in-app route - an owner resets a member from the Members page - cannot help
the person locked out of the *only* owner account: there is nobody left to ask.
This is the way back in, and it fits how the app is deployed. Being able to run
it means having the server's files, which is the same authority as being able
to read the database directly, so it grants nothing that access did not already
imply.

Runs against whatever database the install is configured for, SQLite or
Postgres, and writes the hash through the app's own hasher so the result is
identical to a password set in the UI.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.database.connection import get_db_context, resolve_database_url  # noqa: E402
from app.models.database import Organization, User  # noqa: E402
from app.security import hash_password  # noqa: E402

MIN_LENGTH = 8


async def list_members() -> int:
    async with get_db_context() as db:
        rows = (
            await db.execute(
                select(User, Organization)
                .join(Organization, Organization.id == User.organization_id)
                .order_by(User.email)
            )
        ).all()
    if not rows:
        print("No accounts exist yet - create one in the app.")
        return 0
    width = max(len(user.email) for user, _ in rows)
    print(f"{'EMAIL'.ljust(width)}  ROLE     WORKSPACE")
    for user, org in rows:
        active = "" if user.is_active else "  (deactivated)"
        print(f"{user.email.ljust(width)}  {user.role.ljust(7)}  {org.name}{active}")
    return 0


async def reset(email: str, password: str | None) -> int:
    email = email.strip().lower()
    async with get_db_context() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            print(f"No account with the email {email!r}. Use --list to see them.", file=sys.stderr)
            return 1

        if password is None:
            password = getpass.getpass(f"New password for {email}: ")
            if password != getpass.getpass("Repeat: "):
                print("Those did not match.", file=sys.stderr)
                return 1
        if len(password) < MIN_LENGTH:
            print(f"Password must be at least {MIN_LENGTH} characters.", file=sys.stderr)
            return 1

        user.password_hash = hash_password(password)
        # A locked-out account is usually also a deactivated one; letting the
        # reset fix the password but leave them unable to sign in would be a
        # confusing half-measure.
        user.is_active = True
        await db.commit()

    print(f"Password updated for {email}. Sign in with it now.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("email", nargs="?", help="account to reset")
    parser.add_argument("--password", help="new password (prompted for if omitted)")
    parser.add_argument("--list", action="store_true", help="list accounts and exit")
    args = parser.parse_args()

    if not args.list and not args.email:
        parser.error("give an email address, or --list to see them")

    print(f"database: {resolve_database_url().split('@')[-1]}", file=sys.stderr)
    if args.list:
        return asyncio.run(list_members())
    return asyncio.run(reset(args.email, args.password))


if __name__ == "__main__":
    raise SystemExit(main())
