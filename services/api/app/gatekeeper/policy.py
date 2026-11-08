"""The access rules, written once as plain functions.

Both Gatekeeper backends follow these rules: the local backend evaluates them
directly, and the OpenFGA backend writes tuples that encode the same thing
(see infra/openfga/model.fga). tests/test_gatekeeper.py holds them to that.
"""

import uuid
from dataclasses import dataclass, field

from app.db.models import Role, Sensitivity

APPROVER_ROLES = {Role.admin, Role.approver}


@dataclass(frozen=True)
class Principal:
    """One user's standing inside one project."""

    user_id: uuid.UUID
    roles: frozenset[Role] = field(default_factory=frozenset)
    clearances: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_member(self) -> bool:
        return bool(self.roles)

    def has(self, *roles: Role) -> bool:
        return bool(self.roles & set(roles))


def cleared_for(p: Principal, label: Sensitivity) -> bool:
    if not p.is_member:
        return False
    if label == Sensitivity.team:
        return True
    if label == Sensitivity.restricted:
        return p.has(*APPROVER_ROLES) or bool(p.clearances & {"restricted", "confidential"})
    # Confidential (HR, finance, personal) needs an explicit clearance, whatever the role.
    return "confidential" in p.clearances


def can_read_source(p: Principal, source_readers: list[uuid.UUID]) -> bool:
    if not p.is_member:
        return False
    return not source_readers or p.user_id in source_readers


def can_view_evidence(p: Principal, source_readers: list[uuid.UUID], label: Sensitivity) -> bool:
    return can_read_source(p, source_readers) and cleared_for(p, label)


# --- actions ------------------------------------------------------------

def can_manage_project(p: Principal) -> bool:
    return p.has(Role.admin)


def can_start_run(p: Principal) -> bool:
    return p.has(Role.admin, Role.approver)


def can_view_ledger(p: Principal) -> bool:
    return p.has(Role.admin, Role.approver)


def can_review(p: Principal) -> bool:
    """Approve, edit or reject claims, and publish. Admin is deliberately not
    enough: publishing is the approver's sign-off."""
    return p.has(Role.approver)
