from django.urls import path

from .views import (
    BookingAvailabilityView,
    BookingCheckoutView,
    BookingCreateView,
    BookingDetailView,
    BookingFieldServicesView,
    BookingHistoryListView,
    BookingListView,
    CancelBookingView,
    OwnerBookingFieldOptionsView,
    OwnerBookingDetailView,
    OwnerBookingListView,
    StaffBookingListView,
)

app_name = 'bookings'

urlpatterns = [
    path('lich-su/', BookingHistoryListView.as_view(), name='booking_history'),
    path('', BookingListView.as_view(), name='booking_list'),
    path('create/', BookingCreateView.as_view(), name='booking_create'),
    path('fields/<int:field_id>/create/', BookingCreateView.as_view(), name='booking_create_for_field'),
    path('availability/', BookingAvailabilityView.as_view(), name='booking_availability'),
    path('fields/<int:field_id>/services/', BookingFieldServicesView.as_view(), name='field_services'),
    # Role-based management dashboards (non-/admin)
    path('manage/staff/', StaffBookingListView.as_view(), name='staff_booking_list'),
    path('manage/owner/', OwnerBookingListView.as_view(), name='owner_booking_list'),
    path('manage/owner/fields/', OwnerBookingFieldOptionsView.as_view(), name='owner_booking_fields'),
    path('owner/bookings/', OwnerBookingListView.as_view(), name='owner_booking_list_v2'),
    path('owner/bookings/<uuid:pk>/', OwnerBookingDetailView.as_view(), name='owner_booking_detail'),
    path('<uuid:pk>/', BookingDetailView.as_view(), name='booking_detail'),
    path('<uuid:pk>/cancel/', CancelBookingView.as_view(), name='booking_cancel'),
    path('<uuid:booking_pk>/checkout/', BookingCheckoutView.as_view(), name='booking_checkout'),
]
