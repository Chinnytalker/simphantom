from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import RegisterSerializer, UserSerializer
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.urls import reverse
from django_ratelimit.decorators import ratelimit


class ThreadedPasswordResetForm(PasswordResetForm):
    """Override send_mail so the SMTP call happens in a background thread."""

    def send_mail(self, subject_template_name, email_template_name, context,
                  from_email, to_email, html_email_template_name=None):
        request = context.get('request')
        protocol = context.get('protocol', 'http')
        domain = context.get('domain', '')
        uid = context.get('uid', '')
        token = context.get('token', '')

        reset_url = f"{protocol}://{domain}{reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})}"

        from main.notifications import send_password_reset_email
        send_password_reset_email(context['user'], reset_url)


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            from main.notifications import send_welcome_email
            send_welcome_email(user)
            refresh = RefreshToken.for_user(user)
            return Response({
                'message': 'User registered successfully',
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'user': UserSerializer(user).data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


# ===== PAGE VIEWS =====

def home(request):
    from orders.models import Order
    from decimal import Decimal
    context = {
        'total_users': get_user_model().objects.count(),
        'total_orders': Order.objects.filter(status__in=['RECEIVED', 'FINISHED']).count(),
    }
    return render(request, 'home.html', context)


@ratelimit(key='ip', rate='8/h', method='POST')
def register_page(request):
    if getattr(request, 'limited', False):
        return render(request, 'register.html', {'error': 'Too many registration attempts. Please try again later.'})

    if request.method == 'POST':
        from .turnstile import verify_turnstile
        token = request.POST.get('cf-turnstile-response', '')
        if not verify_turnstile(token, request.META.get('REMOTE_ADDR')):
            return render(request, 'register.html', {'error': 'Security check failed. Please try again.'})

        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')

        if password != password_confirm:
            return render(request, 'register.html', {'error': 'Passwords do not match'})

        if get_user_model().objects.filter(username=username).exists():
            return render(request, 'register.html', {'error': 'Username already exists'})

        if get_user_model().objects.filter(email=email).exists():
            return render(request, 'register.html', {'error': 'Email already exists'})

        user = get_user_model().objects.create_user(username=username, email=email, password=password)
        from main.notifications import send_welcome_email
        send_welcome_email(user)
        login(request, user)
        return redirect('dashboard')

    return render(request, 'register.html')


@ratelimit(key='ip', rate='15/5m', method='POST')
def login_page(request):
    if getattr(request, 'limited', False):
        return render(request, 'login.html', {'error': 'Too many login attempts. Please wait 5 minutes and try again.'})

    if request.method == 'POST':
        from .turnstile import verify_turnstile
        token = request.POST.get('cf-turnstile-response', '')
        if not verify_turnstile(token, request.META.get('REMOTE_ADDR')):
            return render(request, 'login.html', {'error': 'Security check failed. Please try again.'})

        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            return render(request, 'login.html', {'error': 'Invalid credentials'})

    return render(request, 'login.html')


@login_required(login_url='login')
def dashboard(request):
    from orders.models import Order, Transaction
    from django.db.models import Sum
    from decimal import Decimal

    user = request.user

    # Handle Paystack redirect callback — credit wallet if reference is in URL
    paystack_ref = request.GET.get('reference') or request.GET.get('trxref')
    payment_credited = False
    if paystack_ref:
        from orders.models import Transaction as Txn
        from django.db import transaction as db_txn
        from django.db.models import F
        import requests as http_req
        from django.conf import settings as dj_settings
        try:
            txn = Txn.objects.get(reference=paystack_ref, user=user, type='CREDIT')
            if 'pending' in txn.description:
                resp = http_req.get(
                    f'https://api.paystack.co/transaction/verify/{paystack_ref}',
                    headers={'Authorization': f'Bearer {dj_settings.PAYSTACK_SECRET}'},
                    timeout=10,
                )
                result = resp.json()
                if result.get('status') and result['data']['status'] == 'success':
                    amount = Decimal(result['data']['amount']) / 100
                    with db_txn.atomic():
                        get_user_model().objects.filter(pk=user.pk).update(
                            wallet_balance=F('wallet_balance') + amount
                        )
                        txn.description = 'Wallet top-up (confirmed)'
                        txn.save()
                    user.refresh_from_db()
                    payment_credited = True
                    try:
                        from main.notifications import send_deposit_confirmed_email
                        send_deposit_confirmed_email(user, amount, user.wallet_balance)
                    except Exception:
                        pass
        except Exception:
            pass
    orders = Order.objects.filter(user=user)
    active_orders  = orders.filter(status='PENDING').count()
    total_spent    = orders.filter(status__in=['RECEIVED', 'FINISHED']).aggregate(
        t=Sum('amount_charged'))['t'] or Decimal('0.00')
    # Exclude temp email orders from the phone/SMS table — they go in their own section
    recent_orders  = orders.exclude(service_type='TEMPORARY_EMAIL').order_by('-created_at')[:10]
    transactions   = Transaction.objects.filter(user=user).order_by('-created_at')[:20]
    temp_emails    = orders.filter(
        service_type='TEMPORARY_EMAIL'
    ).exclude(status='CANCELED').order_by('-created_at')[:5]

    fivesim_balance = None
    if user.is_staff or user.is_superuser:
        try:
            from services.fivesim import get_balance
            profile = get_balance()
            fivesim_balance = profile.get('balance')
        except Exception:
            pass

    return render(request, 'dashboard.html', {
        'user': user,
        'active_orders': active_orders,
        'total_spent': total_spent,
        'recent_orders': recent_orders,
        'transactions': transactions,
        'temp_emails': temp_emails,
        'fivesim_balance': fivesim_balance,
        'payment_credited': payment_credited,
    })


@require_POST
def logout_view(request):
    logout(request)
    return redirect('home')


def services(request):
    """All services catalog"""
    return render(request, 'services.html')


def service_detail(request, service_slug):
    """Individual service page"""
    context = {}

    service_templates = {
        'virtual-numbers': 'services/virtual-numbers.html',
        'otp-verification': 'services/otp-verification.html',
        'temporary-email': 'services/temporary-email.html',
        'vpn-subscription': 'services/vpn-subscription.html',
        'esim-packages': 'services/esim-packages.html',
        'residential-proxies': 'services/residential-proxies.html',
        'bulk-sms': 'services/bulk-sms.html',
        'phone-number-lookup': 'services/phone-number-lookup.html',
    }

    template = service_templates.get(service_slug)
    if not template:
        return redirect('home')

    if service_slug == 'residential-proxies':
        from services.brightdata import PROXY_PLANS
        context['proxy_plans'] = PROXY_PLANS
        if request.user.is_authenticated:
            from orders.models import Order
            context['proxy_orders'] = list(
                Order.objects.filter(
                    user=request.user,
                    service_type='RESIDENTIAL_PROXY',
                ).exclude(status='CANCELED').order_by('-created_at').values(
                    'id', 'product', 'status', 'amount_charged', 'created_at', 'expires_at', 'credentials'
                )[:10]
            )

    if service_slug == 'temporary-email' and request.user.is_authenticated:
        import json
        from orders.models import Order
        rows = Order.objects.filter(
            user=request.user,
            service_type='TEMPORARY_EMAIL',
        ).exclude(status='CANCELED').order_by('-created_at').values('id', 'email', 'created_at')[:5]
        active_emails = [
            {'id': r['id'], 'email': r['email'], 'created_at': r['created_at'].isoformat()}
            for r in rows
        ]
        context['active_emails'] = active_emails
        context['active_emails_json'] = json.dumps(active_emails)
        context['email_limit'] = 5

    if service_slug == 'bulk-sms':
        import json
        from services.twilio_sms import SMS_PLANS
        context['sms_plans'] = SMS_PLANS
        if request.user.is_authenticated:
            from orders.models import Order
            orders = list(
                Order.objects.filter(
                    user=request.user,
                    service_type='BULK_SMS',
                    status='FINISHED',
                ).order_by('-created_at').values('id', 'product', 'amount_charged', 'created_at', 'credentials')[:10]
            )
            for o in orders:
                creds = json.loads(o['credentials'] or '{}')
                o['credits_total'] = creds.get('credits_total', 0)
                o['credits_remaining'] = creds.get('credits_remaining', 0)
                o['sent_count'] = creds.get('sent_count', 0)
                o['created_at'] = o['created_at'].isoformat()
                del o['credentials']
            context['sms_orders'] = orders
            context['sms_orders_json'] = json.dumps(orders)

    if service_slug == 'phone-number-lookup':
        import json
        from services.twilio_sms import LOOKUP_PLANS
        context['lookup_plans'] = LOOKUP_PLANS
        if request.user.is_authenticated:
            from orders.models import Order
            orders = list(
                Order.objects.filter(
                    user=request.user,
                    service_type='PHONE_LOOKUP',
                    status='FINISHED',
                ).order_by('-created_at').values('id', 'product', 'amount_charged', 'created_at', 'credentials')[:10]
            )
            for o in orders:
                creds = json.loads(o['credentials'] or '{}')
                o['credits_total'] = creds.get('credits_total', 0)
                o['credits_remaining'] = creds.get('credits_remaining', 0)
                o['lookup_count'] = creds.get('lookup_count', 0)
                o['created_at'] = o['created_at'].isoformat()
                del o['credentials']
            context['lookup_orders'] = orders
            context['lookup_orders_json'] = json.dumps(orders)

    return render(request, template, context)


def privacy_page(request):
    return render(request, 'privacy.html')


def terms_page(request):
    return render(request, 'terms.html')


def cookies_page(request):
    return render(request, 'cookies.html')


def contact_page(request):
    return render(request, 'contact.html')


def error_404(request, exception):
    return render(request, '404.html', status=404)


def error_500(request):
    return render(request, '500.html', status=500)