from datetime import date as date_class

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Prefetch, Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from apps.accounts.models import UserRole
from apps.services.models import BookingService, ServiceItem
from apps.venues.models import Field, Venue
from .forms import BookingCreateForm
from .models import Booking
from .permissions import (
    BOOKING_MANAGE_DENIED_MESSAGE,
    OwnerBookingRequiredMixin,
    StaffRequiredMixin,
    can_manage_booking,
    get_booking_queryset_for_user,
    get_owner_profile,
)
from .services import (
    calculate_booking_price,
    cancel_expired_booking_if_needed,
    cancel_expired_pending_bookings,
    create_booking,
    get_booking_slot_options,
    get_bookable_fields_queryset,
    get_time_blocks_for_field_date,
    get_unavailable_time_blocks,
)


FIELD_ACTIVE_STATUS = getattr(Field, 'ACTIVE', 'ACTIVE')
BOOKING_EXPIRED_MESSAGE = 'Đơn đặt sân đã quá hạn thanh toán và đã bị hủy.'


def _is_ajax(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _booking_detail_partial_context(booking, back_url=None):
    return {
        'booking': booking,
        'can_edit_booking_services': booking.can_modify_services(),
        'booking_service_lock_message': booking.get_service_modification_block_message(),
        'can_cancel_booking': booking.can_cancel(),
        'cancel_block_message': booking.get_cancel_block_message(),
        'can_pay_booking': booking.can_pay(),
        'back_url': back_url or reverse('bookings:booking_list'),
    }


def _render_booking_detail_partial(request, booking):
    refreshed_booking = get_object_or_404(_management_base_queryset(), pk=booking.pk)
    return render_to_string(
        'bookings/partials/_booking_detail_content.html',
        _booking_detail_partial_context(refreshed_booking),
        request=request,
    )


def _validation_error_messages(exc):
    if hasattr(exc, 'message_dict'):
        messages = []
        for field, field_messages in exc.message_dict.items():
            for message in field_messages:
                messages.append(f'{field}: {message}')
        return messages
    return exc.messages if hasattr(exc, 'messages') else [str(exc)]


def _parse_booking_date(value):
    if isinstance(value, date_class):
        return value
    if not value:
        return None
    return parse_date(str(value))


def _get_field_from_value(value):
    if isinstance(value, Field):
        return value
    if not value:
        return None
    try:
        return get_bookable_fields_queryset().get(pk=value)
    except (Field.DoesNotExist, TypeError, ValueError):
        return None


def _get_default_field():
    return get_bookable_fields_queryset().order_by('pk').first()


class BookingListView(LoginRequiredMixin, ListView):
    template_name = 'bookings/booking_list.html'
    context_object_name = 'bookings'

    def get_queryset(self):
        # Auto-cancel expired pending holds before listing so statuses are fresh.
        cancel_expired_pending_bookings()
        return get_booking_queryset_for_user(
            self.request.user,
            Booking.objects.select_related('venue', 'field', 'booking_package').prefetch_related(
                'slots',
                Prefetch(
                    'services_ordered',
                    queryset=BookingService.objects.select_related('service_item'),
                ),
            ),
        )


class BookingHistoryListView(LoginRequiredMixin, ListView):
    """History view from main for all booking roles."""

    model = Booking
    template_name = 'bookings/booking_history.html'
    context_object_name = 'bookings'
    login_url = reverse_lazy('accounts:login')

    def _role_names(self):
        if not hasattr(self, '_cached_role_names'):
            self._cached_role_names = set(
                UserRole.objects.filter(user=self.request.user).values_list('role__name', flat=True)
            )
        return self._cached_role_names

    def _is_customer_scope(self):
        privileged_roles = {'ADMIN', 'OWNER', 'STAFF'}
        return not bool(self._role_names() & privileged_roles)

    def get_queryset(self):
        # Auto-cancel expired pending holds so history shows the real status.
        cancel_expired_pending_bookings()
        user = self.request.user
        roles = self._role_names()
        queryset = (
            Booking.objects
            .select_related('booking_package__user', 'venue', 'field')
            .prefetch_related('slots')
            .order_by('-created_at')
        )

        if 'ADMIN' in roles:
            return queryset
        if 'OWNER' in roles:
            if hasattr(user, 'owner_profile'):
                return queryset.filter(venue__owner=user.owner_profile)
            return queryset.none()
        if 'STAFF' in roles:
            if hasattr(user, 'staff_profile') and user.staff_profile.venue:
                return queryset.filter(venue=user.staff_profile.venue)
            if hasattr(user, 'staff_profile') and user.staff_profile.owner:
                return queryset.filter(venue__owner=user.staff_profile.owner)
            return queryset.none()
        return queryset.filter(booking_package__user=user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        roles = self._role_names()

        if 'ADMIN' in roles:
            context['filter_venues'] = Venue.objects.filter(is_deleted=False)
        elif 'OWNER' in roles and hasattr(user, 'owner_profile'):
            context['filter_venues'] = Venue.objects.filter(owner=user.owner_profile, is_deleted=False)
        elif 'STAFF' in roles and hasattr(user, 'staff_profile') and user.staff_profile.owner:
            context['filter_venues'] = Venue.objects.filter(owner=user.staff_profile.owner, is_deleted=False)
        else:
            context['filter_venues'] = None

        if 'ADMIN' in roles:
            context['page_title'] = 'Lịch sử thuê sân toàn hệ thống'
        elif 'OWNER' in roles or 'STAFF' in roles:
            context['page_title'] = 'Lịch sử cho thuê sân'
        else:
            context['page_title'] = 'Lịch sử thuê sân'
        context['show_customer_booking_actions'] = self._is_customer_scope()
        return context


class BookingDetailView(LoginRequiredMixin, DetailView):
    model = Booking
    template_name = 'bookings/booking_detail.html'
    context_object_name = 'booking'

    def get_queryset(self):
        return Booking.objects.select_related(
            'venue',
            'field',
            'booking_package',
            'booking_package__user',
        ).prefetch_related(
            'slots',
            Prefetch(
                'services_ordered',
                queryset=BookingService.objects.select_related('service_item'),
            ),
        ).filter(booking_package__user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Flip the booking to CANCELLED if its 10-minute hold has expired.
        if cancel_expired_booking_if_needed(self.object):
            messages.warning(self.request, BOOKING_EXPIRED_MESSAGE)
        context['can_edit_booking_services'] = self.object.can_modify_services()
        context['booking_service_lock_message'] = self.object.get_service_modification_block_message()
        context['can_cancel_booking'] = self.object.can_cancel()
        context['cancel_block_message'] = self.object.get_cancel_block_message()
        context['can_pay_booking'] = self.object.can_pay()
        context['back_url'] = reverse('bookings:booking_list')

        # Thống kê & Kiểm tra đánh giá
        from apps.reviews.models import Review
        # Booking hoàn thành khi đã thanh toán (PAID) và ngày thuê bằng hoặc trước hôm nay
        context['is_completed'] = (booking.status == Booking.PAID and booking.booking_date <= timezone.localdate())
        context['existing_review'] = Review.objects.filter(booking=booking).first()
        return context


class CreateBookingReviewView(LoginRequiredMixin, View):
    """Xử lý submit đánh giá cho booking hoàn thành."""

    def post(self, request, *args, **kwargs):
        from apps.reviews.models import Review
        booking = get_object_or_404(Booking, pk=kwargs['booking_pk'])
        
        # Quyền kiểm tra: Chỉ người đặt booking mới được đánh giá
        if booking.booking_package.user != request.user:
            raise PermissionDenied("Bạn không có quyền đánh giá booking này.")
            
        # Kiểm tra trạng thái hoàn thành
        is_completed = (booking.status == Booking.PAID and booking.booking_date <= timezone.localdate())
        if not is_completed:
            messages.error(request, "Chỉ có thể đánh giá sau khi hoàn thành lượt thuê sân.")
            return redirect('bookings:booking_detail', pk=booking.pk)
            
        # Kiểm tra xem đã đánh giá chưa
        if Review.objects.filter(booking=booking).exists():
            messages.error(request, "Bạn đã đánh giá booking này rồi.")
            return redirect('bookings:booking_detail', pk=booking.pk)

        try:
            rating = int(request.POST.get('rating') or 5)
            comment = (request.POST.get('comment') or '').strip()
            
            if not (1 <= rating <= 5):
                raise ValueError("Điểm đánh giá phải từ 1 đến 5.")
                
            Review.objects.create(
                user=request.user,
                venue=booking.venue,
                booking=booking,
                rating=rating,
                comment=comment,
            )
            messages.success(request, "Cảm ơn bạn đã gửi đánh giá!")
        except Exception as e:
            messages.error(request, f"Lỗi gửi đánh giá: {str(e)}")
            
        return redirect('bookings:booking_detail', pk=booking.pk)



class BookingCreateView(LoginRequiredMixin, FormView):
    template_name = 'bookings/booking_form.html'
    form_class = BookingCreateForm

    def get_initial(self):
        initial = super().get_initial()
        selected_field = _get_field_from_value(
            self.kwargs.get('field_id') or self.request.GET.get('field_id') or self.request.GET.get('field'),
        ) or _get_default_field()
        selected_date = _parse_booking_date(
            self.request.GET.get('booking_date'),
        ) or timezone.localdate()

        if selected_field:
            initial['field'] = selected_field.pk
        initial['booking_date'] = selected_date
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        user = self.request.user
        queryset = get_bookable_fields_queryset()
        
        # Import lazy để tránh circular imports
        from apps.accounts.models import Role
        from apps.bookings.permissions import user_has_role
        
        if user_has_role(user, Role.STAFF):
            if hasattr(user, 'staff_profile') and user.staff_profile.owner:
                queryset = queryset.filter(venue__owner=user.staff_profile.owner)
            else:
                queryset = queryset.none()
        elif user_has_role(user, Role.OWNER):
            if hasattr(user, 'owner_profile'):
                queryset = queryset.filter(venue__owner=user.owner_profile)
            else:
                queryset = queryset.none()
                
        kwargs['field_queryset'] = queryset
        return kwargs

    def _get_context_selection(self, form):
        cleaned_data = getattr(form, 'cleaned_data', {}) or {}
        selected_field = cleaned_data.get('field')
        selected_date = cleaned_data.get('booking_date')

        if not selected_field:
            raw_field = (
                form.data.get(form.add_prefix('field'))
                if form.is_bound
                else form.initial.get('field')
            )
            selected_field = _get_field_from_value(raw_field)

        if not selected_field and not form.is_bound:
            selected_field = _get_default_field()

        if not selected_date:
            raw_date = (
                form.data.get(form.add_prefix('booking_date'))
                if form.is_bound
                else form.initial.get('booking_date')
            )
            selected_date = _parse_booking_date(raw_date)

        selected_date = selected_date or timezone.localdate()
        return selected_field, selected_date

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Free up slots held by expired pending bookings before drawing the picker.
        cancel_expired_pending_bookings()
        form = context['form']
        selected_field, selected_date = self._get_context_selection(form)
        time_blocks = get_time_blocks_for_field_date(selected_field, selected_date)
        unavailable_blocks = get_unavailable_time_blocks(
            selected_field,
            selected_date,
            time_blocks,
        )
        slot_options = get_booking_slot_options(
            selected_field,
            selected_date,
            time_blocks,
            unavailable_blocks,
        )
        context.update({
            'bookable_fields': form.fields['field'].queryset,
            'time_blocks': time_blocks,
            'unavailable_blocks': unavailable_blocks,
            'slot_options': slot_options,
            'selected_field': selected_field,
            'selected_date': selected_date,
        })
        return context

    def form_valid(self, form):
        data = form.cleaned_data
        price = getattr(form, 'calculated_price', None)
        if price is None:
            price, _ = calculate_booking_price(
                data['field'],
                data['booking_date'],
                data['start_time'],
                data['end_time'],
            )
        try:
            self.booking = create_booking(
                user=self.request.user,
                field=data['field'],
                booking_date=data['booking_date'],
                start_time=data['start_time'],
                end_time=data['end_time'],
                price=price,
                note=data.get('note', ''),
                service_quantities=form.service_quantities,
            )
        except DjangoValidationError as exc:
            error_messages = _validation_error_messages(exc)
            is_conflict = any('SLOT_CONFLICT' in msg for msg in error_messages)

            if is_conflict and self.request.headers.get('Accept') == 'application/json':
                return JsonResponse({
                    "error": "SLOT_CONFLICT",
                    "message": "Khung giờ này vừa có người khác đặt hoặc giữ chỗ. Vui lòng chọn khung giờ khác."
                }, status=409)

            for message in error_messages:
                form.add_error(None, message)
            return self.form_invalid(form)

        messages.success(self.request, 'Đặt sân thành công. Vui lòng kiểm tra lịch sử đặt sân của bạn.')
        if self.request.headers.get('Accept') == 'application/json':
            return JsonResponse({'redirect_url': self.get_success_url()}, status=201)
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        if self.request.headers.get('Accept') == 'application/json':
            return JsonResponse({'error': 'FORM_INVALID', 'errors': form.errors}, status=400)
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse('bookings:booking_detail', kwargs={'pk': self.booking.pk})


class BookingFieldServicesView(LoginRequiredMixin, View):
    """AJAX: return active service items for the venue of a bookable field.

    The field is resolved through ``get_bookable_fields_queryset()`` so that
    inactive or soft-deleted venues yield no services. Filtering is done in the
    backend by ``field.venue`` — the frontend never sees other venues' services.
    """

    def get(self, request, *args, **kwargs):
        field = (
            get_bookable_fields_queryset()
            .filter(pk=kwargs['field_id'])
            .first()
        )
        if field is None:
            return JsonResponse({
                'services': [],
                'message': 'Sân không hợp lệ hoặc không thể đặt.',
            })

        services = ServiceItem.objects.filter(
            venue=field.venue,
            is_active=True,
            stock__gt=0,
        ).order_by('category', 'name')

        data = [
            {
                'id': item.pk,
                'name': item.name,
                'category': item.get_category_display() if item.category else '',
                'price': str(item.price),
                'stock': item.stock,
                'image_url': item.image.url if item.image else None,
            }
            for item in services
        ]
        return JsonResponse({'services': data})


class BookingAvailabilityView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        # Cleanup expired pending holds so freed slots are reported as available.
        cancel_expired_pending_bookings()
        selected_field = _get_field_from_value(
            request.GET.get('field_id') or request.GET.get('field'),
        )
        selected_date = _parse_booking_date(request.GET.get('booking_date'))
        time_blocks = get_time_blocks_for_field_date(selected_field, selected_date)
        unavailable_blocks = get_unavailable_time_blocks(
            selected_field,
            selected_date,
            time_blocks,
        )
        return JsonResponse({
            'time_blocks': time_blocks,
            'unavailable_blocks': unavailable_blocks,
        })


class CancelBookingView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        booking = get_object_or_404(
            Booking.objects.select_related('booking_package', 'booking_package__user'),
            pk=kwargs['pk'],
        )
        if not can_manage_booking(request.user, booking):
            raise PermissionDenied(BOOKING_MANAGE_DENIED_MESSAGE)
        if not booking.can_cancel():
            message = booking.get_cancel_block_message()
            if _is_ajax(request):
                return JsonResponse({'ok': False, 'message': message}, status=400)
            messages.error(request, message)
            return redirect('bookings:booking_detail', pk=booking.pk)
        booking.status = Booking.CANCELLED
        booking.save(update_fields=['status', 'updated_at'])
        message = 'Booking cancelled.'
        if _is_ajax(request):
            return JsonResponse({
                'ok': True,
                'message': message,
                'html': _render_booking_detail_partial(request, booking),
            })
        messages.success(request, message)
        return redirect('bookings:booking_detail', pk=booking.pk)


# ---------------------------------------------------------------------------
# Role-based management dashboards (non-/admin)
# ---------------------------------------------------------------------------

def _to_int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _filters_querystring(params):
    """Encode current filter params (excluding pagination) for page links."""
    query = params.copy()
    query.pop('page', None)
    return query.urlencode()


def _management_base_queryset():
    """Booking queryset prefetched for list/detail rendering (no N+1)."""
    return Booking.objects.select_related(
        'venue',
        'field',
        'booking_package',
        'booking_package__user',
    ).prefetch_related(
        'slots',
        Prefetch(
            'services_ordered',
            queryset=BookingService.objects.select_related('service_item'),
        ),
    )


def _owner_visible_venues(owner_profile):
    return Venue.objects.filter(
        owner=owner_profile,
        is_deleted=False,
    )


def _owner_visible_fields(owner_profile, venue_id):
    return Field.objects.filter(
        venue_id=venue_id,
        venue__owner=owner_profile,
        venue__is_deleted=False,
        status__iexact=FIELD_ACTIVE_STATUS,
    )


def _apply_booking_filters(queryset, params):
    """Apply date/venue/field/status/customer filters from query params.

    The filters only ever narrow an already-authorized queryset, so they cannot
    be used to widen access (e.g. an owner cannot reach another owner's data by
    passing a foreign venue id — the base queryset already excludes it).
    """
    applied = {}

    booking_date = _parse_booking_date(params.get('date'))
    if booking_date:
        queryset = queryset.filter(booking_date=booking_date)
        applied['date'] = booking_date

    venue_id = _to_int_or_none(params.get('venue'))
    if venue_id is not None:
        queryset = queryset.filter(venue_id=venue_id)
        applied['venue'] = venue_id

    field_id = _to_int_or_none(params.get('field'))
    if field_id is not None:
        queryset = queryset.filter(field_id=field_id)
        applied['field'] = field_id

    status = (params.get('status') or '').strip()
    valid_statuses = {choice for choice, _ in Booking.STATUS_CHOICES}
    if status in valid_statuses:
        queryset = queryset.filter(status=status)
        applied['status'] = status

    customer = (params.get('customer') or '').strip()
    if customer:
        queryset = queryset.filter(
            Q(booking_package__user__email__icontains=customer)
            | Q(booking_package__user__username__icontains=customer)
            | Q(booking_package__user__first_name__icontains=customer)
            | Q(booking_package__user__last_name__icontains=customer)
            | Q(booking_package__user__phone__icontains=customer)
        )
        applied['customer'] = customer

    return queryset, applied


def _apply_owner_booking_filters(queryset, params, owner_profile):
    applied = {}

    booking_date = _parse_booking_date(params.get('date'))
    if booking_date:
        queryset = queryset.filter(booking_date=booking_date)
        applied['date'] = booking_date

    venue_id = _to_int_or_none(params.get('venue'))
    if venue_id is not None:
        if not _owner_visible_venues(owner_profile).filter(pk=venue_id).exists():
            raise PermissionDenied('Cơ sở không thuộc quyền quản lý của owner hiện tại.')
        queryset = queryset.filter(venue_id=venue_id)
        applied['venue'] = venue_id

    field_id = _to_int_or_none(params.get('field'))
    if field_id is not None:
        if venue_id is None:
            raise PermissionDenied('Vui lòng chọn cơ sở trước khi lọc theo sân.')
        if not _owner_visible_fields(owner_profile, venue_id).filter(pk=field_id).exists():
            raise PermissionDenied('Sân không thuộc cơ sở đã chọn hoặc không thuộc owner hiện tại.')
        queryset = queryset.filter(field_id=field_id)
        applied['field'] = field_id

    status = (params.get('status') or '').strip()
    valid_statuses = set(OwnerBookingListView.OWNER_STATUSES)
    if status in valid_statuses:
        queryset = queryset.filter(status=status)
        applied['status'] = status

    return queryset, applied


class StaffBookingListView(StaffRequiredMixin, ListView):
    """System-wide booking dashboard for STAFF (read-only)."""

    template_name = 'bookings/staff_booking_list.html'
    context_object_name = 'bookings'
    paginate_by = 50

    def get_queryset(self):
        queryset, self.applied_filters = _apply_booking_filters(
            _management_base_queryset(),
            self.request.GET,
        )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['applied_filters'] = getattr(self, 'applied_filters', {})
        context['querystring'] = _filters_querystring(self.request.GET)
        context['venues'] = Venue.objects.order_by('name')
        context['fields'] = Field.objects.select_related('venue').order_by('venue__name', 'name')
        context['status_choices'] = Booking.STATUS_CHOICES
        return context


class OwnerBookingListView(OwnerBookingRequiredMixin, ListView):
    """Owner dashboard: only bookings for venues owned by the logged-in owner.

    Limited to PENDING / CANCELLED / PAID statuses per requirements.
    """

    template_name = 'bookings/owner_booking_list.html'
    context_object_name = 'bookings'
    paginate_by = 50

    OWNER_STATUSES = (Booking.PENDING, Booking.CANCELLED, Booking.PAID)

    def dispatch(self, request, *args, **kwargs):
        # OwnerBookingRequiredMixin already enforced OWNER-only access; resolve the profile here.
        self.owner_profile = get_owner_profile(request.user) if request.user.is_authenticated else None
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        if not self.owner_profile:
            self.applied_filters = {}
            return Booking.objects.none()
        queryset = _management_base_queryset().filter(
            venue__owner=self.owner_profile,
            status__in=self.OWNER_STATUSES,
        )
        queryset, self.applied_filters = _apply_owner_booking_filters(
            queryset,
            self.request.GET,
            self.owner_profile,
        )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['applied_filters'] = getattr(self, 'applied_filters', {})
        context['querystring'] = _filters_querystring(self.request.GET)
        context['owner_profile'] = self.owner_profile
        if self.owner_profile:
            # Soft-deleted venues must not appear in the filter dropdowns, even
            # though old bookings may still reference them (history is preserved).
            context['venues'] = _owner_visible_venues(self.owner_profile).only('id', 'name').order_by('name')
            selected_venue_id = context['applied_filters'].get('venue')
            if selected_venue_id:
                context['fields'] = _owner_visible_fields(
                    self.owner_profile,
                    selected_venue_id,
                ).only('id', 'name', 'venue_id').order_by('name')
            else:
                context['fields'] = []
        else:
            context['venues'] = Venue.objects.none()
            context['fields'] = []
        context['status_choices'] = [
            (value, label)
            for value, label in Booking.STATUS_CHOICES
            if value in self.OWNER_STATUSES
        ]
        return context

    def render_to_response(self, context, **response_kwargs):
        if _is_ajax(self.request):
            return JsonResponse({
                'ok': True,
                'html': render_to_string(
                    'bookings/partials/_booking_management_table.html',
                    context,
                    request=self.request,
                ),
            })
        return super().render_to_response(context, **response_kwargs)


class OwnerBookingFieldOptionsView(OwnerBookingRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        owner_profile = get_owner_profile(request.user)
        if not owner_profile:
            return HttpResponseForbidden('Tài khoản chủ sân chưa có hồ sơ OwnerProfile.')

        venue_id = _to_int_or_none(request.GET.get('venue_id'))
        if venue_id is None:
            return JsonResponse({'fields': []})

        if not _owner_visible_venues(owner_profile).filter(pk=venue_id).exists():
            return HttpResponseForbidden('Cơ sở không thuộc quyền quản lý của owner hiện tại.')

        fields = _owner_visible_fields(owner_profile, venue_id).only('id', 'name').order_by('name')
        return JsonResponse({
            'fields': [
                {'id': field.pk, 'name': field.name}
                for field in fields
            ],
        })


class OwnerBookingDetailView(OwnerBookingRequiredMixin, DetailView):
    model = Booking
    template_name = 'bookings/booking_detail.html'
    context_object_name = 'booking'

    def dispatch(self, request, *args, **kwargs):
        self.owner_profile = get_owner_profile(request.user) if request.user.is_authenticated else None
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        if not self.owner_profile:
            return Booking.objects.none()
        return _management_base_queryset().filter(venue__owner=self.owner_profile)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_edit_booking_services'] = False
        context['booking_service_lock_message'] = self.object.get_service_modification_block_message()
        context['can_cancel_booking'] = False
        context['cancel_block_message'] = self.object.get_cancel_block_message()
        context['can_pay_booking'] = False
        context['back_url'] = reverse('bookings:owner_booking_list')
        return context


# ===========================================================================
# Đăng ký & Huỷ sân (Owner Venue Registration & Removal)
# ===========================================================================
from django.db import transaction
from django.shortcuts import render
from apps.bookings.permissions import OwnerRequiredMixin
from apps.venues.forms import (
    VenueRegistrationRequestForm,
    VenueFieldFormSet,
    PriceRuleModeForm,
    ManualFieldPriceRuleFormSet,
)
from apps.venues.models import OwnerVenueRequest
from apps.venues.pricing import (
    PRICING_MODE_DEFAULT,
    PRICING_MODE_MANUAL,
    get_default_price_rule_payloads,
)
from apps.venues.services import notify_admins_about_owner_venue_request


def _to_int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_venue_field_formset(data=None):
    return VenueFieldFormSet(
        data=data,
        prefix='fields',
        queryset=Field.objects.none(),
    )


def _build_price_rule_mode_form(data=None):
    return PriceRuleModeForm(data=data, prefix='pricing')


def _build_manual_price_rule_formset(data=None):
    return ManualFieldPriceRuleFormSet(data=data, prefix='price_rules')


def _validate_pricing_submission(pricing_form, manual_price_rule_formset):
    if not pricing_form.is_valid():
        return False, []
    pricing_mode = pricing_form.cleaned_data['pricing_mode']
    if pricing_mode == PRICING_MODE_DEFAULT:
        return True, get_default_price_rule_payloads()
    if pricing_mode == PRICING_MODE_MANUAL:
        if not manual_price_rule_formset.is_valid():
            return False, []
        return True, manual_price_rule_formset.to_payload()
    pricing_form.add_error('pricing_mode', 'Cách nhập bảng giá không hợp lệ.')
    return False, []


class OwnerVenueRegisterView(OwnerRequiredMixin, View):
    """Owner-only page to request registering a new venue."""

    template_name = 'bookings/owner_venue_register.html'

    def _get_owner_profile_or_403(self, request):
        owner_profile = get_owner_profile(request.user)
        if not owner_profile:
            raise PermissionDenied('Tài khoản chủ sân chưa có hồ sơ OwnerProfile.')
        return owner_profile

    def get(self, request, *args, **kwargs):
        owner_profile = self._get_owner_profile_or_403(request)
        return render(request, self.template_name, {
            'form': VenueRegistrationRequestForm(),
            'field_formset': _build_venue_field_formset(),
            'pricing_form': _build_price_rule_mode_form(),
            'price_rule_formset': _build_manual_price_rule_formset(),
            'default_price_rules': get_default_price_rule_payloads(),
            'owner_profile': owner_profile,
        })

    def post(self, request, *args, **kwargs):
        owner_profile = self._get_owner_profile_or_403(request)
        form = VenueRegistrationRequestForm(request.POST)
        field_formset = _build_venue_field_formset(request.POST)
        pricing_form = _build_price_rule_mode_form(request.POST)
        price_rule_formset = _build_manual_price_rule_formset(request.POST)
        pricing_is_valid, price_rule_payloads = _validate_pricing_submission(
            pricing_form,
            price_rule_formset,
        )
        if not form.is_valid() or not field_formset.is_valid() or not pricing_is_valid:
            return render(request, self.template_name, {
                'form': form,
                'field_formset': field_formset,
                'pricing_form': pricing_form,
                'price_rule_formset': price_rule_formset,
                'default_price_rules': get_default_price_rule_payloads(),
                'owner_profile': owner_profile,
            })

        payload = form.to_payload()
        payload['fields'] = field_formset.to_payload()
        payload['pricing'] = {
            'mode': pricing_form.cleaned_data['pricing_mode'],
            'rules': price_rule_payloads,
        }
        with transaction.atomic():
            venue_request = OwnerVenueRequest(
                requested_by=request.user,
                request_type=OwnerVenueRequest.CREATE,
                payload=payload,
            )
            venue_request.full_clean()
            venue_request.save()
            notify_admins_about_owner_venue_request(venue_request)
        messages.success(request, 'Yêu cầu tạo sân đã được gửi và đang chờ admin duyệt.')
        return redirect('bookings:owner_venue_register')


class OwnerVenueRemovalRequestView(OwnerRequiredMixin, View):
    """Owner-only placeholder page to request removing an owned venue.

    Removal is treated as a request only — no venue is deleted from here.
    """

    template_name = 'bookings/owner_venue_removal.html'

    def _owned_venues(self, request):
        owner_profile = get_owner_profile(request.user)
        if not owner_profile:
            raise PermissionDenied('Tài khoản chủ sân chưa có hồ sơ OwnerProfile.')
        return owner_profile, Venue.objects.filter(
            owner=owner_profile,
            is_deleted=False,
        ).order_by('name')

    def get(self, request, *args, **kwargs):
        owner_profile, venues = self._owned_venues(request)
        return render(request, self.template_name, {
            'owner_profile': owner_profile,
            'venues': venues,
        })

    def post(self, request, *args, **kwargs):
        owner_profile, venues = self._owned_venues(request)
        venue_id = _to_int_or_none(request.POST.get('venue'))
        # Only allow requesting removal of a venue the owner actually owns.
        venue = venues.filter(pk=venue_id).first() if venue_id is not None else None
        if venue is None:
            messages.error(request, 'Vui lòng chọn một sân hợp lệ thuộc sở hữu của bạn.')
        else:
            venue_request = OwnerVenueRequest(
                requested_by=request.user,
                request_type=OwnerVenueRequest.DELETE,
                target_venue=venue,
                reason=(request.POST.get('reason') or '').strip(),
            )
            venue_request.full_clean()
            venue_request.save()
            notify_admins_about_owner_venue_request(venue_request)
            messages.success(request, 'Yêu cầu huỷ sân đã được gửi và đang chờ admin duyệt.')
        return redirect('bookings:owner_venue_removal')


class FieldDetailJSONView(LoginRequiredMixin, View):
    """AJAX: Trả về thông tin chi tiết của sân con cùng các reviews của cơ sở đó."""

    def get(self, request, *args, **kwargs):
        from django.db.models import Avg
        from apps.reviews.models import Review
        
        field = get_object_or_404(
            Field.objects.select_related('venue', 'field_type', 'field_type__sport'),
            pk=kwargs['field_id']
        )
        venue = field.venue
        
        # Lấy trung bình đánh giá và danh sách reviews
        reviews_qs = Review.objects.filter(venue=venue).select_related('user').order_by('-created_at')
        avg_rating = reviews_qs.aggregate(avg=Avg('rating'))['avg'] or 0
        
        reviews_list = []
        for r in reviews_qs[:10]:
            reviews_list.append({
                'user': r.user.get_full_name() or r.user.email,
                'rating': r.rating,
                'comment': r.comment or '',
                'created_at': r.created_at.strftime('%d/%m/%Y'),
            })

        # Lấy bảng giá của sân con này
        price_rules = []
        for rule in field.price_rules.all().order_by('day_of_week', 'start_time'):
            day_label = 'Tất cả các ngày'
            if rule.day_of_week is not None:
                days = ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'Chủ nhật']
                if 0 <= rule.day_of_week < len(days):
                    day_label = days[rule.day_of_week]
            price_rules.append({
                'day_of_week': day_label,
                'start_time': rule.start_time.strftime('%H:%M'),
                'end_time': rule.end_time.strftime('%H:%M'),
                'price': float(rule.price_per_hour),
            })
            
        payload = {
            'ok': True,
            'field': {
                'id': field.pk,
                'name': field.name,
                'sport': field.field_type.sport.name,
                'capacity': field.capacity or 0,
                'surface_type': field.surface_type or 'Mặc định',
                'length': float(field.length) if field.length else 0,
                'width': float(field.width) if field.width else 0,
                'status': field.status,
            },
            'venue': {
                'name': venue.name,
                'address': venue.address,
                'latitude': float(venue.latitude) if venue.latitude else None,
                'longitude': float(venue.longitude) if venue.longitude else None,
                'avg_rating': round(float(avg_rating), 1),
                'reviews': reviews_list,
            },
            'price_rules': price_rules,
        }
        return JsonResponse(payload)

