from django.contrib import admin
from .models import ServiceItem, BookingService


@admin.register(ServiceItem)
class ServiceItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'venue', 'category', 'price', 'stock')
    list_filter = ('category', 'venue')


@admin.register(BookingService)
class BookingServiceAdmin(admin.ModelAdmin):
    list_display = ('booking', 'service_item', 'quantity', 'unit_price')
