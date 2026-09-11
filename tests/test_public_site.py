import threading

import pytest

from app.public_site import PublicSiteBuilder, PublicSiteError, PublicSiteWorker


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


def test_public_link_validation_allows_safe_links_and_rejects_every_private_shape(tmp_path):
    """The static publisher must fail closed for every local-link escape route."""

    docs = tmp_path / "docs"
    docs.mkdir()
    page = docs / "index.md"

    # External URLs, anchors, and non-Markdown relative links stay in the
    # generated static site without needing a corresponding local Markdown file.
    page.write_text(
        "[External](https://example.test) [Jump](#section) [Asset](image.png)\n",
        encoding="utf-8",
    )
    PublicSiteBuilder._reject_private_links(docs)
    assert PublicSiteBuilder._public_books(tmp_path / "no-docs") == []
    assert not PublicSiteBuilder._home_is_public(tmp_path / "no-docs")

    page.write_text("[Management](/books/private)\n", encoding="utf-8")
    with pytest.raises(PublicSiteError, match="management-only"):
        PublicSiteBuilder._reject_private_links(docs)

    page.write_text("[Missing asset](/assets/not-here.png)\n", encoding="utf-8")
    with pytest.raises(PublicSiteError, match="non-public"):
        PublicSiteBuilder._reject_private_links(docs)

    page.write_text("[Outside](../outside.md)\n", encoding="utf-8")
    with pytest.raises(PublicSiteError, match="outside"):
        PublicSiteBuilder._reject_private_links(docs)

    page.write_text("[Missing](missing.md)\n", encoding="utf-8")
    with pytest.raises(PublicSiteError, match="non-public"):
        PublicSiteBuilder._reject_private_links(docs)


def test_public_builder_records_optional_publish_failures_without_losing_content(
    app_env, monkeypatch
):
    """An asynchronous public build failure is visible but never blocks a save."""

    app, settings, _admin, _token = app_env
    builder = PublicSiteBuilder(settings, app.state.content)

    monkeypatch.setattr(
        builder, "build", lambda: (_ for _ in ()).throw(PublicSiteError("strict build failed"))
    )
    builder.build_recording_failure()
    assert builder.status().last_error == "strict build failed"

    monkeypatch.setattr(builder, "build", lambda: (_ for _ in ()).throw(OSError("disk full")))
    builder.build_recording_failure()
    assert builder.status().last_error == "Public site build failed"


def test_public_staging_helpers_copy_safe_content_and_reject_unsafe_inputs(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Safe", encoding="utf-8")
    destination = tmp_path / "nested" / "copied.md"
    PublicSiteBuilder._copy_file(source, destination)
    assert destination.read_text(encoding="utf-8") == "# Safe"

    with pytest.raises(PublicSiteError, match="unavailable"):
        PublicSiteBuilder._copy_file(tmp_path / "missing.md", tmp_path / "missing-copy.md")

    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "included.md").write_text("# Included", encoding="utf-8")
    copied_tree = tmp_path / "copied-tree"
    PublicSiteBuilder._copy_tree(tree, copied_tree)
    assert (copied_tree / "included.md").is_file()


def test_public_publish_replaces_the_previous_static_site_atomically(app_env, tmp_path):
    app, settings, _admin, _token = app_env
    settings.public_site_path = tmp_path / "public"
    builder = PublicSiteBuilder(settings, app.state.content)
    builder.destination.mkdir()
    (builder.destination / "index.html").write_text("old", encoding="utf-8")
    previous = builder.destination.with_name(f".{builder.destination.name}.previous")
    previous.mkdir()
    (previous / "index.html").write_text("older", encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "index.html").write_text("new", encoding="utf-8")

    builder._publish(candidate)

    assert (builder.destination / "index.html").read_text(encoding="utf-8") == "new"
    assert not previous.exists()


def test_public_staging_rejects_links_and_symlinks_that_could_escape_the_site(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("private", encoding="utf-8")
    (docs / "linked.md").symlink_to(outside)
    with pytest.raises(PublicSiteError, match="unsupported link"):
        PublicSiteBuilder._reject_private_links(docs)

    source = tmp_path / "source"
    source.mkdir()
    source_link = tmp_path / "source-link"
    source_link.symlink_to(source, target_is_directory=True)
    with pytest.raises(PublicSiteError, match="unsupported link"):
        PublicSiteBuilder._copy_tree(source_link, tmp_path / "destination")


def test_public_staging_keeps_existing_public_assets_and_treats_bad_navigation_as_private(
    tmp_path,
):
    docs = tmp_path / "docs"
    docs.mkdir()
    assets = docs / "assets"
    assets.mkdir()
    (assets / "logo.png").write_bytes(b"image")
    (docs / "index.md").write_text("![Logo](/assets/logo.png)\n", encoding="utf-8")
    PublicSiteBuilder._reject_private_links(docs)

    broken = docs / "broken-book"
    broken.mkdir()
    (broken / ".pages").write_text("title: [not: valid", encoding="utf-8")
    assert PublicSiteBuilder._public_books(docs) == []


def test_public_tree_copy_reports_filesystem_errors_without_exposing_details(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "destination"

    def fail_copytree(*_args, **_kwargs):
        raise OSError("internal path details")

    monkeypatch.setattr("app.public_site.shutil.copytree", fail_copytree)
    with pytest.raises(PublicSiteError, match="could not be staged"):
        PublicSiteBuilder._copy_tree(source, destination)


def test_public_site_worker_coalesces_requests_and_stops_cleanly():
    """Public publishing runs outside saves and does not start duplicate workers."""

    class RecordingBuilder:
        def __init__(self):
            self.built = threading.Event()

        def build_recording_failure(self):
            self.built.set()

    builder = RecordingBuilder()
    worker = PublicSiteWorker(builder)  # type: ignore[arg-type]
    worker.start()
    assert builder.built.wait(timeout=3)
    first_thread = worker._thread
    worker.start()
    assert worker._thread is first_thread
    worker.stop()
    assert not first_thread.is_alive()


def test_public_home_reader_and_tree_copy_fail_closed_on_filesystem_anomalies(
    tmp_path, monkeypatch
):
    docs = tmp_path / "docs"
    docs.mkdir()
    home = docs / "index.md"
    home.write_text("---\npublic: true\n---\n", encoding="utf-8")

    original_read_text = type(home).read_text

    def unreadable(path, *args, **kwargs):
        if path == home:
            raise OSError("unreadable")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(type(home), "read_text", unreadable)
    assert not PublicSiteBuilder._home_is_public(docs)

    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "destination"
    outside = tmp_path / "outside"
    outside.write_text("private", encoding="utf-8")

    def copy_with_link(_source, copied, **_kwargs):
        copied.mkdir()
        (copied / "unsafe.md").symlink_to(outside)

    monkeypatch.setattr("app.public_site.shutil.copytree", copy_with_link)
    with pytest.raises(PublicSiteError, match="unsupported link"):
        PublicSiteBuilder._copy_tree(source, destination)


def test_public_publish_restores_the_previous_site_when_replacement_fails(
    app_env, tmp_path, monkeypatch
):
    app, settings, _admin, _token = app_env
    settings.public_site_path = tmp_path / "public"
    builder = PublicSiteBuilder(settings, app.state.content)
    builder.destination.mkdir()
    (builder.destination / "index.html").write_text("old", encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "index.html").write_text("new", encoding="utf-8")
    original_replace = __import__("os").replace

    def fail_candidate_replace(source, destination):
        if source == candidate and destination == builder.destination:
            raise OSError("replacement failed")
        return original_replace(source, destination)

    monkeypatch.setattr("app.public_site.os.replace", fail_candidate_replace)
    with pytest.raises(PublicSiteError, match="could not be published"):
        builder._publish(candidate)
    assert (builder.destination / "index.html").read_text(encoding="utf-8") == "old"
