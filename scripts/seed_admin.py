"""Create or update an admin user for the web panel and/or bot moderation.

Usage (inside the app container):
    docker compose exec app python scripts/seed_admin.py --username root --password secret --role admin --telegram-id 123456789
"""

import argparse

from app import models
from app.database import SessionLocal
from app.security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True, help="Password for web panel login")
    parser.add_argument("--role", default="admin", choices=["viewer", "moderator", "admin"])
    parser.add_argument("--telegram-id", type=int, default=None, help="Telegram user ID, for bot moderation")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        admin = db.query(models.Admin).filter(models.Admin.username == args.username).first()
        if admin is None:
            admin = models.Admin(username=args.username, role=args.role, telegram_id=args.telegram_id)
            db.add(admin)
            print(f"Creating admin '{args.username}' (role={args.role})")
        else:
            admin.role = args.role
            if args.telegram_id is not None:
                admin.telegram_id = args.telegram_id
            print(f"Updating existing admin '{args.username}' (role={args.role})")
        admin.password_hash = hash_password(args.password)
        admin.active = True
        db.commit()
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
