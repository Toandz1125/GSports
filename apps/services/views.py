from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View
from django.views.generic import FormView, ListView

from apps.bookings.permissions import (
    BOOKING_MANAGE_DENIED_MESSAGE,
    OwnerAssetRequiredMixin,
    can_manage_booking,
    get_owner_profile,
)
from apps.bookings.models import Booking
from .forms import BookingServiceForm, ServiceItemForm
from .models import BookingService, ServiceItem
from .services import add_service_to_booking, remove_service_from_booking, update_booking_service


def _is_ajax(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _redirect_if_booking_services_locked(request, booking):
    message = booking.get_service_modification_block_message()
    if not message:
        return None
    messages.error(request, message)
    return redirect('bookings:booking_detail', pk=booking.pk)


class ServiceItemListView(LoginRequiredMixin, ListView):
    template_name = 'services/serviceitem_list.html'
    context_object_name = 'service_items'

    def get_owner_profile(self):
        if not hasattr(self, '_owner_profile'):
            self._owner_profile = get_owner_profile(self.request.user)
        return self._owner_profile

    def get_template_names(self):
        if self.get_owner_profile():
            return ['services/owner_serviceitem_list.html']
        return [self.template_name]

    def get_queryset(self):
        owner_profile = self.get_owner_profile()
        if owner_profile:
            return (
                ServiceItem.objects.filter(
                    venue__owner=owner_profile,
                    venue__is_deleted=False,
                )
                .select_related('venue')
                .order_by('venue__name', 'category', 'name')
            )

        queryset = ServiceItem.objects.filter(is_active=True).select_related('venue')
        venue_id = self.request.GET.get('venue')
        if venue_id:
            queryset = queryset.filter(venue_id=venue_id)
        return queryset.order_by('venue__name', 'category', 'name')


class OwnerServiceItemMixin(OwnerAssetRequiredMixin):
    owner_profile = None

    def dispatch(self, request, *args, **kwargs):
        self.owner_profile = get_owner_profile(request.user) if request.user.is_authenticated else None
        if request.user.is_authenticated and not self.owner_profile:
            raise PermissionDenied('Tài khoản này chưa có hồ sơ chủ sân để quản lý dịch vụ.')
        return super().dispatch(request, *args, **kwargs)

    def get_owner_service_items_queryset(self):
        return ServiceItem.objects.filter(
            venue__owner=self.owner_profile,
            venue__is_deleted=False,
        ).select_related('venue').order_by('venue__name', 'category', 'name')

    def render_owner_service_item_list(self):
        return render_to_string(
            'services/partials/_owner_serviceitem_list.html',
            {'service_items': self.get_owner_service_items_queryset()},
            request=self.request,
        )

    def ajax_success(self, message, **extra):
        payload = {
            'ok': True,
            'message': message,
        }
        payload.update(extra)
        return JsonResponse(payload)

    def ajax_form_invalid(self, form):
        return JsonResponse({
            'ok': False,
            'message': 'Vui lòng kiểm tra lại dữ liệu dịch vụ.',
            'errors': form.errors,
        }, status=400)


class OwnerServiceItemListView(OwnerServiceItemMixin, ListView):
    template_name = 'services/owner_serviceitem_list.html'
    context_object_name = 'service_items'

    def get_queryset(self):
        return self.get_owner_service_items_queryset()

    def render_to_response(self, context, **response_kwargs):
        if _is_ajax(self.request):
            return JsonResponse({
                'ok': True,
                'html': render_to_string(
                    'services/partials/_owner_serviceitem_list.html',
                    context,
                    request=self.request,
                ),
            })
        return super().render_to_response(context, **response_kwargs)


class OwnerServiceItemCreateView(OwnerServiceItemMixin, FormView):
    template_name = 'services/owner_serviceitem_form.html'
    form_class = ServiceItemForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['owner_profile'] = self.owner_profile
        return kwargs

    def form_valid(self, form):
        service_item = form.save()
        message = f'Đã tạo dịch vụ "{service_item.name}".'
        if _is_ajax(self.request):
            return self.ajax_success(
                message,
                html=self.render_owner_service_item_list(),
                redirect_url=reverse('services:owner_serviceitem_list'),
            )
        messages.success(self.request, message)
        return redirect('services:owner_serviceitem_list')

    def form_invalid(self, form):
        if _is_ajax(self.request):
            return self.ajax_form_invalid(form)
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Tạo dịch vụ'
        context['submit_label'] = 'Tạo dịch vụ'
        return context


class OwnerServiceItemUpdateView(OwnerServiceItemMixin, FormView):
    template_name = 'services/owner_serviceitem_form.html'
    form_class = ServiceItemForm

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        return response

    def get_service_item(self):
        if not hasattr(self, 'service_item'):
            self.service_item = get_object_or_404(
                self.get_owner_service_items_queryset(),
                pk=self.kwargs['item_id'],
            )
        return self.service_item

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['owner_profile'] = self.owner_profile
        kwargs['instance'] = self.get_service_item()
        return kwargs

    def form_valid(self, form):
        service_item = form.save()
        message = f'Đã cập nhật dịch vụ "{service_item.name}".'
        if _is_ajax(self.request):
            return self.ajax_success(
                message,
                html=self.render_owner_service_item_list(),
                redirect_url=reverse('services:owner_serviceitem_list'),
            )
        messages.success(self.request, message)
        return redirect('services:owner_serviceitem_list')

    def form_invalid(self, form):
        if _is_ajax(self.request):
            return self.ajax_form_invalid(form)
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['service_item'] = self.get_service_item()
        context['page_title'] = 'Cập nhật dịch vụ'
        context['submit_label'] = 'Lưu thay đổi'
        return context


class OwnerServiceItemDeleteView(OwnerServiceItemMixin, View):
    template_name = 'services/owner_serviceitem_confirm_delete.html'

    def get_service_item(self):
        return get_object_or_404(
            self.get_owner_service_items_queryset(),
            pk=self.kwargs['item_id'],
        )

    def get(self, request, *args, **kwargs):
        from django.shortcuts import render
        return render(request, self.template_name, {
            'service_item': self.get_service_item(),
        })

    def post(self, request, *args, **kwargs):
        service_item = self.get_service_item()
        service_item.is_active = False
        service_item.save(update_fields=['is_active', 'updated_at'])
        message = f'Đã tắt dịch vụ "{service_item.name}".'
        if _is_ajax(request):
            return self.ajax_success(
                message,
                html=self.render_owner_service_item_list(),
                redirect_url=reverse('services:owner_serviceitem_list'),
            )
        messages.success(request, message)
        return redirect('services:owner_serviceitem_list')


class OwnerServiceItemToggleActiveView(OwnerServiceItemMixin, View):
    def get_service_item(self):
        return get_object_or_404(
            self.get_owner_service_items_queryset(),
            pk=self.kwargs['item_id'],
        )

    def post(self, request, *args, **kwargs):
        service_item = self.get_service_item()
        requested_value = (request.POST.get('is_active') or '').strip()
        if requested_value in {'1', 'true', 'True', 'ACTIVE'}:
            service_item.is_active = True
        elif requested_value in {'0', 'false', 'False', 'INACTIVE'}:
            service_item.is_active = False
        else:
            service_item.is_active = not service_item.is_active

        service_item.save(update_fields=['is_active', 'updated_at'])
        state_label = 'bật bán' if service_item.is_active else 'ngừng bán'
        message = f'Đã {state_label} dịch vụ "{service_item.name}".'
        if _is_ajax(request):
            return self.ajax_success(
                message,
                html=self.render_owner_service_item_list(),
            )
        messages.success(request, message)
        return redirect('services:owner_serviceitem_list')


class AddBookingServiceView(LoginRequiredMixin, FormView):
    template_name = 'services/bookingservice_form.html'
    form_class = BookingServiceForm
    page_title = 'Thêm dịch vụ'
    submit_label = 'Thêm dịch vụ'

    def dispatch(self, request, *args, **kwargs):
        self.booking = get_object_or_404(
            Booking.objects.select_related('venue', 'booking_package', 'booking_package__user'),
            pk=kwargs['booking_pk'],
        )
        if not can_manage_booking(request.user, self.booking):
            raise PermissionDenied(BOOKING_MANAGE_DENIED_MESSAGE)
        locked_response = _redirect_if_booking_services_locked(request, self.booking)
        if locked_response:
            return locked_response
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['booking'] = self.booking
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['booking'] = self.booking
        context['page_title'] = self.page_title
        context['submit_label'] = self.submit_label
        return context

    def form_valid(self, form):
        try:
            add_service_to_booking(
                booking=self.booking,
                service_item=form.cleaned_data['service_item'],
                quantity=form.cleaned_data['quantity'],
            )
        except DjangoValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, 'Service added to booking.')
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse('bookings:booking_detail', kwargs={'pk': self.booking.pk})


class EditBookingServiceView(LoginRequiredMixin, FormView):
    template_name = 'services/bookingservice_form.html'
    form_class = BookingServiceForm
    page_title = 'Chỉnh sửa dịch vụ'
    submit_label = 'Lưu thay đổi'

    def dispatch(self, request, *args, **kwargs):
        self.booking_service = get_object_or_404(
            BookingService.objects.select_related(
                'booking',
                'booking__venue',
                'booking__field',
                'booking__booking_package',
                'booking__booking_package__user',
                'service_item',
            ),
            pk=kwargs['pk'],
        )
        self.booking = self.booking_service.booking
        if not can_manage_booking(request.user, self.booking):
            raise PermissionDenied(BOOKING_MANAGE_DENIED_MESSAGE)
        locked_response = _redirect_if_booking_services_locked(request, self.booking)
        if locked_response:
            return locked_response
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['booking'] = self.booking
        kwargs['instance'] = self.booking_service
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['booking'] = self.booking
        context['booking_service'] = self.booking_service
        context['page_title'] = self.page_title
        context['submit_label'] = self.submit_label
        return context

    def form_valid(self, form):
        try:
            update_booking_service(
                booking_service=self.booking_service,
                service_item=form.cleaned_data['service_item'],
                quantity=form.cleaned_data['quantity'],
            )
        except DjangoValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, 'Service updated.')
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse('bookings:booking_detail', kwargs={'pk': self.booking.pk})


class RemoveBookingServiceView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        booking_service = get_object_or_404(
            BookingService.objects.select_related(
                'booking',
                'booking__booking_package',
                'booking__booking_package__user',
            ),
            pk=kwargs['pk'],
        )
        booking_pk = booking_service.booking_id
        if not can_manage_booking(request.user, booking_service.booking):
            raise PermissionDenied(BOOKING_MANAGE_DENIED_MESSAGE)
        locked_response = _redirect_if_booking_services_locked(request, booking_service.booking)
        if locked_response:
            return locked_response
        remove_service_from_booking(booking_service)
        messages.success(request, 'Service removed.')
        return redirect('bookings:booking_detail', pk=booking_pk)
