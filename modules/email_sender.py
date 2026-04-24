"""Email delivery for the newsletter.

Supports two providers:
  * SMTP — any standards-compliant server (Gmail, Fastmail, self-hosted).
  * SendGrid — via the v3 /mail/send HTTP API (no SDK dependency).

Configure via .env. See config.py for the full set of keys.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import List, Sequence

import requests

from config import settings

log = logging.getLogger(__name__)


class EmailError(RuntimeError):
    """Raised when delivery is attempted but misconfigured or fails."""


def _recipients(override: Sequence[str] | None) -> List[str]:
    recipients = list(override) if override else list(settings.email_to)
    return [r for r in recipients if r]


def send_via_smtp(subject: str, html_body: str, text_body: str,
                  recipients: List[str]) -> None:
    if not settings.smtp_host:
        raise EmailError("SMTP_HOST is not configured.")
    if not settings.email_from:
        raise EmailError("EMAIL_FROM is not configured.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = ", ".join(recipients)
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port,
                      timeout=settings.http_timeout) as client:
        client.ehlo()
        if settings.smtp_use_tls:
            client.starttls()
            client.ehlo()
        if settings.smtp_user:
            client.login(settings.smtp_user, settings.smtp_password)
        client.send_message(msg)
    log.info("SMTP delivery OK -> %s", recipients)


def send_via_sendgrid(subject: str, html_body: str, text_body: str,
                      recipients: List[str]) -> None:
    if not settings.sendgrid_api_key:
        raise EmailError("SENDGRID_API_KEY is not configured.")
    if not settings.email_from:
        raise EmailError("EMAIL_FROM is not configured.")

    payload = {
        "personalizations": [{"to": [{"email": r} for r in recipients]}],
        "from": {"email": settings.email_from},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text_body},
            {"type": "text/html", "value": html_body},
        ],
    }
    resp = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        json=payload,
        headers={
            "Authorization": f"Bearer {settings.sendgrid_api_key}",
            "Content-Type": "application/json",
        },
        timeout=settings.http_timeout,
    )
    if resp.status_code >= 300:
        raise EmailError(f"SendGrid rejected send: {resp.status_code} {resp.text}")
    log.info("SendGrid delivery OK -> %s", recipients)


def send_newsletter(markdown_body: str, html_body: str, issue_date: str,
                    recipients: Sequence[str] | None = None) -> None:
    """Route to the configured provider. Raises EmailError if unusable."""
    provider = settings.email_provider
    if not provider:
        raise EmailError(
            "EMAIL_PROVIDER is not set. Set it to 'smtp' or 'sendgrid' in .env."
        )

    targets = _recipients(recipients)
    if not targets:
        raise EmailError("No recipients. Set EMAIL_TO in .env or pass --email-to.")

    subject = f"{settings.email_subject_prefix} — {issue_date}"

    if provider == "smtp":
        send_via_smtp(subject, html_body, markdown_body, targets)
    elif provider == "sendgrid":
        send_via_sendgrid(subject, html_body, markdown_body, targets)
    else:
        raise EmailError(f"Unknown EMAIL_PROVIDER: {provider!r}")
