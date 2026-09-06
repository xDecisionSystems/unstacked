"""Private, runtime-editable SMTP delivery configuration.

Mail delivery is operator configuration, not wiki data; it therefore lives in
``data/`` beside the other private runtime settings rather than in SQLite.
The password is never returned by :func:`load`'s public representation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.backup_config import write_private_bytes


@dataclass(frozen=True)
class SMTPConfig:
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_email: str = ""
    starttls: bool = True
    use_ssl: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.host and self.from_email)


def load(path: Path) -> SMTPConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return SMTPConfig()
    if not isinstance(raw, dict):
        return SMTPConfig()
    try:
        return SMTPConfig(
            host=_text(raw.get("host")),
            port=int(raw.get("port", 587)),
            username=_text(raw.get("username")),
            password=_text(raw.get("password")),
            from_email=_text(raw.get("from_email")),
            starttls=bool(raw.get("starttls", True)),
            use_ssl=bool(raw.get("use_ssl", False)),
        )
    except (TypeError, ValueError):
        return SMTPConfig()


def save(path: Path, config: SMTPConfig) -> SMTPConfig:
    if not config.host or not config.from_email:
        raise ValueError("SMTP host and sender email are required")
    if not 1 <= config.port <= 65535:
        raise ValueError("SMTP port must be between 1 and 65535")
    if config.starttls and config.use_ssl:
        raise ValueError("Choose either STARTTLS or implicit TLS, not both")
    write_private_bytes(
        path,
        (json.dumps(config.__dict__, indent=2) + "\n").encode("utf-8"),
    )
    return config


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
