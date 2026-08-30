"""Asset uploads: what the bytes are decides everything, never what they claim."""

import asyncio
import base64
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.assets import AssetTooLarge, UnsupportedAsset, detect_image
from app.auth import create_api_token, hash_password
from app.config import Settings
from app.main import create_app
from app.models import Group, Permission, User, UserGroup
from app.render import rewrite_contextual_url
from app.upload_limit import UploadSizeLimitMiddleware
from tests.conftest import bearer

# Real encoder output rather than hand-waved magic bytes: a validator that
# only ever sees fixtures built by the same assumptions it encodes is not
# evidence that a genuine image is accepted.
ONE_PIXEL_GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
ONE_PIXEL_WEBP = base64.b64decode("UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==")
ONE_PIXEL_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4n"
    "ICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEB"
    "AQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKB"
    "kaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1"
    "dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl"
    "5ufo6erx8vP09fb3+Pn6/9oACAEBAAA/AP38ooooA//Z"
)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload))
    )


def png(width: int, height: int, *, declared: tuple[int, int] | None = None) -> bytes:
    """A real, decodable RGB PNG; ``declared`` makes the header lie about its size."""

    stated = declared or (width, height)
    header = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", *stated, 8, 2, 0, 0, 0))
    scanlines = b"".join(b"\x00" + b"\x7f\x40\x20" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + header
        + _png_chunk(b"IDAT", zlib.compress(scanlines, 9))
        + _png_chunk(b"IEND", b"")
    )


def _make_app(tmp_path: Path, **overrides):
    """Build an app whose limits the test controls, plus an admin bearer token."""

    settings = Settings(
        environment="test",
        content_repo_path=tmp_path / "content",
        db_path=tmp_path / "data" / "app.db",
        content_lock_path=tmp_path / "data" / "content.lock",
        static_export_path=tmp_path / "data" / "static-export",
        api_token_secret="test-secret-that-is-long-and-random-enough",
        **overrides,
    )
    app = create_app(settings)
    with Session(app.state.engine) as session:
        admin = User(
            username="admin",
            email="admin@example.com",
            password_hash=hash_password("correct horse battery staple"),
            display_name="Admin Agent",
            is_admin=True,
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        token = create_api_token(admin, settings)
    return app, settings, token


def _grant(app, settings, *, prefix: str, can_write: bool) -> str:
    """Create a scoped non-admin user and return their bearer token."""

    with Session(app.state.engine) as session:
        user = User(
            username=f"scoped-{prefix.replace('/', '-')}-{int(can_write)}",
            email=f"scoped-{prefix.replace('/', '-')}-{int(can_write)}@example.com",
            password_hash=hash_password("a sufficiently long scoped password"),
            display_name="Scoped User",
        )
        group = Group(name=f"group-{prefix.replace('/', '-')}-{int(can_write)}")
        session.add_all([user, group])
        session.commit()
        session.refresh(user)
        session.refresh(group)
        session.add_all(
            [
                UserGroup(user_id=user.id, group_id=group.id),
                Permission(
                    group_id=group.id,
                    path_prefix=prefix,
                    can_read=True,
                    can_write=can_write,
                ),
            ]
        )
        session.commit()
        return create_api_token(user, settings)


def _seed_book(client: TestClient, token: str) -> None:
    headers = bearer(token)
    assert client.post(
        "/api/ai/books", json={"title": "Knowledge"}, headers=headers
    ).status_code == 201


def _upload(client: TestClient, token: str, name: str, data: bytes, mime: str = "image/png"):
    return client.post(
        "/api/ai/books/knowledge/assets",
        files={"file": (name, data, mime)},
        headers=bearer(token),
    )


# --- Detection ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("blob", "media_type", "extension"),
    [
        (png(4, 3), "image/png", "png"),
        (ONE_PIXEL_JPEG, "image/jpeg", "jpg"),
        (ONE_PIXEL_GIF, "image/gif", "gif"),
        (ONE_PIXEL_WEBP, "image/webp", "webp"),
    ],
)
def test_every_allowlisted_format_is_recognized_from_its_own_bytes(blob, media_type, extension):
    """The allowlist has to admit genuine encoder output, or it is just a denial."""

    detected = detect_image(blob, max_pixels=40_000_000, max_dimension=12_000)
    assert (detected.media_type, detected.extension) == (media_type, extension)


@pytest.mark.parametrize(
    "blob",
    [
        pytest.param(png(4, 3) + b"<html><script>alert(1)</script></html>", id="png-then-html"),
        pytest.param(png(4, 3) + b"PK\x03\x04" + b"\x00" * 64, id="png-then-zip"),
        pytest.param(ONE_PIXEL_GIF + b"PK\x03\x04" + b"\x00" * 64, id="gifar"),
        pytest.param(ONE_PIXEL_JPEG + b"PK\x03\x04" + b"\x00" * 64, id="jpeg-then-zip"),
        pytest.param(ONE_PIXEL_WEBP + b"PK\x03\x04" + b"\x00" * 64, id="webp-then-zip"),
    ],
)
def test_a_second_payload_appended_to_a_valid_image_is_refused(blob):
    """A polyglot is valid as its cover format; only whole-file parsing sees the rest."""

    with pytest.raises(UnsupportedAsset, match="trailing data"):
        detect_image(blob, max_pixels=40_000_000, max_dimension=12_000)


@pytest.mark.parametrize(
    "blob",
    [
        pytest.param(b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>', id="svg"),
        pytest.param(b"<!DOCTYPE html><html><body>hi</body></html>", id="html"),
        pytest.param(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", id="pdf"),
        pytest.param(b"\x7fELF" + b"\x00" * 64, id="elf"),
        pytest.param(b"\xff\xd8\xff" + png(4, 3), id="jpeg-header-over-png"),
        pytest.param(png(4, 3)[:20], id="truncated-png"),
    ],
)
def test_active_content_and_spoofed_headers_are_refused(blob):
    """Only four raster formats are storable; nothing scriptable has a way in."""

    with pytest.raises(UnsupportedAsset):
        detect_image(blob, max_pixels=40_000_000, max_dimension=12_000)


@pytest.mark.parametrize(
    "blob",
    [
        pytest.param(
            b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + _png_chunk(b"IEND", b""),
            id="png-without-idat",
        ),
        pytest.param(b"GIF89a\x01\x00\x01\x00\x00\x00\x00;", id="gif-without-image"),
        pytest.param(
            b"RIFF\x16\x00\x00\x00WEBPVP8X\x0a\x00\x00\x00"
            + b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
            id="webp-metadata-without-frame",
        ),
    ],
)
def test_a_container_without_image_data_is_not_accepted_as_an_image(blob):
    with pytest.raises(UnsupportedAsset, match="image data"):
        detect_image(blob, max_pixels=40_000_000, max_dimension=12_000)


def test_a_small_file_that_decodes_huge_is_refused_on_dimensions():
    """A decompression bomb is cheap on disk and only ruinous once decoded."""

    bomb = png(1, 1, declared=(30_000, 30_000))
    assert len(bomb) < 200
    with pytest.raises(AssetTooLarge, match="pixel limit"):
        detect_image(bomb, max_pixels=40_000_000, max_dimension=12_000)


def test_dimensions_within_each_side_can_still_exceed_the_pixel_budget():
    """Two legal sides multiply into an illegal bitmap, so area is capped too."""

    with pytest.raises(AssetTooLarge, match="pixel limit"):
        detect_image(
            png(1, 1, declared=(11_000, 11_000)), max_pixels=40_000_000, max_dimension=12_000
        )


# --- Upload, storage and naming ----------------------------------------------


def test_an_uploaded_image_is_stored_committed_and_served_back(tmp_path):
    """An asset is ordinary content: same git history, same permissions as a page."""

    app, settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        response = _upload(client, token, "Team Logo.PNG", png(6, 4))
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["path"] == "assets/knowledge/team-logo.png"
        assert (body["media_type"], body["width"], body["height"]) == ("image/png", 6, 4)

        stored = settings.content_repo_path / "docs" / "assets" / "knowledge" / "team-logo.png"
        assert stored.is_file()
        log = subprocess.run(
            ["git", "log", "-1", "--name-only", "--format=%an"],
            cwd=settings.content_repo_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "Admin Agent" in log
        assert "docs/assets/knowledge/team-logo.png" in log

        served = client.get("/assets/assets/knowledge/team-logo.png", headers=bearer(token))
        assert served.status_code == 200
        assert served.content == png(6, 4)


def test_the_stored_extension_comes_from_the_bytes_not_the_submitted_name(tmp_path):
    """A name that misdescribes its content must not get to choose how it is served."""

    app, _settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        # A genuine GIF submitted as a .png with an image/jpeg content type.
        response = _upload(client, token, "diagram.png", ONE_PIXEL_GIF, mime="image/jpeg")
        assert response.status_code == 201, response.text
        assert response.json()["path"] == "assets/knowledge/diagram.gif"
        assert response.json()["media_type"] == "image/gif"


@pytest.mark.parametrize(
    "hostile",
    [
        pytest.param("../../../../etc/passwd.png", id="traversal"),
        pytest.param("..\\..\\windows\\system32\\evil.png", id="windows-traversal"),
        pytest.param("logo\x00.png", id="null-byte"),
        pytest.param("/etc/shadow.png", id="absolute"),
        pytest.param("....//....//escape.png", id="doubled-dots"),
    ],
)
def test_a_hostile_filename_cannot_place_a_file_outside_the_book(tmp_path, hostile):
    """The name is untrusted input, so it is slugified rather than used as a path."""

    app, settings, token = _make_app(tmp_path)
    docs = settings.content_repo_path / "docs"
    with TestClient(app) as client:
        _seed_book(client, token)
        response = _upload(client, token, hostile, png(2, 2))
        if response.status_code == 201:
            path = response.json()["path"]
            assert path.startswith("assets/knowledge/")
            assert (docs / path).resolve().parent == (docs / "assets" / "knowledge").resolve()
        else:
            assert response.status_code in {404, 422}
    # Whatever happened, nothing was written outside docs/assets/knowledge/.
    assert not (settings.content_repo_path.parent / "etc").exists()
    written = {path for path in docs.rglob("*") if path.is_file()}
    assert not any(
        path.suffix == ".png" and path.parent != docs / "assets" / "knowledge"
        for path in written
    )


@pytest.mark.parametrize("reserved", ["CON.png", "nul.png", "com1.png", "LPT9.png"])
def test_a_windows_reserved_name_is_refused_rather_than_stored(tmp_path, reserved):
    """The content repo is meant to be checked out anywhere, Windows included."""

    app, _settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        response = _upload(client, token, reserved, png(2, 2))
        assert response.status_code == 422, response.text


def test_a_name_with_nothing_sluggable_left_is_refused(tmp_path):
    """Silently inventing a name would hide that the author's link will not match."""

    app, _settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        assert _upload(client, token, "???.png", png(2, 2)).status_code == 422


def test_a_repeated_name_is_refused_instead_of_silently_renamed(tmp_path):
    """Authors write asset links by hand; a surprise suffix breaks them invisibly."""

    app, _settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        assert _upload(client, token, "logo.png", png(2, 2)).status_code == 201
        clash = _upload(client, token, "logo.png", png(3, 3))
        assert clash.status_code == 409
        assert "already exists" in clash.json()["detail"]


def test_a_spoofed_upload_is_refused_and_leaves_nothing_behind(tmp_path):
    """A refused upload must not leave a partial file for a later read to serve."""

    app, settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        html = b"<!DOCTYPE html><html><script>alert(1)</script></html>"
        response = _upload(client, token, "innocent.png", html)
        assert response.status_code == 422
        assert "HTML content" in response.json()["detail"]
        assert not (settings.content_repo_path / "docs" / "assets" / "knowledge").exists()


def test_an_upload_to_a_missing_book_is_refused(tmp_path):
    """Assets are owned by a book; there is no place for one that has no owner."""

    app, _settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        response = _upload(client, token, "logo.png", png(2, 2))
        assert response.status_code == 404


# --- Serving -----------------------------------------------------------------


def test_a_served_asset_forbids_sniffing_and_renders_inline(tmp_path):
    """Inline display is only safe while the browser cannot re-interpret the body."""

    app, _settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        _upload(client, token, "logo.png", png(2, 2))
        served = client.get("/assets/assets/knowledge/logo.png", headers=bearer(token))
        assert served.headers["x-content-type-options"] == "nosniff"
        assert served.headers["content-type"] == "image/png"
        assert served.headers["content-disposition"].startswith('inline; filename="logo.png"')
        assert served.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert "private" in served.headers["cache-control"]


def test_a_hand_placed_non_image_is_never_served_as_one(tmp_path):
    """Detection runs on read too, so the repository cannot be poisoned by hand."""

    app, settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        planted = settings.content_repo_path / "docs" / "assets" / "knowledge"
        planted.mkdir(parents=True)
        (planted / "evil.png").write_bytes(b"<svg onload=alert(1)></svg>")
        served = client.get("/assets/assets/knowledge/evil.png", headers=bearer(token))
        assert served.status_code == 422
        assert "svg" in served.json()["detail"].casefold()


def test_serving_refuses_a_path_that_is_not_an_asset_slot(tmp_path):
    """Assets get the same fixed depth pages do, so nothing else becomes reachable."""

    app, _settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        assert client.post(
            "/api/ai/books/knowledge/pages",
            json={"title": "Notes", "markdown": "secret"},
            headers=bearer(token),
        ).status_code == 201
        for path in ("assets/knowledge/nested/deep.png", "knowledge/notes.md", "../mkdocs.yml"):
            assert client.get(f"/assets/{path}", headers=bearer(token)).status_code == 404


def test_serving_requires_authentication(tmp_path):
    """An asset is behind the same login as the book it belongs to."""

    app, _settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        _upload(client, token, "logo.png", png(2, 2))
        assert client.get("/assets/assets/knowledge/logo.png").status_code == 401


# --- Permissions --------------------------------------------------------------


def test_read_access_to_a_book_is_not_permission_to_add_to_it(tmp_path):
    """Upload is a content write, authorized exactly like creating a page."""

    app, settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        # The book has to exist before the grant: creating content under a
        # pre-existing grant is refused by design.
        _seed_book(client, token)
        reader = _grant(app, settings, prefix="knowledge", can_write=False)
        assert _upload(client, reader, "logo.png", png(2, 2)).status_code == 404


def test_a_user_with_no_grant_on_the_book_cannot_upload_or_read(tmp_path):
    """Assets inherit the book's ACL; there is no separate asset permission space."""

    app, settings, token = _make_app(tmp_path)
    outsider = _grant(app, settings, prefix="other-book", can_write=True)
    with TestClient(app) as client:
        _seed_book(client, token)
        _upload(client, token, "logo.png", png(2, 2))
        assert _upload(client, outsider, "sneak.png", png(2, 2)).status_code == 404
        assert (
            client.get("/assets/assets/knowledge/logo.png", headers=bearer(outsider)).status_code
            == 404
        )


def test_a_writer_on_the_book_may_upload_read_and_delete(tmp_path):
    """The whole asset lifecycle rides on one grant, not on admin rights."""

    app, settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        writer = _grant(app, settings, prefix="knowledge", can_write=True)
        assert _upload(client, writer, "logo.png", png(2, 2)).status_code == 201
        assert client.get(
            "/assets/assets/knowledge/logo.png", headers=bearer(writer)
        ).status_code == 200
        listed = client.get("/api/ai/books/knowledge/assets", headers=bearer(writer))
        assert listed.json()["assets"] == ["assets/knowledge/logo.png"]
        removed = client.delete(
            "/api/ai/books/knowledge/assets/logo.png", headers=bearer(writer)
        )
        assert removed.status_code == 200
        assert client.get(
            "/assets/assets/knowledge/logo.png", headers=bearer(writer)
        ).status_code == 404


def test_a_reader_cannot_delete_an_asset(tmp_path):
    """Deleting is a write; read access must not be a route to removing content."""

    app, settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        reader = _grant(app, settings, prefix="knowledge", can_write=False)
        _upload(client, token, "logo.png", png(2, 2))
        assert client.delete(
            "/api/ai/books/knowledge/assets/logo.png", headers=bearer(reader)
        ).status_code == 404
        assert client.get(
            "/assets/assets/knowledge/logo.png", headers=bearer(reader)
        ).status_code == 200


def test_a_deleted_asset_stays_recoverable_in_git(tmp_path):
    """Git is the recycle bin here, so a deletion must be a commit, not an unlink."""

    app, settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        _upload(client, token, "logo.png", png(2, 2))
        assert client.delete(
            "/api/ai/books/knowledge/assets/logo.png", headers=bearer(token)
        ).status_code == 200
    history = subprocess.run(
        ["git", "log", "--follow", "--format=%s", "--", "docs/assets/knowledge/logo.png"],
        cwd=settings.content_repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "Add asset: assets/knowledge/logo.png" in history
    assert "Delete asset: assets/knowledge/logo.png" in history


def test_deleting_a_book_deletes_its_assets_in_the_same_recoverable_commit(tmp_path):
    """Book-owned files must not remain published after their owner is deleted."""

    app, settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        _upload(client, token, "logo.png", png(2, 2))
        with Session(app.state.engine) as session:
            actor = session.exec(select(User).where(User.username == "admin")).one()
            deletion = app.state.content.delete_book("knowledge", actor)

    asset = settings.content_repo_path / "docs/assets/knowledge/logo.png"
    assert not asset.exists()
    history = subprocess.run(
        ["git", "show", "--format=%H", "--name-status", deletion],
        cwd=settings.content_repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "D\tdocs/assets/knowledge/logo.png" in history


def test_renaming_a_book_moves_assets_and_rewrites_relative_links(tmp_path):
    """Asset ownership and links must follow the book's new ACL namespace."""

    app, settings, token = _make_app(tmp_path)
    headers = bearer(token)
    with TestClient(app) as client:
        _seed_book(client, token)
        _upload(client, token, "logo.png", png(2, 2))
        assert client.post(
            "/api/ai/books/knowledge/pages",
            json={"title": "Overview", "markdown": "![Logo](../assets/knowledge/logo.png)"},
            headers=headers,
        ).status_code == 201
        assert client.post(
            "/api/ai/books/knowledge/pages",
            json={
                "title": "Details",
                "markdown": "![Logo](../assets/knowledge/logo.png)",
            },
            headers=headers,
        ).status_code == 201
        with Session(app.state.engine) as session:
            actor = session.exec(select(User).where(User.username == "admin")).one()
            app.state.content.rename_book("knowledge", "handbook", actor)

        assert client.get(
            "/assets/assets/handbook/logo.png", headers=headers
        ).status_code == 200
        assert client.get(
            "/assets/assets/knowledge/logo.png", headers=headers
        ).status_code == 404

    docs = settings.content_repo_path / "docs"
    assert not (docs / "assets/knowledge").exists()
    assert (docs / "assets/handbook/logo.png").is_file()
    assert "assets/handbook/logo.png" in (docs / "handbook/overview.md").read_text()
    assert "assets/handbook/logo.png" in (
        docs / "handbook/reference/details.md"
    ).read_text()


# --- Size limits --------------------------------------------------------------


def test_an_upload_over_the_declared_length_is_refused_before_the_body_is_read(tmp_path):
    """Measuring after the framework has spooled the body is measuring too late."""

    app, settings, token = _make_app(tmp_path, max_upload_bytes=4096)
    with TestClient(app) as client:
        _seed_book(client, token)
        oversized = png(2, 2) + b"\x00" * 40_000
        response = _upload(client, token, "huge.png", oversized)
        assert response.status_code == 413
        # Only the middleware's own refusal closes the connection, because only
        # it answers with the request stream still unread.  The route's later
        # belt-and-braces check would not set this, so the header is the
        # evidence that nothing buffered the body first.
        assert response.headers.get("connection") == "close"
        assert not (settings.content_repo_path / "docs" / "assets").exists()


def test_a_body_larger_than_it_declares_is_cut_off_part_way_through():
    """A client-supplied Content-Length is a claim, so the bytes are counted too."""

    pulled: list[int] = []

    async def drain(scope, receive, send):
        while True:
            message = await receive()
            pulled.append(len(message.get("body", b"")))
            if not message.get("more_body"):
                return

    limited = UploadSizeLimitMiddleware(drain, max_bytes=4096, overhead_bytes=0)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/ai/books/knowledge/assets",
        # Understates the body by three orders of magnitude.
        "headers": [(b"content-length", b"64")],
    }

    async def receive():
        return {"type": "http.request", "body": b"x" * 1024, "more_body": True}

    with pytest.raises(HTTPException) as raised:
        asyncio.run(limited(scope, receive, _noop_send))
    assert raised.value.status_code == 413
    # Four 1 KiB chunks fit the 4096-byte budget and were handed on; the fifth
    # crossed it and was never delivered.  Without the counter, this generator
    # never ends and the body grows without bound.
    assert pulled == [1024] * 4


def test_a_declared_oversize_body_never_reaches_the_application():
    """The cheapest rejection is the one that never lets the app see the request."""

    reached = False

    async def downstream(scope, receive, send):
        nonlocal reached
        reached = True

    limited = UploadSizeLimitMiddleware(downstream, max_bytes=4096, overhead_bytes=0)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/ai/books/knowledge/assets",
        "headers": [(b"content-length", b"5000000")],
    }
    sent: list[dict] = []

    async def receive():  # pragma: no cover - reading the body would be the bug
        raise AssertionError("the body must not be read")

    async def send(message):
        sent.append(message)

    asyncio.run(limited(scope, receive, send))
    assert reached is False
    assert sent[0]["status"] == 413


def test_the_limit_applies_only_to_upload_requests():
    """A body cap that quietly governed every route would shadow the documented ones."""

    seen: list[str] = []

    async def downstream(scope, receive, send):
        seen.append(scope["path"])

    limited = UploadSizeLimitMiddleware(downstream, max_bytes=1, overhead_bytes=0)
    for method, path in [("GET", "/api/ai/books/x/assets"), ("POST", "/api/ai/books/x/pages")]:
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(b"content-length", b"9999999")],
        }
        asyncio.run(limited(scope, _unused_receive, _noop_send))
    assert seen == ["/api/ai/books/x/assets", "/api/ai/books/x/pages"]


async def _unused_receive():  # pragma: no cover - never awaited by these scopes
    raise AssertionError("no body should be read")


async def _noop_send(message):  # pragma: no cover - nothing is sent in these scopes
    return None


# --- Markdown links, preview and the static build -----------------------------


def test_the_preview_url_for_a_markdown_link_resolves_to_the_serving_route(tmp_path):
    """One Markdown link has to work in the preview and in the build alike."""

    app, _settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        _upload(client, token, "logo.png", png(5, 5))
        # The link an author writes in docs/knowledge/notes.md, put through the
        # renderer that the live app uses.
        preview_url = rewrite_contextual_url("../assets/knowledge/logo.png", "knowledge/notes.md")
        assert preview_url == "/assets/assets/knowledge/logo.png"
        assert client.get(preview_url, headers=bearer(token)).status_code == 200


def test_an_uploaded_image_survives_a_strict_standalone_mkdocs_build(tmp_path):
    """The content repo must build into a working site with no app or database."""

    app, settings, token = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_book(client, token)
        assert _upload(client, token, "logo.png", png(8, 6)).status_code == 201
        assert client.post(
            "/api/ai/books/knowledge/pages",
            json={
                "title": "Overview",
                "markdown": "# Overview\n\n![Logo](../assets/knowledge/logo.png)\n",
            },
            headers=bearer(token),
        ).status_code == 201
        assert client.post(
            "/api/ai/books/knowledge/pages",
            json={
                "title": "Detail",
                "markdown": "# Detail\n\n![Logo](../assets/knowledge/logo.png)\n",
            },
            headers=bearer(token),
        ).status_code == 201

    build = subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "--strict"],
        cwd=settings.content_repo_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    site = settings.content_repo_path / "site"
    # The asset is copied verbatim, so a browser loads it straight from disk
    # without any application route in the way.
    assert (site / "assets" / "knowledge" / "logo.png").read_bytes() == png(8, 6)
    for page in (site / "knowledge" / "overview", site / "knowledge" / "reference" / "detail"):
        html = (page / "index.html").read_text(encoding="utf-8")
        source = html.split('<img alt="Logo" src="', 1)[1].split('"', 1)[0]
        # MkDocs rewrote the link for the page's own depth; following it from
        # that page's directory has to land on the copied file.
        assert (page / source).resolve() == (site / "assets" / "knowledge" / "logo.png").resolve()
