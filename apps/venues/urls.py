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
    path('san/<int:pk>/sua/', views.FieldUpdateView.as_view(), name='field_edit'),
    path('san/<int:pk>/xoa/', views.FieldDeleteView.as_view(), name='field_delete'),

    # --- Sân yêu thích (Favorites API) ---
    path('api/favorites/', views.FavoriteVenueListView.as_view(), name='api_favorite_list'),
    path('api/favorites/toggle/', views.ToggleFavoriteVenueView.as_view(), name='api_favorite_toggle'),
]
