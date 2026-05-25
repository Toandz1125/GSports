from django.db import models


class VenueStaff(models.Model):
    """Nhân viên tại cơ sở."""

    venue = models.ForeignKey('venues.Venue', on_delete=models.CASCADE, related_name='staff_members')
    staff = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='venue_assignments')
    permission_level = models.CharField(max_length=50)

    class Meta:
        db_table = 'venue_staff'
        unique_together = ('venue', 'staff')

    def __str__(self):
        return f'{self.staff.email} @ {self.venue.name}'


class StaffShift(models.Model):
    """Ca làm việc."""

    venue_staff = models.ForeignKey(VenueStaff, on_delete=models.CASCADE, related_name='shifts')
    weekday = models.SmallIntegerField(help_text='0=Monday, 6=Sunday')
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'staff_shift'
        unique_together = ('venue_staff', 'weekday', 'start_time')

    def __str__(self):
        days = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']
        return f'{days[self.weekday]} {self.start_time}-{self.end_time}'


class DailyVenueStats(models.Model):
    """Thống kê hàng ngày."""

    venue = models.ForeignKey('venues.Venue', on_delete=models.CASCADE, related_name='daily_stats')
    date = models.DateField()
    revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    booking_count = models.IntegerField(default=0)
    occupancy_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        db_table = 'daily_venue_stats'
        unique_together = ('venue', 'date')

    def __str__(self):
        return f'{self.venue.name} — {self.date}: {self.revenue:,.0f}đ'


class AuditLog(models.Model):
    """Nhật ký hệ thống."""

    user = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL,
        blank=True, null=True, related_name='audit_logs',
    )
    action = models.CharField(max_length=50)
    target_type = models.CharField(max_length=50)
    target_id = models.CharField(max_length=255)
    old_value = models.TextField(blank=True, null=True)
    new_value = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_log'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['target_type', 'target_id']),
        ]

    def __str__(self):
        return f'{self.action} {self.target_type}#{self.target_id}'


class SystemEvent(models.Model):
    """Sự kiện hệ thống."""

    event_type = models.CharField(max_length=100)
    payload = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'system_event'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.event_type} @ {self.created_at}'
