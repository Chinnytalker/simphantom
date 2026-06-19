from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class StaticSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.6

    def items(self):
        return [
            'home', 'services', 'login', 'register',
            'privacy', 'terms', 'cookies', 'contact',
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
