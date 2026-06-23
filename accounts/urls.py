from django.urls import path
from django.contrib.auth import views as auth_views
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from . import views

urlpatterns = [
    # PAGE ROUTES
    path('', views.home, name='home'),
    path('register/', views.register_page, name='register'),
    path('login/', views.login_page, name='login'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('logout/', views.logout_view, name='logout'),

    # PASSWORD RESET
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='registration/password_reset_form.html',
        form_class=views.ThreadedPasswordResetForm,
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html',
    ), name='password_reset_done'),
    path('password-reset/confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html',
    ), name='password_reset_confirm'),
    path('password-reset/complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html',
    ), name='password_reset_complete'),

    # SERVICES ROUTES
    path('services/', views.services, name='services'),
    path('services/<str:service_slug>/', views.service_detail, name='service-detail'),

    # LEGAL / INFO PAGES
    path('privacy/', views.privacy_page, name='privacy'),
    path('terms/', views.terms_page, name='terms'),
    path('cookies/', views.cookies_page, name='cookies'),
    path('contact/', views.contact_page, name='contact'),

    # LANDING PAGES
    path('virtual-number-for-whatsapp/', views.landing_whatsapp_number, name='landing-whatsapp-number'),
    path('vpn-nigeria/', views.landing_vpn_nigeria, name='landing-vpn-nigeria'),

    # API ROUTES (full paths — no conflict with page routes above)
    path('api/auth/register/', views.RegisterView.as_view(), name='api-register'),
    path('api/auth/login/', TokenObtainPairView.as_view(), name='token-obtain-pair'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('api/auth/profile/', views.ProfileView.as_view(), name='profile'),
]