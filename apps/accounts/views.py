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

        # Nếu là ADMIN, lấy thêm các chỉ số hệ thống
        if 'ADMIN' in context['user_roles'] or user.is_admin:
            from django.db.models import Sum, Count
            from django.utils import timezone
            from datetime import timedelta
            from apps.venues.models import Venue
            from apps.payments.models import WalletTransaction, Payment
            from apps.bookings.models import Booking
            from apps.accounts.models import OwnerRegistrationRequest

            # Thống kê số lượng các vai trò
            context['total_users'] = User.objects.count()
            context['total_owners'] = UserRole.objects.filter(role__name='OWNER').count()
            context['total_staffs'] = UserRole.objects.filter(role__name='STAFF').count()
            context['total_customers'] = UserRole.objects.filter(role__name='CUSTOMER').count()
            context['total_venues'] = Venue.objects.filter(is_deleted=False).count()
            
            # Tổng doanh thu & giao dịch
            total_rev_agg = Payment.objects.filter(status__in=['COMPLETED', 'PAID']).aggregate(sum_amount=Sum('amount'))
            context['total_revenue'] = total_rev_agg['sum_amount'] or 0
            context['total_transactions'] = Payment.objects.filter(status__in=['COMPLETED', 'PAID']).count()
            
            # Báo cáo hàng đợi
            context['pending_venues'] = Venue.objects.filter(status='PENDING', is_deleted=False).order_by('-updated_at')
            context['pending_owners'] = OwnerRegistrationRequest.objects.filter(status=OwnerRegistrationRequest.PENDING).order_by('-created_at')
            context['recent_registered_users'] = User.objects.order_by('-date_joined')[:5]

            # Báo cáo vi phạm (Mock data)
            context['violation_reports'] = [
                {
                    'id': 1,
                    'reporter': 'user.customer1@gmail.com',
                    'target_type': 'Venue',
                    'target_name': 'Sân bóng cỏ nhân tạo Nguyễn Du',
                    'reason': 'Thông tin giá thuê trên app chênh lệch cao so với thực tế tại sân.',
                    'status': 'PENDING',
                    'created_at': timezone.now() - timedelta(hours=3),
                },
                {
                    'id': 2,
                    'reporter': 'sporty_guy99@gmail.com',
                    'target_type': 'Review',
                    'target_name': 'Đánh giá của khách hàng về Sân cầu lông Ngôi Sao',
                    'reason': 'Đánh giá chứa ngôn từ thô tục, công kích cá nhân.',
                    'status': 'PENDING',
                    'created_at': timezone.now() - timedelta(days=1),
                },
                {
                    'id': 3,
                    'reporter': 'owner.minh@gmail.com',
                    'target_type': 'User',
                    'target_name': 'hoang_linh_90',
                    'reason': 'Khách hàng liên tục đặt sân rồi tự ý hủy mà không qua quy trình thanh toán.',
                    'status': 'PENDING',
                    'created_at': timezone.now() - timedelta(days=2),
                }
            ]

            # Dữ liệu biểu đồ Doanh thu & Booking theo thời gian (30 ngày gần nhất)
            today = timezone.now().date()
            dates_30d = [today - timedelta(days=i) for i in range(29, -1, -1)]
            context['chart_dates'] = [d.strftime('%d/%m') for d in dates_30d]

            # Doanh thu từng ngày trong 30 ngày qua
            rev_by_date = {}
            payments_30d = Payment.objects.filter(
                status__in=['COMPLETED', 'PAID'],
                created_at__date__gte=today - timedelta(days=30)
            ).values('created_at__date').annotate(day_sum=Sum('amount'))
            for p in payments_30d:
                rev_by_date[p['created_at__date']] = float(p['day_sum'] or 0)
            context['chart_revenue_data'] = [rev_by_date.get(d, 0.0) for d in dates_30d]

            # Booking từng ngày trong 30 ngày qua
            bookings_by_date = {}
            bookings_30d = Booking.objects.filter(
                booking_date__gte=today - timedelta(days=30)
            ).values('booking_date').annotate(day_count=Count('id'))
            for b in bookings_30d:
                bookings_by_date[b['booking_date']] = b['day_count']
            context['chart_bookings_data'] = [bookings_by_date.get(d, 0) for d in dates_30d]

            # Top cơ sở có doanh thu cao nhất
            top_venues_qs = Payment.objects.filter(status__in=['COMPLETED', 'PAID']).values('booking__venue__name').annotate(
                total_rev=Sum('amount')
            ).order_by('-total_rev')[:5]
            
            context['top_venues_names'] = [tv['booking__venue__name'] or 'Cơ sở ẩn' for tv in top_venues_qs]
            context['top_venues_revs'] = [float(tv['total_rev'] or 0) for tv in top_venues_qs]

        elif 'OWNER' in context['user_roles'] or user.is_owner:
            from django.db.models import Sum, Count
            from django.utils import timezone
            from datetime import timedelta
            from apps.venues.models import Venue, Field
            from apps.payments.models import Payment
            from apps.bookings.models import Booking, BookingSlot
            from apps.reviews.models import Review

            owner_profile = None
            try:
                owner_profile = user.owner_profile
            except Exception:
                pass

            if owner_profile:
                owner_venue_ids = list(owner_profile.venues.values_list('id', flat=True))
            else:
                owner_venue_ids = []

            # 1. Venues & Fields counts
            context['owner_venue_count'] = len(owner_venue_ids)
            context['owner_fields_count'] = Field.objects.filter(venue_id__in=owner_venue_ids).count()

            # 2. Revenue (Doanh thu hôm nay, tuần, tháng, năm)
            today = timezone.now().date()
            owner_payments = Payment.objects.filter(
                booking__venue_id__in=owner_venue_ids,
                status__in=['COMPLETED', 'PAID']
            )
            context['owner_rev_today'] = owner_payments.filter(created_at__date=today).aggregate(Sum('amount'))['amount__sum'] or 0
            context['owner_rev_week'] = owner_payments.filter(created_at__date__gte=today - timedelta(days=7)).aggregate(Sum('amount'))['amount__sum'] or 0
            context['owner_rev_month'] = owner_payments.filter(created_at__date__gte=today - timedelta(days=30)).aggregate(Sum('amount'))['amount__sum'] or 0
            context['owner_rev_year'] = owner_payments.filter(created_at__date__gte=today - timedelta(days=365)).aggregate(Sum('amount'))['amount__sum'] or 0

            # 3. Booking hôm nay & tháng
            owner_bookings = Booking.objects.filter(venue_id__in=owner_venue_ids).exclude(status='CANCELLED')
            context['owner_booking_today'] = owner_bookings.filter(booking_date=today).count()
            context['owner_booking_month'] = owner_bookings.filter(booking_date__month=today.month, booking_date__year=today.year).count()

            # 4. Tỷ lệ lấp đầy sân hôm nay
            today_slots = BookingSlot.objects.filter(
                booking__venue_id__in=owner_venue_ids,
                booking__booking_date=today
            ).exclude(booking__status='CANCELLED')
            
            total_hours_today = 0.0
            for slot in today_slots:
                try:
                    import datetime
                    t1 = datetime.datetime.combine(datetime.date.min, slot.start_time)
                    t2 = datetime.datetime.combine(datetime.date.min, slot.end_time)
                    total_hours_today += (t2 - t1).total_seconds() / 3600.0
                except Exception:
                    pass

            active_fields_count = Field.objects.filter(venue_id__in=owner_venue_ids, status='ACTIVE').count()
            if active_fields_count > 0:
                context['owner_occupancy_rate'] = round((total_hours_today / (active_fields_count * 15.0)) * 100, 1)
            else:
                context['owner_occupancy_rate'] = 0.0

            # 5. Tổng khách hàng & Khách quay lại
            customer_bookings = Booking.objects.filter(venue_id__in=owner_venue_ids).exclude(status='CANCELLED')
            customer_counts = customer_bookings.values('booking_package__user').annotate(cnt=Count('id'))
            context['owner_total_customers'] = len(customer_counts)
            context['owner_returning_customers'] = sum(1 for c in customer_counts if c['cnt'] >= 2)

            # 6. Tổng đánh giá
            owner_reviews = Review.objects.filter(venue_id__in=owner_venue_ids)
            context['owner_total_reviews'] = owner_reviews.count()

            # 7. Biểu đồ: Doanh thu & Booking theo thời gian
            dates_30d = [today - timedelta(days=i) for i in range(29, -1, -1)]
            context['owner_chart_dates'] = [d.strftime('%d/%m') for d in dates_30d]

            rev_by_date = {}
            payments_30d = owner_payments.filter(created_at__date__gte=today - timedelta(days=30)).values('created_at__date').annotate(day_sum=Sum('amount'))
            for p in payments_30d:
                rev_by_date[p['created_at__date']] = float(p['day_sum'] or 0)
            context['owner_chart_rev_data'] = [rev_by_date.get(d, 0.0) for d in dates_30d]

            bookings_by_date = {}
            bookings_30d = owner_bookings.filter(booking_date__gte=today - timedelta(days=30)).values('booking_date').annotate(day_count=Count('id'))
            for b in bookings_30d:
                bookings_by_date[b['booking_date']] = b['day_count']
            context['owner_chart_bookings_data'] = [bookings_by_date.get(d, 0) for d in dates_30d]

            # 8. Biểu đồ: Hiệu suất sử dụng từng sân
            fields_perf = []
            fields_labels = []
            fields_revs = []
            fields_bookings = []
            
            for field in Field.objects.filter(venue_id__in=owner_venue_ids):
                slots_this_month = BookingSlot.objects.filter(
                    booking__field=field,
                    booking__booking_date__month=today.month,
                    booking__booking_date__year=today.year
                ).exclude(booking__status='CANCELLED')
                
                hours = 0.0
                for s in slots_this_month:
                    try:
                        import datetime
                        t1 = datetime.datetime.combine(datetime.date.min, s.start_time)
                        t2 = datetime.datetime.combine(datetime.date.min, s.end_time)
                        hours += (t2 - t1).total_seconds() / 3600.0
                    except Exception:
                        pass
                
                rev = owner_payments.filter(booking__field=field).aggregate(Sum('amount'))['amount__sum'] or 0
                
                fields_labels.append(field.name)
                fields_perf.append(round(hours, 1))
                fields_revs.append(float(rev))
                fields_bookings.append(owner_bookings.filter(field=field).count())

            context['owner_fields_labels'] = fields_labels
            context['owner_fields_perf'] = fields_perf
            context['owner_fields_revs'] = fields_revs
            context['owner_fields_bookings'] = fields_bookings

            # 9. Biểu đồ: Khung giờ đông khách & ít khách (Peak hours)
            hour_counts = [0] * 24
            all_slots = BookingSlot.objects.filter(booking__venue_id__in=owner_venue_ids).exclude(booking__status='CANCELLED')
            for slot in all_slots:
                hour_counts[slot.start_time.hour] += 1
            context['owner_chart_hours'] = [f'{h:02d}:00' for h in range(6, 23)]
            context['owner_chart_hour_counts'] = [hour_counts[h] for h in range(6, 23)]

            # 10. Bảng biểu
            fields_stats = []
            for idx, field in enumerate(Field.objects.filter(venue_id__in=owner_venue_ids)):
                total_hours_month = fields_perf[idx] if idx < len(fields_perf) else 0.0
                use_rate = round((total_hours_month / (30.0 * 15.0)) * 100, 1)
                fields_stats.append({
                    'name': field.name,
                    'venue_name': field.venue.name,
                    'hours': total_hours_month,
                    'revenue': fields_revs[idx] if idx < len(fields_revs) else 0.0,
                    'use_rate': use_rate,
                    'status': field.status
                })
            context['owner_fields_stats'] = fields_stats

            # Booking gần đây
            context['owner_recent_bookings'] = Booking.objects.filter(
                venue_id__in=owner_venue_ids
            ).select_related('booking_package__user', 'field').order_by('-created_at')[:10]

            # Đánh giá mới
            context['owner_recent_reviews'] = owner_reviews.select_related('user', 'venue').order_by('-created_at')[:5]

        elif 'STAFF' in context['user_roles'] or user.is_staff_member:
            from django.db.models import Sum, Count
            from django.utils import timezone
            from datetime import timedelta, datetime
            from apps.venues.models import Venue, Field
            from apps.payments.models import Payment
            from apps.bookings.models import Booking, BookingSlot
            from apps.services.models import BookingService

            staff_profile = None
            try:
                staff_profile = user.staff_profile
            except Exception:
                pass

            if staff_profile:
                if staff_profile.venue_id:
                    staff_venue_ids = [staff_profile.venue_id]
                elif staff_profile.owner_id:
                    staff_venue_ids = list(Venue.objects.filter(owner_id=staff_profile.owner_id, is_deleted=False).values_list('id', flat=True))
                else:
                    staff_venue_ids = []
            else:
                staff_venue_ids = []

            today = timezone.localtime().date()
            now_time = timezone.localtime().time()

            # 1. Booking hôm nay
            staff_bookings_today = Booking.objects.filter(
                venue_id__in=staff_venue_ids,
                booking_date=today
            ).exclude(status='CANCELLED')
            context['staff_booking_today'] = staff_bookings_today.count()

            # 2. Khách đang chơi & Sân đang sử dụng (real-time)
            active_slots = BookingSlot.objects.filter(
                booking__venue_id__in=staff_venue_ids,
                booking__booking_date=today,
                start_time__lte=now_time,
                end_time__gte=now_time
            ).exclude(booking__status='CANCELLED')
            
            context['staff_playing_now'] = active_slots.values('booking__booking_package__user').distinct().count()
            context['staff_fields_in_use'] = active_slots.values('booking__field').distinct().count()

            # 3. Sân sắp bắt đầu & Sân sắp kết thúc trong 1 giờ tới
            now_dt = datetime.combine(today, now_time)
            one_hour_later = (now_dt + timedelta(hours=1)).time()
            
            upcoming_slots = BookingSlot.objects.filter(
                booking__venue_id__in=staff_venue_ids,
                booking__booking_date=today,
                start_time__gt=now_time,
                start_time__lte=one_hour_later
            ).exclude(booking__status='CANCELLED')
            context['staff_fields_starting'] = upcoming_slots.values('booking__field').distinct().count()

            ending_slots = BookingSlot.objects.filter(
                booking__venue_id__in=staff_venue_ids,
                booking__booking_date=today,
                end_time__gt=now_time,
                end_time__lte=one_hour_later
            ).exclude(booking__status='CANCELLED')
            context['staff_fields_ending'] = ending_slots.values('booking__field').distinct().count()

            # 4. Dịch vụ bán hôm nay
            today_services = BookingService.objects.filter(
                booking__venue_id__in=staff_venue_ids,
                created_at__date=today
            )
            sold_count = today_services.aggregate(Sum('quantity'))['quantity__sum'] or 0
            sold_rev = sum(item.quantity * item.unit_price for item in today_services)
            context['staff_services_sold'] = f'{sold_count} sản phẩm ({sold_rev:,.0f}đ)'

            # 5. Biểu đồ: Booking theo giờ hôm nay
            hour_counts = [0] * 24
            for slot in BookingSlot.objects.filter(booking__venue_id__in=staff_venue_ids, booking__booking_date=today).exclude(booking__status='CANCELLED'):
                hour_counts[slot.start_time.hour] += 1
            context['staff_chart_hours'] = [f'{h:02d}:00' for h in range(6, 23)]
            context['staff_chart_hour_counts'] = [hour_counts[h] for h in range(6, 23)]

            # 6. Bảng biểu
            # Danh sách Booking hôm nay
            context['staff_today_bookings'] = Booking.objects.filter(
                venue_id__in=staff_venue_ids,
                booking_date=today
            ).select_related('booking_package__user', 'field').exclude(status='CANCELLED').order_by('slots__start_time').distinct()

            # Khách đang sử dụng sân
            context['staff_active_slots_list'] = active_slots.select_related('booking__booking_package__user', 'booking__field')

            # Booking sắp tới
            context['staff_upcoming_bookings'] = Booking.objects.filter(
                venue_id__in=staff_venue_ids,
                booking_date__gte=today
            ).exclude(status='CANCELLED').select_related('booking_package__user', 'field').order_by('booking_date', 'slots__start_time').distinct()[:10]

            # Đơn dịch vụ gần đây
            context['staff_recent_services'] = BookingService.objects.filter(
                booking__venue_id__in=staff_venue_ids
            ).select_related('booking__booking_package__user', 'service_item').order_by('-created_at')[:10]

        else:
            # Dành cho CUSTOMER
            from django.db.models import Sum, Count, F
            from django.utils import timezone
            from datetime import timedelta, datetime
            from apps.payments.models import Promotion
            from apps.accounts.models import WalletTransaction
            from apps.bookings.models import Booking, BookingSlot
            from apps.reviews.models import Review

            today = timezone.localtime().date()

            # 1. Điểm tích lũy & Ví
            cust_profile = getattr(user, 'customer_profile', None)
            context['cust_loyalty_points'] = cust_profile.loyalty_points if cust_profile else 0
            
            wallet = context.get('wallet')
            context['cust_wallet_balance'] = wallet.balance if wallet else 0

            # 2. Booking sắp tới và đã hoàn thành
            user_bookings = Booking.objects.filter(booking_package__user=user)
            context['cust_upcoming_count'] = user_bookings.filter(booking_date__gte=today).exclude(status='CANCELLED').count()
            context['cust_completed_count'] = user_bookings.filter(status__in=['COMPLETED', 'PAID']).count()

            # 3. Tổng giờ chơi trong tháng hiện tại
            user_slots_month = BookingSlot.objects.filter(
                booking__booking_package__user=user,
                booking__booking_date__month=today.month,
                booking__booking_date__year=today.year,
                booking__status__in=['COMPLETED', 'PAID']
            )
            total_hours = 0.0
            for slot in user_slots_month:
                try:
                    import datetime as dt_mod
                    t1 = dt_mod.datetime.combine(dt_mod.date.min, slot.start_time)
                    t2 = dt_mod.datetime.combine(dt_mod.date.min, slot.end_time)
                    total_hours += (t2 - t1).total_seconds() / 3600.0
                except Exception:
                    pass
            context['cust_hours_month'] = round(total_hours, 1)

            # 4. Voucher/Promotion khả dụng
            active_promos = Promotion.objects.filter(
                is_active=True,
                quantity__gt=F('used_quantity'),
                start_date__lte=today,
                end_date__gte=today
            )
            context['cust_voucher_count'] = active_promos.count()
            context['cust_vouchers'] = active_promos[:5]

            # 5. Biểu đồ số giờ thuê theo tháng trong năm hiện tại
            months_hours = [0.0] * 12
            user_slots_year = BookingSlot.objects.filter(
                booking__booking_package__user=user,
                booking__booking_date__year=today.year,
                booking__status__in=['COMPLETED', 'PAID']
            )
            for slot in user_slots_year:
                try:
                    import datetime as dt_mod
                    t1 = dt_mod.datetime.combine(dt_mod.date.min, slot.start_time)
                    t2 = dt_mod.datetime.combine(dt_mod.date.min, slot.end_time)
                    m = slot.booking.booking_date.month - 1
                    months_hours[m] += (t2 - t1).total_seconds() / 3600.0
                except Exception:
                    pass

            context['cust_chart_labels'] = ['Thg 1', 'Thg 2', 'Thg 3', 'Thg 4', 'Thg 5', 'Thg 6', 'Thg 7', 'Thg 8', 'Thg 9', 'Thg 10', 'Thg 11', 'Thg 12']
            context['cust_chart_hours'] = [round(h, 1) for h in months_hours]

            # 6. Bảng biểu
            context['cust_bookings_history'] = user_bookings.select_related('field__venue').order_by('-booking_date', '-created_at')[:10]

            if wallet:
                context['cust_transactions_history'] = WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')[:10]
            else:
                context['cust_transactions_history'] = []

            context['cust_favorite_venues'] = user.favorite_venues.select_related('venue').all()[:6]

            context['cust_reviews'] = Review.objects.filter(user=user).select_related('venue').order_by('-created_at')[:10]

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

