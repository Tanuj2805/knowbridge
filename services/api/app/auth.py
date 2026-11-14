"""Who is calling.

The web app signs users in (OAuth or demo personas) and, for every API call it
makes on their behalf, mints a short-lived HS256 token. This module checks
that token and returns the matching user, creating them on first sight.

The editor extension and MCP server use a personal access token instead
("kb_..."), made by the user in KnowBridge. It is read-only and tied to one
project: it reaches only the routes in TOKEN_ROUTES, only for that project,
and everything behind them still goes through the same permission checks.
"""

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import ApiToken, User
from app.db.session import get_db
from app.gatekeeper import principal
from app.gatekeeper.policy import Principal

ISSUER = "knowbridge-web"
AUDIENCE = "knowbridge-api"


def _decode(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            get_settings().api_jwt_secret,
            algorithms=["HS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail="Your session has expired. Sign in again.") from e


# --- personal access tokens ------------------------------------------------------------

TOKEN_PREFIX = "kb_"  # noqa: S105 - the visible start of every token, not a secret
_UUID = r"[0-9a-fA-F-]{36}"
# What a token may do: read and search one project, and ask its chat. Nothing that changes anything.
TOKEN_ROUTES = [
    ("GET", re.compile(r"^/token$")),
    ("GET", re.compile(r"^/projects/resolve$")),
    ("GET", re.compile(rf"^/projects/(?P<project>{_UUID})$")),
    ("GET", re.compile(rf"^/projects/(?P<project>{_UUID})/code-context$")),
    ("GET", re.compile(rf"^/projects/(?P<project>{_UUID})/claims/{_UUID}$")),
    ("GET", re.compile(rf"^/projects/(?P<project>{_UUID})/evidence/{_UUID}$")),
    ("GET", re.compile(rf"^/projects/(?P<project>{_UUID})/rag/status$")),
    ("POST", re.compile(rf"^/projects/(?P<project>{_UUID})/rag/(ask|retrieve)$")),
]


def new_token() -> tuple[str, str, str]:
    """A fresh token, its hash (stored) and its prefix (shown in lists)."""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_token(raw), raw[:9]


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _token_user(db: Session, raw: str, request: Request) -> User:
    now = datetime.now(UTC)
    row = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(raw)))
    if row is None or row.revoked_at or (row.expires_at and row.expires_at <= now):
        raise HTTPException(status_code=401, detail="This access token isn't valid any more. Make a new one in "
                                                    "KnowBridge.")
    path = request.url.path.rstrip("/") or "/"
    match = next((m for method, rx in TOKEN_ROUTES if method == request.method and (m := rx.match(path))), None)
    if match is None:
        raise HTTPException(status_code=403, detail="Access tokens are read-only: they can read, search and ask "
                                                    "the chat, nothing else.")
    project = match.groupdict().get("project")
    if project and project.lower() != str(row.project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    if row.last_used_at is None or now - row.last_used_at > timedelta(minutes=1):
        row.last_used_at = now
        db.commit()
    request.state.api_token = row
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="This access token isn't valid any more.")
    return user


def token_of(request: Request) -> ApiToken | None:
    """The access token this request came with, if it came with one."""
    return getattr(request.state, "api_token", None)


def current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    raw = authorization.split(" ", 1)[1].strip()
    if raw.startswith(TOKEN_PREFIX):
        return _token_user(db, raw, request)
    claims = _decode(raw)
    provider = claims.get("provider", "unknown")
    if provider == "demo" and not get_settings().demo_mode:
        raise HTTPException(status_code=401, detail="Demo sign-in is turned off.")
    if provider == "dev" and not get_settings().dev_login:
        raise HTTPException(status_code=401, detail="Local test sign-in is turned off.")

    email = str(claims["sub"]).strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is not None and provider in ("google", "github"):
        from app import accounts

        accounts.forget_unconfirmed(db, user)  # an unconfirmed password for this address can't linger
    if user is None:
        user = User(
            email=email,
            name=claims.get("name") or email.split("@")[0],
            avatar_url=claims.get("picture"),
            auth_provider=provider,
        )
        db.add(user)
        db.commit()
    elif claims.get("picture") and user.avatar_url != claims["picture"]:
        user.avatar_url = claims["picture"]
        db.commit()
    return user


CurrentUser = Annotated[User, Depends(current_user)]
DB = Annotated[Session, Depends(get_db)]


def project_principal(project_id: uuid.UUID, user: CurrentUser, db: DB) -> Principal:
    """Dependency for /projects/{project_id}/... routes: the caller's standing,
    with a 404 (not 403) for non-members so project ids don't leak."""
    p = principal(db, project_id, user.id)
    if not p.is_member:
        raise HTTPException(status_code=404, detail="Project not found.")
    return p


ProjectPrincipal = Annotated[Principal, Depends(project_principal)]
