from django.urls import path
from . import views

app_name = 'reviews'

urlpatterns = [
    path('venue/<int:venue_id>/them/', views.CreateReviewView.as_view(), name='create_review'),
]
