from django.contrib import admin
from .models import VenueStaff, StaffShift, DailyVenueStats, AuditLog, SystemEvent


@admin.register(VenueStaff)
class VenueStaffAdmin(admin.ModelAdmin):
    list_display = ('staff', 'venue', 'permission_level')
    list_filter = ('venue',)


@admin.register(StaffShift)
class StaffShiftAdmin(admin.ModelAdmin):
    list_display = ('venue_staff', 'weekday', 'start_time', 'end_time', 'is_active')


@admin.register(DailyVenueStats)
class DailyVenueStatsAdmin(admin.ModelAdmin):
    list_display = ('venue', 'date', 'revenue', 'booking_count', 'occupancy_rate')
    list_filter = ('venue',)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'target_type', 'target_id', 'created_at')
    list_filter = ('action', 'target_type')


@admin.register(SystemEvent)
class SystemEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'created_at')
