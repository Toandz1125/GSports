from django.urls import path
from . import views

app_name = 'venues'

urlpatterns = [
    # --- Quản lý Cơ sở (Venues) ---
    path('', views.VenueListView.as_view(), name='venue_list'),
    path('tao/', views.VenueCreateView.as_view(), name='venue_create'),
    path('<int:pk>/', views.VenueDetailView.as_view(), name='venue_detail'),
    path('<int:pk>/sua/', views.VenueUpdateView.as_view(), name='venue_edit'),
    
    # --- Quản lý Sân con (Fields) ---
    path('<int:venue_id>/san/them/', views.FieldCreateView.as_view(), name='field_create'),
    path('san/<int:pk>/sua/', views.FieldManageView.as_view(), name='field_edit'),
    path('san/<int:pk>/xoa/', views.FieldDeleteView.as_view(), name='field_delete'),

    # --- Quản lý bảng giá & dịch vụ của sân con ---
    path('san/<int:pk>/gia/', views.FieldPricingUpdateView.as_view(), name='field_pricing_update'),
    path('san/<int:pk>/dich-vu/<int:item_id>/gia/', views.FieldServicePriceUpdateView.as_view(), name='field_service_price'),
    path('san/<int:pk>/dich-vu/<int:item_id>/trang-thai/', views.FieldServiceToggleView.as_view(), name='field_service_toggle'),
]
