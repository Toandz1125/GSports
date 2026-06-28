from django.urls import path

from .views import PaymentCheckoutPlaceholderView

app_name = 'payments'

urlpatterns = [
    path(
        'bookings/<uuid:booking_id>/',
        PaymentCheckoutPlaceholderView.as_view(),
        name='checkout',
    ),
]
