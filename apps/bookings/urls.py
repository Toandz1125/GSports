from django.urls import path
from . import views

app_name = 'bookings'

urlpatterns = [
    path('lich-su/', views.BookingHistoryListView.as_view(), name='booking_history'),
]
