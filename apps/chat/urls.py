from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    path('rooms/', views.room_list, name='room_list'),
    path('rooms/create/', views.room_create, name='room_create'),
    path('rooms/<int:room_id>/messages/', views.room_messages, name='room_messages'),
]
