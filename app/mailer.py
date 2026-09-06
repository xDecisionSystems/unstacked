"""Small SMTP sender used solely for application transactional messages."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from app.smtp_config import SMTPConfig


class MailDeliveryError(RuntimeError):
    pass


def send_password_reset(config: SMTPConfig, recipient: str, url: str) -> None:
    if not config.configured:
        raise MailDeliveryError("Email delivery has not been configured")
    message = EmailMessage()
    message["From"] = config.from_email
    message["To"] = recipient
    message["Subject"] = "Reset your Unstacked password"
    message.set_content(
        "A password reset was requested for your Unstacked account.\n\n"
        f"Set a new password: {url}\n\n"
        "This link expires in 30 minutes. If you did not request it, you can ignore this email."
    )
    try:
        client_type = smtplib.SMTP_SSL if config.use_ssl else smtplib.SMTP
        with client_type(config.host, config.port, timeout=10) as client:
            if config.starttls:
                client.starttls(context=ssl.create_default_context())
            if config.username:
                client.login(config.username, config.password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailDeliveryError("Email could not be delivered") from exc
