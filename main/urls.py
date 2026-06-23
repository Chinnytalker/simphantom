from django.contrib import admin
from django.urls import path, include
from django.contrib.sitemaps.views import sitemap
from django.views.generic import RedirectView, TemplateView
from .sitemaps import StaticSitemap, ServiceSitemap, LandingSitemap, BlogSitemap

sitemaps = {
    'static': StaticSitemap,
    'services': ServiceSitemap,
    'landing': LandingSitemap,
    'blog': BlogSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('', include('accounts.urls')),
    path('', include('support.urls')),
    path('api/services/', include('services.urls')),
    path('api/orders/', include('orders.urls')),
    path('api/payments/', include('payments.urls')),
    path('blog/', include('blog.urls', namespace='blog')),

    # SEO
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain')),

    # Browsers request /favicon.ico directly regardless of <link> tags
    path('favicon.ico', RedirectView.as_view(url='/static/img/favicon.ico', permanent=True)),
]

handler404 = 'accounts.views.error_404'
handler500 = 'accounts.views.error_500'
