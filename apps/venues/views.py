from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.contrib import messages
from .models import Venue, Field
from .forms import VenueForm, FieldForm

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

class FieldUpdateView(OwnerRequiredMixin, UpdateView):
    """Chỉnh sửa thông tin sân con."""
    model = Field
    form_class = FieldForm
    template_name = 'venues/field_form.html'

    def get_queryset(self):
        # Đảm bảo sân con thuộc cơ sở của chủ sân hiện tại
        return Field.objects.filter(
            venue__owner=self.request.user.owner_profile,
            venue__is_deleted=False
        )

    def get_success_url(self):
        return reverse('venues:venue_detail', kwargs={'pk': self.object.venue.pk})

    def form_valid(self, form):
        messages.success(self.request, f"Cập nhật sân con '{form.instance.name}' thành công!")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f'Chỉnh sửa sân con: {self.object.name}'
        context['venue'] = self.object.venue
        context['is_create'] = False
        return context

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
