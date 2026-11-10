"""The access rules, as a matrix. If one of these changes, the OpenFGA model
(app/gatekeeper/openfga.py) must change with it."""

import uuid

import pytest

from app.db.models import Role, Sensitivity
from app.gatekeeper.policy import (
    Principal,
    can_manage_project,
    can_review,
    can_view_evidence,
    can_view_ledger,
)

ME = uuid.uuid4()
OTHER = uuid.uuid4()


def who(*roles: Role, clear: tuple[str, ...] = ()) -> Principal:
    return Principal(ME, frozenset(roles), frozenset(clear))


@pytest.mark.parametrize(
    ("p", "label", "readers", "expected"),
    [
        (who(Role.successor), Sensitivity.team, [], True),
        (who(Role.successor), Sensitivity.restricted, [], False),
        (who(Role.successor, clear=("restricted",)), Sensitivity.restricted, [], True),
        (who(Role.successor, clear=("restricted",)), Sensitivity.confidential, [], False),
        (who(Role.approver), Sensitivity.restricted, [], True),
        (who(Role.approver), Sensitivity.confidential, [], False),
        (who(Role.admin), Sensitivity.restricted, [], True),
        (who(Role.admin), Sensitivity.confidential, [], False),  # role alone never unlocks confidential
        (who(Role.approver, clear=("confidential",)), Sensitivity.confidential, [], True),
        (who(Role.viewer, clear=("confidential",)), Sensitivity.restricted, [], True),  # confidential ⊇ restricted
        (who(Role.approver, clear=("confidential",)), Sensitivity.team, [OTHER], False),  # not a source reader
        (who(Role.successor), Sensitivity.team, [ME, OTHER], True),
        (who(), Sensitivity.team, [], False),  # not a member at all
        (who(clear=("confidential",)), Sensitivity.team, [ME], False),
    ],
)
def test_evidence_visibility(p, label, readers, expected):
    assert can_view_evidence(p, readers, label) is expected


def test_actions():
    assert can_manage_project(who(Role.admin)) and not can_manage_project(who(Role.approver))
    assert can_view_ledger(who(Role.admin)) and can_view_ledger(who(Role.approver))
    assert not can_view_ledger(who(Role.successor)) and not can_view_ledger(who(Role.leaver))
    # Publishing is the approver's sign-off; being admin isn't enough.
    assert can_review(who(Role.approver)) and not can_review(who(Role.admin))


def test_local_test_sign_in_is_off_unless_enabled(database, monkeypatch):
    import time

    import jwt
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    def call():
        now = int(time.time())
        token = jwt.encode({"sub": "someone@example.com", "provider": "dev", "iss": "knowbridge-web",
                            "aud": "knowbridge-api", "iat": now, "exp": now + 60}, get_settings().api_jwt_secret,
                           "HS256")
        return TestClient(app).get("/me", headers={"Authorization": f"Bearer {token}"})

    monkeypatch.setenv("DEV_LOGIN", "false")
    get_settings.cache_clear()
    assert call().status_code == 401
    monkeypatch.setenv("DEV_LOGIN", "true")
    get_settings.cache_clear()
    assert call().status_code == 200
    get_settings.cache_clear()
