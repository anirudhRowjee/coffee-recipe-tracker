"""
Set someone's password from the server's terminal. Mainly for the very first
sign-in, when nobody can reach the admin page yet; after that, use Manage.

Usage (on the VPS, or locally):
    python scripts/set_password.py            # lists accounts
    python scripts/set_password.py 1          # by user id

Prompts for the password, so it never appears in shell history. Signs that user
out everywhere.
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session
from app import auth, crud, db, models


def main() -> None:
    db.create_db_and_tables()
    db.run_migrations()
    with Session(db.engine) as session:
        if len(sys.argv) != 2:
            for user in crud.get_users(session):
                state = "password set" if user.password_hash else "no password"
                print(f"{user.id:>3}  {user.name}{'  (admin)' if user.is_admin else ''}  [{state}]")
            print("\nRun again with a user id to set that password.")
            return
        user = session.get(models.User, int(sys.argv[1]))
        if not user:
            sys.exit(f"No user with id {sys.argv[1]}")
        password = getpass.getpass(f"New password for {user.name}: ")
        if len(password) < auth.MIN_PASSWORD_LENGTH:
            sys.exit(f"Use at least {auth.MIN_PASSWORD_LENGTH} characters. Nothing changed.")
        if password != getpass.getpass("Same again: "):
            sys.exit("Those didn't match. Nothing changed.")
        crud.set_user_password(session, user, password, must_change=False)
        crud.delete_sessions_for_user(session, user.id)  # type: ignore[arg-type]
        print(f"Password set for {user.name}.")


if __name__ == "__main__":
    main()
