"""GitHub Pages publication pushes only the built site, fast-forward only."""

from pathlib import Path

import pytest
from git import Repo

from app import backup_config, pages_publish
from app.config import Settings
from tests.conftest import bearer


def _settings(tmp_path: Path) -> Settings:
    settings = Settings(
        environment="test",
        backup_config_path=tmp_path / "data" / "backup_config.json",
        api_token_secret="test-secret-that-is-long-and-random-enough",
    )
    # A local bare remote never invokes ssh, but publication still insists on
    # a key and pinned host file existing, as it would for a real target.
    backup_config.write_private_bytes(pages_publish.deploy_key_path(settings), b"key")
    backup_config.write_private_bytes(pages_publish.known_hosts_path(settings), b"host key\n")
    return settings


def _site(tmp_path: Path, body: str) -> Path:
    site = tmp_path / "site"
    site.mkdir(exist_ok=True)
    (site / "index.html").write_text(body, encoding="utf-8")
    (site / "_static").mkdir(exist_ok=True)
    (site / "_static" / "app.css").write_text("body{}", encoding="utf-8")
    return site


def test_publish_pushes_site_then_fast_forwards_without_force(tmp_path: Path):
    settings = _settings(tmp_path)
    remote = tmp_path / "pages.git"
    Repo.init(remote, bare=True)
    target = pages_publish.PagesTarget(
        url=str(remote),
        branch="gh-pages",
        ssh_host_fingerprint="SHA256:x",
        cname="docs.example.com",
    )

    assert pages_publish.publish(settings, target, _site(tmp_path, "v1")) is True
    tree = Repo(remote).commit("gh-pages").tree
    assert {"index.html", ".nojekyll", "CNAME", "_static"} <= {item.name for item in tree}
    assert (tree / "CNAME").data_stream.read() == b"docs.example.com\n"

    # Nothing changed: no empty commit.
    assert pages_publish.publish(settings, target, _site(tmp_path, "v1")) is False

    # Someone else pushed to the branch: the next publish builds on top of it.
    other = Repo.clone_from(remote, tmp_path / "other", branch="gh-pages")
    (Path(other.working_dir) / "extra.txt").write_text("x", encoding="utf-8")
    other.index.add(["extra.txt"])
    other.index.commit("external")
    other.remote().push("gh-pages")

    assert pages_publish.publish(settings, target, _site(tmp_path, "v2")) is True
    head = Repo(remote).commit("gh-pages")
    assert head.parents[0].message.strip() == "external"
    assert (head.tree / "index.html").data_stream.read() == b"v2"
    assert "extra.txt" not in {item.name for item in head.tree}


def test_publish_requires_a_deploy_key(tmp_path: Path):
    settings = _settings(tmp_path)
    pages_publish.deploy_key_path(settings).unlink()
    target = pages_publish.PagesTarget(url="x", branch="gh-pages", ssh_host_fingerprint="x")
    with pytest.raises(pages_publish.PagesPublishError, match="deploy key"):
        pages_publish.publish(settings, target, _site(tmp_path, "v1"))


@pytest.mark.parametrize(
    ("url", "branch", "cname"),
    [
        ("https://github.com/org/repo.git", "gh-pages", None),
        ("git@github.com:org/repo.git", "-bad", None),
        ("git@github.com:org/repo.git", "gh-pages", "https://docs.example.com"),
    ],
)
def test_validate_rejects_bad_input(url, branch, cname):
    with pytest.raises(ValueError):
        pages_publish.validate(url, branch, cname)


def test_pages_api_generates_own_key_and_requires_fingerprint(app_env, client, monkeypatch):
    _app, settings, _admin, token = app_env
    status = client.get("/api/admin/public-site/pages", headers=bearer(token)).json()
    assert status["configured"] is False and status["public_key"] is None

    created = client.post(
        "/api/admin/public-site/pages/deploy-key", json={}, headers=bearer(token)
    )
    assert created.status_code == 200, created.text
    assert created.json()["public_key"].endswith("unstacked-pages")
    assert "PRIVATE KEY" not in created.text
    assert not backup_config.managed_deploy_key_path(settings).exists()

    monkeypatch.setattr(
        backup_config,
        "discover_ssh_host_key",
        lambda _url: backup_config.SshHostKey("SHA256:real", "github.com ssh-ed25519 AAAA\n"),
    )
    payload = {"url": "git@github.com:org/org.github.io.git", "ssh_host_fingerprint": "SHA256:x"}
    rejected = client.put("/api/admin/public-site/pages", json=payload, headers=bearer(token))
    assert rejected.status_code == 409

    monkeypatch.setattr(pages_publish, "test_access", lambda _settings, _url: None)
    payload["ssh_host_fingerprint"] = "SHA256:real"
    saved = client.put("/api/admin/public-site/pages", json=payload, headers=bearer(token))
    assert saved.status_code == 200, saved.text
    assert saved.json()["configured"] is True
    assert saved.json()["branch"] == "gh-pages"

    cleared = client.delete("/api/admin/public-site/pages", headers=bearer(token))
    assert cleared.json()["configured"] is False
