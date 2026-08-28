import difflib
import os
import re
import shlex
import stat
import tempfile
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from filelock import FileLock, Timeout
from git import Actor, BadName, GitCommandError, RemoteProgress, Repo

SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")

# ASCII unit/record separators cannot appear in a commit trailer, so parsing
# stays unambiguous even for multi-line messages.
_FIELD_SEPARATOR = "\x1f"
_RECORD_SEPARATOR = "\x1e"
_LOG_FORMAT = _FIELD_SEPARATOR.join(["%H", "%an", "%ae", "%aI", "%B"]) + _RECORD_SEPARATOR


class RevisionNotFound(RuntimeError):
    """Raised when a revision or its version of a path cannot be found."""


class GitWriteLockTimeout(RuntimeError):
    """A content write could not acquire the repository lock in time."""


class GitSyncError(RuntimeError):
    """A safe, operator-actionable Git remote synchronization failure."""


class GitRemoteConfigError(GitSyncError):
    """The backup remote or its credential is missing or unusable.

    Distinct from an authentication failure: nothing was attempted over the
    network, so the fix is a configuration change, not a new credential.
    """


class GitAuthError(GitSyncError):
    """The backup remote refused the configured credential.

    Separate from :class:`GitNonFastForwardError` so an operator (and the
    background push worker) can tell "rotate the token / re-add the deploy
    key" apart from "the histories disagree", which no credential can fix.
    """


class GitHostKeyError(GitSyncError):
    """The SSH host key did not match the pinned ``known_hosts`` entry.

    Never retried and never auto-accepted: an unexpected host key is what a
    machine-in-the-middle looks like, so the deploy key is not offered.
    """


class GitNonFastForwardError(GitSyncError):
    """Local and remote content histories disagree.

    Always reported, never resolved by this code: the only ways out are a
    fast-forward or an operator's explicit reconciliation.  A force-push would
    destroy backed-up revisions, which are the only revision history this
    project keeps.
    """


# GitHub token shapes, an ``Authorization`` header, a URL with embedded
# userinfo, and PEM private keys — the forms credential material takes when a
# transport echoes something back at us.  Our own configuration never puts a
# credential anywhere git can print it; this is the second layer, for
# transports and helpers we do not control.
_SCRUB_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(://)[^/\s@]+@"), r"\1***@"),
    (re.compile(r"\b(gh[pousr]_|github_pat_)[A-Za-z0-9_]+"), "***"),
    (re.compile(r"(?i)(authorization\s*:\s*)\S+"), r"\1***"),
    (re.compile(r"(?i)\b(password|token|secret)\s*[=:]\s*\S+"), r"\1=***"),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "***",
    ),
)

_HOST_KEY_MARKERS = (
    "host key verification failed",
    "no matching host key",
    "remote host identification has changed",
)
_AUTH_MARKERS = (
    "authentication failed",
    "could not read username",
    "could not read password",
    "terminal prompts disabled",
    "permission denied (publickey",
    "invalid username or password",
    "403 forbidden",
    "401 unauthorized",
    "repository not found",
    "access denied",
)
_NON_FAST_FORWARD_MARKERS = (
    "non-fast-forward",
    "fetch first",
    "updates were rejected",
    "cannot lock ref",
)

# Only ever spoken to over an encrypted or local transport.  Plain ``http://``
# is refused because it would put a bearer token on the wire in clear text,
# and ``git://`` because it is unauthenticated.
_ALLOWED_URL_SCHEMES = ("https", "ssh", "file")
_SCP_LIKE_URL = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[A-Za-z0-9._~/-]+$")

# GitHub accepts any username alongside a PAT; this is the conventional one.
_TOKEN_USERNAME = "x-access-token"
_TOKEN_ENV_VAR = "UNSTACKED_GITHUB_TOKEN"
_CREDENTIAL_HELPER_NAME = "unstacked-credential-helper"


@dataclass(frozen=True)
class RemoteConfig:
    """Operator-supplied description of the content backup remote.

    ``token`` is excluded from the generated ``repr`` so a settings dump, a
    log line, or a traceback frame cannot render it.  Prefer ``token_path``:
    with a path, the secret is read by the credential helper at the moment git
    asks for it and never enters this process at all after validation.
    """

    url: str | None = None
    confirmed_private: bool = False
    token: str | None = field(default=None, repr=False)
    token_path: Path | None = None
    ssh_key_path: Path | None = None
    ssh_known_hosts_path: Path | None = None


@dataclass(frozen=True)
class Revision:
    sha: str
    message: str
    author_name: str
    author_email: str
    authored_at: str


class GitBackend:
    def __init__(self, repo_path: Path, lock_path: Path, *, lock_timeout_seconds: float = 15.0):
        self.repo_path = repo_path.resolve()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(lock_path, timeout=lock_timeout_seconds)

    @contextmanager
    def write_lock(self):
        """Acquire the single repository mutation lock with a finite wait.

        The lock is deliberately shared by all app processes pointing at this
        content checkout, not merely by one FastAPI process.  FileLock is
        re-entrant for this backend instance, so callers can safely compose a
        high-level mutation with ``commit_paths``.
        """

        try:
            with self.lock:
                yield
        except Timeout as exc:
            raise GitWriteLockTimeout("content repository is busy; retry the request") from exc

    @property
    def repo(self) -> Repo:
        repo = Repo(self.repo_path)
        # The app is headless, so a missing or rejected credential must fail
        # immediately rather than block a request thread on git's interactive
        # username prompt forever.
        repo.git.update_environment(GIT_TERMINAL_PROMPT="0")
        return repo

    def configure_remote(self, config: RemoteConfig) -> None:
        """Point ``origin`` at the configured backup and wire up its credential.

        Called once at startup (see ``ContentRepository.initialize``) so that
        ``push`` and ``fetch_and_fast_forward`` stay credential-unaware: by the
        time they run, ``origin`` either exists and is authenticated or the app
        never finished starting.

        The credential never enters the remote URL, a git config value, or a
        process argument.  HTTPS uses a repo-local credential helper that reads
        the operator's secret at the moment git asks for it; SSH uses a
        repo-local ``core.sshCommand`` naming the deploy key file and a pinned
        ``known_hosts``.  ``git remote -v``, the reflog, and any error text git
        produces therefore carry the bare URL and nothing else.

        The remote must be a **private** repository for MVP.  A ``content/``
        backup is a complete, unfiltered copy of the wiki, drafts included,
        with no per-user ACL — the same caveat the static export carries — so a
        public remote would publish every page to everyone.  Confirming that
        needs a network call this code deliberately does not make, so the
        operator affirms it with ``UNSTACKED_GITHUB_REMOTE_CONFIRMED_PRIVATE``
        and configuration is refused without the affirmation.

        Idempotent: re-running replaces the previous remote URL and clears
        credential configuration left over from a different transport.
        """

        if not config.url:
            # No backup configured.  An operator may still have wired `origin`
            # up by hand, so nothing existing is touched or removed.
            return
        url = _validated_remote_url(config.url)
        if not config.confirmed_private:
            raise GitRemoteConfigError(
                "content backup remote must be confirmed private before it is configured"
            )
        with self.lock:
            repo = self.repo
            self._set_origin(repo, url)
            self._clear_remote_auth_config(repo)
            transport = _transport(url)
            if transport == "https":
                self._configure_token_credential(repo, url, config)
            elif transport == "ssh":
                self._configure_ssh_credential(repo, config)
            # A `file://` backup needs no credential: it is reachable only by a
            # process that already has filesystem access to it.

    def commit_paths(self, paths: list[Path], *, name: str, email: str, message: str) -> str:
        """Commit exactly ``paths`` on top of HEAD, present or already removed.

        The index is reset to HEAD first, so content an operator (or a crashed
        earlier operation) left staged cannot be swept into this commit and
        misattributed to ``name``.  Only staging is discarded; working-tree
        files are never modified.

        Callers declare every path a logical operation touched, including the
        source half of a rename and the pages of a deleted book.  Both halves
        of a rename therefore land in one commit, which is what lets Git's own
        similarity detection — and so ``git log --follow`` — carry a page's
        history across a slug change.
        """

        with self.write_lock():
            relative = [self._relative_path(path) for path in paths]
            repo = self.repo
            # A failed add/commit must put the index back byte-for-byte.  A
            # reset-to-HEAD would silently erase an operator's staged work.
            index_snapshot = self._snapshot_index()
            if repo.head.is_valid():
                # Discard anything else that was staged before adding our paths.
                # Working-tree files are untouched, so an operator's edits survive;
                # only their staging is dropped, which is far better than silently
                # committing their work under this user's name.
                repo.index.reset(repo.head.commit)
            present, removed = [], []
            for item in relative:
                (present if (self.repo_path / item).exists() else removed).append(item)
            try:
                if removed and repo.head.is_valid():
                    # `git add` raises on a path that is gone, so a deletion has to
                    # be staged explicitly.  ``--cached`` only: the working tree is
                    # already in its post-operation state and must not be touched.
                    # ``--ignore-unmatch`` keeps a declared-but-untracked path (an
                    # operator's scratch file inside a deleted book) from failing
                    # the whole operation; it was never in history to remove.
                    repo.index.remove(removed, r=True, ignore_unmatch=True)
                if present:
                    repo.index.add(present)
                actor = Actor(name, email)
                commit = repo.index.commit(message, author=actor, committer=actor)
                return commit.hexsha
            except Exception:
                self._restore_index(index_snapshot)
                raise

    def blob_sha(self, path: Path | str) -> str:
        """Return the current HEAD blob SHA for one tracked content file."""

        relative = self._relative_path(path)
        repo = self.repo
        if not repo.head.is_valid():
            raise RevisionNotFound("content repository has no commits")
        try:
            blob = repo.head.commit.tree / relative
        except KeyError as exc:
            raise RevisionNotFound("revision does not contain path") from exc
        if blob.type != "blob":
            raise RevisionNotFound("revision path is not a file")
        return blob.hexsha

    def log(self, path: Path | str) -> list[Revision]:
        """Revisions touching ``path``, newest first, following renames.

        Uses ``git log --follow`` rather than ``rev-list`` because only the
        former can trace a page across a slug rename, and git history is the
        only revision history this project keeps.
        """

        relative = self._relative_path(path)
        repo = self.repo
        if not repo.head.is_valid():
            return []
        raw = repo.git.log(
            "--follow",
            f"--format={_LOG_FORMAT}",
            "--",
            relative,
        )
        revisions = []
        for record in raw.split(_RECORD_SEPARATOR):
            record = record.strip("\n")
            if not record:
                continue
            sha, author_name, author_email, authored_at, message = record.split(
                _FIELD_SEPARATOR
            )
            revisions.append(
                Revision(
                    sha=sha,
                    message=message.rstrip("\n"),
                    author_name=author_name,
                    author_email=author_email,
                    authored_at=authored_at,
                )
            )
        return revisions

    def diff(self, sha_a: str, sha_b: str, path: Path | str) -> str:
        relative = self._relative_path(path)
        before = self._show_or_empty(sha_a, relative)
        after = self._show_or_empty(sha_b, relative)
        if before is None and after is None:
            raise RevisionNotFound("revision does not contain path")
        return "".join(
            difflib.unified_diff(
                (before or "").splitlines(keepends=True),
                (after or "").splitlines(keepends=True),
                fromfile=f"{sha_a}:{relative}" if before is not None else "/dev/null",
                tofile=f"{sha_b}:{relative}" if after is not None else "/dev/null",
            )
        )

    def show(self, sha: str, path: Path | str) -> str:
        relative = self._relative_path(path)
        commit = self._commit(sha)
        try:
            blob = commit.tree / relative
        except KeyError as exc:
            raise RevisionNotFound("revision does not contain path") from exc
        if blob.type != "blob":
            raise RevisionNotFound("revision path is not a file")
        try:
            return blob.data_stream.read().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RevisionNotFound("revision path is not a UTF-8 text file") from exc

    def restore_as_new_commit(
        self,
        path: Path,
        revision: str,
        *,
        name: str,
        email: str,
        message: str,
    ) -> str:
        """Restore one tracked file without rewriting history or staging other paths.

        A page deleted in an earlier commit is recreated, which is what stands
        in for a recycle bin here.
        """

        relative = self._relative_path(path)
        restored = self.show(revision, relative)
        existed = path.exists()
        original = path.read_bytes() if existed else None
        created_parents = not path.parent.exists()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(path, restored)
            return self.commit_paths([path], name=name, email=email, message=message)
        except Exception:
            if existed:
                assert original is not None
                self._atomic_write_bytes(path, original)
            else:
                path.unlink(missing_ok=True)
                if created_parents:
                    self._remove_empty_parents(path.parent)
            raise

    def push(self) -> None:
        """Push the current branch to ``origin`` without exposing remote details.

        Content commits remain local and usable if a backup is unavailable;
        callers can retry this operation.  GitPython receives the refspec as a
        single argument, never through a shell.

        This is the only push in the codebase and it is never a force-push: no
        force flag is passed and ``_push_refspec`` cannot produce the leading
        ``+`` git reads as one.  A backup that has diverged is reported, never
        overwritten — those commits are the only revision history this project
        keeps.
        """

        with self.lock:
            repo = self.repo
            self._push_locked(repo)

    def pending_backup_count(self) -> int:
        """Return locally committed revisions not represented by known upstream refs.

        This is intentionally a refs-only check: it has no network side effect
        and therefore remains useful after a restart or an offline period.  If
        this checkout has never pushed, every local commit is pending.
        """

        with self.lock:
            return self._pending_backup_count_locked(self.repo)

    def push_pending(self) -> int:
        """Push local pending commits, if any, under one repository lock.

        The count is derived from refs rather than an in-memory queue, so a
        process crash cannot lose the fact that a content commit needs backup.
        """

        with self.lock:
            repo = self.repo
            pending = self._pending_backup_count_locked(repo)
            if pending:
                self._push_locked(repo)
            return pending

    def _push_locked(self, repo: Repo) -> None:
        """Push while the caller owns ``self.lock``; never force-push."""

        branch = self._active_branch(repo)
        remote = self._origin(repo)
        # GitPython keeps only `error:`/`fatal:` lines in the exception it
        # raises, which drops exactly the lines that say *why* a transport
        # failed ("Permission denied (publickey)", "Host key verification
        # failed").  The progress object retains them, so classification
        # can see the real cause.
        progress = RemoteProgress()
        try:
            results = remote.push(refspec=_push_refspec(branch.name), progress=progress)
        except GitCommandError as exc:
            raise _sync_error(exc, "unable to push content backup", progress.other_lines) from None
        failures = [result for result in results if result.flags & result.ERROR]
        if failures:
            # `git push` reports a stale branch as a rejection rather than a
            # process failure, so it is classified here instead.
            rejected = any(
                result.flags & (result.REJECTED | result.REMOTE_REJECTED) for result in failures
            )
            if rejected:
                raise GitNonFastForwardError(
                    "content backup rejected the push as non-fast-forward"
                )
            raise GitSyncError("content backup rejected the push")

    def _pending_backup_count_locked(self, repo: Repo) -> int:
        branch = self._active_branch(repo)
        remote = self._origin(repo)
        try:
            upstream = repo.commit(f"{remote.name}/{branch.name}")
        except (BadName, ValueError):
            # No remote-tracking ref exists until the first successful push.
            return sum(1 for _commit in repo.iter_commits(branch.name))
        return int(repo.git.rev_list("--count", f"{upstream.hexsha}..{branch.name}"))

    def fetch_and_fast_forward(self) -> bool:
        """Fast-forward the current branch from ``origin`` when it is clean.

        Refusing dirty repositories and non-fast-forward histories prevents a
        remote backup from silently overwriting operator work or content that
        was edited independently on another checkout.
        """

        with self.lock:
            repo = self.repo
            if repo.is_dirty(untracked_files=True):
                raise GitSyncError("cannot synchronize a content repository with local changes")
            branch = self._active_branch(repo)
            remote = self._origin(repo)
            progress = RemoteProgress()
            try:
                remote.fetch(progress=progress)
                remote_ref = repo.refs[f"{remote.name}/{branch.name}"]
            except GitCommandError as exc:
                raise _sync_error(
                    exc, "unable to fetch content backup", progress.other_lines
                ) from None
            except IndexError as exc:
                raise GitSyncError("unable to fetch content backup") from exc

            local_sha = repo.head.commit.hexsha
            remote_sha = remote_ref.commit.hexsha
            if local_sha == remote_sha:
                return False
            try:
                repo.git.merge_base("--is-ancestor", local_sha, remote_sha)
            except GitCommandError as exc:
                if exc.status == 1:
                    raise GitNonFastForwardError(
                        "content histories diverged; manual reconciliation required"
                    ) from _sanitized(exc)
                raise GitSyncError("unable to compare content backup history") from _sanitized(exc)
            try:
                repo.git.merge("--ff-only", remote_ref.name)
            except GitCommandError as exc:
                raise GitSyncError("unable to fast-forward content from backup") from _sanitized(
                    exc
                )
            return True

    def _show_or_empty(self, sha: str, relative: str) -> str | None:
        try:
            return self.show(sha, relative)
        except RevisionNotFound:
            return None

    def _relative_path(self, path: Path | str) -> str:
        if isinstance(path, str):
            return path
        try:
            return path.resolve().relative_to(self.repo_path).as_posix()
        except ValueError as exc:
            raise ValueError("path is outside the content repository") from exc

    def _snapshot_index(self) -> bytes | None:
        index_path = Path(self.repo.git_dir) / "index"
        return index_path.read_bytes() if index_path.exists() else None

    def _restore_index(self, snapshot: bytes | None) -> None:
        """Restore a pre-mutation index snapshot without changing HEAD/files."""

        index_path = Path(self.repo.git_dir) / "index"
        if snapshot is None:
            index_path.unlink(missing_ok=True)
            return
        descriptor, temporary = tempfile.mkstemp(dir=index_path.parent, prefix=".index.restore.")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(snapshot)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, index_path)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise

    def _remove_empty_parents(self, directory: Path) -> None:
        while directory != self.repo_path and directory.is_dir():
            try:
                directory.rmdir()
            except OSError:
                return
            directory = directory.parent

    def _commit(self, sha: str):
        if not SHA_RE.fullmatch(sha):
            raise RevisionNotFound("invalid revision")
        try:
            return self.repo.commit(sha)
        except (BadName, ValueError) as exc:
            raise RevisionNotFound("revision not found") from exc

    @staticmethod
    def _active_branch(repo: Repo):
        try:
            return repo.active_branch
        except TypeError as exc:
            raise GitSyncError("content repository must be on a branch to synchronize") from exc

    @staticmethod
    def _origin(repo: Repo):
        try:
            return repo.remotes.origin
        except AttributeError as exc:
            raise GitSyncError("content backup remote 'origin' is not configured") from exc

    @staticmethod
    def _set_origin(repo: Repo, url: str) -> None:
        """Make ``origin`` point at ``url``, creating it if it is absent.

        ``url`` has already been validated, so it can neither carry embedded
        credentials nor be mistaken by git for a command-line option.
        """

        if hasattr(repo.remotes, "origin"):
            repo.git.remote("set-url", "origin", url)
        else:
            repo.create_remote("origin", url)
        # An `origin` an operator added by hand may have no fetch refspec, and
        # fetch_and_fast_forward needs `origin/<branch>` to resolve.  The `+`
        # here forces the *remote-tracking* ref to follow the remote, which is
        # git's default and has nothing to do with force-pushing.
        repo.git.config(
            "--local",
            "--replace-all",
            "remote.origin.fetch",
            "+refs/heads/*:refs/remotes/origin/*",
        )

    @staticmethod
    def _clear_remote_auth_config(repo: Repo) -> None:
        """Drop repo-local credential settings from a previous configuration.

        Switching from HTTPS to SSH (or to a different host) must not leave a
        stale helper behind that would keep offering an old token.
        """

        (Path(repo.git_dir) / _CREDENTIAL_HELPER_NAME).unlink(missing_ok=True)
        try:
            listed = repo.git.config("--local", "--name-only", "--list")
        except GitCommandError:
            return
        for name in listed.splitlines():
            if name != "core.sshcommand" and not name.startswith("credential."):
                continue
            try:
                repo.git.config("--local", "--unset-all", name)
            except GitCommandError:
                continue

    def _configure_token_credential(self, repo: Repo, url: str, config: RemoteConfig) -> None:
        """Wire an HTTPS PAT in without it ever touching git's command line.

        The token reaches git through the credential protocol on the helper's
        stdout, which git reads and discards; it is never an argument, a config
        value, or part of the remote URL.
        """

        token_path = config.token_path.expanduser() if config.token_path else None
        if token_path is not None:
            token = _read_token_file(token_path)
        elif config.token:
            token = config.token
            # No secret file to read from, so hand the helper — a grandchild of
            # this process — the value through our own environment rather than
            # writing the token to disk ourselves.  It never leaves the process
            # tree, and an inline token is already environment-visible.
            os.environ[_TOKEN_ENV_VAR] = token
        else:
            raise GitRemoteConfigError(
                "https content backup remote requires a token file or token value"
            )
        _validate_token(token)
        helper = self._write_credential_helper(repo, token_path)
        context = _credential_context(url)
        # An empty helper value resets the inherited helper list, so a keychain
        # or a plaintext store configured globally on the host cannot answer
        # for this remote.  It is written first so it precedes ours in the file
        # and therefore in git's evaluation order.
        repo.git.config("--local", "--replace-all", "credential.helper", "")
        repo.git.config(
            "--local",
            "--replace-all",
            f"credential.{context}.helper",
            # Git runs an absolute-path helper through a shell, so a repository
            # path containing a space would otherwise split into two words.
            shlex.quote(str(helper)),
        )
        repo.git.config(
            "--local", "--replace-all", f"credential.{context}.username", _TOKEN_USERNAME
        )

    @staticmethod
    def _configure_ssh_credential(repo: Repo, config: RemoteConfig) -> None:
        """Pin the host key and offer only the configured deploy key.

        ``StrictHostKeyChecking=yes`` against a known_hosts file this
        installation controls is the point: trusting whatever the host's global
        known_hosts happens to contain (or accepting an unknown key on first
        use) would let a machine-in-the-middle collect the deploy key.
        """

        if config.ssh_key_path is None:
            raise GitRemoteConfigError("ssh content backup remote requires a deploy key file")
        if config.ssh_known_hosts_path is None:
            raise GitRemoteConfigError(
                "ssh content backup remote requires a pinned known_hosts file"
            )
        key = config.ssh_key_path.expanduser()
        known_hosts = config.ssh_known_hosts_path.expanduser()
        if not key.is_file():
            raise GitRemoteConfigError("configured content backup deploy key is missing")
        if not known_hosts.is_file() or known_hosts.stat().st_size == 0:
            raise GitRemoteConfigError(
                "configured content backup known_hosts file is missing or empty"
            )
        command = " ".join(
            [
                "ssh",
                # Fail instead of prompting: this runs headless.
                "-o BatchMode=yes",
                # Offer the deploy key alone, never an agent key that might
                # carry more access than this repository needs.
                "-o IdentitiesOnly=yes",
                f"-i {shlex.quote(str(key))}",
                f"-o UserKnownHostsFile={shlex.quote(str(known_hosts))}",
                "-o GlobalKnownHostsFile=/dev/null",
                "-o StrictHostKeyChecking=yes",
            ]
        )
        repo.git.config("--local", "--replace-all", "core.sshCommand", command)

    @staticmethod
    def _write_credential_helper(repo: Repo, token_path: Path | None) -> Path:
        """Generate the repo-local helper git calls to obtain the token.

        Lives inside ``.git/`` so it is neither content, nor tracked, nor part
        of any export, and holds only the *path* the secret is read from.
        """

        if token_path is None:
            read_token = f'token=${{{_TOKEN_ENV_VAR}:-}}'
        else:
            read_token = f"token=$(cat {shlex.quote(str(token_path))} 2>/dev/null)"
        script = f"""#!/bin/sh
# Generated by Unstacked; do not edit.
# Git calls this to obtain the content backup credential.  Reading the secret
# here, at the moment git asks, is what keeps the token out of the remote URL,
# out of .git/config, and out of every process argument list.
[ "${{1:-}}" = get ] || exit 0
# Consume git's request; the answer is the same for the one remote we serve.
cat >/dev/null
{read_token}
# Answer nothing rather than a blank credential, so git reports a normal
# authentication failure instead of "credential helper died".
[ -n "$token" ] || exit 0
printf 'username=%s\\n' {shlex.quote(_TOKEN_USERNAME)}
printf 'password=%s\\n' "$token"
"""
        path = Path(repo.git_dir) / _CREDENTIAL_HELPER_NAME
        _write_private_file(path, script, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        return path

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        GitBackend._atomic_write_bytes(path, text.encode("utf-8"))

    @staticmethod
    def _atomic_write_bytes(path: Path, content: bytes) -> None:
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise


def _push_refspec(branch: str) -> str:
    """Build the only push refspec this project ever uses.

    Separated out so the guarantee is one readable line: the leading ``+`` git
    reads as "force" cannot appear here, and no caller supplies a refspec of
    its own.  A branch name that could smuggle one in is refused outright.
    """

    if branch.startswith("+") or ":" in branch:
        raise GitSyncError("refusing to push an unsafe branch name")
    return f"{branch}:{branch}"


def _validated_remote_url(url: str) -> str:
    """Return ``url`` if it is a usable backup remote, else raise.

    The URL itself is kept out of every message: an operator who pasted a URL
    with an embedded token would otherwise see it echoed back into a log.
    """

    url = url.strip()
    if not url:
        raise GitRemoteConfigError("content backup remote URL is empty")
    if any(character.isspace() or not character.isprintable() for character in url):
        raise GitRemoteConfigError("content backup remote URL contains invalid characters")
    if url.startswith("-"):
        # Would be read as an option by `git remote set-url`.
        raise GitRemoteConfigError("content backup remote URL is not a valid location")
    if _SCP_LIKE_URL.fullmatch(url):
        return url
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_URL_SCHEMES:
        raise GitRemoteConfigError(
            "content backup remote must use https, ssh, or a local file URL"
        )
    if "@" in parts.netloc and parts.scheme != "ssh":
        raise GitRemoteConfigError(
            "content backup remote URL must not embed credentials; "
            "configure a token file or deploy key instead"
        )
    if parts.scheme == "ssh" and parts.password:
        raise GitRemoteConfigError(
            "content backup remote URL must not embed credentials; "
            "configure a deploy key instead"
        )
    if parts.scheme != "file" and not parts.hostname:
        raise GitRemoteConfigError("content backup remote URL has no host")
    return url


def _transport(url: str) -> str:
    if _SCP_LIKE_URL.fullmatch(url):
        return "ssh"
    return urlsplit(url).scheme


def _credential_context(url: str) -> str:
    """The ``credential.<context>`` scope this remote's helper answers for.

    Scoped to scheme and host so the token is never offered to some other
    HTTPS host the repository might later be pointed at.
    """

    parts = urlsplit(url)
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}"


def _read_token_file(path: Path) -> str:
    if not path.is_file():
        raise GitRemoteConfigError("configured content backup token file is missing")
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        # Deliberately unchained: a UnicodeDecodeError renders the offending
        # bytes, which are the secret.
        raise GitRemoteConfigError(
            "configured content backup token file is unreadable"
        ) from None


def _validate_token(token: str) -> None:
    """Reject tokens the credential protocol cannot carry safely.

    The protocol is line-oriented, so whitespace in a token would either
    truncate it or let a crafted value inject additional credential fields.
    The value is never included in the error.
    """

    if not token:
        raise GitRemoteConfigError("configured content backup token is empty")
    if len(token) > 512 or any(
        character.isspace() or not character.isprintable() or not character.isascii()
        for character in token
    ):
        raise GitRemoteConfigError(
            "configured content backup token must be a single line of printable ASCII"
        )


def _write_private_file(path: Path, text: str, mode: int) -> None:
    """Atomically write ``text`` to ``path`` with owner-only permissions."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def scrub_git_output(text: str | None) -> str:
    """Redact credential material from text produced by git or a transport.

    Nothing this module configures puts a credential where git could print it,
    so this is the second layer — for transports, helpers, and remotes we do
    not control, and for a URL an operator pasted a token into.
    """

    if not text:
        return ""
    for pattern, replacement in _SCRUB_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _sanitized(exc: GitCommandError) -> GitCommandError:
    """A copy of ``exc`` with credential material redacted.

    Chained as the ``__cause__`` of the typed error instead of the original, so
    a rendered traceback cannot surface what the original stderr contained.
    """

    command = exc.command if isinstance(exc.command, (list, tuple)) else [str(exc.command)]
    return GitCommandError(
        [scrub_git_output(str(part)) for part in command],
        exc.status,
        scrub_git_output(exc.stderr),
        scrub_git_output(exc.stdout),
    )


def _sync_error(
    exc: GitCommandError, fallback: str, transport_lines: Sequence[str] = ()
) -> GitSyncError:
    """Classify a git failure into an actionable, credential-free error.

    Telling these apart is what lets a caller react correctly: a rejected
    credential needs a new token or deploy key, a diverged history needs an
    operator, and a pinned host key that stopped matching needs neither — it
    needs investigating.

    ``transport_lines`` are matched but never surfaced; only the fixed message
    reaches the caller, so nothing a remote or a transport printed can escape.
    """

    detail = "\n".join([exc.stderr or "", exc.stdout or "", *transport_lines]).casefold()
    if any(marker in detail for marker in _HOST_KEY_MARKERS):
        error: GitSyncError = GitHostKeyError(
            "content backup host key does not match the pinned known_hosts entry"
        )
    elif any(marker in detail for marker in _AUTH_MARKERS):
        error = GitAuthError("content backup rejected the configured credentials")
    elif any(marker in detail for marker in _NON_FAST_FORWARD_MARKERS):
        error = GitNonFastForwardError(
            "content backup and local history are not fast-forwardable"
        )
    else:
        error = GitSyncError(fallback)
    # Assigning __cause__ also suppresses the raw exception as implicit
    # context, so only the sanitized copy can ever be rendered.
    error.__cause__ = _sanitized(exc)
    return error
