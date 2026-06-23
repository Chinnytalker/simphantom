from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.urls import reverse


class Post(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    excerpt = models.TextField(max_length=300, blank=True, help_text='Short summary shown on listing page (max 300 chars)')
    body = models.TextField(help_text='Full post content. HTML is supported.')
    meta_description = models.CharField(max_length=160, blank=True, help_text='SEO description (max 160 chars). Defaults to excerpt if empty.')
    og_image = models.ImageField(upload_to='blog/og/', blank=True, null=True, help_text='Social share image (1200×630 recommended)')
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at', '-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        if self.is_published and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('blog:post-detail', kwargs={'slug': self.slug})

    @property
    def seo_description(self):
        return self.meta_description or self.excerpt or ''

    @property
    def reading_time(self):
        words = len(self.body.split())
        minutes = max(1, round(words / 200))
        return f'{minutes} min read'
