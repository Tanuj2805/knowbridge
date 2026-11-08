"""Encrypts connector credentials (e.g. a Jira API token) at rest.

Uses SECRETS_KEY when set. Otherwise a key is derived from API_JWT_SECRET, so a
fresh install works without extra setup; set SECRETS_KEY in production so
rotating the JWT secret doesn't make stored tokens unreadable.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class SecretUnreadable(Exception):
    """The stored credential can't be decrypted with the current key."""


def _fernet() -> Fernet:
    s = get_settings()
    if s.secrets_key:
        return Fernet(s.secrets_key.encode())
    derived = hashlib.sha256(b"knowbridge-secretbox:" + s.api_jwt_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def seal(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def unseal(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise SecretUnreadable("The saved credential can't be read. Reconnect the source with a new token.") from e
