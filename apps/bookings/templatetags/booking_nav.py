"""Template filters exposing booking-management role checks to the nav.

Reuses apps.bookings.permissions so templates and views share one source of
truth for who may see the staff/owner dashboards.
"""
from django import template

from apps.accounts.models import Role
from apps.bookings.permissions import (
    can_manage_owner_bookings as can_manage_owner_bookings_permission,
    is_admin,
    is_staff_member,
    user_has_role,
)

register = template.Library()


@register.filter
def can_manage_all_bookings(user):
    """True for STAFF (or superuser): may see the system booking dashboard."""
    return is_staff_member(user)


@register.filter
def can_manage_owner_bookings(user):
    """True for OWNER role users who are not admins."""
    return can_manage_owner_bookings_permission(user)


@register.filter
def can_manage_owner_services(user):
    """True for OWNER role users; admin-facing accounts should not see owner service menu."""
    return user_has_role(user, Role.OWNER) and not is_admin(user)
