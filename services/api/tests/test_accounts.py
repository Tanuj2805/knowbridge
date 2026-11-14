"""Email-and-password accounts confirmed with a 6-digit code: no sign-in before the code, no telling
who has an account, lockouts, code expiry and retry limits, and the website-only door."""

import re
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import accounts, mailer
from app.config import get_settings
from app.db.models import EmailToken, PasswordCredential, User

pytestmark = pytest.mark.db

PASSWORD = "correct horse battery"  # noqa: S105 - test value


def _site(aud: str = "knowbridge-accounts", sub: str = "web") -> TestClient:
    from app.main import app

    now = int(time.time())
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer " + jwt.encode(
        {"sub": sub, "iss": "knowbridge-web", "aud": aud, "iat": now, "exp": now + 60},
        get_settings().api_jwt_secret, "HS256")
    return c


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html="": sent.append(
        {"to": to, "subject": subject, "text": text, "html": html}) or True)
    return sent


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:8]}@example.com"


def _code(mail: dict) -> str:
    return re.search(r"\b(\d{6})\b", mail["subject"]).group(1)


def _signup(outbox, email: str, password: str = PASSWORD) -> str:
    assert _site().post("/auth/register", json={"name": "Asha Rao", "email": email, "password": password}
                        ).status_code == 202
    return _code(outbox[-1])


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


def test_passwords_are_hashed_and_checked():
    h = accounts.hash_password(PASSWORD)
    assert h.startswith("scrypt$") and "correct" not in h
    assert accounts.check_password(PASSWORD, h)
    assert not accounts.check_password("wrong", h) and not accounts.check_password("x", "garbage")


def test_only_the_website_may_call(outbox):
    body = {"email": _email(), "password": "whatever123"}
    from app.main import app

    assert TestClient(app).post("/auth/login", json=body).status_code == 401
    assert _site(aud="knowbridge-api").post("/auth/login", json=body).status_code == 401  # a user's token
    assert _site(sub="someone@example.com").post("/auth/login", json=body).status_code == 401


def test_the_code_email_looks_right(outbox):
    email = _email()
    code = _signup(outbox, email)
    mail = outbox[-1]
    assert mail["to"] == email and mail["subject"] == f"{code} is your KnowBridge code"
    assert code in mail["text"] and "10 minutes" in mail["text"]
    assert "Confirm your email" in mail["html"] and all(d in mail["html"] for d in code)
    assert "Hi Asha" in mail["html"] and "Never share this code" in mail["html"]


def test_sign_up_then_the_code_signs_you_in(db, outbox):
    email = _email()
    code = _signup(outbox, email)
    r = _site().post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "unverified"  # not before the code

    r = _site().post("/auth/verify", json={"email": email.upper(), "code": f" {code[:3]} {code[3:]} "})
    assert r.status_code == 200 and r.json()["email"] == email and r.json()["name"] == "Asha Rao"
    assert _site().post("/auth/verify", json={"email": email, "code": code}).status_code == 401  # one use
    assert _site().post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200


def test_five_wrong_codes_retire_the_code(db, outbox):
    email = _email()
    code = _signup(outbox, email)
    for left in (4, 3, 2, 1):
        r = _site().post("/auth/verify", json={"email": email, "code": _wrong(code)})
        assert r.json()["detail"]["code"] == "invalid_code" and f"{left} tr" in r.json()["detail"]["message"]
    r = _site().post("/auth/verify", json={"email": email, "code": _wrong(code)})
    assert r.json()["detail"]["code"] == "too_many"
    assert _site().post("/auth/verify", json={"email": email, "code": code}).status_code == 401  # now dead


def test_expired_codes_dont_work(db, outbox):
    email = _email()
    code = _signup(outbox, email)
    user = db.scalar(select(User).where(User.email == email))
    row = db.scalar(select(EmailToken).where(EmailToken.user_id == user.id, EmailToken.purpose == "verify"))
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    r = _site().post("/auth/verify", json={"email": email, "code": code})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "expired"


def test_codes_are_stored_only_as_keyed_hashes(db, outbox):
    email = _email()
    code = _signup(outbox, email)
    user = db.scalar(select(User).where(User.email == email))
    row = db.scalar(select(EmailToken).where(EmailToken.user_id == user.id))
    assert code not in row.token_hash and len(row.token_hash) == 64


def test_a_new_code_replaces_the_old_one_at_most_once_a_minute(db, outbox):
    email = _email()
    first = _signup(outbox, email)
    _site().post("/auth/resend", json={"email": email})
    assert len(outbox) == 1  # too soon
    user = db.scalar(select(User).where(User.email == email))
    db.query(EmailToken).filter(EmailToken.user_id == user.id).update(
        {EmailToken.created_at: datetime.now(UTC) - timedelta(minutes=2)})
    db.commit()
    _site().post("/auth/resend", json={"email": email})
    second = _code(outbox[-1])
    if second != first:
        assert _site().post("/auth/verify", json={"email": email, "code": first}).status_code == 401
    assert _site().post("/auth/verify", json={"email": email, "code": second}).status_code == 200


def test_weak_passwords_are_refused(outbox):
    r = _site().post("/auth/register", json={"name": "A", "email": _email(), "password": "short"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "weak"
    email = _email()
    assert _site().post("/auth/register", json={"name": "A", "email": email, "password": email}).status_code == 422
    assert outbox == []


def test_signing_up_again_never_reveals_an_account(db, outbox):
    email = _email()
    _site().post("/auth/verify", json={"email": email, "code": _signup(outbox, email)})
    r = _site().post("/auth/register", json={"name": "Mallory", "email": email, "password": "another password"})
    assert r.status_code == 202  # same answer as a new sign-up
    assert outbox[-1]["subject"] == "You already have a KnowBridge account"  # the owner is told instead
    assert _site().post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200


def test_wrong_passwords_lock_the_account(db, outbox):
    email = _email()
    _site().post("/auth/verify", json={"email": email, "code": _signup(outbox, email)})
    for _ in range(accounts.MAX_FAILURES):
        assert _site().post("/auth/login", json={"email": email, "password": "nope nope"}).json()["detail"][
            "code"] == "invalid"
    r = _site().post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.json()["detail"]["code"] == "locked"  # even with the right password, for a while


def test_unknown_email_and_wrong_password_look_the_same(outbox):
    r = _site().post("/auth/login", json={"email": _email(), "password": "whatever123"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid"
    r = _site().post("/auth/verify", json={"email": _email(), "code": "123456"})
    assert r.json()["detail"]["code"] == "invalid_code"


def test_forgot_password_with_a_code(db, outbox):
    email = _email()
    _site().post("/auth/verify", json={"email": email, "code": _signup(outbox, email)})
    assert _site().post("/auth/forgot", json={"email": email}).status_code == 202
    mail = outbox[-1]
    assert "password reset code" in mail["subject"] and "Reset your password" in mail["html"]
    code = _code(mail)
    body = {"email": email, "code": code}
    assert _site().post("/auth/reset", json=body | {"password": "abc"}).status_code == 422  # code not used up
    r = _site().post("/auth/reset", json=body | {"password": "a brand new one"})
    assert r.status_code == 200 and r.json()["email"] == email
    assert _site().post("/auth/reset", json=body | {"password": "again again"}).status_code == 401
    assert _site().post("/auth/login", json={"email": email, "password": "a brand new one"}).status_code == 200
    assert _site().post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401


def test_forgot_password_for_unknown_email_sends_nothing(outbox):
    assert _site().post("/auth/forgot", json={"email": _email()}).status_code == 202 and outbox == []


def test_github_sign_in_drops_an_unconfirmed_password_for_that_address(db, outbox):
    """Someone signs up with your address and never confirms; when you sign in another way, their
    password is thrown away, so it can never be confirmed into your account."""
    from app.main import app

    email = _email()
    code = _signup(outbox, email, "attackers password")
    user = db.scalar(select(User).where(User.email == email))
    now = int(time.time())
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer " + jwt.encode(
        {"sub": email, "provider": "github", "iss": "knowbridge-web", "aud": "knowbridge-api", "iat": now,
         "exp": now + 300}, get_settings().api_jwt_secret, "HS256")
    assert c.get("/projects").status_code == 200
    db.expire_all()
    assert db.get(PasswordCredential, user.id) is None
    assert _site().post("/auth/verify", json={"email": email, "code": code}).status_code == 401


def test_options_say_whether_email_is_set_up():
    assert _site().get("/auth/options").json() == {"password": True, "email_delivery": mailer.configured(),
                                                    "app_name": "KnowBridge"}
