"""Safe, private MkDocs static-export builds.

The build output is a full recovery artifact, not an ACL-aware representation
of the wiki.  This module deliberately contains no HTTP transport; a future
admin UI owns acknowledgement and download while calling this narrow runner.
"""

import os
import re
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from app.config import Settings
from app.content import ContentRepository
from app.models import User

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class ExportError(RuntimeError):
    """A safe-to-display explanation of why a static export was not replaced."""


class ExportAccessDenied(ExportError):
    """Raised when a non-administrator tries to create or retrieve an export."""


class StaticExportRunner:
    """Build into a fresh directory and publish it only after a successful build."""

    def __init__(self, settings: Settings, content: ContentRepository):
        self.settings = settings
        self.content = content
        self.destination = settings.static_export_path.resolve()

    def build_for(self, user: User) -> Path:
        """Build a complete non-draft site for an administrator only.

        The caller must separately obtain an acknowledgement that static
        exports have no runtime ACL; making that an HTTP/UI concern keeps this
        runner usable for an operator command as well.
        """

        if not user.is_admin:
            raise ExportAccessDenied("Administrator access required")
        return self.build()

    def package_for(self, user: User) -> bytes:
        """Return the last completed static export as an administrator-only ZIP.

        The archive deliberately has a stable, synthetic top-level directory
        rather than preserving the local export path.  In particular, neither
        absolute paths nor symlinks from the server filesystem can enter a
        download artifact.
        """

        if not user.is_admin:
            raise ExportAccessDenied("Administrator access required")
        return self._package()

    def build(self) -> Path:
        """Build and atomically publish the new artifact, preserving the old one.

        Content writes and builds share the repository lock.  This avoids
        asking MkDocs to traverse a half-mutated content tree and serializes
        publication of the one last-successful-export directory.
        """

        self.destination.parent.mkdir(parents=True, exist_ok=True)
        with self.content.git.lock:
            with tempfile.TemporaryDirectory(
                dir=self.destination.parent, prefix=".unstacked-static-export-"
            ) as temporary:
                candidate = Path(temporary) / "site"
                command = [
                    self.settings.mkdocs_executable,
                    "build",
                    "--strict",
                    "--site-dir",
                    str(candidate),
                ]
                output, problem = self._run(command)
                if problem:
                    raise ExportError(problem)
                if not candidate.is_dir():
                    raise ExportError("Static export failed: MkDocs produced no site directory")
                self._publish(candidate)
        return self.destination

    def _package(self) -> bytes:
        """Archive a published export while excluding links outside of it.

        Publication and packaging take the same lock, so an archive observes
        either the complete prior site or the complete replacement site, never
        a directory while ``_publish`` is swapping it.
        """

        with self.content.git.lock:
            if not self.destination.is_dir() or self.destination.is_symlink():
                raise ExportError("No completed static export is available")

            output = BytesIO()
            try:
                with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
                    for current, directories, filenames in os.walk(
                        self.destination, followlinks=False
                    ):
                        current_path = Path(current)
                        # A directory link is not followed by os.walk, but reject it
                        # instead of silently representing something ambiguous.
                        directories[:] = [
                            name for name in directories if not (current_path / name).is_symlink()
                        ]
                        for filename in filenames:
                            source = current_path / filename
                            if source.is_symlink() or not source.is_file():
                                continue
                            relative = source.relative_to(self.destination)
                            archive_name = (Path("unstacked-static-export") / relative).as_posix()
                            archive.write(source, archive_name)
            except (OSError, ValueError) as exc:
                raise ExportError("Static export could not be packaged") from exc
        return output.getvalue()

    def _run(self, command: list[str]) -> tuple[str, str | None]:
        """Run MkDocs with a bounded pipe, timeout, and deliberately small env."""

        # Do not pass database URLs, credentials, deploy-platform variables,
        # or a caller-controlled current directory to a subprocess.  PATH is
        # the only inherited execution setting, and even it is copied into a
        # fresh mapping rather than sharing the app's environment.
        environment = {
            "PATH": os.environ.get("PATH", os.defpath),
            "PYTHONIOENCODING": "utf-8",
            "LC_ALL": "C.UTF-8",
        }
        try:
            process = subprocess.Popen(
                command,
                cwd=self.content.root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            return "", f"Static export could not start MkDocs: {self._sanitize(str(exc))}"

        assert process.stdout is not None
        captured = bytearray()
        deadline = time.monotonic() + self.settings.static_export_timeout_seconds
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        failure: str | None = None
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    failure = "Static export timed out"
                    self._stop(process)
                    break
                for key, _events in selector.select(min(remaining, 0.25)):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    space = self.settings.static_export_output_limit_bytes - len(captured)
                    if len(chunk) > space:
                        captured.extend(chunk[: max(space, 0)])
                        failure = (
                            "Static export failed: MkDocs output exceeded the configured limit"
                        )
                        self._stop(process)
                        break
                    captured.extend(chunk)
                if failure:
                    break
            return_code = process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._stop(process)
            return_code = process.wait()
        finally:
            selector.close()
            process.stdout.close()

        output = captured.decode("utf-8", "replace")
        if failure:
            return output, failure
        if return_code:
            detail = self._sanitize(output)
            suffix = f": {detail}" if detail else ""
            return output, f"Static export failed (MkDocs exited {return_code}){suffix}"
        return output, None

    @staticmethod
    def _stop(process: subprocess.Popen[bytes]) -> None:
        """Stop MkDocs and any child process it spawned without leaking one."""

        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _publish(self, candidate: Path) -> None:
        """Replace the old export only after the candidate is complete.

        ``rename`` cannot replace a nonempty directory.  Keep the prior site
        under a sibling name while publishing, and restore it if the second
        rename fails; the temporary directory cleanup handles leftovers.
        """

        previous = self.destination.parent / f".{self.destination.name}.previous"
        if previous.exists():
            shutil.rmtree(previous)
        moved_previous = False
        try:
            if self.destination.exists():
                os.replace(self.destination, previous)
                moved_previous = True
            os.replace(candidate, self.destination)
            self._fsync_directory(self.destination.parent)
        except OSError as exc:
            if moved_previous and not self.destination.exists() and previous.exists():
                os.replace(previous, self.destination)
            raise ExportError(
                f"Static export could not be published: {self._sanitize(str(exc))}"
            ) from exc
        if moved_previous:
            shutil.rmtree(previous)

    def _sanitize(self, value: str) -> str:
        """Keep diagnostics useful without exposing absolute application paths."""

        clean = _ANSI_ESCAPE.sub("", value).replace("\x00", "").strip()
        for path, replacement in (
            (str(self.content.root), "<content>"),
            (str(self.destination), "<export>"),
        ):
            clean = clean.replace(path, replacement)
        clean = " ".join(clean.split())
        return clean[:2000]

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
