from django.contrib import admin
from .models import (
    BookingPackage, BookingRecurrenceDay, Booking,
    BookingSlot, SlotLock, BookingPromotion,
)


@admin.register(BookingPackage)
class BookingPackageAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'package_type', 'start_date', 'end_date', 'created_at')
    list_filter = ('package_type',)


@admin.register(BookingRecurrenceDay)
class BookingRecurrenceDayAdmin(admin.ModelAdmin):
    list_display = ('booking_package', 'weekday')


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'field', 'venue', 'booking_date', 'status', 'total_amount', 'booking_channel')
    list_filter = ('status', 'booking_channel', 'venue')
    search_fields = ('id',)


@admin.register(BookingSlot)
class BookingSlotAdmin(admin.ModelAdmin):
    list_display = ('booking', 'start_time', 'end_time', 'price')


@admin.register(SlotLock)
class SlotLockAdmin(admin.ModelAdmin):
    list_display = ('field', 'booking_date', 'start_time', 'end_time', 'user', 'status', 'expires_at')
    list_filter = ('status',)


@admin.register(BookingPromotion)
class BookingPromotionAdmin(admin.ModelAdmin):
    list_display = ('booking', 'promotion', 'discount_amount_applied')
