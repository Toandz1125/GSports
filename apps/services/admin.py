from django.contrib import admin
from .models import ServiceItem, BookingService


@admin.register(ServiceItem)
class ServiceItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'venue', 'category', 'price', 'stock', 'is_active', 'created_at')
    list_filter = ('category', 'venue', 'is_active', 'created_at')
    search_fields = ('name', 'venue__name')


@admin.register(BookingService)
class BookingServiceAdmin(admin.ModelAdmin):
    list_display = ('booking', 'service_item', 'quantity', 'unit_price', 'created_at')
    list_filter = ('service_item__category', 'created_at')
    search_fields = ('booking__id', 'service_item__name', 'service_item__venue__name')
