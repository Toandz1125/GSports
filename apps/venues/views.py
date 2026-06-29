from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy, reverse
from django.views import View
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.contrib import messages

from apps.services.models import ServiceItem
from .models import Venue, Field
from .forms import VenueForm, FieldForm
from .pricing import (
    apply_field_prices,
    get_field_pricing_blocks,
    get_pricing_window,
    parse_price,
)

FIELD_FOREIGN_DENIED_MESSAGE = 'Bạn chỉ có thể quản lý sân con thuộc cơ sở của mình.'
VALID_FIELD_TABS = ('info', 'pricing', 'services')

class OwnerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Yêu cầu người dùng đăng nhập và phải có vai trò OWNER (Chủ sân)."""
    login_url = reverse_lazy('accounts:login')

    def test_func(self):
        return self.request.user.is_authenticated and hasattr(self.request.user, 'owner_profile')

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            messages.error(self.request, "Bạn không có quyền truy cập trang này. Chỉ dành cho Chủ sân.")
            return redirect('accounts:dashboard')
        return super().handle_no_permission()

class VenueListView(OwnerRequiredMixin, ListView):
    """Danh sách các cơ sở thể thao của chủ sân hiện tại."""
    model = Venue
    template_name = 'venues/venue_list.html'
    context_object_name = 'venues'

    def get_queryset(self):
        # Chỉ hiển thị các cơ sở của chủ sân hiện tại và chưa bị xóa
        return Venue.objects.filter(
            owner=self.request.user.owner_profile,
            is_deleted=False
        ).order_by('-updated_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Danh sách cơ sở thể thao'
        return context

class VenueDetailView(OwnerRequiredMixin, DetailView):
    """Chi tiết một cơ sở và danh sách các sân con thuộc cơ sở đó."""
    model = Venue
    template_name = 'venues/venue_detail.html'
    context_object_name = 'venue'

    def get_queryset(self):
        # Đảm bảo chủ sân chỉ xem được cơ sở của mình
        return Venue.objects.filter(
            owner=self.request.user.owner_profile,
            is_deleted=False
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        venue = self.get_object()
        context['fields'] = venue.fields.all()
        context['page_title'] = f'Chi tiết: {venue.name}'
        return context

class VenueCreateView(OwnerRequiredMixin, CreateView):
    """Tạo cơ sở thể thao mới."""
    model = Venue
    form_class = VenueForm
    template_name = 'venues/venue_form.html'

    def get_success_url(self):
        return reverse('venues:venue_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        # Gán chủ sân hiện tại cho cơ sở mới tạo
        form.instance.owner = self.request.user.owner_profile
        messages.success(self.request, "Tạo cơ sở thể thao mới thành công!")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Tạo cơ sở thể thao mới'
        context['is_create'] = True
        return context

class VenueUpdateView(OwnerRequiredMixin, UpdateView):
    """Cập nhật thông tin cơ sở thể thao."""
    model = Venue
    form_class = VenueForm
    template_name = 'venues/venue_form.html'

    def get_queryset(self):
        return Venue.objects.filter(
            owner=self.request.user.owner_profile,
            is_deleted=False
        )

    def get_success_url(self):
        return reverse('venues:venue_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Cập nhật thông tin cơ sở thành công!")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f'Chỉnh sửa: {self.object.name}'
        context['is_create'] = False
        return context

class FieldCreateView(OwnerRequiredMixin, CreateView):
    """Thêm sân con mới vào một cơ sở thể thao."""
    model = Field
    form_class = FieldForm
    template_name = 'venues/field_form.html'

    def dispatch(self, request, *args, **kwargs):
        # Đảm bảo cơ sở thuộc về chủ sân hiện tại
        self.venue = get_object_or_404(
            Venue,
            pk=self.kwargs.get('venue_id'),
            owner=request.user.owner_profile,
            is_deleted=False
        )
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse('venues:venue_detail', kwargs={'pk': self.venue.pk})

    def form_valid(self, form):
        form.instance.venue = self.venue
        messages.success(self.request, f"Đã thêm sân con '{form.instance.name}' thành công!")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f'Thêm sân con mới — {self.venue.name}'
        context['venue'] = self.venue
        context['is_create'] = True
        return context

def _is_ajax(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


class OwnerFieldMixin(OwnerRequiredMixin):
    """Resolve a field and ensure it belongs to the current owner.

    Missing field -> 404. Foreign field (other owner / deleted venue) -> 403,
    matching the project convention of an explicit PermissionDenied for assets
    the user is not allowed to manage.
    """

    def get_field(self):
        if not hasattr(self, '_field'):
            field = get_object_or_404(
                Field.objects.select_related('venue'),
                pk=self.kwargs['pk'],
            )
            owner_profile = self.request.user.owner_profile
            if field.venue.owner_id != owner_profile.pk or field.venue.is_deleted:
                raise PermissionDenied(FIELD_FOREIGN_DENIED_MESSAGE)
            self._field = field
        return self._field

    def field_tab_url(self, field, tab):
        url = reverse('venues:field_edit', kwargs={'pk': field.pk})
        return f'{url}?tab={tab}'

    def get_venue_service_items(self, field):
        return field.venue.service_items.all().order_by('category', 'name')

    def render_pricing_panel_html(self, field):
        return render_to_string(
            'venues/partials/_field_pricing_panel.html',
            {'field': field, 'pricing_blocks': get_field_pricing_blocks(field)},
            request=self.request,
        )

    def render_services_panel_html(self, field):
        return render_to_string(
            'venues/partials/_field_services_panel.html',
            {'field': field, 'service_items': self.get_venue_service_items(field)},
            request=self.request,
        )


class FieldManageView(OwnerFieldMixin, View):
    """Màn quản lý sân con 3 panel: thông tin / bảng giá / services."""
    template_name = 'venues/field_manage.html'

    def get_active_tab(self):
        tab = (self.request.GET.get('tab') or '').strip().lower()
        return tab if tab in VALID_FIELD_TABS else 'info'

    def build_context(self, field, active_tab, form=None):
        window_start, window_end = get_pricing_window(field)
        return {
            'field': field,
            'venue': field.venue,
            'active_tab': active_tab,
            'form': form if form is not None else FieldForm(instance=field),
            'pricing_blocks': get_field_pricing_blocks(field),
            'pricing_window_start': window_start,
            'pricing_window_end': window_end,
            'service_items': self.get_venue_service_items(field),
            'page_title': f'Quản lý sân con: {field.name}',
            'is_create': False,
        }

    def get(self, request, *args, **kwargs):
        field = self.get_field()
        context = self.build_context(field, self.get_active_tab())
        from django.shortcuts import render
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        """Panel 1 — cập nhật thông tin sân."""
        field = self.get_field()
        form = FieldForm(request.POST, instance=field)
        if form.is_valid():
            form.save()
            messages.success(request, f"Cập nhật sân con '{field.name}' thành công!")
            return redirect(self.field_tab_url(field, 'info'))
        from django.shortcuts import render
        context = self.build_context(field, 'info', form=form)
        return render(request, self.template_name, context, status=400)


class FieldPricingUpdateView(OwnerFieldMixin, View):
    """Panel 2 — tạo/cập nhật bảng giá cho các khung giờ được chọn."""

    def post(self, request, *args, **kwargs):
        field = self.get_field()
        block_values = request.POST.getlist('blocks')
        try:
            price = parse_price(request.POST.get('price_per_hour'))
            if not block_values:
                raise ValueError('Vui lòng chọn ít nhất một khung giờ.')
            updated = apply_field_prices(field, block_values, price)
        except ValueError as exc:
            message = str(exc)
            if _is_ajax(request):
                return JsonResponse({'ok': False, 'message': message}, status=400)
            messages.error(request, message)
            return redirect(self.field_tab_url(field, 'pricing'))

        message = f'Đã cập nhật giá cho {updated} khung giờ.'
        if _is_ajax(request):
            return JsonResponse({
                'ok': True,
                'message': message,
                'html': self.render_pricing_panel_html(field),
            })
        messages.success(request, message)
        return redirect(self.field_tab_url(field, 'pricing'))


class OwnerServiceItemActionMixin(OwnerFieldMixin):
    """Resolve a ServiceItem that belongs to the managed field's venue."""

    def get_service_item(self, field):
        return get_object_or_404(
            ServiceItem,
            pk=self.kwargs['item_id'],
            venue=field.venue,
        )


class FieldServicePriceUpdateView(OwnerServiceItemActionMixin, View):
    """Panel 3 — chỉnh giá một dịch vụ của cơ sở chứa sân."""

    def post(self, request, *args, **kwargs):
        field = self.get_field()
        item = self.get_service_item(field)
        try:
            item.price = parse_price(request.POST.get('price'))
        except ValueError as exc:
            message = str(exc)
            if _is_ajax(request):
                return JsonResponse({'ok': False, 'message': message}, status=400)
            messages.error(request, message)
            return redirect(self.field_tab_url(field, 'services'))

        item.save(update_fields=['price', 'updated_at'])
        message = f'Đã cập nhật giá dịch vụ "{item.name}".'
        if _is_ajax(request):
            return JsonResponse({
                'ok': True,
                'message': message,
                'html': self.render_services_panel_html(field),
            })
        messages.success(request, message)
        return redirect(self.field_tab_url(field, 'services'))


class FieldServiceToggleView(OwnerServiceItemActionMixin, View):
    """Panel 3 — bật/tạm ngưng bán một dịch vụ."""

    def post(self, request, *args, **kwargs):
        field = self.get_field()
        item = self.get_service_item(field)
        requested = (request.POST.get('is_active') or '').strip()
        if requested in {'1', 'true', 'True', 'ACTIVE'}:
            item.is_active = True
        elif requested in {'0', 'false', 'False', 'INACTIVE'}:
            item.is_active = False
        else:
            item.is_active = not item.is_active

        item.save(update_fields=['is_active', 'updated_at'])
        state_label = 'bật bán' if item.is_active else 'tạm ngưng'
        message = f'Đã {state_label} dịch vụ "{item.name}".'
        if _is_ajax(request):
            return JsonResponse({
                'ok': True,
                'message': message,
                'is_active': item.is_active,
                'html': self.render_services_panel_html(field),
            })
        messages.success(request, message)
        return redirect(self.field_tab_url(field, 'services'))

class FieldDeleteView(OwnerRequiredMixin, DeleteView):
    """Xóa sân con."""
    model = Field
    template_name = 'venues/field_confirm_delete.html'

    def get_queryset(self):
        # Đảm bảo sân con thuộc cơ sở của chủ sân hiện tại
        return Field.objects.filter(
            venue__owner=self.request.user.owner_profile,
            venue__is_deleted=False
        )

    def get_success_url(self):
        venue_id = self.object.venue.pk
        messages.success(self.request, f"Đã xóa sân con '{self.object.name}' thành công!")
        return reverse('venues:venue_detail', kwargs={'pk': venue_id})
