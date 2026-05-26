"""Row-level per-action permission checks (ADR-0009 Settings polish).

Companion to ``users.role`` and ``users.accessible_groups``: this module
resolves whether a given user is allowed to perform a specific action on a
specific scope (typically a group name), backed by the ``user_permissions``
table populated through the Settings UI.

Design notes
------------
- **Admins bypass.** ``role == 'admin'`` returns True for every check; we
  do not require explicit rows in ``user_permissions`` for admins. This
  matches the existing intuition for the role and keeps the bootstrap
  story sane (a freshly-seeded admin can immediately do everything).
- **No per-request cache.** Permission changes must take effect on the
  very next request. Caching across a request lifetime is fine and the
  cost is one indexed lookup per check.
- **Scope semantics.** A row with ``scope = '*'`` grants the action on
  any scope. Otherwise the row's scope must equal the requested scope
  string (e.g. the host's ``group_name``). We deliberately keep matching
  exact-string (no glob) to avoid surprising matches; if the operator
  wants the action on three groups, they grant three rows.
- **Unknown scope.** If the caller passes ``scope=None`` we treat it as
  "no specific scope" and require a ``*`` grant. That keeps callers that
  haven't been refactored yet safe by default.

Wired enforcement
-----------------
Today only ``POST /v1/admin/commands`` consults this module (see
``routers/commands.py``). The other privileged endpoints still rely on
``role`` + ``accessible_groups`` — they will migrate to ``require_permission``
as the rest of ADR-0009 lands.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.models import User, UserPermission


# Canonical list of actions the UI is allowed to grant. Kept tight on
# purpose: every new action should land alongside the enforcement that
# consumes it, otherwise it's just dead config.
ALLOWED_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "command.issue",
        "command.approve",
        "host.delete",
        "enroll.create",
    }
)


def is_action_allowed(action: str) -> bool:
    """Whether ``action`` is in the canonical enum.

    Centralised so the API layer and the test suite agree on the
    membership rule without import cycles.
    """
    return action in ALLOWED_ACTIONS


async def user_has_permission(
    db: AsyncSession,
    user: User,
    action: str,
    scope: str | None = None,
) -> bool:
    """Return True if ``user`` may perform ``action`` on ``scope``.

    Resolution order:

    1. ``user.role == 'admin'`` -> True (always).
    2. Any ``user_permissions`` row with ``(user_id, action, scope='*')``
       -> True. A wildcard grant beats per-scope grants.
    3. If ``scope`` is provided, any row with that exact ``scope`` ->
       True.
    4. Otherwise -> False.

    The query is a single indexed lookup (``idx_user_permissions_user``
    plus the unique constraint) so we make no attempt to cache across
    requests — admins running the Settings UI need permission changes
    to apply on the very next API call.
    """
    if not user.is_active:
        return False
    if user.role == "admin":
        return True

    scopes_to_try: list[str] = ["*"]
    if scope is not None and scope != "*":
        scopes_to_try.append(scope)

    stmt = (
        select(UserPermission.id)
        .where(UserPermission.user_id == user.id)
        .where(UserPermission.action == action)
        .where(UserPermission.scope.in_(scopes_to_try))
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None
