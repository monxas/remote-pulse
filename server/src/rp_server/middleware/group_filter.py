"""Multi-user group filtering middleware.

F5 implementation. Filters hosts by user's accessible_groups for multi-tenant
fleet visibility in web dashboard.
"""

from sqlalchemy import Select
from sqlalchemy.sql import ColumnElement

from rp_server.models import Host, User


def filter_hosts_by_user_groups(stmt: Select, user: User) -> Select:
    """Apply WHERE clause to filter hosts by user's accessible_groups.

    Admin users see all hosts regardless of group.
    Non-admin users only see hosts in groups they have access to.

    Args:
        stmt: SQLAlchemy SELECT statement for hosts query
        user: Authenticated user

    Returns:
        Modified SELECT statement with group filter applied
    """
    # Admin sees all hosts
    if user.role == "admin":
        return stmt

    # Non-admin: filter by accessible_groups
    # Host.group_name IN (user.accessible_groups)
    if not user.accessible_groups:
        # User has no groups - return empty result set
        # Use 1=0 to ensure no results but valid SQL
        return stmt.where(ColumnElement.cast(False, bool))

    return stmt.where(Host.group_name.in_(user.accessible_groups))
