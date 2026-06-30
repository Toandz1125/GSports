from django.db import models
from django.conf import settings
import uuid

class Wallet(models.Model):
    """Ví điện tử của người dùng"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payment_wallet'
    )
    balance = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Wallet of {self.user.username} - {self.balance}đ"
    
    def deposit(self, amount):
        self.balance += amount
        self.save()
        return self.balance
    
    def withdraw(self, amount):
        if self.balance < amount:
            raise ValueError("Số dư không đủ")
        self.balance -= amount
        self.save()
        return self.balance

class WalletTransaction(models.Model):
    """Lịch sử giao dịch ví"""
    class TransactionType(models.TextChoices):
        DEPOSIT = 'DEPOSIT', 'Nạp tiền'
        WITHDRAWAL = 'WITHDRAWAL', 'Rút tiền'
        PAYMENT = 'PAYMENT', 'Thanh toán'
        REFUND = 'REFUND', 'Hoàn tiền'
    
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Đang xử lý'
        COMPLETED = 'COMPLETED', 'Hoàn thành'
        FAILED = 'FAILED', 'Thất bại'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    description = models.TextField(blank=True, default="")
    reference_id = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount}đ"

class Payment(models.Model):
    """Thanh toán"""
    class Method(models.TextChoices):
        WALLET = 'WALLET', 'Ví điện tử'
        CASH = 'CASH', 'Tiền mặt'
        VIETQR = 'VIETQR', 'VietQR'
    
    class PaymentType(models.TextChoices):
        DEPOSIT = 'DEPOSIT', 'Đặt cọc'
        FINAL = 'FINAL', 'Thanh toán cuối'
        REFUND = 'REFUND', 'Hoàn tiền'
    
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Chờ xử lý'
        PAID = 'PAID', 'Đã thanh toán'
        COMPLETED = 'COMPLETED', 'Hoàn thành'
        FAILED = 'FAILED', 'Thất bại'
        CANCELLED = 'CANCELLED', 'Đã hủy'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey('bookings.Booking', on_delete=models.CASCADE, related_name='payments')
    method = models.CharField(max_length=20, choices=Method.choices)
    payment_type = models.CharField(max_length=20, choices=PaymentType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    transaction_code = models.CharField(max_length=100, blank=True, null=True, unique=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Payment {self.id} - {self.get_method_display()} - {self.amount}đ"

    class Meta:
        db_table = 'payment'


class Invoice(models.Model):
    """Hóa đơn cho payment đã hoàn tất."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name='invoice')
    invoice_code = models.CharField(max_length=50, unique=True)
    subtotal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    issued_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Invoice {self.invoice_code} - {self.total_amount}đ"

    class Meta:
        db_table = 'invoice'

class Promotion(models.Model):
    """Mã khuyến mãi"""
    class DiscountType(models.TextChoices):
        PERCENTAGE = 'PERCENTAGE', 'Phần trăm'
        FIXED = 'FIXED', 'Cố định'
    
    code = models.CharField(max_length=50, unique=True)
    discount_type = models.CharField(max_length=20, choices=DiscountType.choices)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    max_discount_amount = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True)
    min_order_value = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    start_date = models.DateField()
    end_date = models.DateField()
    quantity = models.PositiveIntegerField()
    used_quantity = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.code} - {self.discount_value}{'%' if self.discount_type == 'PERCENTAGE' else 'đ'}"

    class Meta:
        db_table = 'promotion'
    
    def is_valid(self):
        from django.utils import timezone
        today = timezone.now().date()
        return (self.start_date <= today <= self.end_date and 
                self.used_quantity < self.quantity and
                self.is_active)
