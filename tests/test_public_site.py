import pytest

from app.public_site import PublicSiteBuilder, PublicSiteError


def _make_public_book(app_env) -> None:
    app, _settings, admin, _token = app_env
    content = app.state.content
    content.create_book("Public handbook", "public-handbook", admin)
    content.create_page(
        "public-handbook",
        "Welcome",
        "welcome",
        "# Welcome\n\nVisible outside the workspace.",
        [],
        False,
        admin,
    )
    content.set_subtree_public("public-handbook", True, admin)


def test_public_build_contains_only_explicitly_public_content(app_env):
    app, settings, admin, _token = app_env
    content = app.state.content
    _make_public_book(app_env)
    content.create_book("Private notes", "private-notes", admin)
    content.create_page(
        "private-notes", "Secret", "secret", "# Secret\n\nDo not publish this.", [], False, admin
    )

    destination = PublicSiteBuilder(settings, content).build()

    public_html = (destination / "public-handbook" / "welcome" / "index.html").read_text(
        encoding="utf-8"
    )
    search = (destination / "search" / "search_index.json").read_text(encoding="utf-8")
    assert "Visible outside the workspace." in public_html
    assert not (destination / "private-notes").exists()
    assert "Private notes" not in search
    assert "Do not publish this." not in search


def test_public_build_fails_closed_on_link_to_private_content_and_keeps_last_site(app_env):
    app, settings, admin, _token = app_env
    content = app.state.content
    _make_public_book(app_env)
    content.create_book("Private notes", "private-notes", admin)
    content.create_page(
        "private-notes", "Secret", "secret", "# Secret\n\nPrivate.", [], False, admin
    )
    builder = PublicSiteBuilder(settings, content)
    destination = builder.build()
    previous = (destination / "public-handbook" / "welcome" / "index.html").read_bytes()

    content.update_page(
        "public-handbook/welcome.md",
        "# Welcome\n\n[Private](../private-notes/secret.md)",
        [],
        False,
        admin,
        base_blob_sha=content.page_blob_sha("public-handbook/welcome.md"),
    )

    with pytest.raises(PublicSiteError, match="non-public"):
        builder.build()
    assert (destination / "public-handbook" / "welcome" / "index.html").read_bytes() == previous


def test_public_build_fails_closed_on_raw_html_link_to_a_management_path(app_env):
    """Guards the ``href=``/``src=`` branch of ``_reject_private_links``.

    Markdown passes raw inline HTML through unchanged, so an editor writing
    ``<a href="/pages/...">`` rather than Markdown-link syntax must be caught
    the same way -- this exercises that branch specifically, since the other
    fail-closed test above only covers the Markdown-syntax regex.
    """

    app, settings, admin, _token = app_env
    content = app.state.content
    _make_public_book(app_env)
    builder = PublicSiteBuilder(settings, content)
    destination = builder.build()
    previous = (destination / "public-handbook" / "welcome" / "index.html").read_bytes()

    content.update_page(
        "public-handbook/welcome.md",
        '# Welcome\n\n<a href="/pages/private-notes/secret">management link</a>',
        [],
        False,
        admin,
        base_blob_sha=content.page_blob_sha("public-handbook/welcome.md"),
    )

    with pytest.raises(PublicSiteError, match="management-only"):
        builder.build()
    assert (destination / "public-handbook" / "welcome" / "index.html").read_bytes() == previous


def test_empty_public_site_has_a_safe_home_page(app_env):
    app, settings, _admin, _token = app_env

    destination = PublicSiteBuilder(settings, app.state.content).build()

    assert (destination / "index.html").is_file()
    assert "No public content is available yet." in (destination / "index.html").read_text(
        encoding="utf-8"
    )
