from pathlib import Path

from filelock import FileLock
from git import Actor, Repo


class GitBackend:
    def __init__(self, repo_path: Path, lock_path: Path):
        self.repo_path = repo_path.resolve()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(lock_path, timeout=15)

    @property
    def repo(self) -> Repo:
        return Repo(self.repo_path)

    def commit_paths(self, paths: list[Path], *, name: str, email: str, message: str) -> str:
        relative = [path.resolve().relative_to(self.repo_path).as_posix() for path in paths]
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
