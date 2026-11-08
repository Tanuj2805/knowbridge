"""Who is calling.

The web app signs users in (OAuth or demo personas) and, for every API call it
makes on their behalf, mints a short-lived HS256 token. This module checks
that token and returns the matching user, creating them on first sight.
"""

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import User
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


def current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    claims = _decode(authorization.split(" ", 1)[1])
    provider = claims.get("provider", "unknown")
    if provider == "demo" and not get_settings().demo_mode:
        raise HTTPException(status_code=401, detail="Demo sign-in is turned off.")

    email = str(claims["sub"]).strip().lower()
    user = db.scalar(select(User).where(User.email == email))
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
