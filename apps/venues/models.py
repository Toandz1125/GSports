from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from .pricing import resolve_pricing_payload_rules, validate_price_rule_payloads


class Sport(models.Model):
    """Môn thể thao."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    icon = models.CharField(max_length=50, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'sport'

    def __str__(self):
        return self.name


class Venue(models.Model):
    """Cơ sở thể thao."""

    ACTIVE = 'ACTIVE'
    INACTIVE = 'INACTIVE'
    ADMIN_STATUS_CHOICES = [
        (ACTIVE, 'Đang hoạt động'),
        (INACTIVE, 'Tạm ngưng'),
    ]

    owner = models.ForeignKey(
        'accounts.OwnerProfile',
        on_delete=models.CASCADE,
        related_name='venues',
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    address = models.CharField(max_length=500)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True)
    status = models.CharField(max_length=20, default='ACTIVE')
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'venue'

    def __str__(self):
        return self.name

    @property
    def is_active_status(self):
        return self.status == self.ACTIVE

    @property
    def can_admin_deactivate(self):
        return not self.is_deleted and self.status != self.INACTIVE

    @property
    def can_admin_restore(self):
        return self.is_deleted or self.status != self.ACTIVE


class VenueRegistrationRequest(models.Model):
    """Owner-submitted request for admin approval before a venue is created."""

    PENDING = 'PENDING'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    CANCELLED = 'CANCELLED'
    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'),
        (CANCELLED, 'Cancelled'),
    ]

    owner = models.ForeignKey(
        'accounts.OwnerProfile',
        on_delete=models.CASCADE,
        related_name='venue_registration_requests',
    )
    venue_name = models.CharField(max_length=255)
    venue_address = models.CharField(max_length=500)
    venue_note = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='reviewed_venue_registration_requests',
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    rejection_reason = models.TextField(blank=True)
    approved_venue = models.OneToOneField(
        Venue,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='registration_request',
    )

    class Meta:
        db_table = 'venue_registration_request'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['owner', 'status']),
            models.Index(fields=['created_at']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(status__in=['PENDING', 'APPROVED', 'REJECTED', 'CANCELLED']),
                name='venue_registration_request_status_valid',
            ),
        ]

    def __str__(self):
        return f'{self.venue_name} ({self.status})'


class OwnerVenueRequest(models.Model):
    """Owner request that requires admin approval before mutating venues."""

    CREATE = 'CREATE'
    UPDATE = 'UPDATE'
    DELETE = 'DELETE'
    REQUEST_TYPE_CHOICES = [
        (CREATE, 'Tạo cơ sở'),
        (UPDATE, 'Cập nhật cơ sở'),
        (DELETE, 'Hủy cơ sở'),
    ]

    PENDING = 'PENDING'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    STATUS_CHOICES = [
        (PENDING, 'Đang chờ'),
        (APPROVED, 'Đã duyệt'),
        (REJECTED, 'Đã từ chối'),
    ]

    requested_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='owner_venue_requests',
    )
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPE_CHOICES)
    target_venue = models.ForeignKey(
        Venue,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='owner_venue_requests',
    )
    payload = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    reason = models.TextField(blank=True)
    admin_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='reviewed_owner_venue_requests',
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'owner_venue_request'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['request_type', 'status']),
            models.Index(fields=['requested_by', 'status']),
            models.Index(fields=['created_at']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(request_type__in=['CREATE', 'UPDATE', 'DELETE']),
                name='owner_venue_request_type_valid',
            ),
            models.CheckConstraint(
                check=models.Q(status__in=['PENDING', 'APPROVED', 'REJECTED']),
                name='owner_venue_request_status_valid',
            ),
        ]

    @property
    def venue_name(self):
        if self.request_type == self.DELETE and self.target_venue_id:
            return self.target_venue.name
        return (self.payload or {}).get('name') or ''

    @property
    def venue_address(self):
        if self.request_type == self.DELETE and self.target_venue_id:
            return self.target_venue.address
        return (self.payload or {}).get('address') or ''

    @property
    def venue_note(self):
        return (self.payload or {}).get('description') or self.reason

    @property
    def owner_profile(self):
        try:
            return self.requested_by.owner_profile
        except ObjectDoesNotExist:
            return None

    def clean(self):
        errors = {}
        payload = self.payload or {}

        if self.request_type in {self.CREATE, self.UPDATE}:
            if not isinstance(payload, dict):
                errors['payload'] = 'Payload phải là object.'
            else:
                if not (payload.get('name') or '').strip():
                    errors['payload'] = 'Payload tạo/cập nhật cơ sở cần có tên cơ sở.'
                if not (payload.get('address') or '').strip():
                    errors['payload'] = 'Payload tạo/cập nhật cơ sở cần có địa chỉ.'
                if self.request_type == self.CREATE and payload.get('fields'):
                    field_payloads = payload.get('fields') or []
                    if not isinstance(field_payloads, list):
                        errors['payload'] = 'Payload sân con không hợp lệ.'
                    elif field_payloads:
                        for index, field_payload in enumerate(field_payloads, start=1):
                            if not isinstance(field_payload, dict):
                                errors['payload'] = f'Sân con #{index} không hợp lệ.'
                                break
                            if not (field_payload.get('name') or '').strip():
                                errors['payload'] = f'Sân con #{index} cần có tên sân.'
                                break
                            field_type_id = field_payload.get('field_type')
                            if not field_type_id or not FieldType.objects.filter(pk=field_type_id).exists():
                                errors['payload'] = f'Sân con #{index} cần có loại sân hợp lệ.'
                                break
                    if self.request_type == self.CREATE and 'payload' not in errors:
                        try:
                            price_rules = resolve_pricing_payload_rules(payload.get('pricing'))
                            validate_price_rule_payloads(price_rules)
                        except ValidationError as exc:
                            errors['payload'] = exc.messages[0] if getattr(exc, 'messages', None) else str(exc)

        if self.request_type in {self.UPDATE, self.DELETE} and not self.target_venue_id:
            errors['target_venue'] = 'Yêu cầu cập nhật hoặc hủy sân cần target_venue.'

        if self.requested_by_id:
            from apps.accounts.models import Role

            is_owner_user = (
                self.requested_by.is_superuser
                or self.requested_by.user_roles.filter(role__name=Role.OWNER).exists()
            )
            if not is_owner_user:
                errors['requested_by'] = 'Chỉ tài khoản OWNER được tạo yêu cầu sân.'

        if self.target_venue_id and self.requested_by_id and not self.requested_by.is_superuser:
            if self.target_venue.owner.user_id != self.requested_by_id:
                errors['target_venue'] = 'Owner chỉ được tạo yêu cầu cho sân thuộc sở hữu của mình.'

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.get_request_type_display()} - {self.venue_name or "Venue"} ({self.status})'


class FieldCreationRequest(models.Model):
    """Owner request that requires admin approval before creating a field."""

    ACTIVE = 'ACTIVE'
    MAINTENANCE = 'MAINTENANCE'
    INACTIVE = 'INACTIVE'
    FIELD_STATUS_CHOICES = [
        (ACTIVE, 'Hoạt động'),
        (MAINTENANCE, 'Bảo trì'),
        (INACTIVE, 'Ngừng hoạt động'),
    ]

    PENDING = 'PENDING'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    STATUS_CHOICES = [
        (PENDING, 'Đang chờ'),
        (APPROVED, 'Đã duyệt'),
        (REJECTED, 'Đã từ chối'),
    ]

    owner = models.ForeignKey(
        'accounts.OwnerProfile',
        on_delete=models.CASCADE,
        related_name='field_creation_requests',
    )
    venue = models.ForeignKey(
        Venue,
        on_delete=models.CASCADE,
        related_name='field_creation_requests',
    )
    field_type = models.ForeignKey(
        'venues.FieldType',
        on_delete=models.PROTECT,
        related_name='field_creation_requests',
    )
    name = models.CharField(max_length=100)
    capacity = models.IntegerField(blank=True, null=True)
    surface_type = models.CharField(max_length=50, blank=True, null=True)
    length = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    width = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    field_status = models.CharField(max_length=20, choices=FIELD_STATUS_CHOICES, default=ACTIVE)
    pricing_payload = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    reject_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='reviewed_field_creation_requests',
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'field_creation_request'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['owner', 'status']),
            models.Index(fields=['venue', 'status']),
            models.Index(fields=['created_at']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(field_status__in=['ACTIVE', 'MAINTENANCE', 'INACTIVE']),
                name='field_creation_request_field_status_valid',
            ),
            models.CheckConstraint(
                check=models.Q(status__in=['PENDING', 'APPROVED', 'REJECTED']),
                name='field_creation_request_status_valid',
            ),
        ]

    def clean(self):
        errors = {}
        if self.owner_id and self.venue_id and self.venue.owner_id != self.owner_id:
            errors['venue'] = 'Owner chỉ được gửi yêu cầu tạo sân cho cơ sở thuộc sở hữu của mình.'
        if self.venue_id and getattr(self.venue, 'is_deleted', False):
            errors['venue'] = 'Không thể tạo sân cho cơ sở đã bị xóa.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.name} - {self.venue.name if self.venue_id else "Venue"} ({self.status})'


class VenueOperatingHour(models.Model):
    """Giờ hoạt động theo ngày trong tuần."""

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='operating_hours')
    weekday = models.SmallIntegerField(help_text='0=Monday, 6=Sunday')
    open_time = models.TimeField()
    close_time = models.TimeField()

    class Meta:
        db_table = 'venue_operating_hour'
        unique_together = ('venue', 'weekday')

    def __str__(self):
        days = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']
        return f'{self.venue.name} — {days[self.weekday]}: {self.open_time}-{self.close_time}'


class VenueImage(models.Model):
    """Ảnh cơ sở."""

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='venue_images/')
    is_thumbnail = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'venue_image'
        ordering = ['sort_order']

    def __str__(self):
        return f'{self.venue.name} — img#{self.sort_order}'


class FieldType(models.Model):
    """Loại sân (Sân 5, Sân 7, Sân đơn...)."""

    sport = models.ForeignKey(Sport, on_delete=models.CASCADE, related_name='field_types')
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    icon = models.CharField(max_length=50, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    player_count = models.IntegerField()
    status = models.CharField(max_length=20, default='ACTIVE')

    class Meta:
        db_table = 'field_type'
        unique_together = ('sport', 'name')

    def __str__(self):
        return f'{self.sport.name} — {self.name}'


class Field(models.Model):
    """Sân con thuộc cơ sở."""

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='fields')
    field_type = models.ForeignKey(FieldType, on_delete=models.CASCADE, related_name='fields')
    name = models.CharField(max_length=100)
    capacity = models.IntegerField(blank=True, null=True)
    surface_type = models.CharField(max_length=50, blank=True, null=True)
    length = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    width = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    status = models.CharField(max_length=20, default='ACTIVE')

    class Meta:
        db_table = 'field'

    def __str__(self):
        return f'{self.venue.name} — {self.name}'


class FieldPriceRule(models.Model):
    """Bảng giá sân theo khung giờ và ngày."""

    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name='price_rules')
    day_of_week = models.SmallIntegerField(blank=True, null=True, help_text='Null = tất cả các ngày')
    start_time = models.TimeField()
    end_time = models.TimeField()
    price_per_hour = models.DecimalField(max_digits=10, decimal_places=2)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    priority = models.IntegerField(default=0)
    is_holiday = models.BooleanField(default=False)
    special_event = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'field_price_rule'
        indexes = [
            models.Index(fields=['field', 'day_of_week', 'start_time']),
        ]

    def __str__(self):
        return f'{self.field.name}: {self.start_time}-{self.end_time} = {self.price_per_hour:,.0f}đ/h'


class VenuePolicy(models.Model):
    """Chính sách huỷ/hoàn tiền của cơ sở."""

    venue = models.OneToOneField(Venue, on_delete=models.CASCADE, related_name='policy')
    cancel_before_hours = models.IntegerField()
    refund_percent = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        db_table = 'venue_policy'

    def __str__(self):
        return f'{self.venue.name}: huỷ trước {self.cancel_before_hours}h → hoàn {self.refund_percent}%'
