"""Optional, best-effort backup synchronization outside content requests."""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from app.git_backend import (
    GitAuthError,
    GitBackend,
    GitHostKeyError,
    GitNonFastForwardError,
    GitRemoteConfigError,
    GitSyncError,
    scrub_git_output,
)


@dataclass(frozen=True)
class BackupStatus:
    """Credential-free state that a later admin UI may render directly."""

    ahead_count: int
    last_success_at: str | None = None
    last_error: str | None = None
    retry_at: str | None = None
    requires_admin_action: bool = False


class BackupSyncWorker:
    """Coalesce content commits into safe, background-only remote pushes.

    It deliberately owns no durable queue.  ``GitBackend.pending_backup_count``
    compares local and remote-tracking refs, so pending work survives restart.
    This class is only constructed when a backup target was configured.
    """

    def __init__(
        self,
        git: GitBackend,
        *,
        debounce_seconds: float,
        max_backoff_seconds: float,
    ) -> None:
        self.git = git
        self.debounce_seconds = debounce_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._guard = threading.Lock()
        self._thread: threading.Thread | None = None
        self._status = BackupStatus(ahead_count=0)
        self._retry_attempt = 0

    def start(self) -> None:
        """Start once.  A pending branch is checked promptly after startup."""

        with self._guard:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._run, name="unstacked-backup-sync", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self.debounce_seconds + 1)

    def request_sync(self) -> None:
        """Wake the worker for a future manual action without doing I/O here."""

        with self._guard:
            if self._status.requires_admin_action:
                self._status = BackupStatus(ahead_count=self._status.ahead_count)
                self._retry_attempt = 0
        self._wake.set()

    def status(self) -> BackupStatus:
        with self._guard:
            return self._status

    def sync_once(self) -> None:
        """One testable synchronization attempt; callers remain off request paths."""

        try:
            pending = self.git.push_pending()
            ahead = self.git.pending_backup_count()
        except (GitAuthError, GitHostKeyError, GitNonFastForwardError, GitRemoteConfigError) as exc:
            self._set_terminal_error(exc)
            return
        except GitSyncError as exc:
            self._set_retryable_error(exc)
            return
        except Exception:
            # Do not leak a filesystem path, remote response, or accidental
            # credential through a future UI.  Unexpected failures are still
            # retryable because a transient local issue can clear itself.
            self._set_retryable_error("content backup synchronization failed")
            return

        with self._guard:
            self._retry_attempt = 0
            previous = self._status.last_success_at
            self._status = BackupStatus(
                ahead_count=ahead,
                last_success_at=(datetime.now(timezone.utc).isoformat() if pending else previous),
            )

    def _run(self) -> None:
        # Initial check resumes a branch that was committed before a restart.
        wait_seconds = 0.0
        while not self._stop.is_set():
            if wait_seconds:
                self._wake.wait(wait_seconds)
                self._wake.clear()
                if self._stop.is_set():
                    break
            self.sync_once()
            current = self.status()
            if current.requires_admin_action:
                self._wake.wait()
                self._wake.clear()
                wait_seconds = 0.0
            elif current.retry_at:
                wait_seconds = self._next_backoff()
            else:
                # Polling refs after this interval is the debounce: a burst
                # of ten local commits yields one push, never ten request-time
                # network calls.  New durable work is discovered from refs.
                wait_seconds = self.debounce_seconds

    def _set_terminal_error(self, error: Exception) -> None:
        with self._guard:
            self._status = BackupStatus(
                ahead_count=self._safe_ahead_count(),
                last_success_at=self._status.last_success_at,
                last_error=_safe_error(error),
                requires_admin_action=True,
            )

    def _set_retryable_error(self, error: Exception | str) -> None:
        with self._guard:
            self._retry_attempt += 1
            delay = self._backoff_delay()
            retry_at = datetime.now(timezone.utc).timestamp() + delay
            self._status = BackupStatus(
                ahead_count=self._safe_ahead_count(),
                last_success_at=self._status.last_success_at,
                last_error=_safe_error(error),
                retry_at=datetime.fromtimestamp(retry_at, timezone.utc).isoformat(),
            )

    def _safe_ahead_count(self) -> int:
        try:
            return self.git.pending_backup_count()
        except Exception:
            return 0

    def _backoff_delay(self) -> float:
        exponential_delay = self.debounce_seconds * (2 ** (self._retry_attempt - 1))
        return min(self.max_backoff_seconds, exponential_delay)

    def _next_backoff(self) -> float:
        # Jitter avoids many replicas retrying a shared remote at the same
        # instant.  Clamp it so the configured bound remains absolute.
        return min(self.max_backoff_seconds, self._backoff_delay() * random.uniform(0.75, 1.25))


def _safe_error(error: Exception | str) -> str:
    """A bounded, credential-scrubbed error summary safe for UI status."""

    value = scrub_git_output(str(error)).replace("\n", " ").strip()
    return (value or "content backup synchronization failed")[:240]
