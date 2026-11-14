"""Email-and-password accounts, confirmed with a 6-digit code sent by email.

- Passwords are stored only as scrypt hashes (standard library; no extra dependency).
- An account can't be used until its owner types the code we email, so nobody can sign up with a
  teammate's address and inherit the projects that address was added to. Typing the code also signs
  them in.
- Codes: 6 digits, valid 10 minutes, one use, five wrong tries and that code stops working, at most
  one new code a minute. Only a keyed hash (HMAC with the server secret) of each code is stored.
- Five wrong passwords lock the account for 15 minutes.
- Sign-up and "forgot password" never say whether an address already has an account.

The website calls these through `routers/accounts.py`; the session itself is the website's (Auth.js).
"""

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import emails
from app.config import get_settings
from app.db.models import EmailToken, PasswordCredential, User

MIN_PASSWORD = 8
MAX_PASSWORD = 200
MAX_FAILURES = 5
LOCK_FOR = timedelta(minutes=15)
CODE_MINUTES = 10
CODE_TRIES = 5
RESEND_GAP = timedelta(seconds=60)  # at most one code of a kind per minute per account

_N, _R, _P = 2**15, 8, 1  # scrypt cost: ~50 ms and 32 MB per hash
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CODE = re.compile(r"^\d{6}$")


class AccountError(Exception):
    """`code` is what the website shows a message for: invalid, unverified, locked, weak,
    invalid_code, expired, too_many."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass
class Mail:
    to: str
    email: emails.Email


# --- passwords ----------------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024)
    b64 = base64.b64encode
    return f"scrypt${_N}${_R}${_P}${b64(salt).decode()}${b64(digest).decode()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             maxmem=64 * 1024 * 1024, dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


_DUMMY = hash_password(secrets.token_urlsafe(16))  # for unknown emails, so timing doesn't reveal them


def normalise_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL.match(email) or len(email) > 320:
        raise AccountError("invalid_email", "Enter a valid email address.")
    return email


def check_strength(password: str, email: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AccountError("weak", f"Use at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise AccountError("weak", f"Use at most {MAX_PASSWORD} characters.")
    if password.strip().lower() in {email, email.split("@")[0]}:
        raise AccountError("weak", "Don't use your email address as your password.")
    if len(set(password)) < 4:
        raise AccountError("weak", "That password is too easy to guess.")


# --- one-time codes -------------------------------------------------------------------------


def _code_hash(row_id: str, code: str) -> str:
    key = get_settings().api_jwt_secret.encode()
    return hmac.new(key, f"{row_id}:{code}".encode(), hashlib.sha256).hexdigest()


def _recently_sent(db: Session, user: User, purpose: str) -> bool:
    return db.scalar(select(EmailToken.id).where(
        EmailToken.user_id == user.id, EmailToken.purpose == purpose,
        EmailToken.created_at > datetime.now(UTC) - RESEND_GAP).limit(1)) is not None


def _issue(db: Session, user: User, purpose: str) -> str:
    """A fresh code; earlier unused codes of the same kind stop working."""
    import uuid

    now = datetime.now(UTC)
    db.execute(update(EmailToken).where(EmailToken.user_id == user.id, EmailToken.purpose == purpose,
                                        EmailToken.used_at.is_(None)).values(used_at=now))
    code = f"{secrets.randbelow(10**6):06d}"
    row_id = uuid.uuid4()
    db.add(EmailToken(id=row_id, user_id=user.id, purpose=purpose, token_hash=_code_hash(str(row_id), code),
                      expires_at=now + timedelta(minutes=CODE_MINUTES)))
    return code


def _code_mail(db: Session, user: User, purpose: str) -> Mail:
    code = _issue(db, user, purpose)
    return Mail(user.email, emails.code_email(purpose=purpose, name=user.name, code=code, minutes=CODE_MINUTES))


def _check_code(db: Session, email: str, code: str, purpose: str) -> User:
    """The user whose latest code of this kind this is. A wrong code counts against that code; the
    fifth wrong try retires it. Unknown emails get the same answer as a wrong code."""
    code = re.sub(r"\D", "", code or "")
    try:
        email = normalise_email(email)
    except AccountError:
        raise AccountError("invalid_code", "That code isn't right.") from None
    user = db.scalar(select(User).where(User.email == email))
    row = db.scalar(select(EmailToken).where(EmailToken.user_id == user.id, EmailToken.purpose == purpose,
                                             EmailToken.used_at.is_(None))
                    .order_by(EmailToken.created_at.desc()).limit(1)) if user else None
    if row is None:
        raise AccountError("invalid_code", "That code isn't right.")
    now = datetime.now(UTC)
    if row.expires_at <= now:
        raise AccountError("expired", "That code has expired. Ask for a new one.")
    if not _CODE.match(code) or not hmac.compare_digest(row.token_hash, _code_hash(str(row.id), code)):
        row.attempts += 1
        if row.attempts >= CODE_TRIES:
            row.used_at = now
            db.commit()
            raise AccountError("too_many", "Too many wrong tries. Ask for a new code.")
        db.commit()
        left = CODE_TRIES - row.attempts
        raise AccountError("invalid_code", f"That code isn't right. {left} {'try' if left == 1 else 'tries'} left.")
    row.used_at = now
    return user


# --- what the website asks for -------------------------------------------------------------------


def register(db: Session, name: str, email: str, password: str) -> list[Mail]:
    """Creates (or updates, while unconfirmed) a password account and emails a code.
    Says the same thing whether or not the address already has an account."""
    email = normalise_email(email)
    check_strength(password, email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=name.strip()[:200] or email.split("@")[0], auth_provider="password")
        db.add(user)
        db.flush()
    cred = db.get(PasswordCredential, user.id)
    if cred is not None and cred.verified_at is not None:
        if _recently_sent(db, user, "notice"):
            return []
        db.add(EmailToken(user_id=user.id, purpose="notice", token_hash=secrets.token_hex(32),
                          expires_at=datetime.now(UTC), used_at=datetime.now(UTC)))  # rate-limits the notice
        return [Mail(email, emails.already_registered_email(name=user.name))]
    if cred is None:
        cred = PasswordCredential(user_id=user.id, password_hash=hash_password(password))
        db.add(cred)
    else:
        cred.password_hash = hash_password(password)  # still unconfirmed: the latest sign-up wins
    db.flush()
    return [] if _recently_sent(db, user, "verify") else [_code_mail(db, user, "verify")]


def login(db: Session, email: str, password: str) -> User:
    try:
        email = normalise_email(email)
    except AccountError:
        raise AccountError("invalid") from None
    user = db.scalar(select(User).where(User.email == email))
    cred = db.get(PasswordCredential, user.id) if user else None
    if cred is None:
        check_password(password, _DUMMY)
        raise AccountError("invalid")
    now = datetime.now(UTC)
    if cred.locked_until and cred.locked_until > now:
        raise AccountError("locked")
    if not check_password(password, cred.password_hash):
        cred.failed_attempts += 1
        if cred.failed_attempts >= MAX_FAILURES:
            cred.failed_attempts, cred.locked_until = 0, now + LOCK_FOR
        db.commit()
        raise AccountError("invalid")
    if cred.verified_at is None:
        raise AccountError("unverified")
    cred.failed_attempts, cred.locked_until = 0, None
    db.commit()
    return user


def verify(db: Session, email: str, code: str) -> User:
    """The code from the sign-up email: confirms the address and signs the person in."""
    user = _check_code(db, email, code, "verify")
    cred = db.get(PasswordCredential, user.id)
    if cred is None:
        raise AccountError("invalid_code", "That code isn't right.")
    cred.verified_at = cred.verified_at or datetime.now(UTC)
    cred.failed_attempts, cred.locked_until = 0, None
    db.commit()
    return user


def resend(db: Session, email: str) -> list[Mail]:
    try:
        email = normalise_email(email)
    except AccountError:
        return []
    user = db.scalar(select(User).where(User.email == email))
    cred = db.get(PasswordCredential, user.id) if user else None
    if cred is None or cred.verified_at is not None or _recently_sent(db, user, "verify"):
        return []
    return [_code_mail(db, user, "verify")]


def forgot(db: Session, email: str) -> list[Mail]:
    """Emails a reset code to any real account (also one added to a project by an admin that never
    signed in, which then gets a password). Says nothing about whether the address exists."""
    try:
        email = normalise_email(email)
    except AccountError:
        return []
    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.auth_provider == "demo" or _recently_sent(db, user, "reset"):
        return []
    return [_code_mail(db, user, "reset")]


def reset(db: Session, email: str, code: str, password: str) -> User:
    try:
        check_strength(password, normalise_email(email))  # before the code is used up
    except AccountError as e:
        if e.code == "invalid_email":
            raise AccountError("invalid_code", "That code isn't right.") from None
        raise
    user = _check_code(db, email, code, "reset")
    cred = db.get(PasswordCredential, user.id)
    if cred is None:
        cred = PasswordCredential(user_id=user.id, password_hash="")
        db.add(cred)
    cred.password_hash = hash_password(password)
    cred.verified_at = cred.verified_at or datetime.now(UTC)  # the code proved they own the address
    cred.failed_attempts, cred.locked_until = 0, None
    db.commit()
    return user


def forget_unconfirmed(db: Session, user: User) -> None:
    """The address's owner signed in another way (GitHub): a password someone set for it but never
    confirmed is dropped, so it can't be confirmed into their account later."""
    cred = db.get(PasswordCredential, user.id)
    if cred is not None and cred.verified_at is None:
        db.delete(cred)
        db.execute(update(EmailToken).where(EmailToken.user_id == user.id, EmailToken.purpose == "verify",
                                            EmailToken.used_at.is_(None)).values(used_at=datetime.now(UTC)))
        db.commit()
