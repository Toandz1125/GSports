"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.accounts import views as account_views

urlpatterns = [
    path('admin/', admin.site.urls),
    # Redirect root "/" to login page
    path('', RedirectView.as_view(pattern_name='accounts:login', permanent=False)),
    path('', include('apps.accounts.urls')),
    path('dang-nhap/', account_views.LoginView.as_view(), name='login'),
    path('dang-xuat/', account_views.LogoutView.as_view(), name='logout'),
    path('co-so/', include('apps.venues.urls')),
    path('bookings/', include('apps.bookings.urls')),
    path('services/', include('apps.services.urls')),
    path('payments/', include('apps.payments.urls')),
    path('dat-san/', include(('apps.bookings.urls', 'bookings'), namespace='bookings_dat_san')),
]

# Phục vụ media files (avatar, uploads) trong chế độ DEBUG
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
