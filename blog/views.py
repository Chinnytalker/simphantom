from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.core.paginator import Paginator
from .models import Post


def post_list(request):
    posts = Post.objects.filter(is_published=True, published_at__lte=timezone.now())
    paginator = Paginator(posts, 9)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'blog/list.html', {'page_obj': page})


def post_detail(request, slug):
    post = get_object_or_404(Post, slug=slug, is_published=True)
    related = Post.objects.filter(is_published=True).exclude(pk=post.pk).order_by('-published_at')[:3]
    return render(request, 'blog/detail.html', {'post': post, 'related': related})
