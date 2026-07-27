"""Authentication and authorisation primitives.

RBAC plus per-resident row-level checks. ``family_limited`` deliberately cannot reach live
state or media: family members get daily summaries, not a surveillance feed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fastapi import Header, HTTPException, status


class Role(StrEnum):
    CAREGIVER = "caregiver"
    NURSE = "nurse"
    ADMIN = "admin"
    FAMILY_LIMITED = "family_limited"


class Scope(StrEnum):
    READ_STATUS = "read:status"
    READ_EVENTS = "read:events"
    READ_REPORTS = "read:reports"
    READ_MEDIA = "read:media"
    WRITE_ALERTS = "write:alerts"
    WRITE_NOTES = "write:notes"
    ADMIN_IDENTITY = "admin:identity"
    READ_AUDIT = "read:audit"


ROLE_SCOPES: dict[Role, frozenset[Scope]] = {
    Role.CAREGIVER: frozenset(
        {
            Scope.READ_STATUS,
            Scope.READ_EVENTS,
            Scope.READ_REPORTS,
            Scope.READ_MEDIA,
            Scope.WRITE_ALERTS,
            Scope.WRITE_NOTES,
        }
    ),
    Role.NURSE: frozenset(
        {
            Scope.READ_STATUS,
            Scope.READ_EVENTS,
            Scope.READ_REPORTS,
            Scope.READ_MEDIA,
            Scope.WRITE_ALERTS,
            Scope.WRITE_NOTES,
        }
    ),
    Role.ADMIN: frozenset(Scope),
    # No live status, no media: summaries and alerts only.
    Role.FAMILY_LIMITED: frozenset({Scope.READ_REPORTS}),
}


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated actor. Every audited action records this."""

    actor_id: str
    role: Role
    resident_ids: frozenset[str]

    @property
    def scopes(self) -> frozenset[Scope]:
        return ROLE_SCOPES[self.role]

    def require(self, scope: Scope) -> None:
        if scope not in self.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role {self.role.value} lacks {scope.value}",
            )

    def require_resident(self, resident_id: str) -> None:
        """Row-level authorisation: role alone never grants access to a resident."""
        if self.role is not Role.ADMIN and resident_id not in self.resident_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="resident not found"
            )


async def current_principal(
    x_actor_id: str = Header(default="dev-caregiver"),
    x_actor_role: str = Header(default="caregiver"),
    x_actor_residents: str = Header(default=""),
) -> Principal:
    """Development stand-in for OIDC bearer validation.

    Production replaces this dependency with JWT verification against the identity
    provider. The rest of the API is unchanged because it only depends on ``Principal``.
    """
    try:
        role = Role(x_actor_role)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="unknown role") from exc
    residents = frozenset(r for r in x_actor_residents.split(",") if r)
    return Principal(actor_id=x_actor_id, role=role, resident_ids=residents)
