import uuid
from django.db import models


class Payment(models.Model):
    """Thanh toán."""

    CASH = 'CASH'
    VIETQR = 'VIETQR'
    METHOD_CHOICES = [
        (CASH, 'Cash'),
        (VIETQR, 'VietQR'),
    ]

    DEPOSIT = 'DEPOSIT'
    FINAL = 'FINAL'
    REFUND = 'REFUND'
    PAYMENT_TYPE_CHOICES = [
        (DEPOSIT, 'Deposit'),
        (FINAL, 'Final'),
        (REFUND, 'Refund'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.CASCADE, related_name='payments',
    )
    method = models.CharField(max_length=10, choices=METHOD_CHOICES)
    payment_type = models.CharField(max_length=10, choices=PAYMENT_TYPE_CHOICES)
    transaction_code = models.CharField(max_length=100, unique=True, blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, default='PENDING')
    paid_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payment'
        indexes = [
            models.Index(fields=['transaction_code']),
        ]

    def __str__(self):
        return f'{self.payment_type} {self.amount:,.0f}đ [{self.status}]'


class Invoice(models.Model):
    """Hoá đơn."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name='invoice')
    invoice_code = models.CharField(max_length=50, unique=True)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'invoice'

    def __str__(self):
        return f'INV-{self.invoice_code}'


class Promotion(models.Model):
    """Mã khuyến mãi."""

    PERCENTAGE = 'PERCENTAGE'
    FIXED = 'FIXED'
    DISCOUNT_TYPE_CHOICES = [
        (PERCENTAGE, 'Percentage'),
        (FIXED, 'Fixed'),
    ]

    venue = models.ForeignKey(
        'venues.Venue', on_delete=models.CASCADE,
        blank=True, null=True, related_name='promotions',
    )
    code = models.CharField(max_length=50, unique=True)
    discount_type = models.CharField(max_length=15, choices=DISCOUNT_TYPE_CHOICES)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    max_discount_amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    min_order_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    start_date = models.DateField()
    end_date = models.DateField()
    quantity = models.IntegerField()
    used_quantity = models.IntegerField(default=0)

    class Meta:
        db_table = 'promotion'

    def __str__(self):
        return f'{self.code} ({self.discount_type}: {self.discount_value})'
