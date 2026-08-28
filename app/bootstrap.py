from sqlmodel import Session, select

from app.auth import hash_password
from app.config import Settings
from app.content import ContentRepository
from app.models import User, create_db_engine, migrate_schema


def main() -> None:
    settings = Settings()
    migrate_schema(settings.db_path)
    engine = create_db_engine(settings.db_path)
    ContentRepository(settings).initialize()
    with Session(engine) as session:
        existing = session.exec(select(User)).first()
        if existing is not None:
            print("Bootstrap already complete; existing users were left unchanged.")
            return
        user = User(
            username="admin",
            email="admin@unstacked.local",
            password_hash=hash_password("admin"),
            display_name="Administrator",
            is_admin=True,
            must_change_password=True,
        )
        session.add(user)
        session.commit()
    print("Bootstrap complete. Sign in as admin and change the default password immediately.")


if __name__ == "__main__":
    main()
