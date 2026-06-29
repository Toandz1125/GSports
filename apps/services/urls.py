from django.urls import path

from .views import (
    AddBookingServiceView,
    EditBookingServiceView,
    OwnerServiceItemCreateView,
    OwnerServiceItemDeleteView,
    OwnerServiceItemListView,
    OwnerServiceItemToggleActiveView,
    OwnerServiceItemUpdateView,
    RemoveBookingServiceView,
    ServiceItemListView,
)

app_name = 'services'

urlpatterns = [
    path('', ServiceItemListView.as_view(), name='serviceitem_list'),
    path('owner/items/', OwnerServiceItemListView.as_view(), name='owner_serviceitem_list'),
    path('owner/items/create/', OwnerServiceItemCreateView.as_view(), name='owner_serviceitem_create'),
    path('owner/items/<int:item_id>/update/', OwnerServiceItemUpdateView.as_view(), name='owner_serviceitem_update'),
    path('owner/items/<int:item_id>/toggle/', OwnerServiceItemToggleActiveView.as_view(), name='owner_serviceitem_toggle'),
    path('owner/items/<int:item_id>/delete/', OwnerServiceItemDeleteView.as_view(), name='owner_serviceitem_delete'),
    path('bookings/<uuid:booking_pk>/add/', AddBookingServiceView.as_view(), name='bookingservice_add'),
    path('booking-services/<int:pk>/edit/', EditBookingServiceView.as_view(), name='bookingservice_edit'),
    path('booking-services/<int:pk>/remove/', RemoveBookingServiceView.as_view(), name='bookingservice_remove'),
]
