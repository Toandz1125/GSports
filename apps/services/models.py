from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class ServiceItem(models.Model):
    """Dịch vụ / sản phẩm phụ trợ tại cơ sở."""

    DRINK = 'DRINK'
    FOOD = 'FOOD'
    EQUIPMENT = 'EQUIPMENT'
    RENTAL = 'RENTAL'
    OTHER = 'OTHER'
    CATEGORY_CHOICES = [
        (DRINK, 'Drink'),
        (FOOD, 'Food'),
        (EQUIPMENT, 'Equipment'),
        (RENTAL, 'Rental'),
        (OTHER, 'Other'),
    ]

    venue = models.ForeignKey('venues.Venue', on_delete=models.CASCADE, related_name='service_items')
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, blank=True, null=True)
    image = models.ImageField(upload_to='service_items/', blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'service_item'

    def __str__(self):
        return f'{self.name} — {self.price:,.0f}đ'

    def clean(self):
        if self.stock is not None and self.stock < 0:
            raise ValidationError({'stock': 'Stock cannot be negative.'})


class BookingService(models.Model):
    """Dịch vụ kèm theo booking."""

    booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.CASCADE, related_name='services_ordered',
    )
    service_item = models.ForeignKey(ServiceItem, on_delete=models.CASCADE, related_name='order_items')
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'booking_service'

    def __str__(self):
        return f'{self.service_item.name} x{self.quantity}'

    @property
    def total_price(self):
        if self.quantity is None or self.unit_price is None:
            return Decimal('0.00')
        return self.quantity * self.unit_price

    def clean(self):
        errors = {}
        if self.quantity is not None and self.quantity <= 0:
            errors['quantity'] = 'Quantity must be greater than 0.'
        if (
            self.booking_id
            and self.service_item_id
            and self.booking.venue_id != self.service_item.venue_id
        ):
            errors['service_item'] = 'Service item venue must match booking venue.'
        if errors:
            raise ValidationError(errors)
