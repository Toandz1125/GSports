import re
from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from .models import User, OwnerProfile, CustomerProfile


# ---------------------------------------------------------------------------
# Xác thực (Authentication)
# ---------------------------------------------------------------------------

class CustomerRegistrationForm(forms.ModelForm):
    """Đăng ký tài khoản khách hàng."""

    password = forms.CharField(
        label='Mật khẩu',
        widget=forms.PasswordInput(attrs={'placeholder': 'Nhập mật khẩu'}),
    )
    password_confirm = forms.CharField(
        label='Xác nhận mật khẩu',
        widget=forms.PasswordInput(attrs={'placeholder': 'Nhập lại mật khẩu'}),
    )

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'phone']
        labels = {
            'email': 'Email',
            'first_name': 'Họ',
            'last_name': 'Tên',
            'phone': 'Số điện thoại',
        }
        widgets = {
            'email': forms.EmailInput(attrs={'placeholder': 'example@email.com'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'Họ'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Tên'}),
            'phone': forms.TextInput(attrs={'placeholder': '09xxxxxxxx'}),
        }

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('Email này đã được sử dụng.')
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            phone = phone.strip()
            if not re.match(r'^(0|\+84)\d{9,10}$', phone):
                raise forms.ValidationError(
                    'Số điện thoại không hợp lệ. Vui lòng nhập theo định dạng 0xxxxxxxxx hoặc +84xxxxxxxxx.'
                )
        return phone

    def clean_password(self):
        password = self.cleaned_data.get('password')
        validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        pw = cleaned_data.get('password')
        pw_confirm = cleaned_data.get('password_confirm')
        if pw and pw_confirm and pw != pw_confirm:
            self.add_error('password_confirm', 'Mật khẩu xác nhận không khớp.')
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            CustomerProfile.objects.get_or_create(user=user)
        return user


class OwnerRegistrationForm(forms.ModelForm):
    """Đăng ký tài khoản chủ sân."""

    password = forms.CharField(
        label='Mật khẩu',
        widget=forms.PasswordInput(attrs={'placeholder': 'Nhập mật khẩu'}),
    )
    password_confirm = forms.CharField(
        label='Xác nhận mật khẩu',
        widget=forms.PasswordInput(attrs={'placeholder': 'Nhập lại mật khẩu'}),
    )
    business_name = forms.CharField(
        label='Tên doanh nghiệp',
        max_length=255,
        widget=forms.TextInput(attrs={'placeholder': 'Tên doanh nghiệp / cơ sở'}),
    )
    bank_account_number = forms.CharField(
        label='Số tài khoản ngân hàng',
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Số tài khoản'}),
    )
    bank_name = forms.CharField(
        label='Tên ngân hàng',
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Tên ngân hàng'}),
    )

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'phone']
        labels = {
            'email': 'Email',
            'first_name': 'Họ',
            'last_name': 'Tên',
            'phone': 'Số điện thoại',
        }
        widgets = {
            'email': forms.EmailInput(attrs={'placeholder': 'example@email.com'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'Họ'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Tên'}),
            'phone': forms.TextInput(attrs={'placeholder': '09xxxxxxxx'}),
        }

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('Email này đã được sử dụng.')
        from .models import OwnerRegistrationRequest
        if OwnerRegistrationRequest.objects.filter(email=email, status=OwnerRegistrationRequest.PENDING).exists():
            raise forms.ValidationError('Yêu cầu đăng ký của email này đang chờ Admin phê duyệt.')
        return email


    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            phone = phone.strip()
            if not re.match(r'^(0|\+84)\d{9,10}$', phone):
                raise forms.ValidationError(
                    'Số điện thoại không hợp lệ. Vui lòng nhập theo định dạng 0xxxxxxxxx hoặc +84xxxxxxxxx.'
                )
        return phone

    def clean_password(self):
        password = self.cleaned_data.get('password')
        validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        pw = cleaned_data.get('password')
        pw_confirm = cleaned_data.get('password_confirm')
        if pw and pw_confirm and pw != pw_confirm:
            self.add_error('password_confirm', 'Mật khẩu xác nhận không khớp.')
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user._is_owner_registration = True
            user.save()
            OwnerProfile.objects.get_or_create(
                user=user,
                defaults={
                    'business_name': self.cleaned_data['business_name'],
                    'bank_account_number': self.cleaned_data.get('bank_account_number') or None,
                    'bank_name': self.cleaned_data.get('bank_name') or None,
                }
            )
        return user


class LoginForm(forms.Form):
    """Đăng nhập bằng email và mật khẩu."""

    email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={'placeholder': 'Email đăng nhập'}),
    )
    password = forms.CharField(
        label='Mật khẩu',
        widget=forms.PasswordInput(attrs={'placeholder': 'Mật khẩu'}),
    )

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.user_cache = None

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        password = cleaned_data.get('password')

        if email and password:
            self.user_cache = authenticate(
                self.request, username=email, password=password,
            )
            if self.user_cache is None:
                from .models import OwnerRegistrationRequest
                if email:
                    email_clean = email.lower().strip()
                    if OwnerRegistrationRequest.objects.filter(email=email_clean, status=OwnerRegistrationRequest.PENDING).exists():
                        raise forms.ValidationError('Tài khoản chủ sân của bạn đang chờ Admin xét duyệt.')
                raise forms.ValidationError('Email hoặc mật khẩu không chính xác.')
            if not self.user_cache.is_active:
                raise forms.ValidationError('Tài khoản đã bị vô hiệu hóa.')
        return cleaned_data


    def get_user(self):
        return self.user_cache


# ---------------------------------------------------------------------------
# Hồ sơ người dùng (Profile)
# ---------------------------------------------------------------------------

class UserProfileForm(forms.ModelForm):
    """Cập nhật thông tin cá nhân."""

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'phone']
        labels = {
            'username': 'Tên đăng nhập',
            'email': 'Email',
            'first_name': 'Họ',
            'last_name': 'Tên',
            'phone': 'Số điện thoại',
        }
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'Tên đăng nhập'}),
            'email': forms.EmailInput(attrs={'placeholder': 'example@email.com'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'Họ'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Tên'}),
            'phone': forms.TextInput(attrs={'placeholder': '09xxxxxxxx'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].disabled = True
        self.fields['email'].disabled = True

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            phone = phone.strip()
            if not re.match(r'^(0|\+84)\d{9,10}$', phone):
                raise forms.ValidationError(
                    'Số điện thoại không hợp lệ.'
                )
        return phone


class AvatarUploadForm(forms.ModelForm):
    """Upload ảnh đại diện."""

    class Meta:
        model = User
        fields = ['avatar']
        labels = {'avatar': 'Ảnh đại diện'}
        widgets = {
            'avatar': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        }

    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')
        if avatar:
            # Giới hạn kích thước 5 MB
            max_size = 5 * 1024 * 1024
            if avatar.size > max_size:
                raise forms.ValidationError('Ảnh đại diện không được vượt quá 5 MB.')

            # Chỉ chấp nhận JPEG, PNG, WebP
            allowed_types = ['image/jpeg', 'image/png', 'image/webp']
            if avatar.content_type not in allowed_types:
                raise forms.ValidationError(
                    'Chỉ chấp nhận định dạng JPEG, PNG hoặc WebP.'
                )
        return avatar


class OwnerProfileForm(forms.ModelForm):
    """Cập nhật hồ sơ chủ sân."""

    class Meta:
        model = OwnerProfile
        fields = ['business_name', 'bank_account_number', 'bank_name']
        labels = {
            'business_name': 'Tên doanh nghiệp',
            'bank_account_number': 'Số tài khoản',
            'bank_name': 'Tên ngân hàng',
        }
        widgets = {
            'business_name': forms.TextInput(attrs={'placeholder': 'Tên doanh nghiệp'}),
            'bank_account_number': forms.TextInput(attrs={'placeholder': 'Số tài khoản'}),
            'bank_name': forms.TextInput(attrs={'placeholder': 'Tên ngân hàng'}),
        }


# ---------------------------------------------------------------------------
# Mật khẩu (Password)
# ---------------------------------------------------------------------------

class ChangePasswordForm(forms.Form):
    """Đổi mật khẩu."""

    current_password = forms.CharField(
        label='Mật khẩu hiện tại',
        widget=forms.PasswordInput(attrs={'placeholder': 'Mật khẩu hiện tại'}),
    )
    new_password = forms.CharField(
        label='Mật khẩu mới',
        widget=forms.PasswordInput(attrs={'placeholder': 'Mật khẩu mới'}),
    )
    new_password_confirm = forms.CharField(
        label='Xác nhận mật khẩu mới',
        widget=forms.PasswordInput(attrs={'placeholder': 'Nhập lại mật khẩu mới'}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_current_password(self):
        current = self.cleaned_data.get('current_password')
        if self.user and not self.user.check_password(current):
            raise forms.ValidationError('Mật khẩu hiện tại không chính xác.')
        return current

    def clean_new_password(self):
        password = self.cleaned_data.get('new_password')
        validate_password(password, user=self.user)
        return password

    def clean(self):
        cleaned_data = super().clean()
        current_pw = cleaned_data.get('current_password')
        pw = cleaned_data.get('new_password')
        pw_confirm = cleaned_data.get('new_password_confirm')

        # Kiểm tra trùng mật khẩu cũ
        if current_pw and pw and current_pw == pw:
            self.add_error('new_password', 'Mật khẩu mới không được trùng với mật khẩu hiện tại.')

        if pw and pw_confirm and pw != pw_confirm:
            self.add_error('new_password_confirm', 'Mật khẩu xác nhận không khớp.')
        return cleaned_data

    def save(self):
        self.user.set_password(self.cleaned_data['new_password'])
        self.user.save(update_fields=['password'])
        return self.user


# ---------------------------------------------------------------------------
# Tạo tài khoản nhân viên (Staff Registration by Owner)
# ---------------------------------------------------------------------------

class StaffRegistrationForm(forms.ModelForm):
    """Chủ sân tạo tài khoản nhân viên (STAFF)."""

    password = forms.CharField(
        label='Mật khẩu',
        widget=forms.PasswordInput(attrs={'placeholder': 'Nhập mật khẩu'}),
    )
    password_confirm = forms.CharField(
        label='Xác nhận mật khẩu',
        widget=forms.PasswordInput(attrs={'placeholder': 'Nhập lại mật khẩu'}),
    )

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'phone']
        labels = {
            'email': 'Email nhân viên',
            'first_name': 'Họ',
            'last_name': 'Tên',
            'phone': 'Số điện thoại',
        }
        widgets = {
            'email': forms.EmailInput(attrs={'placeholder': 'email@example.com'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'Họ'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Tên'}),
            'phone': forms.TextInput(attrs={'placeholder': '09xxxxxxxx'}),
        }

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner  # OwnerProfile của chủ sân đang đăng nhập
        from apps.venues.models import Venue
        self.fields['venue'] = forms.ModelChoiceField(
            label='Cơ sở làm việc',
            queryset=owner.venues.filter(is_deleted=False) if owner else Venue.objects.none(),
            required=True,
            empty_label="-- Chọn cơ sở --",
        )

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('Email này đã được sử dụng.')
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            phone = phone.strip()
            if not re.match(r'^(0|\+84)\d{9,10}$', phone):
                raise forms.ValidationError(
                    'Số điện thoại không hợp lệ. Vui lòng nhập theo định dạng 0xxxxxxxxx hoặc +84xxxxxxxxx.'
                )
        return phone

    def clean_password(self):
        password = self.cleaned_data.get('password')
        validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        pw = cleaned_data.get('password')
        pw_confirm = cleaned_data.get('password_confirm')
        if pw and pw_confirm and pw != pw_confirm:
            self.add_error('password_confirm', 'Mật khẩu xác nhận không khớp.')
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user._is_staff_registration = True
            user.save()
            from .models import StaffProfile
            from apps.core.models import VenueStaff
            
            # Tạo/Cập nhật StaffProfile
            staff_prof, _ = StaffProfile.objects.get_or_create(user=user, defaults={'owner': self.owner})
            staff_prof.venue = self.cleaned_data.get('venue')
            staff_prof.save()

            # Tạo/Cập nhật VenueStaff
            VenueStaff.objects.update_or_create(
                staff=user,
                defaults={
                    'venue': self.cleaned_data.get('venue'),
                    'permission_level': 'STAFF'
                }
            )
        return user


class StaffUpdateForm(forms.ModelForm):
    """Chủ sân cập nhật thông tin nhân viên (STAFF)."""

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone']
        labels = {
            'first_name': 'Họ',
            'last_name': 'Tên',
            'phone': 'Số điện thoại',
        }
        widgets = {
            'first_name': forms.TextInput(attrs={'placeholder': 'Họ'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Tên'}),
            'phone': forms.TextInput(attrs={'placeholder': '09xxxxxxxx'}),
        }

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        from apps.venues.models import Venue
        
        current_venue = None
        if self.instance and self.instance.pk:
            try:
                current_venue = self.instance.staff_profile.venue
            except Exception:
                pass

        self.fields['venue'] = forms.ModelChoiceField(
            label='Cơ sở làm việc',
            queryset=owner.venues.filter(is_deleted=False) if owner else Venue.objects.none(),
            required=True,
            initial=current_venue,
            empty_label="-- Chọn cơ sở --",
        )

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            phone = phone.strip()
            if not re.match(r'^(0|\+84)\d{9,10}$', phone):
                raise forms.ValidationError(
                    'Số điện thoại không hợp lệ. Vui lòng nhập theo định dạng 0xxxxxxxxx hoặc +84xxxxxxxxx.'
                )
        return phone

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            from .models import StaffProfile
            from apps.core.models import VenueStaff
            
            # Cập nhật StaffProfile
            staff_prof, _ = StaffProfile.objects.get_or_create(user=user, defaults={'owner': self.owner})
            staff_prof.venue = self.cleaned_data.get('venue')
            staff_prof.save()

            # Cập nhật VenueStaff
            VenueStaff.objects.update_or_create(
                staff=user,
                defaults={
                    'venue': self.cleaned_data.get('venue'),
                    'permission_level': 'STAFF'
                }
            )
        return user


# ---------------------------------------------------------------------------
# Ví điện tử (Wallet)
# ---------------------------------------------------------------------------

class WalletTopupForm(forms.Form):
    """Nạp tiền vào ví."""

    amount = forms.DecimalField(
        label='Số tiền nạp',
        min_value=10000,
        max_value=50000000,
        decimal_places=0,
        widget=forms.NumberInput(attrs={'placeholder': 'Nhập số tiền (VNĐ)', 'step': '1000'}),
    )

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount % 1000 != 0:
            raise forms.ValidationError('Số tiền phải là bội số của 1.000 VNĐ.')
        return amount
