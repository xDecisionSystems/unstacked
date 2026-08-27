import difflib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock
from git import Actor, BadName, Repo

SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


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
        relative = [self._relative_path(path) for path in paths]
        repo = self.repo
        try:
            repo.index.add(relative)
            actor = Actor(name, email)
            commit = repo.index.commit(message, author=actor, committer=actor)
            return commit.hexsha
        except Exception:
            if repo.head.is_valid():
                repo.index.reset(repo.head.commit, paths=relative)
            raise

    def log(self, path: Path) -> list[Revision]:
        relative = self._relative_path(path)
        return [
            Revision(
                sha=commit.hexsha,
                message=commit.message.rstrip("\n"),
                author_name=commit.author.name,
                author_email=commit.author.email,
                authored_at=commit.authored_datetime.isoformat(),
            )
            for commit in self.repo.iter_commits(paths=relative)
        ]

    def diff(self, sha_a: str, sha_b: str, path: Path) -> str:
        relative = self._relative_path(path)
        before = self.show(sha_a, relative)
        after = self.show(sha_b, relative)
        return "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"{sha_a}:{relative}",
                tofile=f"{sha_b}:{relative}",
            )
        )

    def show(self, sha: str, path: Path | str) -> str:
        relative = self._relative_path(path) if isinstance(path, Path) else path
        commit = self._commit(sha)
        try:
            blob = commit.tree / relative
        except KeyError as exc:
            raise RevisionNotFound("revision does not contain path") from exc
        if blob.type != "blob":
            raise RevisionNotFound("revision path is not a file")
        return blob.data_stream.read().decode("utf-8")

    def restore_as_new_commit(
        self,
        path: Path,
        revision: str,
        *,
        name: str,
        email: str,
        message: str,
    ) -> str:
        """Restore one tracked file without rewriting history or staging other paths."""
        relative = self._relative_path(path)
        restored = self.show(revision, relative)
        existed = path.exists()
        original = path.read_bytes() if existed else None
        try:
            self._atomic_write(path, restored)
            return self.commit_paths([path], name=name, email=email, message=message)
        except Exception:
            if existed:
                assert original is not None
                self._atomic_write_bytes(path, original)
            else:
                path.unlink(missing_ok=True)
            raise

    def _relative_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.repo_path).as_posix()
        except ValueError as exc:
            raise ValueError("path is outside the content repository") from exc

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
