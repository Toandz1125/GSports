from django.contrib import admin
from .models import Payment, Invoice, Promotion


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'booking', 'method', 'payment_type', 'amount', 'status', 'paid_at')
    list_filter = ('method', 'payment_type', 'status')


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_code', 'payment', 'tax_amount', 'issued_at')


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ('code', 'venue', 'discount_type', 'discount_value', 'quantity', 'used_quantity', 'start_date', 'end_date')
    list_filter = ('discount_type',)
