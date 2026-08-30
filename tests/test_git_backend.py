"""Git is the only revision history this project keeps, so its edges matter."""

import re
import stat
import subprocess
import traceback
from pathlib import Path

import pytest
from git import Repo
from sqlmodel import Session

from app.config import Settings
from app.content import ContentRepository
from app.git_backend import (
    GitAuthError,
    GitBackend,
    GitHostKeyError,
    GitNonFastForwardError,
    GitRemoteConfigError,
    GitSyncError,
    RemoteConfig,
    _push_refspec,
)
from app.models import User
from tests.conftest import bearer


def _repo(settings) -> Repo:
    return Repo(settings.content_repo_path)


def _admin_page(client, headers) -> str:
    client.post("/api/ai/books", json={"title": "Ops"}, headers=headers)
    client.post(
        "/api/ai/books/ops/pages",
        json={"title": "Runbook", "markdown": "original body"},
        headers=headers,
    )
    return "ops/runbook.md"


def test_unrelated_staged_content_is_not_swept_into_a_users_commit(client, app_env):
    """An operator's staged file must not be committed under another author."""

    app, settings, _admin, token = app_env
    headers = bearer(token)
    repo = _repo(settings)

    stray = Path(settings.content_repo_path) / "docs" / "operator-scratch.md"
    stray.write_text("operator work in progress\n", encoding="utf-8")
    repo.index.add(["docs/operator-scratch.md"])

    _admin_page(client, headers)

    head = repo.head.commit
    committed = [item.path for item in head.tree.traverse() if item.type == "blob"]
    assert "docs/operator-scratch.md" not in committed
    # Their file itself is untouched on disk; only the staging was dropped.
    assert stray.read_text(encoding="utf-8") == "operator work in progress\n"


def test_commit_leaves_the_index_consistent_with_head(client, app_env):
    app, settings, _admin, token = app_env
    _admin_page(client, bearer(token))
    repo = _repo(settings)
    assert not repo.is_dirty()


def test_history_follows_a_rename(client, app_env):
    """`git log --follow` is what keeps history across a slug rename."""

    app, settings, _admin, token = app_env
    headers = bearer(token)
    path = _admin_page(client, headers)
    repo = _repo(settings)

    repo.git.mv(f"docs/{path}", "docs/ops/renamed.md")
    repo.index.commit("Rename page")

    content = ContentRepository(settings)
    history = content.page_history("ops/renamed.md")
    messages = [revision.message for revision in history]
    assert "Rename page" in messages
    assert any("Create page" in message for message in messages), (
        "history stopped at the rename instead of following it"
    )


def test_deleted_page_keeps_its_history_and_can_be_restored(client, app_env):
    """Git standing in for a recycle bin only works if deletes stay reachable."""

    app, settings, admin, token = app_env
    headers = bearer(token)
    path = _admin_page(client, headers)
    repo = _repo(settings)
    content = ContentRepository(settings)

    original_sha = content.page_history(path)[0].sha
    repo.git.rm(f"docs/{path}")
    repo.index.commit("Delete page")
    assert not (Path(settings.content_repo_path) / "docs" / path).exists()

    history = content.page_history(path)
    assert any("Delete page" in revision.message for revision in history)

    with Session(app.state.engine) as session:
        actor = session.get(User, admin.id)
        content.restore_page(path, original_sha, actor)

    restored = Path(settings.content_repo_path) / "docs" / path
    assert restored.is_file()
    assert "original body" in restored.read_text(encoding="utf-8")


def test_history_for_a_page_that_never_existed_is_not_found(app_env):
    from app.content import ContentMissing

    _app, settings, _admin, _token = app_env
    content = ContentRepository(settings)
    with pytest.raises(ContentMissing):
        content.page_history("ops/never-written.md")


def test_diff_against_a_revision_predating_the_page_shows_a_creation(client, app_env):
    app, settings, _admin, token = app_env
    headers = bearer(token)
    path = _admin_page(client, headers)
    content = ContentRepository(settings)
    repo = _repo(settings)

    root = list(repo.iter_commits())[-1].hexsha
    head = repo.head.commit.hexsha
    diff = content.page_diff(path, root, head)
    assert "original body" in diff


def _sync_repositories(tmp_path: Path) -> tuple[Repo, Repo, GitBackend]:
    """Create a content checkout and a second checkout sharing a bare backup."""

    remote_path = tmp_path / "remote.git"
    Repo.init(remote_path, bare=True)
    local_path = tmp_path / "local"
    local = Repo.init(local_path, initial_branch="main")
    (local_path / "docs").mkdir()
    (local_path / "docs" / "index.md").write_text("# Initial\n", encoding="utf-8")
    local.index.add(["docs/index.md"])
    local.index.commit("Initial")
    local.create_remote("origin", remote_path.as_uri())
    backend = GitBackend(local_path, tmp_path / "content.lock")
    backend.push()
    peer_path = tmp_path / "peer"
    peer = Repo.clone_from(remote_path.as_uri(), peer_path, branch="main")
    return local, peer, backend


def test_push_and_guarded_fast_forward_use_the_content_backup(tmp_path: Path):
    local, peer, backend = _sync_repositories(tmp_path)
    peer_file = Path(peer.working_tree_dir) / "docs" / "from-peer.md"
    peer_file.write_text("peer update\n", encoding="utf-8")
    peer.index.add(["docs/from-peer.md"])
    peer.index.commit("Peer update")
    peer.remotes.origin.push("main:main")

    assert backend.fetch_and_fast_forward() is True
    assert (Path(local.working_tree_dir) / "docs" / "from-peer.md").is_file()
    assert backend.fetch_and_fast_forward() is False


def test_fast_forward_refuses_dirty_or_divergent_content_history(tmp_path: Path):
    local, peer, backend = _sync_repositories(tmp_path)
    local_file = Path(local.working_tree_dir) / "docs" / "local.md"
    local_file.write_text("uncommitted operator work\n", encoding="utf-8")
    with pytest.raises(GitSyncError, match="local changes"):
        backend.fetch_and_fast_forward()
    local_file.unlink()

    peer_file = Path(peer.working_tree_dir) / "docs" / "peer.md"
    peer_file.write_text("peer update\n", encoding="utf-8")
    peer.index.add(["docs/peer.md"])
    peer.index.commit("Peer update")
    peer.remotes.origin.push("main:main")
    local_file.write_text("local update\n", encoding="utf-8")
    local.index.add(["docs/local.md"])
    local.index.commit("Local update")

    with pytest.raises(GitNonFastForwardError, match="diverged"):
        backend.fetch_and_fast_forward()


# --- Remote and credential handling (T6.1) ---------------------------------
#
# The backup remote is always assumed to be a *private* repository: a
# `content/` backup is a complete, unfiltered copy of the wiki with no
# per-user ACL, so these tests configure it as private deliberately rather
# than incidentally.

# Shaped like a real classic GitHub PAT so the scrubbing tests exercise the
# same pattern a leaked token would match.  It is not a real credential.
FAKE_TOKEN = "ghp_0123456789abcdefghijklmnopqrstuvwxyzAB"
REMOTE_URL = "https://github.com/example/private-wiki.git"
SSH_REMOTE_URL = "ssh://git@github.com/example/private-wiki.git"


def _content_checkout(tmp_path: Path) -> tuple[Repo, GitBackend]:
    local_path = tmp_path / "local"
    local = Repo.init(local_path, initial_branch="main")
    (local_path / "docs").mkdir()
    (local_path / "docs" / "index.md").write_text("# Initial\n", encoding="utf-8")
    local.index.add(["docs/index.md"])
    local.index.commit("Initial")
    return local, GitBackend(local_path, tmp_path / "content.lock")


def _token_file(tmp_path: Path, token: str = FAKE_TOKEN) -> Path:
    path = tmp_path / "github_token"
    path.write_text(f"{token}\n", encoding="utf-8")
    return path


def _ssh_material(tmp_path: Path) -> tuple[Path, Path]:
    key = tmp_path / "deploy_key"
    key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nnot-a-key\n", encoding="utf-8")
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("github.com ssh-ed25519 AAAApinned\n", encoding="utf-8")
    return key, known_hosts


def _fake_ssh(directory: Path, stderr_lines: str) -> Path:
    """A stand-in for the ssh binary that always fails a chosen way.

    Real SSH authentication against github.com cannot be exercised offline, so
    the transport is replaced to drive the error-classification and scrubbing
    paths with the text OpenSSH and git actually emit.
    """

    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "ssh"
    script.write_text(
        f"#!/bin/sh\ncat >&2 <<'EOF'\n{stderr_lines}\nEOF\nexit 255\n", encoding="utf-8"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _credential_fill(repo: Repo, tmp_path: Path, host: str = "github.com") -> str:
    """Ask real git for this repository's credential for ``host``.

    Global and system config are neutralized so the answer can only come from
    the repo-local helper this code configured.
    """

    result = subprocess.run(
        ["git", "-C", str(repo.working_tree_dir), "credential", "fill"],
        input=f"protocol=https\nhost={host}\n\n",
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(tmp_path),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        },
    )
    return result.stdout


def test_configuring_origin_points_the_content_repo_at_the_settings_url(tmp_path: Path):
    local, backend = _content_checkout(tmp_path)

    backend.configure_remote(
        RemoteConfig(
            url=REMOTE_URL, confirmed_private=True, token_path=_token_file(tmp_path)
        )
    )
    assert local.remotes.origin.url == REMOTE_URL
    # `push`/`fetch` resolve `origin/<branch>`, so the fetch refspec has to be
    # there even for an `origin` an operator added by hand.
    assert local.git.config("--local", "--get", "remote.origin.fetch")

    # Re-running replaces rather than duplicating: startup runs this every time.
    moved = "https://github.com/example/moved-wiki.git"
    backend.configure_remote(
        RemoteConfig(url=moved, confirmed_private=True, token_path=_token_file(tmp_path))
    )
    assert local.remotes.origin.url == moved
    assert len(list(local.remotes)) == 1


def test_startup_configures_the_backup_remote_from_settings(tmp_path: Path):
    """`origin` must be right before anything tries to back content up."""

    settings = Settings(
        environment="test",
        content_repo_path=tmp_path / "content",
        db_path=tmp_path / "data" / "app.db",
        content_lock_path=tmp_path / "data" / "content.lock",
        api_token_secret="test-secret-that-is-long-and-random-enough",
        github_remote_url=REMOTE_URL,
        github_remote_confirmed_private=True,
        github_token_path=_token_file(tmp_path),
        _env_file=None,
    )
    content = ContentRepository(settings)
    content.initialize()
    repo = Repo(settings.content_repo_path)
    assert repo.remotes.origin.url == REMOTE_URL

    # Idempotent: startup runs on every boot, including for an existing repo.
    ContentRepository(settings).initialize()
    assert len(list(repo.remotes)) == 1
    assert FAKE_TOKEN not in (Path(repo.git_dir) / "config").read_text(encoding="utf-8")


def test_a_configured_token_never_reaches_the_url_config_or_remote_listing(tmp_path: Path):
    """`git remote -v`, the reflog, and error text must stay credential-free."""

    local, backend = _content_checkout(tmp_path)
    backend.configure_remote(
        RemoteConfig(
            url=REMOTE_URL, confirmed_private=True, token_path=_token_file(tmp_path)
        )
    )

    config = (Path(local.git_dir) / "config").read_text(encoding="utf-8")
    assert FAKE_TOKEN not in config
    assert FAKE_TOKEN not in local.git.remote("-v")
    assert local.remotes.origin.url == REMOTE_URL
    # The helper knows only the path it reads the secret from.
    helper = Path(local.git_dir) / "unstacked-credential-helper"
    assert FAKE_TOKEN not in helper.read_text(encoding="utf-8")
    assert helper.stat().st_mode & 0o077 == 0


def test_git_obtains_the_token_from_the_repo_local_credential_helper(tmp_path: Path):
    """End-to-end through real git: the helper mechanism is actually wired up."""

    local, backend = _content_checkout(tmp_path)
    backend.configure_remote(
        RemoteConfig(
            url=REMOTE_URL, confirmed_private=True, token_path=_token_file(tmp_path)
        )
    )

    filled = _credential_fill(local, tmp_path)
    assert "username=x-access-token" in filled
    assert f"password={FAKE_TOKEN}" in filled


def test_the_credential_helper_is_scoped_to_the_configured_host(tmp_path: Path):
    """A token for the backup must not be offered to some other HTTPS host."""

    local, backend = _content_checkout(tmp_path)
    backend.configure_remote(
        RemoteConfig(
            url=REMOTE_URL, confirmed_private=True, token_path=_token_file(tmp_path)
        )
    )

    config = (Path(local.git_dir) / "config").read_text(encoding="utf-8")
    assert '[credential "https://github.com"]' in config
    # The unscoped entry is the empty reset that drops any helper inherited
    # from the host's global config, not a catch-all that would answer for
    # every host.
    assert re.search(r"\[credential\]\n\thelper = *\n", config)
    assert "password=" not in _credential_fill(local, tmp_path, host="evil.example.com")


def test_an_inline_token_is_handed_over_without_being_written_to_disk(tmp_path, monkeypatch):
    """The env fallback must not make us persist a credential ourselves."""

    # Registered with monkeypatch first so the value configure_remote exports
    # is restored at teardown.
    monkeypatch.setenv("UNSTACKED_GITHUB_TOKEN", "placeholder")
    local, backend = _content_checkout(tmp_path)
    backend.configure_remote(
        RemoteConfig(url=REMOTE_URL, confirmed_private=True, token=FAKE_TOKEN)
    )

    helper = Path(local.git_dir) / "unstacked-credential-helper"
    assert FAKE_TOKEN not in helper.read_text(encoding="utf-8")
    assert FAKE_TOKEN not in (Path(local.git_dir) / "config").read_text(encoding="utf-8")

    result = subprocess.run(
        ["git", "-C", str(local.working_tree_dir), "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(tmp_path),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "UNSTACKED_GITHUB_TOKEN": FAKE_TOKEN,
        },
    )
    assert f"password={FAKE_TOKEN}" in result.stdout


def test_a_configured_remote_still_pushes_and_fast_forwards(tmp_path: Path):
    """Configuration must leave the ordinary backup path working."""

    remote_path = tmp_path / "remote.git"
    Repo.init(remote_path, bare=True)
    local, backend = _content_checkout(tmp_path)
    backend.configure_remote(
        RemoteConfig(url=remote_path.as_uri(), confirmed_private=True)
    )
    backend.push()

    peer = Repo.clone_from(remote_path.as_uri(), tmp_path / "peer", branch="main")
    peer_file = Path(peer.working_tree_dir) / "docs" / "from-peer.md"
    peer_file.write_text("peer update\n", encoding="utf-8")
    peer.index.add(["docs/from-peer.md"])
    peer.index.commit("Peer update")
    peer.remotes.origin.push("main:main")

    assert backend.fetch_and_fast_forward() is True
    assert (Path(local.working_tree_dir) / "docs" / "from-peer.md").is_file()


def test_remote_probe_verifies_write_access_without_updating_the_remote(tmp_path: Path):
    remote_path = tmp_path / "remote.git"
    remote = Repo.init(remote_path, bare=True)
    _local, backend = _content_checkout(tmp_path)
    backend.configure_remote(
        RemoteConfig(url=remote_path.as_uri(), confirmed_private=True)
    )

    backend.test_remote()

    assert not list(remote.references)


def test_remote_configuration_defers_visibility_policy_to_the_settings_layer(tmp_path: Path):
    """The Git helper has no ACL database and therefore accepts the supplied policy."""
    local, backend = _content_checkout(tmp_path)
    backend.configure_remote(RemoteConfig(url=REMOTE_URL, token_path=_token_file(tmp_path)))
    assert local.remotes.origin.url == REMOTE_URL


def test_no_configured_remote_leaves_an_operators_own_origin_alone(tmp_path: Path):
    local, backend = _content_checkout(tmp_path)
    local.create_remote("origin", "https://github.com/example/hand-wired.git")
    backend.configure_remote(RemoteConfig())
    assert local.remotes.origin.url == "https://github.com/example/hand-wired.git"


@pytest.mark.parametrize(
    ("url", "message"),
    [
        # Embedding auth in the URL is exactly what this task exists to avoid:
        # it leaks into `git remote -v`, the reflog, and error text.
        ("https://x-access-token:ghp_leaked@github.com/example/wiki.git", "must not embed"),
        # A PAT over cleartext http would be readable on the wire.
        ("http://github.com/example/wiki.git", "https, ssh, or a local file"),
        ("git://github.com/example/wiki.git", "https, ssh, or a local file"),
        # Would be read as an option, not a location, by `git remote set-url`.
        ("--upload-pack=evil", "not a valid location"),
        ("   ", "is empty"),
    ],
)
def test_unsafe_remote_urls_are_refused_without_being_echoed(
    tmp_path: Path, url: str, message: str
):
    _local, backend = _content_checkout(tmp_path)
    with pytest.raises(GitRemoteConfigError, match=message) as raised:
        backend.configure_remote(
            RemoteConfig(url=url, confirmed_private=True, token_path=_token_file(tmp_path))
        )
    assert "ghp_leaked" not in str(raised.value)


def test_ssh_pins_the_host_key_and_offers_only_the_deploy_key(tmp_path: Path):
    """Trusting the host's global known_hosts is what pinning replaces."""

    local, backend = _content_checkout(tmp_path)
    key, known_hosts = _ssh_material(tmp_path)
    backend.configure_remote(
        RemoteConfig(
            url=SSH_REMOTE_URL,
            confirmed_private=True,
            ssh_key_path=key,
            ssh_known_hosts_path=known_hosts,
        )
    )

    command = local.git.config("--local", "--get", "core.sshCommand")
    assert "StrictHostKeyChecking=yes" in command
    assert f"UserKnownHostsFile={known_hosts}" in command
    assert "GlobalKnownHostsFile=/dev/null" in command
    assert "IdentitiesOnly=yes" in command
    assert "BatchMode=yes" in command
    assert str(key) in command


def test_switching_transports_clears_the_previous_credential_configuration(tmp_path: Path):
    """A stale helper would keep offering a token that should be out of use."""

    local, backend = _content_checkout(tmp_path)
    backend.configure_remote(
        RemoteConfig(
            url=REMOTE_URL, confirmed_private=True, token_path=_token_file(tmp_path)
        )
    )
    key, known_hosts = _ssh_material(tmp_path)
    backend.configure_remote(
        RemoteConfig(
            url=SSH_REMOTE_URL,
            confirmed_private=True,
            ssh_key_path=key,
            ssh_known_hosts_path=known_hosts,
        )
    )

    config = (Path(local.git_dir) / "config").read_text(encoding="utf-8")
    assert "credential" not in config


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ssh_known_hosts_path": None}, "pinned known_hosts"),
        ({"ssh_key_path": None}, "deploy key file"),
    ],
)
def test_ssh_without_a_key_or_a_pinned_host_is_refused(
    tmp_path: Path, overrides: dict, message: str
):
    _local, backend = _content_checkout(tmp_path)
    key, known_hosts = _ssh_material(tmp_path)
    fields = {"ssh_key_path": key, "ssh_known_hosts_path": known_hosts}
    fields.update(overrides)
    with pytest.raises(GitRemoteConfigError, match=message):
        backend.configure_remote(
            RemoteConfig(url=SSH_REMOTE_URL, confirmed_private=True, **fields)
        )


def test_a_missing_token_file_is_a_configuration_error_not_an_auth_error(tmp_path: Path):
    _local, backend = _content_checkout(tmp_path)
    with pytest.raises(GitRemoteConfigError, match="token file is missing"):
        backend.configure_remote(
            RemoteConfig(
                url=REMOTE_URL,
                confirmed_private=True,
                token_path=tmp_path / "never-written",
            )
        )


def test_a_multiline_token_cannot_inject_extra_credential_fields(tmp_path: Path):
    """The credential protocol is line-oriented, so whitespace is unsafe."""

    _local, backend = _content_checkout(tmp_path)
    path = tmp_path / "github_token"
    path.write_text(f"{FAKE_TOKEN}\nusername=attacker\n", encoding="utf-8")
    with pytest.raises(GitRemoteConfigError, match="single line") as raised:
        backend.configure_remote(
            RemoteConfig(url=REMOTE_URL, confirmed_private=True, token_path=path)
        )
    assert FAKE_TOKEN not in str(raised.value)


def _ssh_backed_repo(tmp_path: Path, fake_ssh: Path) -> GitBackend:
    local, backend = _content_checkout(tmp_path)
    key, known_hosts = _ssh_material(tmp_path)
    backend.configure_remote(
        RemoteConfig(
            url=SSH_REMOTE_URL,
            confirmed_private=True,
            ssh_key_path=key,
            ssh_known_hosts_path=known_hosts,
        )
    )
    # Stand in for the real ssh binary, which cannot reach github.com here.
    local.git.config("--local", "--replace-all", "core.sshCommand", str(fake_ssh))
    return backend


def _diverged_push(tmp_path: Path) -> None:
    """Push a branch the shared backup has already moved past."""

    local, peer, backend = _sync_repositories(tmp_path)
    peer_file = Path(peer.working_tree_dir) / "docs" / "peer.md"
    peer_file.write_text("peer update\n", encoding="utf-8")
    peer.index.add(["docs/peer.md"])
    peer.index.commit("Peer update")
    peer.remotes.origin.push("main:main")

    local_file = Path(local.working_tree_dir) / "docs" / "local.md"
    local_file.write_text("local update\n", encoding="utf-8")
    local.index.add(["docs/local.md"])
    local.index.commit("Local update")
    backend.push()


def test_auth_and_non_fast_forward_failures_are_distinguishable(tmp_path: Path):
    """A rejected credential and a diverged history need different responses.

    One is fixed by rotating a token or re-adding a deploy key; the other can
    only be fixed by an operator reconciling two histories.  Collapsing them
    into one error would send the push worker retrying forever on the wrong
    thing.
    """

    denied = _fake_ssh(
        tmp_path / "auth",
        "git@github.com: Permission denied (publickey).\n"
        "fatal: Could not read from remote repository.",
    )
    backend = _ssh_backed_repo(tmp_path / "auth-repo", denied)
    with pytest.raises(GitAuthError) as auth_failure:
        backend.fetch_and_fast_forward()

    with pytest.raises(GitNonFastForwardError) as stale:
        _diverged_push(tmp_path / "diverged")

    # Both stay GitSyncError, so existing callers keep working, but neither is
    # ever mistaken for the other.
    assert isinstance(auth_failure.value, GitSyncError)
    assert not isinstance(auth_failure.value, GitNonFastForwardError)
    assert not isinstance(stale.value, GitAuthError)


def test_a_mismatched_host_key_is_reported_as_its_own_failure(tmp_path: Path):
    """Pinning is pointless if a changed host key looks like a bad password."""

    fake = _fake_ssh(
        tmp_path / "hostkey",
        "@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @@@\n"
        "Host key verification failed.",
    )
    backend = _ssh_backed_repo(tmp_path / "hostkey-repo", fake)
    with pytest.raises(GitHostKeyError, match="pinned known_hosts"):
        backend.fetch_and_fast_forward()


def test_a_leaky_transport_cannot_surface_credential_material(tmp_path: Path):
    """Even a transport that echoes the secret must not reach an operator."""

    fake = _fake_ssh(
        tmp_path / "leak",
        f"remote: Invalid credentials: {FAKE_TOKEN}\n"
        f"Authorization: Bearer {FAKE_TOKEN}\n"
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "b3BlbnNzaC1rZXktdjEAAAAA-secret-key-material\n"
        "-----END OPENSSH PRIVATE KEY-----\n"
        f"fatal: Authentication failed for "
        f"'https://x-access-token:{FAKE_TOKEN}@github.com/example/private-wiki.git/'",
    )
    backend = _ssh_backed_repo(tmp_path / "leak-repo", fake)

    with pytest.raises(GitSyncError) as raised:
        backend.fetch_and_fast_forward()

    rendered = "".join(
        traceback.format_exception(type(raised.value), raised.value, raised.value.__traceback__)
    )
    for surface in (str(raised.value), repr(raised.value), rendered):
        assert FAKE_TOKEN not in surface
        assert "secret-key-material" not in surface
        assert "x-access-token:" not in surface
    # Still useful: the operator learns what to fix.
    assert "credential" in str(raised.value)


def test_no_code_path_can_force_push():
    """A force-push would destroy backed-up revisions permanently."""

    app_dir = Path(__file__).resolve().parent.parent / "app"
    # A `+` on a refspec whose destination is a *remote branch* is a force
    # push; the one on `refs/remotes/origin/*` only updates a local
    # remote-tracking ref and is git's own default.
    forbidden = re.compile(
        r"--force|force[-_]?with[-_]?lease|force\s*=\s*True|\+refs/heads/\S*:refs/heads/"
    )
    for source in sorted(app_dir.rglob("*.py")):
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            assert not forbidden.search(line), f"{source.name}:{number} can force-push"

    # Exactly one real push and one non-mutating configuration probe exist;
    # both refspecs come from _push_refspec rather than a caller who could
    # supply a forcing one.
    pushes = [
        line.strip()
        for source in app_dir.rglob("*.py")
        for line in source.read_text(encoding="utf-8").splitlines()
        if ".push(" in line
    ]
    assert len(pushes) == 2
    assert any("--dry-run" in push and "_push_refspec(branch.name)" in push for push in pushes)
    assert any("refspec=_push_refspec(branch.name)" in push for push in pushes)
    assert "force" not in pushes[0]

    assert _push_refspec("main") == "main:main"
    for smuggled in ("+main", "main:refs/heads/other"):
        with pytest.raises(GitSyncError, match="unsafe branch name"):
            _push_refspec(smuggled)
