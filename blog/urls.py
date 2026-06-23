from django.urls import path
from . import views

app_name = 'blog'

urlpatterns = [
    path('', views.post_list, name='post-list'),
    path('<slug:slug>/', views.post_detail, name='post-detail'),
]
