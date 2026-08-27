import argparse
import getpass
import sys

from sqlmodel import Session, select

from app.auth import create_api_token, hash_password
from app.config import Settings
from app.content import ContentRepository
from app.models import User, create_db_engine, migrate_schema


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise SystemExit("Password from standard input must not be empty")
        return password
    return getpass.getpass("Admin password: ")


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize Unstacked and its first admin")
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the initial password from standard input instead of prompting.",
    )
    args = parser.parse_args()

    settings = Settings()
    migrate_schema(settings.db_path)
    engine = create_db_engine(settings.db_path)
    ContentRepository(settings).initialize()
    with Session(engine) as session:
        existing = session.exec(select(User)).first()
        if existing is not None:
            print("Bootstrap already complete; existing users were left unchanged.")
            return
        password = _read_password(args.password_stdin)
        if len(password) < 12:
            raise SystemExit("Password must contain at least 12 characters")
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
