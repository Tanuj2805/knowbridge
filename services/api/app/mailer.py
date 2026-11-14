"""Outgoing email: Brevo's HTTPS API, or SMTP (standard library).

Used for account emails (the codes that confirm an address or reset a password).
- BREVO_API_KEY set: sent through Brevo over HTTPS. Use this where SMTP ports are blocked
  (Railway's Hobby plan blocks 25, 465, 587 and 2525). MAIL_FROM must be a sender verified in Brevo.
- Otherwise SMTP_HOST etc.: sent over SMTP (fine on your own computer or a host that allows it).
- Neither: the message is written to the log instead, so sign-up still works on a developer's own
  computer, but nobody receives anything on a live site.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def _sender() -> tuple[str, str]:
    """(name, address) the email comes from."""
    s = get_settings()
    name, address = parseaddr(s.mail_from) if s.mail_from else ("", "")
    return name or s.app_name, address or s.smtp_user


def configured() -> bool:
    s = get_settings()
    if s.brevo_api_key:
        return bool(_sender()[1])
    return bool(s.smtp_host and (s.mail_from or s.smtp_user))


def send(to: str, subject: str, text: str, html: str = "") -> bool:
    """Sends one message (plain text, plus HTML if given). Returns False (and logs) if it couldn't be
    sent; never raises."""
    s = get_settings()
    if not configured():
        log.warning("Email isn't set up, so this email was not sent. To %s: %s\n%s", to, subject, text)
        return False
    if s.brevo_api_key:
        return _send_brevo(to, subject, text, html)
    return _send_smtp(to, subject, text, html)


def _send_brevo(to: str, subject: str, text: str, html: str) -> bool:
    name, address = _sender()
    body = {"sender": {"name": name, "email": address}, "to": [{"email": to}], "subject": subject,
            "textContent": text, **({"htmlContent": html} if html else {})}
    try:
        r = httpx.post(BREVO_URL, json=body, timeout=20,
                       headers={"api-key": get_settings().brevo_api_key, "accept": "application/json"})
    except httpx.HTTPError as e:
        log.error("couldn't send %r to %s through Brevo: %s", subject, to, e)
        return False
    if r.status_code >= 300:
        # e.g. 401 (wrong key) or 400 (sender not verified in Brevo); never logs the key itself
        log.error("Brevo refused %r to %s: %s %s", subject, to, r.status_code, r.text[:300])
        return False
    return True


def _send_smtp(to: str, subject: str, text: str, html: str) -> bool:
    s = get_settings()
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
