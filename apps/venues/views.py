from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, FormView, ListView, UpdateView

from apps.accounts.models import Notification, Role
from apps.bookings.permissions import (
    AdminRequiredMixin,
    OwnerAssetRequiredMixin,
    get_owner_profile,
    is_admin,
    user_has_role,
)
from apps.core.models import AuditLog
from .forms import (
    AdminVenueForm,
    FieldCreateForm,
    FieldPriceRuleForm,
    ManualFieldPriceRuleFormSet,
    PriceRuleModeForm,
    VenueCreateForm,
    VenueFieldFormSet,
)
from .models import Field, FieldPriceRule, FieldType, OwnerVenueRequest, Venue
from .pricing import (
    PRICING_MODE_DEFAULT,
    PRICING_MODE_MANUAL,
    get_default_price_rule_payloads,
    resolve_pricing_payload_rules,
    validate_price_rule_payloads,
)
from .services import (
    VENUE_REQUEST_NOTIFICATION_ENTITIES,
    ensure_owner_account,
    notify_admins_about_owner_venue_request,
    notify_owner_venue_request_approved,
    notify_owner_venue_request_rejected,
)


def build_venue_field_formset(data=None):
    return VenueFieldFormSet(
        data=data,
        prefix='fields',
        queryset=Field.objects.none(),
    )


def build_price_rule_mode_form(data=None):
    return PriceRuleModeForm(data=data, prefix='pricing')


def build_manual_price_rule_formset(data=None):
    return ManualFieldPriceRuleFormSet(data=data, prefix='price_rules')


def is_ajax(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def ajax_response(message='', status=200, **extra):
    payload = {
        'ok': status < 400,
    }
    if message:
        payload['message'] = message
    payload.update(extra)
    return JsonResponse(payload, status=status)


def admin_venue_queryset():
    return (
        Venue._base_manager.select_related('owner', 'owner__user')
        .annotate(
            field_count=Count('fields', distinct=True),
            booking_count=Count('bookings', distinct=True),
            service_item_count=Count('service_items', distinct=True),
        )
    )


def field_supports_soft_delete():
    return hasattr(Field, 'is_deleted')


def field_supports_deleted_at():
    return hasattr(Field, 'deleted_at')


def admin_field_queryset(venue, include_deleted=False):
    queryset = Field.objects.filter(venue=venue).select_related('field_type', 'field_type__sport')
    if field_supports_soft_delete() and not include_deleted:
        queryset = queryset.filter(is_deleted=False)
    return queryset.order_by('name')


def render_admin_field_table(request, venue):
    return render_to_string(
        'venues/partials/_admin_field_table.html',
        {
            'venue': venue,
            'fields': admin_field_queryset(venue),
            'field_supports_soft_delete': field_supports_soft_delete(),
        },
        request=request,
    )


def render_admin_field_form(request, venue, form, action_url, submit_label):
    return render_to_string(
        'venues/partials/_admin_field_form.html',
        {
            'venue': venue,
            'form': form,
            'form_action': action_url,
            'submit_label': submit_label,
        },
        request=request,
    )


def render_admin_venue_detail(request, venue_pk):
    venue = get_object_or_404(admin_venue_queryset(), pk=venue_pk)
    return render_to_string(
        'venues/partials/_admin_venue_detail.html',
        {'venue': venue},
        request=request,
    )


def render_admin_registration_request_detail(request, venue_request):
    refreshed = get_object_or_404(
        OwnerVenueRequest.objects.select_related(
            'requested_by',
            'requested_by__owner_profile',
            'reviewed_by',
            'target_venue',
        ),
        pk=venue_request.pk,
    )
    return render_to_string(
        'venues/partials/_admin_registration_request_detail.html',
        {
            'venue_request': refreshed,
            'registration_request': refreshed,
        },
        request=request,
    )


def validate_pricing_submission(pricing_form, manual_price_rule_formset):
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


def create_price_rules_for_field(field, price_rule_payloads):
    normalized_rules = validate_price_rule_payloads(price_rule_payloads)
    created_rules = []
    for rule_payload in normalized_rules:
        rule = FieldPriceRule(field=field, **rule_payload)
        rule.full_clean()
        rule.save()
        created_rules.append(rule)
    if not created_rules:
        raise ValidationError('Vui lòng nhập ít nhất 1 dòng giá hợp lệ.')
    return created_rules


class VenueFieldFormSetCreateMixin:
    def get_field_formset(self):
        data = self.request.POST if self.request.method == 'POST' else None
        return build_venue_field_formset(data=data)

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        field_formset = self.get_field_formset()
        if form.is_valid() and field_formset.is_valid():
            return self.forms_valid(form, field_formset)
        return self.forms_invalid(form, field_formset)

    def forms_invalid(self, form, field_formset):
        return self.render_to_response(
            self.get_context_data(form=form, field_formset=field_formset),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault('field_formset', self.get_field_formset())
        return context


class AdminRegistrationRequestListView(AdminRequiredMixin, ListView):
    model = OwnerVenueRequest
    template_name = 'venues/admin_registration_request_list.html'
    context_object_name = 'venue_requests'
    paginate_by = 50

    def get_queryset(self):
        queryset = OwnerVenueRequest.objects.select_related(
            'requested_by',
            'requested_by__owner_profile',
            'reviewed_by',
            'target_venue',
        )
        status = (self.request.GET.get('status') or '').strip()
        valid_statuses = {value for value, _ in OwnerVenueRequest.STATUS_CHOICES}
        if status in valid_statuses:
            queryset = queryset.filter(status=status)
            self.active_status = status
        else:
            self.active_status = ''

        request_type = (self.request.GET.get('request_type') or '').strip()
        valid_request_types = {value for value, _ in OwnerVenueRequest.REQUEST_TYPE_CHOICES}
        if request_type in valid_request_types:
            queryset = queryset.filter(request_type=request_type)
            self.active_request_type = request_type
        else:
            self.active_request_type = ''

        pending_first = Case(
            When(status=OwnerVenueRequest.PENDING, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
        return queryset.order_by(pending_first, '-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['registration_requests'] = context['venue_requests']
        context['status_choices'] = OwnerVenueRequest.STATUS_CHOICES
        context['request_type_choices'] = OwnerVenueRequest.REQUEST_TYPE_CHOICES
        context['active_status'] = getattr(self, 'active_status', '')
        context['active_request_type'] = getattr(self, 'active_request_type', '')
        return context

    def render_to_response(self, context, **response_kwargs):
        if is_ajax(self.request):
            return ajax_response(
                html=render_to_string(
                    'venues/partials/_admin_registration_request_list.html',
                    context,
                    request=self.request,
                ),
            )
        return super().render_to_response(context, **response_kwargs)


class AdminRegistrationRequestDetailView(AdminRequiredMixin, DetailView):
    model = OwnerVenueRequest
    template_name = 'venues/admin_registration_request_detail.html'
    context_object_name = 'venue_request'

    def get_queryset(self):
        return OwnerVenueRequest.objects.select_related(
            'requested_by',
            'requested_by__owner_profile',
            'reviewed_by',
            'target_venue',
        )

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        Notification.objects.filter(
            user=request.user,
            entity_type__in=VENUE_REQUEST_NOTIFICATION_ENTITIES,
            entity_id=str(self.object.pk),
            is_read=False,
        ).update(is_read=True)
        context = self.get_context_data(object=self.object)
        context['registration_request'] = self.object
        return self.render_to_response(context)

    def render_to_response(self, context, **response_kwargs):
        if is_ajax(self.request):
            return ajax_response(
                html=render_to_string(
                    'venues/partials/_admin_registration_request_detail.html',
                    context,
                    request=self.request,
                ),
            )
        return super().render_to_response(context, **response_kwargs)


class AdminVenueListView(AdminRequiredMixin, ListView):
    template_name = 'venues/admin_venue_list.html'
    context_object_name = 'venues'
    paginate_by = 50

    def get_queryset(self):
        queryset = admin_venue_queryset()

        status = (self.request.GET.get('status') or '').strip()
        valid_statuses = {value for value, _ in Venue.ADMIN_STATUS_CHOICES}
        if status in valid_statuses:
            queryset = queryset.filter(status=status)
            self.active_status = status
        else:
            self.active_status = ''

        deleted = (self.request.GET.get('deleted') or '').strip()
        if deleted == '1':
            queryset = queryset.filter(is_deleted=True)
            self.active_deleted = '1'
        elif deleted == '0':
            queryset = queryset.filter(is_deleted=False)
            self.active_deleted = '0'
        else:
            self.active_deleted = ''

        return queryset.order_by('is_deleted', 'status', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status_choices'] = Venue.ADMIN_STATUS_CHOICES
        context['active_status'] = getattr(self, 'active_status', '')
        context['active_deleted'] = getattr(self, 'active_deleted', '')
        return context

    def render_to_response(self, context, **response_kwargs):
        if is_ajax(self.request):
            return ajax_response(
                html=render_to_string(
                    'venues/partials/_admin_venue_list.html',
                    context,
                    request=self.request,
                ),
            )
        return super().render_to_response(context, **response_kwargs)


class AdminVenueDetailView(AdminRequiredMixin, DetailView):
    model = Venue
    template_name = 'venues/admin_venue_detail.html'
    context_object_name = 'venue'

    def get_queryset(self):
        return admin_venue_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.bookings.models import Booking
        venue = self.object
        # Lịch sử đặt sân của cơ sở
        context['venue_bookings'] = (
            Booking.objects.filter(venue=venue)
            .select_related(
                'field', 'booking_package__user',
            )
            .prefetch_related('services_ordered__service_item')
            .order_by('-booking_date', '-created_at')[:100]
        )
        # Danh sách sân con để lọc
        context['venue_fields'] = venue.fields.select_related('field_type').all()
        return context

    def render_to_response(self, context, **response_kwargs):
        if is_ajax(self.request):
            return ajax_response(
                html=render_to_string(
                    'venues/partials/_admin_venue_detail.html',
                    context,
                    request=self.request,
                ),
            )
        return super().render_to_response(context, **response_kwargs)


class AdminVenueCreateView(AdminRequiredMixin, VenueFieldFormSetCreateMixin, FormView):
    template_name = 'venues/admin_venue_form.html'
    form_class = AdminVenueForm

    def forms_valid(self, form, field_formset):
        with transaction.atomic():
            venue = form.save()
            fields = field_formset.save_for_venue(venue)
        messages.success(self.request, f'Đã tạo cơ sở "{venue.name}" cùng {len(fields)} sân con.')
        return redirect('venues:admin_venue_detail', pk=venue.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_title'] = 'Tạo cơ sở sân'
        context['submit_label'] = 'Tạo cơ sở'
        context['show_field_formset'] = True
        return context


class AdminVenueUpdateView(AdminRequiredMixin, FormView):
    template_name = 'venues/admin_venue_form.html'
    form_class = AdminVenueForm
    venue = None

    def get_venue(self):
        if self.venue is None:
            self.venue = get_object_or_404(
                Venue._base_manager.select_related('owner', 'owner__user'),
                pk=self.kwargs['pk'],
            )
        return self.venue

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['instance'] = self.get_venue()
        return kwargs

    def form_valid(self, form):
        venue = form.save()
        messages.success(self.request, f'Đã cập nhật cơ sở "{venue.name}".')
        return redirect('venues:admin_venue_detail', pk=venue.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['venue'] = self.get_venue()
        context['form_title'] = 'Chỉnh sửa cơ sở sân'
        context['submit_label'] = 'Lưu thay đổi'
        return context


class AdminVenueDeactivateView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        venue = get_object_or_404(Venue._base_manager, pk=kwargs['pk'])
        if venue.is_deleted:
            message = 'Cơ sở đã bị xóa mềm, không thể tắt hoạt động.'
            if is_ajax(request):
                return ajax_response(message, status=400)
            messages.error(request, message)
            return redirect('venues:admin_venue_detail', pk=venue.pk)
        if venue.status == Venue.INACTIVE:
            message = 'Cơ sở đã ở trạng thái tạm ngưng.'
            if is_ajax(request):
                return ajax_response(message, status=400)
            messages.error(request, message)
            return redirect('venues:admin_venue_detail', pk=venue.pk)

        venue.status = Venue.INACTIVE
        venue.save(update_fields=['status', 'updated_at'])
        message = f'Đã tắt hoạt động cơ sở "{venue.name}".'
        if is_ajax(request):
            return ajax_response(message)
        messages.success(request, message)
        return redirect('venues:admin_venue_detail', pk=venue.pk)


class AdminVenueSoftDeleteView(AdminRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        venue = get_object_or_404(
            Venue._base_manager.select_related('owner', 'owner__user')
            .annotate(
                field_count=Count('fields', distinct=True),
                booking_count=Count('bookings', distinct=True),
                service_item_count=Count('service_items', distinct=True),
            ),
            pk=kwargs['pk'],
        )
        return render(request, 'venues/admin_venue_confirm_delete.html', {'venue': venue})

    def post(self, request, *args, **kwargs):
        venue = get_object_or_404(Venue._base_manager, pk=kwargs['pk'])
        if venue.is_deleted:
            message = 'Cơ sở này đã bị xóa mềm.'
            if is_ajax(request):
                return ajax_response(message, status=400)
            messages.error(request, message)
            return redirect('venues:admin_venue_detail', pk=venue.pk)

        venue.status = Venue.INACTIVE
        venue.is_deleted = True
        venue.deleted_at = timezone.now()
        venue.save(update_fields=['status', 'is_deleted', 'deleted_at', 'updated_at'])
        message = f'Đã xóa mềm cơ sở "{venue.name}".'
        if is_ajax(request):
            return ajax_response(message)
        messages.success(request, message)
        return redirect('venues:admin_venue_detail', pk=venue.pk)


class AdminVenueRestoreView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        venue = get_object_or_404(Venue._base_manager, pk=kwargs['pk'])
        if not venue.is_deleted and venue.status == Venue.ACTIVE:
            message = 'Cơ sở đang hoạt động, không cần khôi phục.'
            if is_ajax(request):
                return ajax_response(message, status=400)
            messages.error(request, message)
            return redirect('venues:admin_venue_detail', pk=venue.pk)

        venue.status = Venue.ACTIVE
        venue.is_deleted = False
        venue.deleted_at = None
        venue.save(update_fields=['status', 'is_deleted', 'deleted_at', 'updated_at'])
        message = f'Đã bật lại cơ sở "{venue.name}".'
        if is_ajax(request):
            return ajax_response(message)
        messages.success(request, message)
        return redirect('venues:admin_venue_detail', pk=venue.pk)


class AdminRegistrationRequestApproveView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            venue_request = get_object_or_404(
                OwnerVenueRequest.objects.select_for_update().select_related(
                    'requested_by',
                    'requested_by__owner_profile',
                    'target_venue',
                ),
                pk=kwargs['pk'],
            )
            if venue_request.status != OwnerVenueRequest.PENDING:
                message = 'Yêu cầu này đã được xử lý, không thể duyệt lại.'
                if is_ajax(request):
                    return ajax_response(
                        message,
                        status=400,
                        html=render_admin_registration_request_detail(request, venue_request),
                    )
                messages.error(request, message)
                return redirect(self._detail_url(venue_request))

            venue = self._approve_request(venue_request)
            venue_request.status = OwnerVenueRequest.APPROVED
            venue_request.reviewed_by = request.user
            venue_request.reviewed_at = timezone.now()
            venue_request.save(update_fields=[
                'status',
                'reviewed_by',
                'reviewed_at',
                'target_venue',
                'updated_at',
            ])
            notify_owner_venue_request_approved(venue_request, venue)
            AuditLog.objects.create(
                user=request.user,
                action='APPROVE',
                target_type='OwnerVenueRequest',
                target_id=str(venue_request.pk),
                old_value=OwnerVenueRequest.PENDING,
                new_value=f'{OwnerVenueRequest.APPROVED}: {venue_request.request_type}: Venue#{venue.pk}',
            )

        message = f'Đã duyệt yêu cầu {venue_request.get_request_type_display().lower()} "{venue.name}".'
        if is_ajax(request):
            return ajax_response(
                message,
                html=render_admin_registration_request_detail(request, venue_request),
            )
        messages.success(request, message)
        return redirect(self._detail_url(venue_request))

    def _approve_request(self, venue_request):
        if venue_request.request_type == OwnerVenueRequest.DELETE:
            venue = venue_request.target_venue
            if venue is None:
                raise PermissionDenied('Yêu cầu hủy sân không có target venue hợp lệ.')
            venue.status = Venue.INACTIVE
            venue.is_deleted = True
            venue.deleted_at = timezone.now()
            venue.save(update_fields=['status', 'is_deleted', 'deleted_at', 'updated_at'])
            return venue

        if venue_request.request_type != OwnerVenueRequest.CREATE:
            raise PermissionDenied('Loại yêu cầu này chưa được hỗ trợ.')

        owner_profile = ensure_owner_account(
            venue_request.requested_by,
            registration_request=venue_request,
        )
        payload = venue_request.payload or {}
        price_rule_payloads = validate_price_rule_payloads(
            resolve_pricing_payload_rules(payload.get('pricing')),
        )
        venue_kwargs = {
            'owner': owner_profile,
            'name': (payload.get('name') or '').strip(),
            'address': (payload.get('address') or '').strip(),
            'description': (payload.get('description') or '').strip(),
            'status': Venue.ACTIVE,
        }
        for field_name in ('latitude', 'longitude'):
            value = payload.get(field_name)
            if value not in (None, ''):
                venue_kwargs[field_name] = value
        venue = Venue.objects.create(**venue_kwargs)
        field_payloads = payload.get('fields') or []
        if not field_payloads:
            raise PermissionDenied('Yêu cầu tạo cơ sở cần có ít nhất 1 sân con.')
        for field_payload in field_payloads:
            field_type = FieldType.objects.get(pk=field_payload['field_type'])
            field = Field(
                venue=venue,
                field_type=field_type,
                name=(field_payload.get('name') or '').strip(),
                capacity=field_payload.get('capacity'),
                surface_type=(field_payload.get('surface_type') or '').strip(),
                length=field_payload.get('length'),
                width=field_payload.get('width'),
                status=field_payload.get('status') or 'ACTIVE',
            )
            field.full_clean()
            field.save()
            create_price_rules_for_field(field, price_rule_payloads)
        venue_request.target_venue = venue
        return venue

    def _detail_url(self, venue_request):
        return reverse('venues:admin_venue_request_detail', kwargs={'pk': venue_request.pk})


class OwnerProfileContextMixin(OwnerAssetRequiredMixin):
    owner_profile = None

    def set_owner_profile(self, request):
        self.owner_profile = get_owner_profile(request.user) if request.user.is_authenticated else None

    def dispatch(self, request, *args, **kwargs):
        self.set_owner_profile(request)
        if request.user.is_authenticated:
            if is_admin(request.user) or not user_has_role(request.user, Role.OWNER):
                raise PermissionDenied('Chỉ tài khoản OWNER được truy cập trang quản lý sân.')
        return super().dispatch(request, *args, **kwargs)

    def require_owner_profile(self):
        if not self.owner_profile:
            raise PermissionDenied('Tài khoản này chưa có hồ sơ chủ sân để quản lý cơ sở.')
        return self.owner_profile


class OwnerVenueListView(OwnerProfileContextMixin, ListView):
    template_name = 'venues/owner_venue_list.html'
    context_object_name = 'venues'

    def get_queryset(self):
        if not self.owner_profile:
            return Venue.objects.none()
        return Venue.objects.filter(
            owner=self.owner_profile,
            is_deleted=False,
        ).order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['owner_profile'] = self.owner_profile
        return context


class OwnerVenueCreateView(OwnerProfileContextMixin, VenueFieldFormSetCreateMixin, FormView):
    template_name = 'venues/owner_venue_form.html'
    form_class = VenueCreateForm

    def get_pricing_form(self):
        data = self.request.POST if self.request.method == 'POST' else None
        return build_price_rule_mode_form(data=data)

    def get_manual_price_rule_formset(self):
        data = self.request.POST if self.request.method == 'POST' else None
        return build_manual_price_rule_formset(data=data)

    def get(self, request, *args, **kwargs):
        self.require_owner_profile()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.require_owner_profile()
        form = self.get_form()
        field_formset = self.get_field_formset()
        pricing_form = self.get_pricing_form()
        price_rule_formset = self.get_manual_price_rule_formset()
        pricing_is_valid, price_rule_payloads = validate_pricing_submission(
            pricing_form,
            price_rule_formset,
        )
        if form.is_valid() and field_formset.is_valid() and pricing_is_valid:
            return self.forms_valid(
                form,
                field_formset,
                pricing_form,
                price_rule_formset,
                price_rule_payloads,
            )
        return self.forms_invalid(form, field_formset, pricing_form, price_rule_formset)

    def forms_valid(self, form, field_formset, pricing_form, price_rule_formset, price_rule_payloads):
        payload = form.to_payload()
        payload['fields'] = field_formset.to_payload()
        payload['pricing'] = {
            'mode': pricing_form.cleaned_data['pricing_mode'],
            'rules': price_rule_payloads,
        }
        with transaction.atomic():
            venue_request = OwnerVenueRequest(
                requested_by=self.request.user,
                request_type=OwnerVenueRequest.CREATE,
                payload=payload,
            )
            venue_request.full_clean()
            venue_request.save()
            notify_admins_about_owner_venue_request(venue_request)
        messages.success(self.request, 'Yêu cầu tạo sân đã được gửi và đang chờ admin duyệt.')
        return redirect('venues:owner_venue_list')

    def forms_invalid(self, form, field_formset, pricing_form=None, price_rule_formset=None):
        return self.render_to_response(
            self.get_context_data(
                form=form,
                field_formset=field_formset,
                pricing_form=pricing_form,
                price_rule_formset=price_rule_formset,
            ),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['show_field_formset'] = True
        context.setdefault('pricing_form', self.get_pricing_form())
        context.setdefault('price_rule_formset', self.get_manual_price_rule_formset())
        context['default_price_rules'] = get_default_price_rule_payloads()
        return context


class OwnerFieldListView(OwnerProfileContextMixin, ListView):
    template_name = 'venues/owner_field_list.html'
    context_object_name = 'fields'

    def dispatch(self, request, *args, **kwargs):
        self.set_owner_profile(request)
        self.require_owner_profile()
        self.venue = get_object_or_404(
            Venue.objects.filter(owner=self.owner_profile, is_deleted=False),
            pk=kwargs.get('venue_pk') or kwargs.get('pk'),
        )
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return Field.objects.filter(venue=self.venue).select_related('field_type', 'field_type__sport').order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['venue'] = self.venue
        return context


class OwnerFieldCreateView(OwnerProfileContextMixin, FormView):
    template_name = 'venues/owner_field_form.html'
    form_class = FieldCreateForm

    def dispatch(self, request, *args, **kwargs):
        self.set_owner_profile(request)
        self.require_owner_profile()
        self.venue = get_object_or_404(
            Venue.objects.filter(owner=self.owner_profile, is_deleted=False),
            pk=kwargs['venue_pk'],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_pricing_form(self):
        data = self.request.POST if self.request.method == 'POST' else None
        return build_price_rule_mode_form(data=data)

    def get_manual_price_rule_formset(self):
        data = self.request.POST if self.request.method == 'POST' else None
        return build_manual_price_rule_formset(data=data)

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        pricing_form = self.get_pricing_form()
        price_rule_formset = self.get_manual_price_rule_formset()
        pricing_is_valid, price_rule_payloads = validate_pricing_submission(
            pricing_form,
            price_rule_formset,
        )
        if form.is_valid() and pricing_is_valid:
            return self.forms_valid(form, pricing_form, price_rule_formset, price_rule_payloads)
        return self.render_to_response(
            self.get_context_data(
                form=form,
                pricing_form=pricing_form,
                price_rule_formset=price_rule_formset,
            ),
        )

    def forms_valid(self, form, pricing_form, price_rule_formset, price_rule_payloads):
        with transaction.atomic():
            field = form.save(commit=False)
            field.venue = self.venue
            field.status = field.status or 'ACTIVE'
            field.full_clean()
            field.save()
            create_price_rules_for_field(field, price_rule_payloads)
        messages.success(self.request, f'Đã tạo sân "{field.name}" cùng bảng giá thuê sân.')
        return redirect('venues:owner_field_list', venue_pk=self.venue.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['venue'] = self.venue
        context['page_title'] = 'Tạo sân mới'
        context['eyebrow'] = 'Chủ sân'
        context['submit_label'] = 'Tạo sân'
        context['back_url'] = reverse('venues:owner_field_list', kwargs={'venue_pk': self.venue.pk})
        context.setdefault('pricing_form', self.get_pricing_form())
        context.setdefault('price_rule_formset', self.get_manual_price_rule_formset())
        context['default_price_rules'] = get_default_price_rule_payloads()
        return context


class AdminFieldCreateView(AdminRequiredMixin, FormView):
    template_name = 'venues/admin_field_form.html'
    form_class = FieldCreateForm

    def dispatch(self, request, *args, **kwargs):
        self.venue = get_object_or_404(
            Venue._base_manager.select_related('owner', 'owner__user'),
            pk=kwargs.get('venue_id') or kwargs.get('venue_pk'),
        )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        with transaction.atomic():
            field = form.save(commit=False)
            field.venue = self.venue
            field.status = field.status or 'ACTIVE'
            field.full_clean()
            field.save()
        message = f'Đã tạo sân "{field.name}" cho cơ sở "{self.venue.name}".'
        if is_ajax(self.request):
            return ajax_response(message, html=render_admin_field_table(self.request, self.venue))
        messages.success(self.request, message)
        return redirect('venues:admin_venue_field_list', venue_id=self.venue.pk)

    def form_invalid(self, form):
        if is_ajax(self.request):
            return ajax_response(
                'Vui lòng kiểm tra lại dữ liệu sân.',
                status=400,
                html=render_admin_field_form(
                    self.request,
                    self.venue,
                    form,
                    reverse('venues:admin_venue_field_create', kwargs={'venue_id': self.venue.pk}),
                    'Tạo sân',
                ),
            )
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['venue'] = self.venue
        context['page_title'] = 'Tạo sân mới'
        context['eyebrow'] = 'Quản trị cơ sở sân'
        context['submit_label'] = 'Tạo sân'
        context['form_action'] = reverse('venues:admin_venue_field_create', kwargs={'venue_id': self.venue.pk})
        context['back_url'] = reverse('venues:admin_venue_field_list', kwargs={'venue_id': self.venue.pk})
        return context

    def render_to_response(self, context, **response_kwargs):
        if is_ajax(self.request):
            return ajax_response(
                html=render_admin_field_form(
                    self.request,
                    self.venue,
                    context['form'],
                    context['form_action'],
                    context['submit_label'],
                ),
            )
        return super().render_to_response(context, **response_kwargs)


class AdminVenueFieldListView(AdminRequiredMixin, ListView):
    template_name = 'venues/admin_field_list.html'
    context_object_name = 'fields'

    def dispatch(self, request, *args, **kwargs):
        self.venue = get_object_or_404(
            Venue._base_manager.select_related('owner', 'owner__user'),
            pk=kwargs['venue_id'],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return admin_field_queryset(self.venue)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['venue'] = self.venue
        context['field_supports_soft_delete'] = field_supports_soft_delete()
        return context

    def render_to_response(self, context, **response_kwargs):
        if is_ajax(self.request):
            return ajax_response(
                html=render_to_string(
                    'venues/partials/_admin_field_table.html',
                    context,
                    request=self.request,
                ),
            )
        return super().render_to_response(context, **response_kwargs)


class AdminVenueFieldUpdateView(AdminRequiredMixin, FormView):
    template_name = 'venues/admin_field_form.html'
    form_class = FieldCreateForm

    def dispatch(self, request, *args, **kwargs):
        self.venue = get_object_or_404(
            Venue._base_manager.select_related('owner', 'owner__user'),
            pk=kwargs['venue_id'],
        )
        self.field = get_object_or_404(
            admin_field_queryset(self.venue, include_deleted=False),
            pk=kwargs['pk'],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['instance'] = self.field
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            field = form.save(commit=False)
            field.venue = self.venue
            field.full_clean()
            field.save()
        message = f'Đã cập nhật sân "{field.name}".'
        if is_ajax(self.request):
            return ajax_response(message, html=render_admin_field_table(self.request, self.venue))
        messages.success(self.request, message)
        return redirect('venues:admin_venue_field_list', venue_id=self.venue.pk)

    def form_invalid(self, form):
        if is_ajax(self.request):
            return ajax_response(
                'Vui lòng kiểm tra lại dữ liệu sân.',
                status=400,
                html=render_admin_field_form(
                    self.request,
                    self.venue,
                    form,
                    reverse('venues:admin_venue_field_update', kwargs={
                        'venue_id': self.venue.pk,
                        'pk': self.field.pk,
                    }),
                    'Lưu thay đổi',
                ),
            )
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['venue'] = self.venue
        context['field'] = self.field
        context['page_title'] = 'Chỉnh sửa sân'
        context['eyebrow'] = 'Quản trị cơ sở sân'
        context['submit_label'] = 'Lưu thay đổi'
        context['form_action'] = reverse('venues:admin_venue_field_update', kwargs={
            'venue_id': self.venue.pk,
            'pk': self.field.pk,
        })
        context['back_url'] = reverse('venues:admin_venue_field_list', kwargs={'venue_id': self.venue.pk})
        return context

    def render_to_response(self, context, **response_kwargs):
        if is_ajax(self.request):
            return ajax_response(
                html=render_admin_field_form(
                    self.request,
                    self.venue,
                    context['form'],
                    context['form_action'],
                    context['submit_label'],
                ),
            )
        return super().render_to_response(context, **response_kwargs)


class AdminVenueFieldActionMixin(AdminRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        self.venue = get_object_or_404(
            Venue._base_manager.select_related('owner', 'owner__user'),
            pk=kwargs['venue_id'],
        )
        self.field = get_object_or_404(
            admin_field_queryset(self.venue, include_deleted=False),
            pk=kwargs['pk'],
        )
        return super().dispatch(request, *args, **kwargs)

    def redirect_to_list(self):
        return redirect('venues:admin_venue_field_list', venue_id=self.venue.pk)

    def action_response(self, message):
        if is_ajax(self.request):
            return ajax_response(message, html=render_admin_field_table(self.request, self.venue))
        messages.success(self.request, message)
        return self.redirect_to_list()


class AdminVenueFieldToggleView(AdminVenueFieldActionMixin, View):
    def post(self, request, *args, **kwargs):
        self.field.status = 'INACTIVE' if self.field.status == 'ACTIVE' else 'ACTIVE'
        self.field.save(update_fields=['status'])
        state_label = 'bật hoạt động' if self.field.status == 'ACTIVE' else 'tắt hoạt động'
        return self.action_response(f'Đã {state_label} sân "{self.field.name}".')


class AdminVenueFieldDeleteView(AdminVenueFieldActionMixin, View):
    def post(self, request, *args, **kwargs):
        if field_supports_soft_delete():
            update_fields = ['is_deleted']
            self.field.is_deleted = True
            if field_supports_deleted_at():
                self.field.deleted_at = timezone.now()
                update_fields.append('deleted_at')
            self.field.save(update_fields=update_fields)
            return self.action_response(f'Đã xóa mềm sân "{self.field.name}".')

        self.field.status = 'INACTIVE'
        self.field.save(update_fields=['status'])
        return self.action_response(
            f'Model Field chưa hỗ trợ soft delete, đã chuyển sân "{self.field.name}" sang INACTIVE.',
        )


class OwnerPriceRuleListView(OwnerProfileContextMixin, ListView):
    template_name = 'venues/owner_price_rule_list.html'
    context_object_name = 'price_rules'

    def dispatch(self, request, *args, **kwargs):
        self.set_owner_profile(request)
        self.require_owner_profile()
        self.field = get_object_or_404(
            Field.objects.filter(venue__owner=self.owner_profile, venue__is_deleted=False).select_related('venue'),
            pk=kwargs['field_pk'],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return FieldPriceRule.objects.filter(field=self.field).order_by('day_of_week', 'start_time', '-priority')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['field'] = self.field
        context['venue'] = self.field.venue
        return context


class OwnerPriceRuleCreateView(OwnerProfileContextMixin, FormView):
    template_name = 'venues/owner_price_rule_form.html'
    form_class = FieldPriceRuleForm

    def dispatch(self, request, *args, **kwargs):
        self.set_owner_profile(request)
        self.require_owner_profile()
        self.field = get_object_or_404(
            Field.objects.filter(venue__owner=self.owner_profile, venue__is_deleted=False).select_related('venue'),
            pk=kwargs['field_pk'],
        )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        with transaction.atomic():
            price_rule = form.save(commit=False)
            price_rule.field = self.field
            price_rule.save()
        messages.success(self.request, 'Đã tạo bảng giá cho sân.')
        return redirect('venues:owner_price_rule_list', field_pk=self.field.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['field'] = self.field
        context['venue'] = self.field.venue
        return context


class OwnerPriceRuleUpdateView(OwnerProfileContextMixin, UpdateView):
    model = FieldPriceRule
    form_class = FieldPriceRuleForm
    template_name = 'venues/owner_price_rule_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.set_owner_profile(request)
        self.require_owner_profile()
        self.price_rule = get_object_or_404(
            FieldPriceRule.objects.filter(field__venue__owner=self.owner_profile, field__venue__is_deleted=False).select_related('field', 'field__venue'),
            pk=kwargs['pk'],
        )
        self.field = self.price_rule.field
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        return self.price_rule

    def form_valid(self, form):
        form.save()
        messages.success(self.request, 'Đã cập nhật bảng giá.')
        return redirect('venues:owner_price_rule_list', field_pk=self.field.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['field'] = self.field
        context['venue'] = self.field.venue
        context['is_edit'] = True
        return context


class OwnerPriceRuleDeleteView(OwnerProfileContextMixin, View):
    def post(self, request, *args, **kwargs):
        self.set_owner_profile(request)
        self.require_owner_profile()
        price_rule = get_object_or_404(
            FieldPriceRule.objects.filter(field__venue__owner=self.owner_profile, field__venue__is_deleted=False).select_related('field'),
            pk=kwargs['pk'],
        )
        field_pk = price_rule.field.pk
        price_rule.delete()
        messages.success(request, 'Đã xóa bảng giá.')
        return redirect('venues:owner_price_rule_list', field_pk=field_pk)


class AdminRegistrationRequestRejectView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        admin_note = (request.POST.get('admin_note') or request.POST.get('rejection_reason') or '').strip()
        if not admin_note:
            venue_request = get_object_or_404(OwnerVenueRequest, pk=kwargs['pk'])
            message = 'Vui lòng nhập lý do từ chối.'
            if is_ajax(request):
                return ajax_response(
                    message,
                    status=400,
                    html=render_admin_registration_request_detail(request, venue_request),
                )
            messages.error(request, message)
            return redirect(self._detail_url(venue_request))

        with transaction.atomic():
            venue_request = get_object_or_404(
                OwnerVenueRequest.objects.select_for_update().select_related(
                    'requested_by',
                    'requested_by__owner_profile',
                    'target_venue',
                ),
                pk=kwargs['pk'],
            )
            if venue_request.status != OwnerVenueRequest.PENDING:
                message = 'Yêu cầu này đã được xử lý, không thể từ chối lại.'
                if is_ajax(request):
                    return ajax_response(
                        message,
                        status=400,
                        html=render_admin_registration_request_detail(request, venue_request),
                    )
                messages.error(request, message)
                return redirect(self._detail_url(venue_request))

            venue_request.status = OwnerVenueRequest.REJECTED
            venue_request.admin_note = admin_note
            venue_request.reviewed_by = request.user
            venue_request.reviewed_at = timezone.now()
            venue_request.save(update_fields=[
                'status',
                'admin_note',
                'reviewed_by',
                'reviewed_at',
                'updated_at',
            ])
            notify_owner_venue_request_rejected(venue_request)
            AuditLog.objects.create(
                user=request.user,
                action='REJECT',
                target_type='OwnerVenueRequest',
                target_id=str(venue_request.pk),
                old_value=OwnerVenueRequest.PENDING,
                new_value=f'{OwnerVenueRequest.REJECTED}: {admin_note}',
            )

        message = f'Đã từ chối yêu cầu {venue_request.get_request_type_display().lower()} "{venue_request.venue_name}".'
        if is_ajax(request):
            return ajax_response(
                message,
                html=render_admin_registration_request_detail(request, venue_request),
            )
        messages.success(request, message)
        return redirect(self._detail_url(venue_request))

    def _detail_url(self, venue_request):
        return reverse('venues:admin_venue_request_detail', kwargs={'pk': venue_request.pk})
