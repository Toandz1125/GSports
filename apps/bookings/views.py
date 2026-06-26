from django.shortcuts import render
from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from .models import Booking
from apps.accounts.models import UserRole
from apps.venues.models import Venue

class BookingHistoryListView(LoginRequiredMixin, ListView):
    """Xem và lọc lịch sử thuê sân / đặt sân của mọi vai trò (Admin, Owner, Staff, Customer)."""
    model = Booking
    template_name = 'bookings/booking_history.html'
    context_object_name = 'bookings'
    login_url = reverse_lazy('accounts:login')

    def get_queryset(self):
        user = self.request.user
        roles = UserRole.objects.filter(user=user).values_list('role__name', flat=True)
        
        qs = Booking.objects.select_related('booking_package__user', 'venue', 'field').prefetch_related('slots').order_by('-created_at')

        if 'ADMIN' in roles:
            return qs
        elif 'OWNER' in roles:
            if hasattr(user, 'owner_profile'):
                return qs.filter(venue__owner=user.owner_profile)
            return qs.none()
        elif 'STAFF' in roles:
            if hasattr(user, 'staff_profile') and user.staff_profile.venue:
                return qs.filter(venue=user.staff_profile.venue)
            elif hasattr(user, 'staff_profile') and user.staff_profile.owner:
                return qs.filter(venue__owner=user.staff_profile.owner)
            return qs.none()
        else:
            # Customer
            return qs.filter(booking_package__user=user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        roles = UserRole.objects.filter(user=user).values_list('role__name', flat=True)
        
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
            
        return context

