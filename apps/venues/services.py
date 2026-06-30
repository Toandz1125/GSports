from django.db.models import Q

from apps.accounts.models import Notification, OwnerProfile, Role, User, UserRole


VENUE_REQUEST_NOTIFICATION_ENTITIES = (
    'OwnerVenueRequest',
    'VenueRegistrationRequest',
    'FieldCreationRequest',
)


def _request_entity_type(venue_request):
    return venue_request.__class__.__name__


def _request_entity_id(venue_request):
    return str(venue_request.pk)


def _admin_users():
    # A single filtered query (no ``.union()``) so the model's default ordering
    # does not produce ``ORDER BY`` inside a UNION subquery, which SQL Server
    # rejects ("ORDER BY not allowed in subqueries of compound statements").
    role_admin_ids = UserRole.objects.filter(role__name=Role.ADMIN).values('user_id')
    return User.objects.filter(
        Q(pk__in=role_admin_ids) | Q(is_superuser=True),
    ).distinct()


def _create_notification(user, title, content, venue_request):
    return Notification.objects.create(
        user=user,
        title=title,
        content=content,
        entity_type=_request_entity_type(venue_request),
        entity_id=_request_entity_id(venue_request),
        type=Notification.INAPP,
    )


def ensure_owner_account(user, registration_request=None):
    """Return the user's ``OwnerProfile``, creating a minimal one if needed."""
    owner_profile = getattr(user, 'owner_profile', None)
    if owner_profile is not None:
        return owner_profile

    payload = getattr(registration_request, 'payload', None) or {}
    business_name = (
        payload.get('name')
        or getattr(registration_request, 'venue_name', None)
        or user.get_full_name()
        or user.email
    )
    owner_profile, _ = OwnerProfile.objects.get_or_create(
        user=user,
        defaults={
            'business_name': business_name,
            'is_verified': True,
        },
    )
    return owner_profile


def notify_admins_about_owner_venue_request(venue_request):
    title = 'Yêu cầu sân mới cần duyệt'
    content = (
        f'{venue_request.requested_by.email} đã gửi yêu cầu '
        f'{venue_request.get_request_type_display().lower()} "{venue_request.venue_name}".'
    )
    notifications = [
        _create_notification(admin, title, content, venue_request)
        for admin in _admin_users()
    ]
    return notifications


def notify_owner_venue_request_approved(venue_request, venue):
    title = 'Yêu cầu sân đã được duyệt'
    content = f'Yêu cầu "{venue_request.venue_name}" đã được duyệt. Cơ sở "{venue.name}" đã được tạo/cập nhật.'
    return _create_notification(venue_request.requested_by, title, content, venue_request)


def notify_owner_venue_request_rejected(venue_request):
    title = 'Yêu cầu sân bị từ chối'
    reason = venue_request.admin_note or venue_request.reason or 'Không có ghi chú.'
    content = f'Yêu cầu "{venue_request.venue_name}" bị từ chối. Lý do: {reason}'
    return _create_notification(venue_request.requested_by, title, content, venue_request)


def notify_admins_about_field_creation_request(field_request):
    title = 'Yêu cầu tạo sân mới cần duyệt'
    content = (
        f'{field_request.owner.user.email} đã gửi yêu cầu tạo sân '
        f'"{field_request.name}" tại cơ sở "{field_request.venue.name}".'
    )
    return [
        _create_notification(admin, title, content, field_request)
        for admin in _admin_users()
    ]


def notify_owner_field_request_approved(field_request, field):
    title = 'Yêu cầu tạo sân đã được duyệt'
    content = f'Yêu cầu tạo sân "{field_request.name}" đã được duyệt. Sân "{field.name}" đã được tạo.'
    return _create_notification(field_request.owner.user, title, content, field_request)


def notify_owner_field_request_rejected(field_request):
    title = 'Yêu cầu tạo sân bị từ chối'
    reason = field_request.reject_reason or 'Không có ghi chú.'
    content = f'Yêu cầu tạo sân "{field_request.name}" bị từ chối. Lý do: {reason}'
    return _create_notification(field_request.owner.user, title, content, field_request)
