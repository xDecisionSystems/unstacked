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
    _deliver(config, message)


def send_user_invite(config: SMTPConfig, recipient: str, url: str) -> None:
    if not config.configured:
        raise MailDeliveryError("Email delivery has not been configured")
    message = EmailMessage()
    message["From"] = config.from_email
    message["To"] = recipient
    message["Subject"] = "You're invited to Unstacked"
    message.set_content(
        "An administrator has invited you to create an Unstacked account.\n\n"
        f"Create your account and choose a password: {url}\n\n"
        "This link expires in 7 days. If you were not expecting this invitation, "
        "you can ignore this email."
    )
    _deliver(config, message)


def send_account_created_notification(
    config: SMTPConfig, recipient: str, *, username: str, display_name: str, settings_url: str
) -> None:
    """Tell an administrator an invited user finished creating their account.

    New accounts start in no groups, so this is the administrator's cue to
    assign group memberships -- the invite flow itself has no group picker.
    """

    if not config.configured:
        raise MailDeliveryError("Email delivery has not been configured")
    message = EmailMessage()
    message["From"] = config.from_email
    message["To"] = recipient
    message["Subject"] = f"New Unstacked account: {username}"
    message.set_content(
        f"{display_name} ({username}) accepted their invitation and created an account.\n\n"
        "They have not been added to any groups yet, so they have no book access. "
        f"Assign group memberships here: {settings_url}"
    )
    _deliver(config, message)


def send_test_email(config: SMTPConfig, recipient: str) -> None:
    """Send an administrator-requested SMTP configuration check."""

    if not config.configured:
        raise MailDeliveryError("Email delivery has not been configured")
    message = EmailMessage()
    message["From"] = config.from_email
    message["To"] = recipient
    message["Subject"] = "Unstacked SMTP test"
    message.set_content(
        "This is a practice email from Unstacked. Your SMTP settings are working."
    )
    _deliver(config, message)


def _deliver(config: SMTPConfig, message: EmailMessage) -> None:
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
