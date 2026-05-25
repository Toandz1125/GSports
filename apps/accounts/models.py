import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom User — dùng email làm trường đăng nhập, hỗ trợ OTP."""

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'user'
        ordering = ['-date_joined']

    def __str__(self):
        return self.email


class Role(models.Model):
    """Vai trò: CUSTOMER, OWNER, STAFF, ADMIN."""

    CUSTOMER = 'CUSTOMER'
    OWNER = 'OWNER'
    STAFF = 'STAFF'
    ADMIN = 'ADMIN'

    ROLE_CHOICES = [
        (CUSTOMER, 'Customer'),
        (OWNER, 'Owner'),
        (STAFF, 'Staff'),
        (ADMIN, 'Admin'),
    ]

    name = models.CharField(max_length=20, unique=True, choices=ROLE_CHOICES)

    class Meta:
        db_table = 'role'

    def __str__(self):
        return self.name


class UserRole(models.Model):
    """Bảng trung gian User ↔ Role (N:M)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_roles')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='role_users')

    class Meta:
        db_table = 'user_role'
        unique_together = ('user', 'role')

    def __str__(self):
        return f'{self.user.email} — {self.role.name}'


class OwnerProfile(models.Model):
    """Hồ sơ chủ sân (1-1 với User)."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='owner_profile')
    business_name = models.CharField(max_length=255)
    bank_account_number = models.CharField(max_length=50, blank=True, null=True)
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    is_verified = models.BooleanField(default=False)

    class Meta:
        db_table = 'owner_profile'

    def __str__(self):
        return f'{self.business_name} ({self.user.email})'


class CustomerProfile(models.Model):
    """Hồ sơ khách hàng (1-1 với User)."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='customer_profile')
    loyalty_points = models.IntegerField(default=0)

    class Meta:
        db_table = 'customer_profile'

    def __str__(self):
        return f'Customer: {self.user.email} ({self.loyalty_points} pts)'


class Wallet(models.Model):
    """Ví nội bộ (1-1 với User)."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = 'wallet'

    def __str__(self):
        return f'Wallet {self.user.email}: {self.balance:,.0f}đ'


class WalletTransaction(models.Model):
    """Giao dịch ví."""

    CREDIT = 'CREDIT'
    DEBIT = 'DEBIT'
    TRANSACTION_TYPE_CHOICES = [
        (CREDIT, 'Credit'),
        (DEBIT, 'Debit'),
    ]

    BOOKING = 'BOOKING'
    REFUND = 'REFUND'
    TOPUP = 'TOPUP'
    REWARD = 'REWARD'
    REFERENCE_TYPE_CHOICES = [
        (BOOKING, 'Booking'),
        (REFUND, 'Refund'),
        (TOPUP, 'Topup'),
        (REWARD, 'Reward'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPE_CHOICES)
    sub_total = models.DecimalField(max_digits=12, decimal_places=2)
    final_amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference_type = models.CharField(max_length=20, choices=REFERENCE_TYPE_CHOICES)
    reference_id = models.CharField(max_length=255)
    status = models.CharField(max_length=20)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'wallet_transaction'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.transaction_type} {self.final_amount:,.0f}đ — {self.reference_type}'


class Notification(models.Model):
    """Thông báo."""

    EMAIL = 'EMAIL'
    PUSH = 'PUSH'
    INAPP = 'INAPP'
    TYPE_CHOICES = [
        (EMAIL, 'Email'),
        (PUSH, 'Push'),
        (INAPP, 'In-App'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    content = models.TextField()
    entity_type = models.CharField(max_length=50, blank=True, null=True)
    entity_id = models.CharField(max_length=255, blank=True, null=True)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notification'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read', 'created_at']),
        ]

    def __str__(self):
        return f'[{self.type}] {self.title}'


class FavoriteVenue(models.Model):
    """Cơ sở yêu thích."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorite_venues')
    venue = models.ForeignKey('venues.Venue', on_delete=models.CASCADE, related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'favorite_venue'
        unique_together = ('user', 'venue')

    def __str__(self):
        return f'{self.user.email} ♥ {self.venue.name}'
