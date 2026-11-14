"""Outgoing email: Brevo's HTTPS API when BREVO_API_KEY is set (hosts like Railway's Hobby plan block
SMTP), SMTP otherwise, and the log when neither is set."""

from types import SimpleNamespace

import httpx
import pytest

from app import mailer
from app.config import get_settings


class Recorder:
    """Stands in for the mailer's logger (the app's own log setup may stop pytest seeing it)."""

    def __init__(self):
        self.lines = []

    def _add(self, msg, *args):
        self.lines.append(msg % args)

    warning = error = info = _add

    @property
    def text(self):
        return " | ".join(self.lines)


@pytest.fixture
def logged(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(mailer, "log", r)
    return r


@pytest.fixture
def settings(monkeypatch):
    s = get_settings()
    for k, v in {"brevo_api_key": "", "smtp_host": "", "smtp_user": "", "smtp_password": "", "mail_from": "",
                 "app_name": "KnowBridge"}.items():
        monkeypatch.setattr(s, k, v)
    return s


def test_brevo_is_used_when_its_key_is_set(settings, monkeypatch):
    settings.brevo_api_key = "xkeysib-test"
    settings.mail_from = "KnowBridge <tanuj@example.com>"
    settings.smtp_host = "smtp.gmail.com"  # Brevo wins over SMTP
    sent = []
    ok = SimpleNamespace(status_code=201, text="")
    monkeypatch.setattr(httpx, "post", lambda url, **kw: sent.append((url, kw)) or ok)
    monkeypatch.setattr(mailer.smtplib, "SMTP", lambda *a, **k: pytest.fail("SMTP must not be used"))

    assert mailer.configured()
    assert mailer.send("asha@example.com", "123456 is your KnowBridge code", "Your code: 123456", "<p>123456</p>")
    url, kw = sent[0]
    assert url == "https://api.brevo.com/v3/smtp/email"
    assert kw["headers"]["api-key"] == "xkeysib-test"
    assert kw["json"]["sender"] == {"name": "KnowBridge", "email": "tanuj@example.com"}
    assert kw["json"]["to"] == [{"email": "asha@example.com"}]
    assert kw["json"]["htmlContent"] == "<p>123456</p>" and kw["json"]["textContent"] == "Your code: 123456"


def test_a_brevo_refusal_is_logged_not_raised(settings, monkeypatch, logged):
    settings.brevo_api_key = "xkeysib-wrong"
    settings.mail_from = "tanuj@example.com"
    monkeypatch.setattr(httpx, "post", lambda url, **kw: SimpleNamespace(status_code=401, text="Key not found"))
    assert mailer.send("asha@example.com", "subject", "text") is False
    assert "Brevo refused" in logged.text and "xkeysib-wrong" not in logged.text


def test_brevo_unreachable_is_handled(settings, monkeypatch):
    settings.brevo_api_key = "xkeysib-test"
    settings.mail_from = "tanuj@example.com"

    def down(url, **kw):
        raise httpx.ConnectError("Network is unreachable")

    monkeypatch.setattr(httpx, "post", down)
    assert mailer.send("asha@example.com", "subject", "text") is False


def test_brevo_needs_a_sender(settings):
    settings.brevo_api_key = "xkeysib-test"  # no MAIL_FROM and no SMTP_USER: nothing to send from
    assert not mailer.configured()


def test_without_any_settings_the_email_goes_to_the_log(settings, logged):
    assert not mailer.configured()
    assert mailer.send("asha@example.com", "123456 is your KnowBridge code", "Your code: 123456") is False
    assert "Your code: 123456" in logged.text
