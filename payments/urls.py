from django.urls import path
from . import views

urlpatterns = [
    path('initialize/', views.InitializePaymentView.as_view(), name='initialize-payment'),
    path('verify/', views.VerifyPaymentView.as_view(), name='verify-payment'),
    path('webhook/paystack/', views.PaystackWebhookView.as_view(), name='paystack-webhook'),
    path('crypto/deposit/', views.CryptoDepositView.as_view(), name='crypto-deposit'),
    path('webhook/nowpayments/', views.NowPaymentsWebhookView.as_view(), name='nowpayments-webhook'),
]