from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, FormView, TemplateView, UpdateView, ListView

from .forms import (
    AvatarUploadForm,
    ChangePasswordForm,
    CustomerRegistrationForm,
    LoginForm,
    OwnerProfileForm,
    OwnerRegistrationForm,
    StaffRegistrationForm,
    StaffUpdateForm,
    UserProfileForm,
)
from .models import User, CustomerProfile, Role, UserRole, Wallet


# ---------------------------------------------------------------------------
# Đăng ký (Registration)
# ---------------------------------------------------------------------------

class CustomerRegisterView(CreateView):
    """Đăng ký tài khoản khách hàng (Customer)."""

    template_name = 'accounts/register.html'
    form_class = CustomerRegistrationForm
    success_url = reverse_lazy('accounts:login')

    def dispatch(self, request, *args, **kwargs):
        """Redirect nếu user đã đăng nhập."""
        if request.user.is_authenticated:
            return redirect('accounts:dashboard')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        with transaction.atomic():
            user = form.save()  # Tạo User + CustomerProfile (trong form.save)

            # Gán vai trò CUSTOMER
            customer_role, _ = Role.objects.get_or_create(name=Role.CUSTOMER)
            UserRole.objects.get_or_create(user=user, role=customer_role)

            # Tạo Wallet
            Wallet.objects.get_or_create(user=user)

        messages.success(
            self.request,
            'Đăng ký thành công! Vui lòng đăng nhập.',
        )
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Đăng ký tài khoản'
        return context


class OwnerRegisterView(CreateView):
    """Đăng ký tài khoản chủ sân (Owner)."""

    template_name = 'accounts/register_owner.html'
    form_class = OwnerRegistrationForm
    success_url = reverse_lazy('accounts:login')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('accounts:dashboard')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        from django.contrib.auth.hashers import make_password
        from .models import OwnerRegistrationRequest

        cd = form.cleaned_data
        
        OwnerRegistrationRequest.objects.create(
            email=cd['email'].lower().strip(),
            first_name=cd['first_name'],
            last_name=cd['last_name'],
            phone=cd.get('phone'),
            business_name=cd['business_name'],
            bank_account_number=cd.get('bank_account_number') or None,
            bank_name=cd.get('bank_name') or None,
            password_hash=make_password(cd['password'])
        )

        messages.success(
            self.request,
            'Đăng ký chủ sân thành công! Yêu cầu của bạn đang chờ Admin duyệt.',
        )
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Đăng ký chủ sân'
        return context



# ---------------------------------------------------------------------------
# Đăng nhập / Đăng xuất (Login / Logout)
# ---------------------------------------------------------------------------

class LoginView(FormView):
    """Đăng nhập bằng email và mật khẩu."""

    template_name = 'accounts/login.html'
    form_class = LoginForm
    success_url = reverse_lazy('accounts:dashboard')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('accounts:dashboard')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        user = form.get_user()
        login(self.request, user)
        messages.success(self.request, f'Chào mừng {user.username}!')

        # Redirect đến trang trước đó nếu có, ngược lại về dashboard
        next_url = self.request.GET.get('next') or self.request.POST.get('next')
        if next_url:
            return redirect(next_url)
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Đăng nhập'
        context['next'] = self.request.GET.get('next', '')
        return context


class LogoutView(View):
    """Đăng xuất và redirect về trang đăng nhập."""

    def get(self, request, *args, **kwargs):
        return self._logout(request)

    def post(self, request, *args, **kwargs):
        return self._logout(request)

    def _logout(self, request):
        logout(request)
        messages.info(request, 'Bạn đã đăng xuất thành công.')
        return redirect('accounts:login')


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class DashboardView(LoginRequiredMixin, TemplateView):
    """Trang dashboard sau đăng nhập — hiển thị thông tin tổng quan."""

    template_name = 'accounts/dashboard.html'
    login_url = reverse_lazy('accounts:login')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['page_title'] = 'Dashboard'

        # Lấy danh sách vai trò của user
        context['user_roles'] = UserRole.objects.filter(
            user=user,
        ).select_related('role').values_list('role__name', flat=True)

        # Lấy thông tin ví
        try:
            context['wallet'] = user.wallet
        except Wallet.DoesNotExist:
            context['wallet'] = None

        return context


# ---------------------------------------------------------------------------
# Hồ sơ người dùng (Profile)
# ---------------------------------------------------------------------------

class ProfileView(LoginRequiredMixin, TemplateView):
    """Hiển thị hồ sơ cá nhân."""

    template_name = 'accounts/profile.html'
    login_url = reverse_lazy('accounts:login')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['page_title'] = 'Hồ sơ cá nhân'

        context['user_roles'] = UserRole.objects.filter(
            user=user,
        ).select_related('role').values_list('role__name', flat=True)

        # Tải lịch sử thay đổi tài khoản (AuditLog) từ database (cho Owner và các vai trò muốn xem)
        from apps.core.models import AuditLog
        context['user_audit_logs'] = AuditLog.objects.filter(user=user).order_by('-created_at')

        # Nếu là ADMIN, lấy danh sách đăng ký chủ sân chưa duyệt
        if 'ADMIN' in context['user_roles']:
            from .models import OwnerRegistrationRequest
            context['pending_owner_requests'] = OwnerRegistrationRequest.objects.filter(
                status=OwnerRegistrationRequest.PENDING
            )

        try:
            context['wallet'] = user.wallet
        except Wallet.DoesNotExist:
            context['wallet'] = None

        return context



class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    """Cập nhật thông tin cá nhân."""

    template_name = 'accounts/profile_edit.html'
    form_class = UserProfileForm
    success_url = reverse_lazy('accounts:profile')
    login_url = reverse_lazy('accounts:login')

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        user = self.request.user
        old_first_name = user.first_name
        old_last_name = user.last_name
        old_phone = user.phone
        
        response = super().form_valid(form)
        
        new_first_name = user.first_name
        new_last_name = user.last_name
        new_phone = user.phone
        
        changes = []
        if old_first_name != new_first_name:
            changes.append(f"Họ: {old_first_name} -> {new_first_name}")
        if old_last_name != new_last_name:
            changes.append(f"Tên: {old_last_name} -> {new_last_name}")
        if old_phone != new_phone:
            changes.append(f"SĐT: {old_phone} -> {new_phone}")
            
        if changes:
            from apps.core.models import AuditLog
            AuditLog.objects.create(
                user=user,
                action='UPDATE',
                target_type='User',
                target_id=str(user.id),
                old_value=', '.join(changes),
                new_value='Cập nhật thông tin cá nhân',
                ip_address=self.request.META.get('REMOTE_ADDR')
            )
        messages.success(self.request, 'Cập nhật hồ sơ thành công!')
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Chỉnh sửa hồ sơ'
        return context


class AvatarUpdateView(LoginRequiredMixin, UpdateView):
    """Upload / thay đổi ảnh đại diện."""

    template_name = 'accounts/avatar_edit.html'
    form_class = AvatarUploadForm
    success_url = reverse_lazy('accounts:profile')
    login_url = reverse_lazy('accounts:login')

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        user = self.request.user
        old_avatar = str(user.avatar) if user.avatar else 'None'
        response = super().form_valid(form)
        new_avatar = str(user.avatar) if user.avatar else 'None'
        
        from apps.core.models import AuditLog
        AuditLog.objects.create(
            user=user,
            action='UPDATE',
            target_type='Avatar',
            target_id=str(user.id),
            old_value=old_avatar,
            new_value=new_avatar,
            ip_address=self.request.META.get('REMOTE_ADDR')
        )
        messages.success(self.request, 'Cập nhật ảnh đại diện thành công!')
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Đổi ảnh đại diện'
        return context


class OwnerProfileUpdateView(LoginRequiredMixin, UpdateView):
    """Cập nhật hồ sơ chủ sân (chỉ dành cho Owner)."""

    template_name = 'accounts/owner_profile_edit.html'
    form_class = OwnerProfileForm
    success_url = reverse_lazy('venues:venue_list')
    login_url = reverse_lazy('accounts:login')

    def get_object(self, queryset=None):
        return self.request.user.owner_profile

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        
        # Chỉ duy nhất người dùng có vai trò OWNER mới được quyền chỉnh sửa thông tin doanh nghiệp
        is_owner = UserRole.objects.filter(user=request.user, role__name='OWNER').exists()
        if not is_owner:
            messages.error(request, 'Bạn không có quyền truy cập trang này. Chỉ dành cho chủ sân.')
            return redirect('accounts:profile')
            
        try:
            request.user.owner_profile
        except Exception:
            messages.error(request, 'Bạn không có hồ sơ doanh nghiệp.')
            return redirect('accounts:profile')
            
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        profile = self.get_object()
        old_business_name = profile.business_name
        old_bank_acc = profile.bank_account_number
        old_bank_name = profile.bank_name
        
        response = super().form_valid(form)
        
        new_business_name = profile.business_name
        new_bank_acc = profile.bank_account_number
        new_bank_name = profile.bank_name
        
        changes = []
        if old_business_name != new_business_name:
            changes.append(f"Doanh nghiệp: {old_business_name} -> {new_business_name}")
        if old_bank_acc != new_bank_acc:
            changes.append(f"Số TK: {old_bank_acc} -> {new_bank_acc}")
        if old_bank_name != new_bank_name:
            changes.append(f"Ngân hàng: {old_bank_name} -> {new_bank_name}")
            
        if changes:
            from apps.core.models import AuditLog
            AuditLog.objects.create(
                user=self.request.user,
                action='UPDATE',
                target_type='OwnerProfile',
                target_id=str(profile.id),
                old_value=', '.join(changes),
                new_value='Cập nhật hồ sơ doanh nghiệp',
                ip_address=self.request.META.get('REMOTE_ADDR')
            )
        messages.success(self.request, 'Cập nhật hồ sơ chủ sân thành công!')
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Chỉnh sửa hồ sơ chủ sân'
        return context


# ---------------------------------------------------------------------------
# Đổi mật khẩu (Change Password)
# ---------------------------------------------------------------------------

class ChangePasswordView(LoginRequiredMixin, FormView):
    """Đổi mật khẩu khi đã đăng nhập."""

    template_name = 'accounts/change_password.html'
    form_class = ChangePasswordForm
    success_url = reverse_lazy('accounts:dashboard')
    login_url = reverse_lazy('accounts:login')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        user = form.save()
        # Cập nhật session để người dùng không bị logout
        update_session_auth_hash(self.request, user)
        
        from apps.core.models import AuditLog
        AuditLog.objects.create(
            user=user,
            action='UPDATE',
            target_type='Password',
            target_id=str(user.id),
            old_value='******',
            new_value='Mật khẩu mới đã được thiết lập',
            ip_address=self.request.META.get('REMOTE_ADDR')
        )
        messages.success(
            self.request,
            'Đổi mật khẩu thành công!',
        )
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Đổi mật khẩu'
        return context


# ---------------------------------------------------------------------------
# Xóa tài khoản (Delete Account)
# ---------------------------------------------------------------------------

class DeleteAccountView(LoginRequiredMixin, View):
    """Xóa tài khoản vĩnh viễn khi người dùng yêu cầu."""

    def post(self, request, *args, **kwargs):
        confirm_text = request.POST.get('confirm_text', '')
        confirm_checkbox = request.POST.get('confirm_checkbox')

        if confirm_text == 'Delete' and confirm_checkbox == 'on':
            user = request.user
            user.delete()
            logout(request)
            messages.success(request, 'Tài khoản của bạn đã được xóa vĩnh viễn.')
            return redirect('accounts:login')
        else:
            messages.error(
                request,
                'Xác nhận không chính xác. Bạn phải tích chọn xác nhận và nhập đúng từ "Delete".'
            )
            return redirect('accounts:profile_edit')


# ---------------------------------------------------------------------------
# Tạo tài khoản nhân viên (Staff Creation by Owner)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Quản lý nhân viên (Staff Management by Owner)
# ---------------------------------------------------------------------------
from django.contrib.auth.mixins import UserPassesTestMixin

class OwnerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Yêu cầu người dùng đăng nhập và phải có vai trò OWNER (Chủ sân)."""
    login_url = reverse_lazy('accounts:login')

    def test_func(self):
        return self.request.user.is_authenticated and hasattr(self.request.user, 'owner_profile')

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            messages.error(self.request, "Bạn không có quyền truy cập trang này. Chỉ dành cho Chủ sân.")
            return redirect('accounts:profile')
        return super().handle_no_permission()


class StaffListView(OwnerRequiredMixin, ListView):
    """Chủ sân (OWNER) xem danh sách nhân viên."""
    model = User
    template_name = 'accounts/staff_list.html'
    context_object_name = 'staffs'
    login_url = reverse_lazy('accounts:login')

    def get_queryset(self):
        owner = self.request.user.owner_profile
        from .models import StaffProfile
        staff_ids = StaffProfile.objects.filter(owner=owner).values_list('user_id', flat=True)
        return User.objects.filter(id__in=staff_ids).select_related('staff_profile__venue').order_by('-date_joined')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Quản lý nhân viên'
        context['owner_profile'] = self.request.user.owner_profile
        return context


class StaffCreateView(OwnerRequiredMixin, CreateView):
    """Chủ sân (OWNER) tạo tài khoản nhân viên (STAFF) thuộc cơ sở của mình."""
    template_name = 'accounts/staff_create.html'
    form_class = StaffRegistrationForm
    success_url = reverse_lazy('accounts:staff_list')
    login_url = reverse_lazy('accounts:login')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['owner'] = self.request.user.owner_profile
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            staff_user = form.save()
            # Gán vai trò STAFF
            staff_role, _ = Role.objects.get_or_create(name=Role.STAFF)
            UserRole.objects.get_or_create(user=staff_user, role=staff_role)
            # Tạo ví
            Wallet.objects.get_or_create(user=staff_user)
            
            # Log audit log for owner who performed the action
            from apps.core.models import AuditLog
            AuditLog.objects.create(
                user=self.request.user,
                action='CREATE',
                target_type='StaffUser',
                target_id=str(staff_user.id),
                old_value=None,
                new_value=f"Tạo nhân viên {staff_user.email} (cơ sở: {form.cleaned_data.get('venue')})",
                ip_address=self.request.META.get('REMOTE_ADDR')
            )
        messages.success(
            self.request,
            f'Tạo tài khoản nhân viên {staff_user.email} thành công!',
        )
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Thêm nhân viên'
        context['owner_profile'] = self.request.user.owner_profile
        return context


class StaffUpdateView(OwnerRequiredMixin, UpdateView):
    """Chủ sân (OWNER) chỉnh sửa thông tin nhân viên."""
    model = User
    form_class = StaffUpdateForm
    template_name = 'accounts/staff_edit.html'
    success_url = reverse_lazy('accounts:staff_list')
    login_url = reverse_lazy('accounts:login')

    def get_queryset(self):
        owner = self.request.user.owner_profile
        from .models import StaffProfile
        staff_ids = StaffProfile.objects.filter(owner=owner).values_list('user_id', flat=True)
        return User.objects.filter(id__in=staff_ids)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['owner'] = self.request.user.owner_profile
        return kwargs

    def form_valid(self, form):
        staff_user = self.get_object()
        old_venue = staff_user.staff_profile.venue
        old_name = f"{staff_user.first_name} {staff_user.last_name}"
        old_phone = staff_user.phone
        
        response = super().form_valid(form)
        
        new_venue = staff_user.staff_profile.venue
        new_name = f"{staff_user.first_name} {staff_user.last_name}"
        new_phone = staff_user.phone
        
        changes = []
        if old_name != new_name:
            changes.append(f"Tên: {old_name} -> {new_name}")
        if old_phone != new_phone:
            changes.append(f"SĐT: {old_phone} -> {new_phone}")
        if old_venue != new_venue:
            changes.append(f"Cơ sở: {old_venue} -> {new_venue}")
            
        if changes:
            from apps.core.models import AuditLog
            AuditLog.objects.create(
                user=self.request.user,
                action='UPDATE',
                target_type='StaffUser',
                target_id=str(staff_user.id),
                old_value=', '.join(changes),
                new_value='Cập nhật thông tin nhân viên',
                ip_address=self.request.META.get('REMOTE_ADDR')
            )
        messages.success(self.request, 'Cập nhật thông tin nhân viên thành công.')
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Sửa thông tin nhân viên'
        context['owner_profile'] = self.request.user.owner_profile
        return context


class StaffDeleteView(OwnerRequiredMixin, View):
    """Chủ sân (OWNER) xóa tài khoản nhân viên."""
    login_url = reverse_lazy('accounts:login')

    def post(self, request, pk, *args, **kwargs):
        owner = request.user.owner_profile
        from .models import StaffProfile
        try:
            # Chỉ được xóa nhân viên thuộc owner này quản lý
            staff_prof = StaffProfile.objects.get(user_id=pk, owner=owner)
            staff_user = staff_prof.user
            email = staff_user.email
            
            with transaction.atomic():
                # Xóa VenueStaff tương ứng
                from apps.core.models import VenueStaff
                VenueStaff.objects.filter(staff=staff_user).delete()
                
                # Log audit log before delete
                from apps.core.models import AuditLog
                AuditLog.objects.create(
                    user=request.user,
                    action='DELETE',
                    target_type='StaffUser',
                    target_id=str(pk),
                    old_value=f"Nhân viên: {email}",
                    new_value=None,
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                
                # Xóa User (cũng sẽ xóa StaffProfile do CASCADE)
                staff_user.delete()
                
            messages.success(request, f'Đã xóa tài khoản nhân viên {email} thành công.')
        except StaffProfile.DoesNotExist:
            messages.error(request, 'Không tìm thấy nhân viên hoặc bạn không có quyền xóa.')
        
        return redirect('accounts:staff_list')



# ---------------------------------------------------------------------------
# Duyệt chủ sân (Admin Approval)
# ---------------------------------------------------------------------------

class AdminApproveOwnerView(LoginRequiredMixin, View):
    """Admin duyệt yêu cầu đăng ký chủ sân, tạo tài khoản và ví."""

    def post(self, request, pk, *args, **kwargs):
        from .models import OwnerRegistrationRequest, User, OwnerProfile, Role, UserRole, Wallet
        from django.utils import timezone

        is_admin = UserRole.objects.filter(user=request.user, role__name='ADMIN').exists()
        if not is_admin:
            messages.error(request, 'Bạn không có quyền thực hiện hành động này.')
            return redirect('accounts:profile')

        try:
            req = OwnerRegistrationRequest.objects.get(pk=pk, status=OwnerRegistrationRequest.PENDING)
            with transaction.atomic():
                # Tạo User mới từ request đã lưu
                user = User(
                    email=req.email,
                    first_name=req.first_name,
                    last_name=req.last_name,
                    phone=req.phone,
                    password=req.password_hash,
                    is_active=True
                )
                user._is_owner_registration = True
                user.save()

                # Tạo OwnerProfile
                OwnerProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'business_name': req.business_name,
                        'bank_account_number': req.bank_account_number,
                        'bank_name': req.bank_name,
                        'is_verified': True
                    }
                )

                # Gán vai trò OWNER
                owner_role, _ = Role.objects.get_or_create(name=Role.OWNER)
                UserRole.objects.get_or_create(user=user, role=owner_role)

                # Tạo Wallet
                Wallet.objects.get_or_create(user=user)

                # Đánh dấu yêu cầu đã được duyệt
                req.status = OwnerRegistrationRequest.APPROVED
                req.reviewed_at = timezone.now()
                req.reviewed_by = request.user
                req.save()

            messages.success(request, f'Đã phê duyệt và tạo tài khoản chủ sân cho {req.email}.')
        except OwnerRegistrationRequest.DoesNotExist:
            messages.error(request, 'Yêu cầu đăng ký không tồn tại hoặc đã được xử lý.')
        except Exception as e:
            messages.error(request, f'Lỗi hệ thống: {str(e)}')

        return redirect('accounts:profile')


class AdminRejectOwnerView(LoginRequiredMixin, View):
    """Admin từ chối yêu cầu đăng ký chủ sân."""

    def post(self, request, pk, *args, **kwargs):
        is_admin = UserRole.objects.filter(user=request.user, role__name='ADMIN').exists()
        if not is_admin:
            messages.error(request, 'Bạn không có quyền thực hiện hành động này.')
            return redirect('accounts:profile')

        from .models import OwnerRegistrationRequest

        try:
            req = OwnerRegistrationRequest.objects.get(pk=pk, status=OwnerRegistrationRequest.PENDING)
            # Xóa yêu cầu hoàn toàn để email có thể đăng ký lại nếu muốn
            req.delete()
            messages.success(request, 'Đã từ chối yêu cầu đăng ký chủ sân.')
        except OwnerRegistrationRequest.DoesNotExist:
            messages.error(request, 'Yêu cầu đăng ký không tồn tại hoặc đã được xử lý.')

        return redirect('accounts:profile')


# ---------------------------------------------------------------------------
# Quản lý tài khoản hệ thống (Admin User Management)
# ---------------------------------------------------------------------------
from django.shortcuts import get_object_or_404

class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Yêu cầu người dùng đăng nhập và phải có vai trò ADMIN."""
    login_url = reverse_lazy('accounts:login')

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_admin

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            messages.error(self.request, "Bạn không có quyền truy cập trang này. Chỉ dành cho Admin.")
            return redirect('accounts:profile')
        return super().handle_no_permission()


class AdminUserListView(AdminRequiredMixin, ListView):
    """Admin quản lý danh sách toàn bộ User trong hệ thống."""
    model = User
    template_name = 'accounts/admin_user_list.html'
    context_object_name = 'users'
    paginate_by = 10

    def get_queryset(self):
        from django.db.models import Q
        qs = User.objects.all().order_by('-date_joined')
        
        # Search query
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(email__icontains=q) |
                Q(username__icontains=q) |
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q) |
                Q(phone__icontains=q)
            )

        # Role filter
        role_filter = self.request.GET.get('role', '').strip()
        if role_filter:
            qs = qs.filter(user_roles__role__name=role_filter)

        # Status filter
        status_filter = self.request.GET.get('status', '').strip()
        if status_filter:
            if status_filter == 'active':
                qs = qs.filter(is_active=True)
            elif status_filter == 'inactive':
                qs = qs.filter(is_active=False)

        return qs.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Quản lý tài khoản'
        
        # Get roles for filter dropdown
        context['available_roles'] = ['CUSTOMER', 'OWNER', 'STAFF', 'ADMIN']
        
        # Maintain query params in pagination
        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_params'] = query_params.urlencode()
        
        # Active query values
        context['current_q'] = self.request.GET.get('q', '')
        context['current_role'] = self.request.GET.get('role', '')
        context['current_status'] = self.request.GET.get('status', '')
        
        return context


class AdminUserToggleActiveView(AdminRequiredMixin, View):
    """Admin khóa/mở khóa tài khoản."""

    def post(self, request, pk, *args, **kwargs):
        user_to_toggle = get_object_or_404(User, pk=pk)
        
        # Don't allow toggling self active status
        if user_to_toggle == request.user:
            messages.error(request, 'Bạn không thể tự khóa tài khoản của chính mình.')
            return redirect('accounts:admin_user_list')

        user_to_toggle.is_active = not user_to_toggle.is_active
        user_to_toggle.save()

        status_text = 'Mở khóa' if user_to_toggle.is_active else 'Khóa'
        
        # Log to AuditLog
        from apps.core.models import AuditLog
        AuditLog.objects.create(
            user=request.user,
            action='UPDATE',
            target_type='UserStatus',
            target_id=str(user_to_toggle.id),
            old_value=f"is_active: {not user_to_toggle.is_active}",
            new_value=f"is_active: {user_to_toggle.is_active}",
            ip_address=request.META.get('REMOTE_ADDR')
        )

        messages.success(request, f'Đã {status_text.lower()} tài khoản {user_to_toggle.email} thành công.')
        return redirect('accounts:admin_user_list')


class AdminUserDeleteView(AdminRequiredMixin, View):
    """Admin xóa tài khoản vĩnh viễn."""

    def post(self, request, pk, *args, **kwargs):
        user_to_delete = get_object_or_404(User, pk=pk)

        # Don't allow deleting self
        if user_to_delete == request.user:
            messages.error(request, 'Bạn không thể tự xóa tài khoản của chính mình.')
            return redirect('accounts:admin_user_list')

        email = user_to_delete.email
        with transaction.atomic():
            # Delete VenueStaff if any
            from apps.core.models import VenueStaff
            VenueStaff.objects.filter(staff=user_to_delete).delete()

            # Log to AuditLog
            from apps.core.models import AuditLog
            AuditLog.objects.create(
                user=request.user,
                action='DELETE',
                target_type='User',
                target_id=str(pk),
                old_value=f"Tài khoản: {email}",
                new_value=None,
                ip_address=request.META.get('REMOTE_ADDR')
            )

            # Delete the user (this will cascade delete profiles, etc.)
            user_to_delete.delete()

        messages.success(request, f'Đã xóa tài khoản {email} vĩnh viễn.')
        return redirect('accounts:admin_user_list')

