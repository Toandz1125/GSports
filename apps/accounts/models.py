import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.text import slugify


class User(AbstractUser):
    """Custom User — dùng email làm trường đăng nhập, hỗ trợ OTP."""

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    def save(self, *args, **kwargs):
        """Auto-generate `username` as concatenation of last name + first name.

        Ensures the resulting `username` is unique by appending a counter
        when necessary. Uses slugified (ASCII, lowercase) form without
        separators to keep the username compact.
        """
        base = f"{self.last_name or ''}{self.first_name or ''}"
        # slugify to normalize characters; remove hyphens produced by slugify
        base = slugify(base).replace('-', '')
        if not base:
            base = str(uuid.uuid4())[:8]

        username = base
        counter = 0
        ModelClass = self.__class__
        while ModelClass.objects.filter(username=username).exclude(pk=self.pk).exists():
            counter += 1
            username = f"{base}{counter}"

        self.username = username
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'user'
        ordering = ['-date_joined']

    def __str__(self):
        return self.email

    @property
    def is_admin(self):
        return self.user_roles.filter(role__name='ADMIN').exists()

    @property
    def is_owner(self):
        return self.user_roles.filter(role__name='OWNER').exists()

    @property
    def is_staff_member(self):
        return self.user_roles.filter(role__name='STAFF').exists()


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
        constraints = [
            models.UniqueConstraint(fields=['user'], name='unique_user_role')
        ]

    def save(self, *args, **kwargs):
        # Enforce single role per user: delete any other roles for this user
        if self.user_id:
            UserRole.objects.filter(user_id=self.user_id).exclude(pk=self.pk).delete()
        super().save(*args, **kwargs)

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


class OwnerRegistrationRequest(models.Model):
    """Yêu cầu đăng ký tài khoản chủ sân."""

    PENDING = 'PENDING'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'

    STATUS_CHOICES = [
        (PENDING, 'Chờ duyệt'),
        (APPROVED, 'Đã duyệt'),
        (REJECTED, 'Từ chối'),
    ]

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True, null=True)
    business_name = models.CharField(max_length=255)
    bank_account_number = models.CharField(max_length=50, blank=True, null=True)
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    password_hash = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_requests')

    class Meta:
        db_table = 'owner_registration_request'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.business_name} ({self.email}) — {self.get_status_display()}'



class CustomerProfile(models.Model):
    """Hồ sơ khách hàng (1-1 với User)."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='customer_profile')
    loyalty_points = models.IntegerField(default=0)

    class Meta:
        db_table = 'customer_profile'

    def __str__(self):
        return f'Customer: {self.user.email} ({self.loyalty_points} pts)'


class StaffProfile(models.Model):
    """Hồ sơ nhân viên (1-1 với User) — được tạo bởi chủ sân."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='staff_profile')
    owner = models.ForeignKey(
        OwnerProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff_members',
    )
    venue = models.ForeignKey(
        'venues.Venue',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='profile_staff_members',
    )


    class Meta:
        db_table = 'staff_profile'

    def __str__(self):
        owner_name = self.owner.business_name if self.owner else 'N/A'
        venue_name = self.venue.name if self.venue else 'Tất cả cơ sở'
        return f'Staff: {self.user.email} ({owner_name} - {venue_name})'



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
