from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.contrib import messages
from django.http import JsonResponse
from django.views import View
from apps.accounts.models import FavoriteVenue
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

class VenueListView(LoginRequiredMixin, ListView):
    """Danh sách các cơ sở thể thao."""
    model = Venue
    template_name = 'venues/venue_list.html'
    context_object_name = 'venues'

    def get_queryset(self):
        user = self.request.user
        # Nếu là chủ sân, chỉ hiển thị cơ sở của chủ sân đó
        if hasattr(user, 'owner_profile') and user.owner_profile:
            return Venue.objects.filter(
                owner=user.owner_profile,
                is_deleted=False
            ).order_by('-updated_at')
        # Nếu là khách hàng / admin / staff, hiển thị toàn bộ cơ sở đang hoạt động
        return Venue.objects.filter(
            status='ACTIVE',
            is_deleted=False
        ).order_by('-updated_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        if hasattr(user, 'owner_profile') and user.owner_profile:
            context['page_title'] = 'Danh sách cơ sở thể thao'
        else:
            context['page_title'] = 'Tìm kiếm sân thể thao'

        if user.is_authenticated:
            context['favorite_venue_ids'] = set(
                FavoriteVenue.objects.filter(user=user).values_list('venue_id', flat=True)
            )
        else:
            context['favorite_venue_ids'] = set()
        return context

class VenueDetailView(LoginRequiredMixin, DetailView):
    """Chi tiết một cơ sở và danh sách các sân con thuộc cơ sở đó."""
    model = Venue
    template_name = 'venues/venue_detail.html'
    context_object_name = 'venue'

    def get_queryset(self):
        # Owners/Staff/Admin có thể xem bất kỳ cơ sở nào không bị xóa mềm,
        # Khách hàng chỉ xem được các cơ sở đang hoạt động
        user = self.request.user
        if (hasattr(user, 'owner_profile') and user.owner_profile) or user.is_staff or user.is_superuser:
            return Venue.objects.filter(is_deleted=False)
        return Venue.objects.filter(status='ACTIVE', is_deleted=False)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        venue = self.get_object()
        context['fields'] = venue.fields.all()
        context['page_title'] = f'Chi tiết: {venue.name}'
        context['is_favorite'] = FavoriteVenue.objects.filter(
            user=self.request.user,
            venue=venue
        ).exists()
        
        # Lấy danh sách đánh giá của cơ sở
        context['reviews'] = venue.reviews.select_related('user').order_by('-created_at')
        
        # Đánh giá hiện tại của user này (nếu có) để điền sẵn vào form sửa
        context['user_review'] = venue.reviews.filter(user=self.request.user).first()
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


class FavoriteVenueListView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        favorites = FavoriteVenue.objects.filter(user=request.user).select_related('venue')
        data = [
            {
                'id': fav.venue.id,
                'name': fav.venue.name,
                'url': reverse('venues:venue_detail', kwargs={'pk': fav.venue.pk})
            }
            for fav in favorites if not fav.venue.is_deleted
        ]
        return JsonResponse({'favorites': data})


class ToggleFavoriteVenueView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        import json
        try:
            body = json.loads(request.body)
            venue_id = body.get('venue_id')
        except Exception:
            venue_id = request.POST.get('venue_id')
            
        if not venue_id:
            return JsonResponse({'error': 'Missing venue_id'}, status=400)
            
        venue = get_object_or_404(Venue, pk=venue_id, is_deleted=False)
        fav, created = FavoriteVenue.objects.get_or_create(user=request.user, venue=venue)
        
        if not created:
            fav.delete()
            is_favorite = False
            message = f'Đã xóa {venue.name} khỏi danh sách yêu thích.'
        else:
            is_favorite = True
            message = f'Đã thêm {venue.name} vào danh sách yêu thích.'
            
        return JsonResponse({
            'ok': True,
            'is_favorite': is_favorite,
            'message': message
        })
