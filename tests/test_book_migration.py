from sqlmodel import Session, select

from app.content import ContentRepository, new_page
from app.models import User


def test_legacy_chapters_are_promoted_idempotently(app_env):
    app, settings, _admin, _token = app_env
    content = ContentRepository(settings)
    with Session(app.state.engine) as session:
        actor = session.exec(select(User).where(User.username == "admin")).one()
        content.create_book("Operations", "operations", actor)
        # Construct a legacy nested tree directly: the normal creation API
        # correctly refuses chapters in the new book/page-only model.
        legacy_chapter = settings.content_repo_path / "docs" / "operations" / "runbooks"
        legacy_chapter.mkdir()
        (legacy_chapter / ".pages").write_text("title: Runbooks\n", encoding="utf-8")
        (legacy_chapter / "restart.md").write_text(
            new_page("body", {"title": "Restart", "tags": [], "draft": False}),
            encoding="utf-8",
        )

    mapping = content.migrate_legacy_chapters()

    assert mapping == {"operations/runbooks": "runbooks"}
    assert (settings.content_repo_path / "docs" / "runbooks" / "restart.md").is_file()
    assert not (settings.content_repo_path / "docs" / "operations").exists()
    assert content.migrate_legacy_chapters() == mapping


def test_flat_tree_excludes_nested_legacy_pages(app_env):
    app, settings, _admin, _token = app_env
    content = ContentRepository(settings)
    with Session(app.state.engine) as session:
        actor = session.exec(select(User).where(User.username == "admin")).one()
        content.create_book("Operations", "operations", actor)
        content.create_page("operations", "Overview", "overview", "body", [], False, actor)
        assert content.tree(session, actor) == [
            {"slug": "operations", "pages": ["operations/overview.md"]}
        ]


def test_untouched_legacy_home_placeholders_are_removed(app_env):
    _app, settings, _admin, _token = app_env
    book = settings.content_repo_path / "docs" / "main-read"
    book.mkdir()
    (book / ".pages").write_text("title: Read\n", encoding="utf-8")
    (book / "welcome.md").write_text(
        new_page(
            "# Read\n",
            {"title": "Read", "author": "Unstacked", "tags": [], "draft": False},
        ),
        encoding="utf-8",
    )

    ContentRepository(settings).initialize()

    assert not book.exists()
