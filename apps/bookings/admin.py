from django.contrib import admin
from .models import (
    BookingPackage, BookingRecurrenceDay, Booking,
    BookingSlot, SlotLock, BookingPromotion,
)


@admin.register(BookingPackage)
class BookingPackageAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'package_type', 'start_date', 'end_date', 'created_at')
    list_filter = ('package_type', 'start_date', 'created_at')
    search_fields = ('id', 'user__email', 'user__username')


@admin.register(BookingRecurrenceDay)
class BookingRecurrenceDayAdmin(admin.ModelAdmin):
    list_display = ('booking_package', 'weekday')
    list_filter = ('weekday',)
    search_fields = ('booking_package__id', 'booking_package__user__email')


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'field', 'venue', 'booking_date', 'status', 'total_amount', 'booking_channel', 'created_at')
    list_filter = ('status', 'booking_channel', 'venue', 'booking_date', 'created_at')
    search_fields = ('id', 'field__name', 'venue__name', 'booking_package__user__email')


@admin.register(BookingSlot)
class BookingSlotAdmin(admin.ModelAdmin):
    list_display = ('booking', 'start_time', 'end_time', 'price')
    list_filter = ('booking__booking_date', 'booking__status')
    search_fields = ('booking__id', 'booking__field__name', 'booking__venue__name')


@admin.register(SlotLock)
class SlotLockAdmin(admin.ModelAdmin):
    list_display = ('field', 'booking_date', 'start_time', 'end_time', 'user', 'status', 'expires_at')
    list_filter = ('status', 'booking_date', 'expires_at')
    search_fields = ('field__name', 'field__venue__name', 'user__email', 'lock_session_id')


@admin.register(BookingPromotion)
class BookingPromotionAdmin(admin.ModelAdmin):
    list_display = ('booking', 'promotion', 'discount_amount_applied')
    search_fields = ('booking__id', 'promotion__code')
