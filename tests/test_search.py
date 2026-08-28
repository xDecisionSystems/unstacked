import subprocess

import pytest
from sqlmodel import Session

from app.auth import hash_password
from app.content import ContentRepository
from app.models import Group, Permission, User, UserGroup
from app.search import ContentSearch, SearchError, SearchTimeout


def _write_page(settings, relative: str, text: str) -> None:
    page = settings.content_repo_path / "docs" / relative
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(text, encoding="utf-8")


def _reader(session: Session, *, prefix: str = "public") -> User:
    user = User(
        username="searcher",
        email="searcher@example.com",
        password_hash=hash_password("search password is sufficiently long"),
        display_name="Search Reader",
    )
    group = Group(name="search-readers")
    session.add_all([user, group])
    session.commit()
    session.refresh(user)
    session.refresh(group)
    session.add_all(
        [
            UserGroup(user_id=user.id, group_id=group.id),
            Permission(group_id=group.id, path_prefix=prefix, can_read=True, can_write=False),
        ]
    )
    session.commit()
    return user


def test_search_filters_unreadable_paths_before_any_content_read(app_env, monkeypatch):
    app, settings, _admin, _token = app_env
    _write_page(settings, "public/visible.md", "---\ntitle: Visible\ntags: [guide]\n---\nneedle")
    _write_page(settings, "secret/hidden.md", "---\ntitle: Secret\n---\nneedle")
    observed: list[str] = []
    from app import search as search_module

    original = search_module.read_confined_text

    def recording_read(root, relative, **kwargs):
        observed.append(relative)
        return original(root, relative, **kwargs)

    monkeypatch.setattr(search_module, "read_confined_text", recording_read)
    with Session(app.state.engine) as session:
        user = _reader(session)
        result = ContentSearch(ContentRepository(settings), rg_path=None).search(
            session, user, "needle"
        )

    assert [item.path for item in result.items] == ["public/visible.md"]
    assert "secret/hidden.md" not in observed


def test_ripgrep_and_fallback_have_the_same_verified_ordered_contract(app_env):
    app, settings, admin, _token = app_env
    _write_page(settings, "book/zeta.md", "---\ntitle: needle title\ntags: [one]\n---\nbody")
    _write_page(settings, "book/alpha.md", "---\ntitle: Alpha\ntags: [needle]\n---\nbody")
    _write_page(settings, "book/ignored.md", "---\ncustom: needle\ntitle: Ignored\n---\nbody")
    expected_paths = ["book/alpha.md", "book/zeta.md"]
    seen_command: list[str] = []

    def fake_rg(command, **kwargs):
        seen_command.extend(command)
        # Report every file like ripgrep can; app-level semantic verification
        # must exclude a match that appears only in unrelated front matter.
        output = b"".join(
            str(settings.content_repo_path / "docs" / path).encode() + b"\0"
            for path in ["book/zeta.md", "book/ignored.md", "book/alpha.md"]
        )
        return subprocess.CompletedProcess(command, 0, stdout=output)

    with Session(app.state.engine) as session:
        fallback = ContentSearch(ContentRepository(settings), rg_path=None).search(
            session, admin, "needle"
        )
        accelerated = ContentSearch(
            ContentRepository(settings), rg_path="/usr/bin/rg", runner=fake_rg
        ).search(session, admin, "needle")

    assert [item.path for item in fallback.items] == expected_paths
    assert accelerated == fallback
    assert "--fixed-strings" in seen_command
    assert "--" in seen_command


def test_query_is_never_an_option_or_regex_and_pagination_follows_acl_filtering(app_env):
    app, settings, _admin, _token = app_env
    _write_page(settings, "public/a.md", "---\ntitle: A\n---\n--glob=*.md|(?")
    _write_page(settings, "public/b.md", "---\ntitle: B\n---\n--glob=*.md|(?")
    _write_page(settings, "secret/c.md", "---\ntitle: C\n---\n--glob=*.md|(?")
    command_seen: list[str] = []

    def fake_rg(command, **kwargs):
        command_seen.extend(command)
        output = b"".join(
            str(settings.content_repo_path / "docs" / path).encode() + b"\0"
            for path in ["public/a.md", "public/b.md"]
        )
        return subprocess.CompletedProcess(command, 0, stdout=output)

    query = "--glob=*.md|(?"
    with Session(app.state.engine) as session:
        user = _reader(session)
        result = ContentSearch(
            ContentRepository(settings), rg_path="rg", runner=fake_rg
        ).search(session, user, query, page=2, page_size=1)

    assert result.total == 2
    assert [item.path for item in result.items] == ["public/b.md"]
    separator = command_seen.index("--")
    assert command_seen[separator + 1] == query
    assert command_seen[0] == "rg"


def test_file_result_snippet_and_input_limits_are_bounded(app_env):
    app, settings, admin, _token = app_env
    settings.max_search_file_bytes = 80
    settings.max_search_snippet_chars = 20
    _write_page(settings, "book/large.md", "needle" + "x" * 100)
    _write_page(settings, "book/small.md", "x" * 30 + "needle" + "y" * 30)
    engine = ContentSearch(ContentRepository(settings), rg_path=None)
    with Session(app.state.engine) as session:
        result = engine.search(session, admin, "needle")
        with pytest.raises(SearchError, match="length limit"):
            engine.search(session, admin, "x" * (settings.max_search_query_chars + 1))
        with pytest.raises(SearchError, match="invalid character"):
            engine.search(session, admin, "needle\nnext")
        with pytest.raises(SearchError, match="page size"):
            engine.search(session, admin, "needle", page_size=101)

    assert [item.path for item in result.items] == ["book/small.md"]
    assert len(result.items[0].snippet) <= settings.max_search_snippet_chars
    assert "needle" in result.items[0].snippet


def test_timeout_is_a_bounded_safe_failure(app_env):
    app, settings, admin, _token = app_env
    _write_page(settings, "book/page.md", "needle")
    settings.search_timeout_seconds = 1
    clock_values = iter([0.0, 0.0, 2.0])
    with Session(app.state.engine) as session:
        engine = ContentSearch(
            ContentRepository(settings), rg_path=None, clock=lambda: next(clock_values)
        )
        with pytest.raises(SearchTimeout, match="timed out"):
            engine.search(session, admin, "needle")
