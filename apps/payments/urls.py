from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('', views.wallet_page, name='wallet_page'),
    path('wallet/', views.wallet_page, name='wallet_page'),
    path('bookings/<uuid:booking_pk>/', views.BookingCheckoutView.as_view(), name='booking_checkout'),
    path('bookings/<uuid:booking_pk>/invoice/', views.BookingInvoiceView.as_view(), name='booking_invoice'),
    path('checkout/<uuid:booking_id>/', views.checkout_page, name='checkout'),
    path('process-payment/', views.process_payment, name='process_payment'),
    path('payment/success/', views.payment_success, name='payment_success'),
    path('deposit/', views.deposit_wallet, name='deposit'),
    path('apply-promo/', views.apply_promotion, name='apply_promo'),
]
