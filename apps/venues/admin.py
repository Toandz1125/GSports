from django.contrib import admin
from .models import (
    Sport, Venue, VenueOperatingHour, VenueImage,
    FieldType, Field, FieldPriceRule, VenuePolicy,
)


@admin.register(Sport)
class SportAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active')


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'address', 'status', 'is_deleted')
    list_filter = ('status', 'is_deleted')
    search_fields = ('name', 'address')


@admin.register(VenueOperatingHour)
class VenueOperatingHourAdmin(admin.ModelAdmin):
    list_display = ('venue', 'weekday', 'open_time', 'close_time')


@admin.register(VenueImage)
class VenueImageAdmin(admin.ModelAdmin):
    list_display = ('venue', 'is_thumbnail', 'sort_order')


@admin.register(FieldType)
class FieldTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'sport', 'player_count', 'status')
    list_filter = ('sport',)


@admin.register(Field)
class FieldAdmin(admin.ModelAdmin):
    list_display = ('name', 'venue', 'field_type', 'status')
    list_filter = ('venue', 'field_type', 'status')


@admin.register(FieldPriceRule)
class FieldPriceRuleAdmin(admin.ModelAdmin):
    list_display = ('field', 'day_of_week', 'start_time', 'end_time', 'price_per_hour', 'priority')


@admin.register(VenuePolicy)
class VenuePolicyAdmin(admin.ModelAdmin):
    list_display = ('venue', 'cancel_before_hours', 'refund_percent')
