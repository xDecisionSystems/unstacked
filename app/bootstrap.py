import argparse
import getpass

from sqlmodel import Session, select

from app.auth import create_api_token, hash_password
from app.config import Settings
from app.content import ContentRepository
from app.models import User, create_db_engine, migrate_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize Unstacked and its first admin")
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Admin password: ")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters")

    settings = Settings()
    migrate_schema(settings.db_path)
    engine = create_db_engine(settings.db_path)
    ContentRepository(settings).initialize()
    with Session(engine) as session:
        existing = session.exec(select(User)).first()
        if existing is not None:
            raise SystemExit("Bootstrap refused: a user already exists")
        user = User(
            email=args.email.casefold(),
            password_hash=hash_password(password),
            display_name=args.display_name,
            is_admin=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        token = create_api_token(user, settings)
    print("Bootstrap complete. Initial API token (shown once):")
    print(token)


if __name__ == "__main__":
    main()
