"""Role-based access helpers for booking/service management UI.

Reuses the existing role system (accounts.UserRole -> accounts.Role) instead of
introducing a parallel role mechanism. ``is_superuser`` is supported as a
fallback so the dashboards remain testable by an admin account.
"""
from django.contrib.auth.mixins import LoginRequiredMixin

from apps.accounts.models import OwnerProfile, Role


BOOKING_ACCESS_DENIED_MESSAGE = 'Bạn không có quyền truy cập booking này.'
BOOKING_MANAGE_DENIED_MESSAGE = 'Bạn không có quyền thao tác trên booking này.'


def user_has_role(user, role_name):
    """Return True if the user is linked to the given Role.name via UserRole."""
    if not user or not user.is_authenticated:
        return False
    return user.user_roles.filter(role__name=role_name).exists()


def is_staff_member(user):
    """Staff = users with the STAFF role (superuser allowed as fallback)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user_has_role(user, Role.STAFF)


def is_admin(user):
    """Admin = active users with the ADMIN role (superuser allowed)."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return user_has_role(user, Role.ADMIN)


def is_owner(user):
    """Owner = users with the OWNER role (superuser allowed as fallback)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user_has_role(user, Role.OWNER)


def can_manage_owner_bookings(user):
    """Owner booking dashboard is only for OWNER role users who are not admins."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    return user_has_role(user, Role.OWNER) and not is_admin(user)


def can_manage_owner_assets(user):
    """True for venue owners, verified owner profiles, or admins."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if is_admin(user) or is_owner(user):
        return True
    return OwnerProfile.objects.filter(user=user, is_verified=True).exists()


def get_owner_profile(user):
    """Return the user's OwnerProfile or None."""
    if not user or not user.is_authenticated:
        return None
    return OwnerProfile.objects.filter(user=user).first()


def get_booking_queryset_for_user(user, queryset=None):
    """Return the customer-facing booking history queryset for this user only."""
    if queryset is None:
        from apps.bookings.models import Booking
        queryset = Booking.objects.all()
    if not user or not user.is_authenticated:
        return queryset.none()
    return queryset.filter(booking_package__user=user)


def user_owns_booking(user, booking):
    """True only when the booking belongs to the logged-in customer."""
    if not user or not user.is_authenticated or not booking:
        return False
    try:
        return booking.booking_package.user_id == user.id
    except AttributeError:
        return False


def can_view_booking(user, booking):
    """Read access for booking-aware pages that support customer/staff/owner scopes."""
    if user_owns_booking(user, booking):
        return True
    if is_staff_member(user):
        return True
    owner_profile = get_owner_profile(user)
    if owner_profile and getattr(booking, 'venue_id', None) and booking.venue.owner_id == owner_profile.id:
        return True
    return False


def can_manage_booking(user, booking):
    """Customer mutation routes are limited to the user who owns the booking."""
    return user_owns_booking(user, booking)


class StaffRequiredMixin(LoginRequiredMixin):
    """Require login + STAFF role (or superuser). Returns 403 otherwise."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not is_staff_member(request.user):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('Bạn không có quyền truy cập trang quản lý booking hệ thống.')
        return super().dispatch(request, *args, **kwargs)


class AdminRequiredMixin(LoginRequiredMixin):
    """Require login + ADMIN role (or superuser). Returns 403 otherwise."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not is_admin(request.user):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('Bạn không có quyền truy cập chức năng quản trị này.')
        return super().dispatch(request, *args, **kwargs)


class OwnerAssetRequiredMixin(LoginRequiredMixin):
    """Require an owner-capable account for owner venue/field management."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not can_manage_owner_assets(request.user):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('Bạn không có quyền quản lý sân của chủ sân.')
        return super().dispatch(request, *args, **kwargs)


class OwnerRequiredMixin(LoginRequiredMixin):
    """Require login + OWNER role (or superuser). Returns 403 otherwise.

    Note: having the role grants access to the page; the absence of an
    OwnerProfile is handled inside the view as a safe empty state rather than a
    hard error.
    """

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not is_owner(request.user):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('Bạn không có quyền truy cập trang quản lý sân của chủ sân.')
        return super().dispatch(request, *args, **kwargs)


class OwnerBookingRequiredMixin(LoginRequiredMixin):
    """Require OWNER role and explicitly exclude ADMIN accounts."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not can_manage_owner_bookings(request.user):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('Bạn không có quyền truy cập trang quản lý booking của chủ sân.')
        return super().dispatch(request, *args, **kwargs)
