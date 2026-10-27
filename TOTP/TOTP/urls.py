from django.contrib import admin
from django.templatetags.static import static
from django.urls import path, include
from django.utils.functional import lazy
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    # Browsers request /favicon.ico on pages that don't declare an icon (e.g. admin login).
    path('favicon.ico', RedirectView.as_view(url=lazy(static, str)('verify/favicon-32.png'), permanent=True)),
    path('', include('verify.urls'))
]
