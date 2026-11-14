"""Email-and-password accounts, for the website's sign-in pages (confirmed with emailed codes).

Only the website's server may call these: each request carries a one-minute token signed with the
shared API_JWT_SECRET for this audience (a user's session token can't be used here). Emails go out
after the response, so how long a request takes doesn't reveal whether an address has an account.
"""

from typing import Annotated

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app import accounts, audit, mailer
from app.auth import DB, ISSUER
from app.config import get_settings

AUDIENCE = "knowbridge-accounts"


def website_only(authorization: Annotated[str | None, Header()] = None) -> None:
    raw = (authorization or "").removeprefix("Bearer ").strip()
    try:
        claims = jwt.decode(raw, get_settings().api_jwt_secret, algorithms=["HS256"], audience=AUDIENCE,
                            issuer=ISSUER, options={"require": ["exp"]})
    except jwt.PyJWTError as e:
        raise HTTPException(401, "Not allowed.") from e
    if claims.get("sub") != "web":
        raise HTTPException(401, "Not allowed.")
    if not get_settings().password_auth:
        raise HTTPException(404, "Email sign-in is turned off.")


router = APIRouter(prefix="/auth", tags=["accounts"], dependencies=[Depends(website_only)])


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=accounts.MAX_PASSWORD)


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=accounts.MAX_PASSWORD)


class EmailIn(BaseModel):
    email: str = Field(max_length=320)


class CodeIn(BaseModel):
    email: str = Field(max_length=320)
    code: str = Field(min_length=1, max_length=20)


class ResetIn(CodeIn):
    password: str = Field(min_length=1, max_length=accounts.MAX_PASSWORD)


def _send(tasks: BackgroundTasks, mails: list[accounts.Mail]) -> None:
    for m in mails:
        tasks.add_task(mailer.send, m.to, m.email.subject, m.email.text, m.email.html)


def _fail(e: accounts.AccountError, status: int = 400):
    return HTTPException(status, {"code": e.code, "message": str(e) if str(e) != e.code else ""})


@router.post("/register", status_code=202)
def register(body: RegisterIn, db: DB, tasks: BackgroundTasks) -> dict:
    try:
        mails = accounts.register(db, body.name, body.email, body.password)
    except accounts.AccountError as e:
        db.rollback()
        raise _fail(e, 422) from e
    db.commit()
    _send(tasks, mails)
    return {"ok": True}


@router.post("/login")
def login(body: LoginIn, db: DB) -> dict:
    try:
        user = accounts.login(db, body.email, body.password)
    except accounts.AccountError as e:
        raise _fail(e, 401) from e
    audit.record(db, actor_id=user.id, action="account.signin", object_type="user", object_id=user.id,
                 method="password")
    db.commit()
    return {"id": str(user.id), "email": user.email, "name": user.name}


def _signed_in(db: DB, user, action: str) -> dict:
    audit.record(db, actor_id=user.id, action=action, object_type="user", object_id=user.id)
    db.commit()
    return {"id": str(user.id), "email": user.email, "name": user.name}


@router.post("/verify")
def verify(body: CodeIn, db: DB) -> dict:
    """The sign-up code: confirms the email and signs the person in."""
    try:
        user = accounts.verify(db, body.email, body.code)
    except accounts.AccountError as e:
        db.rollback()
        raise _fail(e, 401) from e
    return _signed_in(db, user, "account.verify")


@router.post("/resend", status_code=202)
def resend(body: EmailIn, db: DB, tasks: BackgroundTasks) -> dict:
    mails = accounts.resend(db, body.email)
    db.commit()
    _send(tasks, mails)
    return {"ok": True}


@router.post("/forgot", status_code=202)
def forgot(body: EmailIn, db: DB, tasks: BackgroundTasks) -> dict:
    mails = accounts.forgot(db, body.email)
    db.commit()
    _send(tasks, mails)
    return {"ok": True}


@router.post("/reset")
def reset(body: ResetIn, db: DB) -> dict:
    """The reset code and a new password: sets it and signs the person in."""
    try:
        user = accounts.reset(db, body.email, body.code, body.password)
    except accounts.AccountError as e:
        db.rollback()
        raise _fail(e, 422 if e.code == "weak" else 401) from e
    return _signed_in(db, user, "account.reset")


@router.get("/options")
def options() -> dict:
    """What the sign-in pages can offer."""
    return {"password": True, "email_delivery": mailer.configured(), "app_name": get_settings().app_name}
