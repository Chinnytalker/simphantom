from django.contrib import admin
from django.urls import path, include
from django.contrib.sitemaps.views import sitemap
from django.views.generic import RedirectView, TemplateView
from django.contrib.staticfiles.storage import staticfiles_storage
from .sitemaps import StaticSitemap, ServiceSitemap

sitemaps = {
    'static': StaticSitemap,
    'services': ServiceSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('accounts.urls')),
    path('', include('support.urls')),
    path('api/services/', include('services.urls')),
    path('api/orders/', include('orders.urls')),
    path('api/payments/', include('payments.urls')),

    # SEO
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain')),

    # Browsers request /favicon.ico directly regardless of <link> tags
    path('favicon.ico', RedirectView.as_view(
        url=staticfiles_storage.url('img/favicon.ico'), permanent=True,
    )),
]

handler404 = 'accounts.views.error_404'
handler500 = 'accounts.views.error_500'
