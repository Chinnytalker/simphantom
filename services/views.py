import json
from decimal import Decimal
from django.db import transaction as db_transaction
from django.db.models import F
from django.contrib.auth import get_user_model
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status
from . import fivesim, mailtm, tigersms
from .config import USD_TO_NGN, FLAT_MARKUP_NGN, esim_naira_price, VPN_PLANS
from orders.models import Order, Transaction


class CountriesView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        data = fivesim.get_countries()
        return Response(data)


class ProductsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, country):
        operator = request.query_params.get('operator', 'any')
        data = fivesim.get_products(country, operator)

        if isinstance(data, dict) and 'error' not in data:
            for service in data:
                if 'Price' in data[service]:
                    cost_ngn = data[service]['Price'] * USD_TO_NGN
                    data[service]['naira_price'] = round(cost_ngn + FLAT_MARKUP_NGN, 2)

        return Response(data)


class PricesByProductView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        product = request.query_params.get('product', '').strip().lower()
        if not product:
            return Response({'error': 'product param required'}, status=400)

        raw = fivesim.get_prices_by_product(product)

        # Debug: return raw 5sim response to inspect structure
        if request.query_params.get('raw') == '1':
            return Response(raw)

        if isinstance(raw, dict) and 'error' in raw:
            return Response(raw, status=502)

        # 5sim can return either:
        #   A) { country: { operator: {cost, count} } }
        #   B) { product_name: { country: { operator: {cost, count} } } }
        # Unwrap structure B by checking if the product name is a top-level key.
        country_map = raw.get(product, raw) if isinstance(raw, dict) else raw

        results = []
        for country_key, operators in country_map.items():
            if not isinstance(operators, dict):
                continue
            op_key = 'any' if 'any' in operators else (next(iter(operators)) if operators else None)
            if op_key is None:
                continue
            op_data = operators[op_key]
            if not isinstance(op_data, dict):
                continue
            # Handle both lowercase (prices endpoint) and titlecase (products endpoint)
            count = op_data.get('count', op_data.get('Count', op_data.get('Qty', 0)))
            cost_usd = op_data.get('cost', op_data.get('Cost', op_data.get('Price', 0)))
            try:
                count = int(count)
                cost_usd = float(cost_usd)
            except (TypeError, ValueError):
                continue
            if count <= 0:
                continue
            naira_price = round(cost_usd * USD_TO_NGN + FLAT_MARKUP_NGN, 2)
            results.append({
                'country': country_key,
                'operator': op_key,
                'cost_usd': cost_usd,
                'naira_price': naira_price,
                'count': count,
            })

        results.sort(key=lambda x: x['naira_price'])
        return Response(results)


class ServiceCatalogView(APIView):
    """Return product names that are actually available (using Russia as proxy)."""
    permission_classes = [AllowAny]

    def get(self, request):
        data = fivesim.get_products('russia', 'any')
        if isinstance(data, dict) and 'error' in data:
            return Response(data, status=502)
        products = [
            {'name': name, 'qty': details.get('Qty', 0)}
            for name, details in data.items()
            if isinstance(details, dict) and details.get('Qty', 0) > 0
        ]
        products.sort(key=lambda x: x['name'])
        return Response(products)


# ── Temporary Email (mail.tm) ─────────────────────────────────────────────────

class TempEmailCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        domains = mailtm.get_domains()
        if isinstance(domains, dict) and 'error' in domains:
            return Response({'error': 'Could not reach email service. Try again.'}, status=502)
        if not domains:
            return Response({'error': 'No email domains available right now.'}, status=503)

        domain = domains[0]['domain']
        address = mailtm.random_address() + '@' + domain
        password = mailtm.random_password()

        account = mailtm.create_account(address, password)
        if 'error' in account:
            return Response({'error': account['error']}, status=502)

        token_data = mailtm.get_token(address, password)
        if 'error' in token_data:
            return Response({'error': token_data['error']}, status=502)

        order = Order.objects.create(
            user=request.user,
            service_type='TEMPORARY_EMAIL',
            email=address,
            product='temporary-email',
            status='FINISHED',
            amount_charged=Decimal('0.00'),
            credentials=json.dumps({
                'account_id': account['id'],
                'token': token_data['token'],
                'password': password,
            }),
        )

        return Response({
            'id': order.id,
            'email': address,
            'created_at': order.created_at.isoformat(),
        }, status=201)


class TempEmailInboxView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, user=request.user,
                                       service_type='TEMPORARY_EMAIL')
        except Order.DoesNotExist:
            return Response({'error': 'Email not found'}, status=404)

        if order.status == 'CANCELED':
            return Response({'error': 'This email has been deleted'}, status=410)

        creds = json.loads(order.credentials or '{}')
        token = creds.get('token', '')

        messages = mailtm.get_messages(token)

        # Token may have expired — re-auth and retry once
        if isinstance(messages, dict) and 'error' in messages:
            td = mailtm.get_token(order.email, creds.get('password', ''))
            if 'error' not in td:
                token = td['token']
                creds['token'] = token
                order.credentials = json.dumps(creds)
                order.save(update_fields=['credentials'])
                messages = mailtm.get_messages(token)

        if isinstance(messages, dict) and 'error' in messages:
            return Response({'error': messages['error']}, status=502)

        result = [{
            'id': m['id'],
            'from': m.get('from', {}).get('address', 'Unknown'),
            'from_name': m.get('from', {}).get('name', ''),
            'subject': m.get('subject') or '(No subject)',
            'intro': m.get('intro', ''),
            'seen': m.get('seen', False),
            'created_at': m.get('createdAt', ''),
        } for m in messages]

        return Response(result)


class TempEmailMessageView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id, message_id):
        try:
            order = Order.objects.get(id=order_id, user=request.user,
                                       service_type='TEMPORARY_EMAIL')
        except Order.DoesNotExist:
            return Response({'error': 'Email not found'}, status=404)

        creds = json.loads(order.credentials or '{}')
        msg = mailtm.get_message(creds.get('token', ''), message_id)

        if isinstance(msg, dict) and 'error' in msg:
            return Response({'error': msg['error']}, status=502)

        html_parts = msg.get('html', [])
        return Response({
            'id': msg['id'],
            'from': msg.get('from', {}).get('address', 'Unknown'),
            'from_name': msg.get('from', {}).get('name', ''),
            'subject': msg.get('subject') or '(No subject)',
            'created_at': msg.get('createdAt', ''),
            'text': msg.get('text', ''),
            'html': html_parts[0] if html_parts else '',
        })


class TempEmailDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, user=request.user,
                                       service_type='TEMPORARY_EMAIL')
        except Order.DoesNotExist:
            return Response({'error': 'Email not found'}, status=404)

        creds = json.loads(order.credentials or '{}')
        mailtm.delete_account(creds.get('token', ''), creds.get('account_id', ''))

        order.status = 'CANCELED'
        order.save(update_fields=['status'])

        return Response({'success': True})


# ── Residential Proxies (Bright Data) ─────────────────────────────────────────

class ProxyPurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from . import brightdata
        from django.utils import timezone
        import uuid

        plan_id = request.data.get('plan_id', '').strip()
        plan = brightdata.PLAN_MAP.get(plan_id)
        if not plan:
            return Response({'error': 'Invalid plan.'}, status=400)

        price = Decimal(str(plan['price_ngn']))
        user = request.user
        User = get_user_model()

        deducted = User.objects.filter(pk=user.pk, wallet_balance__gte=price).update(
            wallet_balance=F('wallet_balance') - price
        )
        if not deducted:
            user.refresh_from_db(fields=['wallet_balance'])
            return Response({
                'error': f'Insufficient balance. You need ₦{price:,.0f} but have ₦{user.wallet_balance:,.0f}.'
            }, status=400)

        ref = 'PROXY-' + uuid.uuid4().hex[:12].upper()
        Transaction.objects.create(
            user=user,
            amount=price,
            type='DEBIT',
            reference=ref,
            description=f'Residential Proxy — {plan["name"]} ({plan["gb"]}GB)',
        )

        # Generate session-based credentials instantly (no API call)
        creds = brightdata.create_session_credentials()
        provisioned = creds.get('provisioned', False)

        if not provisioned:
            # Zone not configured yet — order stored, credentials delivered later
            creds = {
                'provisioned': False,
                'plan_id': plan_id,
                'gb': plan['gb'],
                'note': 'Credentials will be delivered to your email once the zone is configured.',
            }

        expires_at = timezone.now() + timezone.timedelta(days=30)

        order = Order.objects.create(
            user=user,
            service_type='RESIDENTIAL_PROXY',
            product=f"proxy-{plan_id}",
            status='FINISHED' if provisioned else 'PENDING',
            amount_charged=price,
            credentials=json.dumps(creds),
            expires_at=expires_at,
        )

        from main.notifications import send_purchase_email
        send_purchase_email(
            user,
            'Residential Proxy',
            [('Plan', plan['name']), ('Data', f'{plan["gb"]} GB'), ('Validity', '30 days'),
             ('Status', 'Active' if provisioned else 'Pending provisioning')],
            order.id,
            price,
        )

        return Response({
            'id': order.id,
            'plan': plan['name'],
            'gb': plan['gb'],
            'provisioned': provisioned,
            'credentials': creds if provisioned else None,
            'proxy_string': brightdata.build_proxy_string(creds) if provisioned else None,
            'expires_at': expires_at.isoformat(),
        }, status=201)


class ProxyOrderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, user=request.user,
                                       service_type='RESIDENTIAL_PROXY')
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=404)

        from . import brightdata
        creds = json.loads(order.credentials or '{}')
        proxy_str = brightdata.build_proxy_string(creds) if creds.get('provisioned') else None

        return Response({
            'id': order.id,
            'plan': order.product.replace('proxy-', '').title(),
            'status': order.status,
            'provisioned': creds.get('provisioned', False),
            'credentials': creds if creds.get('provisioned') else None,
            'proxy_string': proxy_str,
            'amount_charged': str(order.amount_charged),
            'created_at': order.created_at.isoformat(),
            'expires_at': order.expires_at.isoformat() if order.expires_at else None,
        })


# ── Bulk SMS (Twilio) ──────────────────────────────────────────────────────────

class SMSBuyCreditsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .twilio_sms import SMS_PLAN_MAP
        import uuid

        plan_id = request.data.get('plan_id', '').strip()
        plan = SMS_PLAN_MAP.get(plan_id)
        if not plan:
            return Response({'error': 'Invalid plan.'}, status=400)

        price = Decimal(str(plan['price_ngn']))
        user = request.user
        User = get_user_model()

        deducted = User.objects.filter(pk=user.pk, wallet_balance__gte=price).update(
            wallet_balance=F('wallet_balance') - price
        )
        if not deducted:
            user.refresh_from_db(fields=['wallet_balance'])
            return Response({
                'error': f'Insufficient balance. Need ₦{price:,.0f}, have ₦{user.wallet_balance:,.0f}.'
            }, status=400)

        ref = 'SMS-' + uuid.uuid4().hex[:12].upper()
        Transaction.objects.create(
            user=user,
            amount=price,
            type='DEBIT',
            reference=ref,
            description=f'Bulk SMS — {plan["credits"]:,} credits',
        )

        order = Order.objects.create(
            user=user,
            service_type='BULK_SMS',
            product=plan_id,
            status='FINISHED',
            amount_charged=price,
            credentials=json.dumps({
                'credits_total': plan['credits'],
                'credits_remaining': plan['credits'],
                'sent_count': 0,
            }),
        )

        from main.notifications import send_purchase_email
        send_purchase_email(
            user,
            'Bulk SMS Credits',
            [('Credits purchased', f'{plan["credits"]:,}'), ('Plan', plan_id)],
            order.id,
            price,
        )

        return Response({
            'id': order.id,
            'credits': plan['credits'],
            'plan_id': plan_id,
        }, status=201)


class SMSSendView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .twilio_sms import send_sms

        order_id = request.data.get('order_id')
        recipients_raw = request.data.get('recipients', '')
        message = request.data.get('message', '').strip()

        if not message:
            return Response({'error': 'Message is required.'}, status=400)
        if len(message) > 160:
            return Response({'error': 'Message must be 160 characters or fewer.'}, status=400)

        # Parse recipients: comma or newline separated
        recipients = [r.strip() for r in recipients_raw.replace('\n', ',').split(',') if r.strip()]
        if not recipients:
            return Response({'error': 'At least one recipient is required.'}, status=400)
        if len(recipients) > 500:
            return Response({'error': 'Maximum 500 recipients per send.'}, status=400)

        try:
            order = Order.objects.get(id=order_id, user=request.user,
                                       service_type='BULK_SMS', status='FINISHED')
        except Order.DoesNotExist:
            return Response({'error': 'SMS credit order not found.'}, status=404)

        creds = json.loads(order.credentials or '{}')
        remaining = creds.get('credits_remaining', 0)

        if remaining < len(recipients):
            return Response({
                'error': f'Not enough credits. Need {len(recipients)}, have {remaining}.'
            }, status=400)

        results = {'sent': 0, 'failed': 0, 'errors': []}
        for number in recipients:
            res = send_sms(number, message)
            if res['success']:
                results['sent'] += 1
            else:
                results['failed'] += 1
                results['errors'].append({'number': number, 'error': res['error']})

        # Deduct only successfully sent
        creds['credits_remaining'] -= results['sent']
        creds['sent_count'] = creds.get('sent_count', 0) + results['sent']
        order.credentials = json.dumps(creds)
        order.save(update_fields=['credentials'])

        return Response({
            'sent': results['sent'],
            'failed': results['failed'],
            'credits_remaining': creds['credits_remaining'],
            'errors': results['errors'][:10],
        })


class SMSOrdersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        orders = Order.objects.filter(
            user=request.user,
            service_type='BULK_SMS',
            status='FINISHED',
        ).order_by('-created_at')[:20]

        result = []
        for o in orders:
            creds = json.loads(o.credentials or '{}')
            result.append({
                'id': o.id,
                'plan_id': o.product,
                'credits_total': creds.get('credits_total', 0),
                'credits_remaining': creds.get('credits_remaining', 0),
                'sent_count': creds.get('sent_count', 0),
                'amount_charged': str(o.amount_charged),
                'created_at': o.created_at.isoformat(),
            })

        return Response(result)


# ── Phone Number Lookup (Twilio Lookup API) ────────────────────────────────────

class LookupBuyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .twilio_sms import LOOKUP_PLAN_MAP
        import uuid

        plan_id = request.data.get('plan_id', '').strip()
        plan = LOOKUP_PLAN_MAP.get(plan_id)
        if not plan:
            return Response({'error': 'Invalid plan.'}, status=400)

        price = Decimal(str(plan['price_ngn']))
        user = request.user
        User = get_user_model()

        deducted = User.objects.filter(pk=user.pk, wallet_balance__gte=price).update(
            wallet_balance=F('wallet_balance') - price
        )
        if not deducted:
            user.refresh_from_db(fields=['wallet_balance'])
            return Response({
                'error': f'Insufficient balance. Need ₦{price:,.0f}, have ₦{user.wallet_balance:,.0f}.'
            }, status=400)

        ref = 'LOOKUP-' + uuid.uuid4().hex[:12].upper()
        Transaction.objects.create(
            user=user,
            amount=price,
            type='DEBIT',
            reference=ref,
            description=f'Phone Lookup — {plan["credits"]:,} credits',
        )

        order = Order.objects.create(
            user=user,
            service_type='PHONE_LOOKUP',
            product=plan_id,
            status='FINISHED',
            amount_charged=price,
            credentials=json.dumps({
                'credits_total': plan['credits'],
                'credits_remaining': plan['credits'],
                'lookup_count': 0,
            }),
        )

        from main.notifications import send_purchase_email
        send_purchase_email(
            user,
            'Phone Number Lookup Credits',
            [('Credits purchased', f'{plan["credits"]:,}'), ('Plan', plan_id)],
            order.id,
            price,
        )

        return Response({
            'id': order.id,
            'credits': plan['credits'],
            'plan_id': plan_id,
        }, status=201)


class LookupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .twilio_sms import lookup_phone

        order_id = request.data.get('order_id')
        phone = request.data.get('phone', '').strip()

        if not phone:
            return Response({'error': 'Phone number is required.'}, status=400)

        try:
            order = Order.objects.get(id=order_id, user=request.user,
                                       service_type='PHONE_LOOKUP', status='FINISHED')
        except Order.DoesNotExist:
            return Response({'error': 'Lookup credit order not found.'}, status=404)

        creds = json.loads(order.credentials or '{}')
        if creds.get('credits_remaining', 0) < 1:
            return Response({'error': 'No lookup credits remaining.'}, status=400)

        result = lookup_phone(phone)
        if 'error' in result:
            return Response({'error': result['error']}, status=502)

        creds['credits_remaining'] -= 1
        creds['lookup_count'] = creds.get('lookup_count', 0) + 1
        order.credentials = json.dumps(creds)
        order.save(update_fields=['credentials'])

        result['credits_remaining'] = creds['credits_remaining']
        return Response(result)


class LookupOrdersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        orders = Order.objects.filter(
            user=request.user,
            service_type='PHONE_LOOKUP',
            status='FINISHED',
        ).order_by('-created_at')[:20]

        result = []
        for o in orders:
            creds = json.loads(o.credentials or '{}')
            result.append({
                'id': o.id,
                'plan_id': o.product,
                'credits_total': creds.get('credits_total', 0),
                'credits_remaining': creds.get('credits_remaining', 0),
                'lookup_count': creds.get('lookup_count', 0),
                'amount_charged': str(o.amount_charged),
                'created_at': o.created_at.isoformat(),
            })

        return Response(result)


# ── eSIM (ESIMCard) ───────────────────────────────────────────────────────────

class ESIMCountriesView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        from . import esimcard
        data = esimcard.get_countries()
        if not data.get('status'):
            return Response({'error': 'Could not fetch eSIM countries'}, status=502)
        return Response(data.get('data', []))


class ESIMCountryPackagesView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, country_id):
        from . import esimcard
        package_type = request.query_params.get('package_type', 'DATA-ONLY')
        data = esimcard.get_country_packages(country_id, package_type)

        if not data.get('status'):
            return Response({'error': 'Could not fetch packages'}, status=502)

        packages = data.get('data', [])
        for pkg in packages:
            try:
                price_usd = float(pkg.get('price', 0))
            except (TypeError, ValueError):
                price_usd = 0.0
            pkg['naira_price'] = esim_naira_price(price_usd)
            pkg['price_usd'] = price_usd

        return Response({'data': packages, 'meta': data.get('meta', {})})


class ESIMPurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from . import esimcard
        import uuid

        package_id = request.data.get('package_id', '').strip()
        if not package_id:
            return Response({'error': 'package_id is required'}, status=400)

        # Fetch authoritative price from esimcard API (never trust client-sent price)
        pkg_resp = esimcard.get_package_detail(package_id)
        if not pkg_resp.get('status'):
            return Response({'error': 'Could not verify package. Please try again.'}, status=502)

        pkg = pkg_resp.get('data', {})
        try:
            price_usd = float(pkg.get('price', 0))
        except (TypeError, ValueError):
            return Response({'error': 'Invalid package price.'}, status=502)

        price_ngn = Decimal(str(esim_naira_price(price_usd)))
        package_name = pkg.get('name', 'eSIM Package')
        validity_days = int(pkg.get('package_validity', 30))

        user = request.user
        User = get_user_model()

        deducted = User.objects.filter(pk=user.pk, wallet_balance__gte=price_ngn).update(
            wallet_balance=F('wallet_balance') - price_ngn
        )
        if not deducted:
            user.refresh_from_db(fields=['wallet_balance'])
            return Response({
                'error': f'Insufficient balance. Need ₦{price_ngn:,.0f}, have ₦{user.wallet_balance:,.0f}.'
            }, status=400)

        ref = 'ESIM-' + uuid.uuid4().hex[:12].upper()
        Transaction.objects.create(
            user=user,
            amount=price_ngn,
            type='DEBIT',
            reference=ref,
            description=f'eSIM — {package_name}',
        )

        result = esimcard.purchase_esim(package_id)

        if not result.get('status'):
            User.objects.filter(pk=user.pk).update(wallet_balance=F('wallet_balance') + price_ngn)
            Transaction.objects.create(
                user=user,
                amount=price_ngn,
                type='CREDIT',
                reference='REFUND-' + ref,
                description='Refund — eSIM purchase failed',
            )
            return Response({'error': 'eSIM purchase failed. Your wallet has been refunded.'}, status=502)

        api_data = result.get('data', {})
        sim_applied = api_data.get('sim_applied', False)
        credentials = {}
        order_status = 'PENDING'

        if sim_applied:
            sim = api_data.get('sim', {})
            esim_id = sim.get('id', '')
            iccid = sim.get('iccid', '')

            # universal_link lives in the /my-esims list, not in the purchase response
            universal_link = ''
            if esim_id:
                my_esims = esimcard.get_my_esims()
                for e in my_esims.get('data', []):
                    if e.get('id') == esim_id:
                        universal_link = e.get('universal_link', '')
                        break

            credentials = {
                'esim_id': esim_id,
                'iccid': iccid,
                'universal_link': universal_link,
                'sim_status': sim.get('status', ''),
            }
            order_status = 'FINISHED'
        else:
            credentials = {
                'sim_applied': False,
                'message': api_data.get('message', 'eSIM is being provisioned.'),
            }

        from django.utils import timezone as tz
        expires_at = tz.now() + tz.timedelta(days=validity_days)

        order = Order.objects.create(
            user=user,
            service_type='ESIM',
            product=package_name,
            status=order_status,
            amount_charged=price_ngn,
            credentials=json.dumps(credentials),
            expires_at=expires_at,
        )

        from main.notifications import send_purchase_email
        esim_details = [
            ('Package', package_name),
            ('Validity', f'{validity_days} days'),
            ('Status', 'Active' if sim_applied else 'Being provisioned'),
        ]
        if credentials.get('iccid'):
            esim_details.append(('ICCID', credentials['iccid']))
        if credentials.get('universal_link'):
            esim_details.append(('Activation link', credentials['universal_link']))
        send_purchase_email(user, 'eSIM', esim_details, order.id, price_ngn)

        return Response({
            'id': order.id,
            'status': order_status,
            'package': package_name,
            'sim_applied': sim_applied,
            'iccid': credentials.get('iccid', ''),
            'universal_link': credentials.get('universal_link', ''),
            'message': credentials.get('message', ''),
        }, status=201)


class ESIMOrdersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        orders = Order.objects.filter(
            user=request.user,
            service_type='ESIM',
        ).order_by('-created_at')[:30]

        result = []
        for o in orders:
            creds = json.loads(o.credentials or '{}')
            result.append({
                'id': o.id,
                'package': o.product,
                'status': o.status,
                'amount_charged': str(o.amount_charged),
                'created_at': o.created_at.isoformat(),
                'expires_at': o.expires_at.isoformat() if o.expires_at else None,
                'iccid': creds.get('iccid', ''),
                'universal_link': creds.get('universal_link', ''),
                'sim_status': creds.get('sim_status', ''),
                'sim_applied': bool(creds.get('esim_id', '')),
            })

        return Response(result)


class ESIMOrderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, user=request.user, service_type='ESIM')
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=404)

        creds = json.loads(order.credentials or '{}')
        esim_id = creds.get('esim_id', '')

        usage = None
        if esim_id:
            from . import esimcard
            usage_resp = esimcard.get_esim_usage(esim_id)
            if usage_resp.get('status'):
                usage = usage_resp.get('data', {})

        return Response({
            'id': order.id,
            'package': order.product,
            'status': order.status,
            'amount_charged': str(order.amount_charged),
            'created_at': order.created_at.isoformat(),
            'expires_at': order.expires_at.isoformat() if order.expires_at else None,
            'iccid': creds.get('iccid', ''),
            'universal_link': creds.get('universal_link', ''),
            'sim_status': creds.get('sim_status', ''),
            'sim_applied': bool(esim_id),
            'usage': usage,
        })


class ESIMRefreshView(APIView):
    """Poll my-esims to resolve a pending (delayed) eSIM purchase."""
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        from . import esimcard

        try:
            order = Order.objects.get(id=order_id, user=request.user, service_type='ESIM', status='PENDING')
        except Order.DoesNotExist:
            return Response({'error': 'Pending eSIM order not found'}, status=404)

        my_esims = esimcard.get_my_esims()
        if not my_esims.get('status'):
            return Response({'error': 'Could not reach eSIM service.'}, status=502)

        esims = my_esims.get('data', [])
        if not esims:
            return Response({'ready': False, 'message': 'eSIM not ready yet. Please try again shortly.'})

        matched = None
        for esim in esims:
            created_str = esim.get('created_at', '')
            if not created_str:
                continue
            try:
                from datetime import datetime
                created_at = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                if created_at >= order.created_at:
                    matched = esim
                    break
            except (ValueError, TypeError):
                continue

        if not matched:
            matched = esims[0]

        universal_link = matched.get('universal_link', '')
        if not universal_link:
            return Response({'ready': False, 'message': 'eSIM not ready yet. Please try again shortly.'})

        creds = {
            'esim_id': matched.get('id', ''),
            'iccid': matched.get('iccid', ''),
            'universal_link': universal_link,
            'sim_status': matched.get('status', ''),
        }
        order.credentials = json.dumps(creds)
        order.status = 'FINISHED'
        order.save(update_fields=['credentials', 'status'])

        return Response({
            'ready': True,
            'id': order.id,
            'iccid': creds['iccid'],
            'universal_link': universal_link,
        })


# ── WireGuard VPN ─────────────────────────────────────────────────────────────

class VPNPlansView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        plans = [
            {
                'id': plan_id,
                'name': plan['name'],
                'location': plan['location'],
                'duration_days': plan['duration_days'],
                'price_ngn': plan['price_ngn'],
            }
            for plan_id, plan in VPN_PLANS.items()
        ]
        return Response(plans)


class VPNPurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from . import wireguard, vpn_server
        import uuid
        from django.utils import timezone

        plan_id = request.data.get('plan_id', '').strip()
        plan = VPN_PLANS.get(plan_id)
        if not plan:
            return Response({'error': 'Invalid VPN plan.'}, status=400)

        price = Decimal(str(plan['price_ngn']))
        user = request.user
        User = get_user_model()

        deducted = User.objects.filter(pk=user.pk, wallet_balance__gte=price).update(
            wallet_balance=F('wallet_balance') - price
        )
        if not deducted:
            user.refresh_from_db(fields=['wallet_balance'])
            return Response({
                'error': f'Insufficient balance. Need ₦{price:,.0f}, have ₦{user.wallet_balance:,.0f}.'
            }, status=400)

        client_private_key, client_public_key = wireguard.generate_keypair()

        result = vpn_server.add_peer(plan['location'], client_public_key)
        if 'error' in result:
            User.objects.filter(pk=user.pk).update(wallet_balance=F('wallet_balance') + price)
            return Response({'error': f"VPN provisioning failed: {result['error']}"}, status=502)

        assigned_ip = result['assigned_ip']
        server_public_key = result['server_public_key']
        server_endpoint = vpn_server.VPN_SERVERS[plan['location']]['endpoint']

        config_str = wireguard.build_client_config(
            client_private_key, assigned_ip, server_public_key, server_endpoint
        )

        ref = 'VPN-' + uuid.uuid4().hex[:12].upper()
        Transaction.objects.create(
            user=user, amount=price, type='DEBIT', reference=ref,
            description=f'VPN — {plan["name"]}',
        )

        expires_at = timezone.now() + timezone.timedelta(days=plan['duration_days'])

        order = Order.objects.create(
            user=user,
            service_type='VPN',
            product=plan_id,
            status='FINISHED',
            amount_charged=price,
            expires_at=expires_at,
            credentials=json.dumps({
                'plan_name': plan['name'],
                'location': plan['location'],
                'client_private_key': client_private_key,
                'client_public_key': client_public_key,
                'server_public_key': server_public_key,
                'server_endpoint': server_endpoint,
                'assigned_ip': assigned_ip,
                'config': config_str,
            }),
        )

        from main.notifications import send_purchase_email
        send_purchase_email(
            user, 'VPN Subscription',
            [
                ('Plan', plan['name']),
                ('Location', {'us': 'United States', 'uk': 'United Kingdom'}.get(plan['location'], plan['location'])),
                ('Validity', f'{plan["duration_days"]} days'),
                ('Assigned IP', assigned_ip),
            ],
            order.id, price,
        )

        return Response({
            'id': order.id,
            'plan': plan['name'],
            'location': plan['location'],
            'assigned_ip': assigned_ip,
            'expires_at': expires_at.isoformat(),
            'config': config_str,
        }, status=201)


class VPNOrdersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        orders = Order.objects.filter(
            user=request.user, service_type='VPN'
        ).order_by('-created_at')[:20]

        result = []
        for o in orders:
            creds = json.loads(o.credentials or '{}')
            result.append({
                'id': o.id,
                'plan': creds.get('plan_name', o.product),
                'location': creds.get('location', ''),
                'assigned_ip': creds.get('assigned_ip', ''),
                'status': o.status,
                'amount_charged': str(o.amount_charged),
                'created_at': o.created_at.isoformat(),
                'expires_at': o.expires_at.isoformat() if o.expires_at else None,
            })

        return Response(result)


class VPNOrderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, user=request.user, service_type='VPN')
        except Order.DoesNotExist:
            return Response({'error': 'VPN order not found'}, status=404)

        from . import wireguard as wg
        creds = json.loads(order.credentials or '{}')
        config_str = creds.get('config', '')
        qr_code = wg.config_to_qr_base64(config_str) if config_str else None

        return Response({
            'id': order.id,
            'plan': creds.get('plan_name', order.product),
            'location': creds.get('location', ''),
            'assigned_ip': creds.get('assigned_ip', ''),
            'server_endpoint': creds.get('server_endpoint', ''),
            'status': order.status,
            'amount_charged': str(order.amount_charged),
            'created_at': order.created_at.isoformat(),
            'expires_at': order.expires_at.isoformat() if order.expires_at else None,
            'config': config_str,
            'qr_code': qr_code,
        })


class VPNConfigDownloadView(APIView):
    """Serve the .conf file as a direct file download."""
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        from django.http import HttpResponse
        try:
            order = Order.objects.get(id=order_id, user=request.user, service_type='VPN')
        except Order.DoesNotExist:
            return Response({'error': 'VPN order not found'}, status=404)

        creds = json.loads(order.credentials or '{}')
        config_str = creds.get('config', '')
        if not config_str:
            return Response({'error': 'Config not available'}, status=404)

        location = creds.get('location', 'vpn').upper()
        filename = f'simphantom-vpn-{location}-{order.id}.conf'
        response = HttpResponse(config_str, content_type='text/plain; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class VPNCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        from . import vpn_server
        try:
            order = Order.objects.get(id=order_id, user=request.user, service_type='VPN', status='FINISHED')
        except Order.DoesNotExist:
            return Response({'error': 'Active VPN order not found'}, status=404)

        creds = json.loads(order.credentials or '{}')
        location = creds.get('location', '')
        public_key = creds.get('client_public_key', '')

        if location and public_key:
            vpn_server.remove_peer(location, public_key)

        order.status = 'CANCELED'
        order.save(update_fields=['status'])
        return Response({'success': True})


# ── TigerSMS — virtual number countries & products ────────────────────────────

class TigerCountriesView(APIView):
    """
    Returns countries available in TigerSMS, validated against the live getPrices dump.
    Add ?raw=1 to run the full diagnostic.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        if request.query_params.get('raw') == '1':
            return Response(tigersms.diagnose())

        countries = tigersms.get_all_countries()
        result = {c['code']: {'text_en': c['text_en'], 'tiger_id': c['tiger_id']}
                  for c in countries}
        return Response(result)


class TigerProductsView(APIView):
    """
    Returns TigerSMS services + prices for a given country code (5sim name).
    Add ?raw=1 to see the raw cached slice for debugging.
    """
    permission_classes = [AllowAny]

    def get(self, request, country):
        country_id = tigersms.resolve_country_id(country)

        if request.query_params.get('raw') == '1':
            return Response(tigersms.get_prices_raw(country_id) if country_id else {'country_id': None})

        operator = request.query_params.get('operator', 'any')

        # Try TigerSMS prices from cache
        tiger_result = {}
        if country_id is not None:
            prices = tigersms.get_prices(country_id)
            for service_code, data in prices.items():
                count = data.get('count', 0)
                cost_usd = data.get('cost', 0.0)
                if count <= 0 or cost_usd <= 0:
                    continue
                product_name = tigersms.CODE_TO_FIVESIM.get(service_code, service_code)
                naira_price = round(cost_usd * USD_TO_NGN + FLAT_MARKUP_NGN, 2)
                tiger_result[product_name] = {
                    'Price': cost_usd,
                    'Qty': count,
                    'naira_price': naira_price,
                }

        if tiger_result:
            return Response(tiger_result)

        # Cache miss or country not in dump yet — fall back to 5sim for listing
        data = fivesim.get_products(country, operator)
        if isinstance(data, dict) and 'error' not in data:
            for svc in data:
                if 'Price' in data[svc]:
                    data[svc]['naira_price'] = round(
                        data[svc]['Price'] * USD_TO_NGN + FLAT_MARKUP_NGN, 2
                    )
        return Response(data)
