"""Multi-user group filtering middleware.

F5 implementation. Filters hosts by user's accessible_groups for multi-tenant
fleet visibility in web dashboard.
"""

from sqlalchemy import Select, false

from rp_server.models import Host, User


def filter_hosts_by_user_groups(stmt: Select, user: User) -> Select:
    """Apply WHERE clause to filter hosts by user's accessible_groups.

    - Admin users see all hosts (no filter applied).
    - Non-admin users only see hosts whose group_name is in
      ``user.accessible_groups``.
    - Non-admin with empty accessible_groups → empty result set.
    """
    if user.role == "admin":
        return stmt

    if not user.accessible_groups:
        return stmt.where(false())

    return stmt.where(Host.group_name.in_(user.accessible_groups))
