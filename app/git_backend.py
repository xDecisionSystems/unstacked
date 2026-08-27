import difflib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock
from git import Actor, BadName, Repo

SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")

# ASCII unit/record separators cannot appear in a commit trailer, so parsing
# stays unambiguous even for multi-line messages.
_FIELD_SEPARATOR = "\x1f"
_RECORD_SEPARATOR = "\x1e"
_LOG_FORMAT = _FIELD_SEPARATOR.join(["%H", "%an", "%ae", "%aI", "%B"]) + _RECORD_SEPARATOR


class RevisionNotFound(RuntimeError):
    """Raised when a revision or its version of a path cannot be found."""


@dataclass(frozen=True)
class Revision:
    sha: str
    message: str
    author_name: str
    author_email: str
    authored_at: str


class GitBackend:
    def __init__(self, repo_path: Path, lock_path: Path):
        self.repo_path = repo_path.resolve()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(lock_path, timeout=15)

    @property
    def repo(self) -> Repo:
        return Repo(self.repo_path)

    def commit_paths(self, paths: list[Path], *, name: str, email: str, message: str) -> str:
        """Commit exactly ``paths`` on top of HEAD.

        The index is reset to HEAD first, so content an operator (or a crashed
        earlier operation) left staged cannot be swept into this commit and
        misattributed to ``name``.  Only staging is discarded; working-tree
        files are never modified.
        """

        relative = [self._relative_path(path) for path in paths]
        repo = self.repo
        if repo.head.is_valid():
            # Discard anything else that was staged before adding our paths.
            # Working-tree files are untouched, so an operator's edits survive;
            # only their staging is dropped, which is far better than silently
            # committing their work under this user's name.
            repo.index.reset(repo.head.commit)
        try:
            # Plain `git add` also records removals, so this same path serves
            # deletions once they exist.
            repo.index.add(relative)
            actor = Actor(name, email)
            commit = repo.index.commit(message, author=actor, committer=actor)
            return commit.hexsha
        except Exception:
            if repo.head.is_valid():
                repo.index.reset(repo.head.commit)
            raise

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
