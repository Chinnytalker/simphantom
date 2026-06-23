from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class StaticSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.6

    def items(self):
        return [
            'home', 'services', 'login', 'register',
            'privacy', 'terms', 'cookies', 'contact',
            'blog:post-list',
        ]

    def location(self, item):
        return reverse(item)


class ServiceSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.9

    def items(self):
        return [
            'virtual-numbers',
            'otp-verification',
            'temporary-email',
            'vpn-subscription',
            'esim-packages',
            'residential-proxies',
            'bulk-sms',
            'phone-number-lookup',
        ]

    def location(self, item):
        return reverse('service-detail', kwargs={'service_slug': item})


class LandingSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.8

    def items(self):
        return ['landing-whatsapp-number', 'landing-vpn-nigeria']

    def location(self, item):
        return reverse(item)


class BlogSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        from blog.models import Post
        from django.utils import timezone
        return Post.objects.filter(is_published=True, published_at__lte=timezone.now())

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return obj.get_absolute_url()
