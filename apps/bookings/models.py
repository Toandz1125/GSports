import uuid
from django.db import models


class BookingPackage(models.Model):
    """Gói đặt sân (single hoặc recurring)."""

    SINGLE = 'SINGLE'
    RECURRING = 'RECURRING'
    PACKAGE_TYPE_CHOICES = [
        (SINGLE, 'Single'),
        (RECURRING, 'Recurring'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='booking_packages')
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
        return f'{days[self.weekday]}'


class Booking(models.Model):
    """Đặt sân."""

    PENDING = 'PENDING'
    PAID = 'PAID'
    WAITING = 'WAITING'
    CANCELLED = 'CANCELLED'
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


class SlotLock(models.Model):
    """Khoá slot tạm thời để tránh double-booking."""

    field = models.ForeignKey('venues.Field', on_delete=models.CASCADE, related_name='slot_locks')
    booking_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    user = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='slot_locks',
    )
    status = models.CharField(max_length=20, default='ACTIVE')
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL,
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
