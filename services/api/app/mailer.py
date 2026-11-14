"""Outgoing email over SMTP (standard library only).

Used for account emails (the codes that confirm an address or reset a password). Without SMTP
settings the message is written to the API log instead, so sign-up still works on a developer's own
computer, but nobody receives anything on a live site.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.config import get_settings

log = logging.getLogger(__name__)


def configured() -> bool:
    s = get_settings()
    return bool(s.smtp_host and (s.mail_from or s.smtp_user))


def send(to: str, subject: str, text: str, html: str = "") -> bool:
    """Sends one message (plain text, plus HTML if given). Returns False (and logs) if it couldn't be
    sent; never raises."""
    s = get_settings()
    if not configured():
        log.warning("SMTP isn't set up, so this email was not sent. To %s: %s\n%s", to, subject, text)
        return False
    msg = EmailMessage()
    msg["From"] = s.mail_from or formataddr((s.app_name, s.smtp_user))
    msg["To"], msg["Subject"] = to, subject
    msg["Message-ID"] = make_msgid(domain=(s.smtp_user.split("@")[-1] if "@" in s.smtp_user else None))
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        if s.smtp_ssl:
            with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ssl.create_default_context(), timeout=20) as smtp:
                _deliver(smtp, msg)
        else:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                _deliver(smtp, msg)
        return True
    except (smtplib.SMTPException, OSError) as e:
        log.error("couldn't send %r to %s: %s", subject, to, e)
        return False


def _deliver(smtp: smtplib.SMTP, msg: EmailMessage) -> None:
    s = get_settings()
    if s.smtp_user:
        smtp.login(s.smtp_user, s.smtp_password)
    smtp.send_message(msg)
