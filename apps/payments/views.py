from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.views.generic import DetailView

from apps.bookings.models import Booking
from apps.bookings.permissions import BOOKING_ACCESS_DENIED_MESSAGE, can_view_booking
from apps.services.models import BookingService


class PaymentCheckoutPlaceholderView(LoginRequiredMixin, DetailView):
    """Placeholder checkout landing page.

    Navigation-only: it shows the booking summary but does NOT process payment,
    create Payment/Invoice records, or change the booking status.
    """

    model = Booking
    pk_url_kwarg = 'booking_id'
    template_name = 'payments/checkout.html'
    context_object_name = 'booking'

    def get_queryset(self):
        return Booking.objects.select_related(
            'venue', 'field', 'booking_package', 'booking_package__user',
        ).prefetch_related(
            'slots',
            Prefetch(
                'services_ordered',
                queryset=BookingService.objects.select_related('service_item'),
            ),
        )

    def get_object(self, queryset=None):
        booking = get_object_or_404(
            queryset or self.get_queryset(),
            pk=self.kwargs[self.pk_url_kwarg],
        )
        if not can_view_booking(self.request.user, booking):
            raise PermissionDenied(BOOKING_ACCESS_DENIED_MESSAGE)
        return booking
