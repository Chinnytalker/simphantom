from django.urls import path
from . import views

urlpatterns = [
    path('initialize/', views.InitializePaymentView.as_view(), name='initialize-payment'),
    path('webhook/paystack/', views.PaystackWebhookView.as_view(), name='paystack-webhook'),
]