from django.contrib import admin
from .models import Post


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ['title', 'is_published', 'published_at', 'reading_time', 'updated_at']
    list_editable = ['is_published']
    list_filter = ['is_published']
    search_fields = ['title', 'excerpt', 'body']
    prepopulated_fields = {'slug': ('title',)}
    date_hierarchy = 'published_at'
    fieldsets = (
        (None, {'fields': ('title', 'slug', 'is_published', 'published_at')}),
        ('Content', {'fields': ('excerpt', 'body')}),
        ('SEO', {'fields': ('meta_description', 'og_image'), 'classes': ('collapse',)}),
    )
