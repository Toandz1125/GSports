import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import models
from django.utils import timezone

from .validators import validate_booking_time_range


def _merge_validation_error(errors, exc):
    if hasattr(exc, 'message_dict'):
        for field, messages in exc.message_dict.items():
            errors.setdefault(field, []).extend(messages)
        return
    errors.setdefault(NON_FIELD_ERRORS, []).extend(exc.messages)


class BookingPackage(models.Model):
    """Gói đặt sân (single hoặc recurring)."""

    SINGLE = 'SINGLE'
    RECURRING = 'RECURRING'
    PACKAGE_TYPE_CHOICES = [
        (SINGLE, 'Single'),
        (RECURRING, 'Recurring'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='booking_packages')
    package_type = models.CharField(max_length=20, choices=PACKAGE_TYPE_CHOICES)
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    refund_amount_applied = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = 'booking_package'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.package_type} — {self.user.email} ({self.start_date})'

    def clean(self):
        errors = {}
        if self.end_date and self.start_date and self.end_date < self.start_date:
            errors['end_date'] = 'End date must be greater than or equal to start date.'
        if errors:
            raise ValidationError(errors)


class BookingRecurrenceDay(models.Model):
    """Ngày lặp lại trong tuần cho gói recurring."""

    booking_package = models.ForeignKey(
        BookingPackage, on_delete=models.CASCADE, related_name='recurrence_days',
    )
    weekday = models.SmallIntegerField(help_text='0=Monday, 6=Sunday')

    class Meta:
        db_table = 'booking_recurrence_day'

    def __str__(self):
        days = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']
        if self.weekday is not None and 0 <= self.weekday <= 6:
            return f'{days[self.weekday]}'
        return f'Weekday {self.weekday}'

    def clean(self):
        if self.weekday is not None and not 0 <= self.weekday <= 6:
            raise ValidationError({'weekday': 'Weekday must be between 0 and 6.'})


class Booking(models.Model):
    """Đặt sân."""

    PENDING = 'PENDING'
    PAID = 'PAID'
    WAITING = 'WAITING'
    CANCELLED = 'CANCELLED'
    CANCELLABLE_STATUSES = (PENDING, WAITING)
    SERVICE_LOCKED_STATUSES = (PAID, CANCELLED)
    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (PAID, 'Paid'),
        (WAITING, 'Waiting'),
        (CANCELLED, 'Cancelled'),
    ]

    WEB = 'WEB'
    WALKIN = 'WALKIN'
    CHANNEL_CHOICES = [
        (WEB, 'Web'),
        (WALKIN, 'Walk-in'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking_package = models.ForeignKey(
        BookingPackage, on_delete=models.CASCADE, related_name='bookings',
    )
    venue = models.ForeignKey(
        'venues.Venue', on_delete=models.CASCADE, related_name='bookings',
    )
    field = models.ForeignKey(
        'venues.Field', on_delete=models.CASCADE, related_name='bookings',
    )
    booking_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    booking_channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default=WEB)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_deadline = models.DateTimeField(blank=True, null=True)
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'booking'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['field', 'booking_date']),
            models.Index(fields=['venue', 'booking_date']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'{self.field.name} — {self.booking_date} [{self.status}]'

    @property
    def court_total(self):
        return sum((slot.price for slot in self.slots.all()), Decimal('0.00'))

    @property
    def service_total(self):
        return sum(
            (booking_service.total_price for booking_service in self.services_ordered.all()),
            Decimal('0.00'),
        )

    @property
    def grand_total(self):
        """Final total stored on Booking, including court and service charges."""
        return self.total_amount or Decimal('0.00')

    def can_cancel(self):
        return self.status in self.CANCELLABLE_STATUSES

    def get_cancel_block_message(self):
        if self.status == self.CANCELLED:
            return 'Booking đã hủy, không thể hủy lại.'
        if self.status == self.PAID:
            return 'Booking đã thanh toán, không thể hủy.'
        if not self.can_cancel():
            return 'Booking ở trạng thái hiện tại không thể hủy.'
        return ''

    def can_modify_services(self):
        return self.status not in self.SERVICE_LOCKED_STATUSES

    def get_service_modification_block_message(self):
        if self.status == self.PAID:
            return 'Booking đã thanh toán, không thể chỉnh sửa dịch vụ.'
        if self.status == self.CANCELLED:
            return 'Booking đã hủy, không thể chỉnh sửa dịch vụ.'
        return ''

    def clean(self):
        errors = {}
        if self.field_id and self.venue_id and self.field.venue_id != self.venue_id:
            errors['venue'] = 'Booking venue must match the selected field venue.'
        if errors:
            raise ValidationError(errors)


class BookingSlot(models.Model):
    """Slot thời gian trong booking."""

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='slots')
    start_time = models.TimeField()
    end_time = models.TimeField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'booking_slot'
        indexes = [
            models.Index(fields=['booking', 'start_time']),
        ]

    def __str__(self):
        return f'{self.start_time}-{self.end_time}: {self.price:,.0f}đ'

    def clean(self):
        errors = {}
        time_range_is_valid = True
        try:
            validate_booking_time_range(self.start_time, self.end_time)
        except ValidationError as exc:
            time_range_is_valid = False
            _merge_validation_error(errors, exc)

        try:
            booking = self.booking
        except Booking.DoesNotExist:
            booking = None

        if (
            time_range_is_valid
            and booking
            and booking.field_id
            and booking.booking_date
            and self.start_time
            and self.end_time
        ):
            overlapping_slots = BookingSlot.objects.filter(
                booking__field=booking.field,
                booking__booking_date=booking.booking_date,
                start_time__lt=self.end_time,
                end_time__gt=self.start_time,
            ).exclude(booking__status=Booking.CANCELLED)
            if self.pk:
                overlapping_slots = overlapping_slots.exclude(pk=self.pk)
            if overlapping_slots.exists():
                errors.setdefault(NON_FIELD_ERRORS, []).append('This slot overlaps an existing booking.')

            active_locks = SlotLock.objects.filter(
                field=booking.field,
                booking_date=booking.booking_date,
                status=SlotLock.ACTIVE,
                expires_at__gt=timezone.now(),
                start_time__lt=self.end_time,
                end_time__gt=self.start_time,
            )
            if active_locks.exists():
                errors.setdefault(NON_FIELD_ERRORS, []).append('This slot is currently locked.')

        if errors:
            raise ValidationError(errors)


class SlotLock(models.Model):
    """Khoá slot tạm thời để tránh double-booking."""

    ACTIVE = 'ACTIVE'
    EXPIRED = 'EXPIRED'
    RELEASED = 'RELEASED'
    STATUS_CHOICES = [
        (ACTIVE, 'Active'),
        (EXPIRED, 'Expired'),
        (RELEASED, 'Released'),
    ]

    field = models.ForeignKey('venues.Field', on_delete=models.CASCADE, related_name='slot_locks')
    booking_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='slot_locks',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        blank=True, null=True, related_name='created_slot_locks',
    )
    lock_session_id = models.CharField(max_length=255)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'slot_lock'
        indexes = [
            models.Index(fields=['field', 'booking_date', 'start_time', 'end_time']),
        ]

    def __str__(self):
        return f'Lock {self.field.name} {self.booking_date} {self.start_time}-{self.end_time}'

    def clean(self):
        errors = {}
        time_range_is_valid = True
        try:
            validate_booking_time_range(self.start_time, self.end_time)
        except ValidationError as exc:
            time_range_is_valid = False
            _merge_validation_error(errors, exc)

        if (
            time_range_is_valid
            and self.status == self.ACTIVE
            and self.field_id
            and self.booking_date
            and self.start_time
            and self.end_time
            and self.expires_at
            and self.expires_at > timezone.now()
        ):
            overlapping_slots = BookingSlot.objects.filter(
                booking__field=self.field,
                booking__booking_date=self.booking_date,
                start_time__lt=self.end_time,
                end_time__gt=self.start_time,
            ).exclude(booking__status=Booking.CANCELLED)
            if overlapping_slots.exists():
                errors.setdefault(NON_FIELD_ERRORS, []).append('This lock overlaps an existing booking.')

            overlapping_locks = SlotLock.objects.filter(
                field=self.field,
                booking_date=self.booking_date,
                status=self.ACTIVE,
                expires_at__gt=timezone.now(),
                start_time__lt=self.end_time,
                end_time__gt=self.start_time,
            )
            if self.pk:
                overlapping_locks = overlapping_locks.exclude(pk=self.pk)
            if overlapping_locks.exists():
                errors.setdefault(NON_FIELD_ERRORS, []).append('This lock overlaps an active lock.')

        if errors:
            raise ValidationError(errors)


class BookingPromotion(models.Model):
    """Khuyến mãi áp dụng cho booking."""

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='promotions_applied')
    promotion = models.ForeignKey(
        'payments.Promotion', on_delete=models.CASCADE, related_name='booking_applications',
    )
    discount_amount_applied = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'booking_promotion'
        unique_together = ('booking', 'promotion')

    def __str__(self):
        return f'{self.booking} — giảm {self.discount_amount_applied:,.0f}đ'
