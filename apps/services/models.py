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

    class Meta:
        db_table = 'service_item'

    def __str__(self):
        return f'{self.name} — {self.price:,.0f}đ'


class BookingService(models.Model):
    """Dịch vụ kèm theo booking."""

    booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.CASCADE, related_name='services_ordered',
    )
    service_item = models.ForeignKey(ServiceItem, on_delete=models.CASCADE, related_name='order_items')
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'booking_service'

    def __str__(self):
        return f'{self.service_item.name} x{self.quantity}'
