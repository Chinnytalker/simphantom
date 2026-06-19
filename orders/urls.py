from django.urls import path
from . import views

urlpatterns = [
    path('buy/', views.BuyNumberView.as_view(), name='buy-number'),
    path('check/<int:order_id>/', views.CheckOrderView.as_view(), name='check-order'),
    path('cancel/<int:order_id>/', views.CancelOrderView.as_view(), name='cancel-order'),
    path('history/', views.OrderHistoryView.as_view(), name='order-history'),
]