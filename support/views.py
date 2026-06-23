from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum, Q
from django.core.paginator import Paginator
from django.utils import timezone
from django.http import JsonResponse
from decimal import Decimal
import json
from .models import Ticket, TicketMessage
from orders.models import Order, Transaction


def _is_staff(user):
    return user.is_active and (user.is_staff or user.is_superuser or user.is_agent)

def _is_admin(user):
    return user.is_active and (user.is_staff or user.is_superuser)

staff_required = user_passes_test(_is_staff, login_url='login')
admin_required = user_passes_test(_is_admin, login_url='login')


# ══════════════════════════════════════════════════
# USER SUPPORT
# ══════════════════════════════════════════════════

@login_required(login_url='login')
def support_list(request):
    from django.db.models import Count
    status_filter = request.GET.get('status', '')

    all_tickets = Ticket.objects.filter(user=request.user)
    counts = {s: all_tickets.filter(status=s).count() for s, _ in Ticket.STATUS_CHOICES}
    counts['ALL'] = all_tickets.count()

    tickets = all_tickets
    if status_filter:
        tickets = tickets.filter(status=status_filter)
    tickets = tickets.annotate(message_count=Count('messages')).order_by('-updated_at')

    return render(request, 'support/list.html', {
        'tickets': tickets,
        'status_filter': status_filter,
        'counts': counts,
    })


@login_required(login_url='login')
def create_ticket(request):
    if request.method == 'POST':
        subject  = request.POST.get('subject', '').strip()
        category = request.POST.get('category', 'OTHER')
        message  = request.POST.get('message', '').strip()
        if not subject or not message:
            return render(request, 'support/create.html', {
                'error': 'Subject and message are required.',
                'form_data': request.POST,
            })
        ticket = Ticket.objects.create(
            user=request.user,
            subject=subject,
            category=category,
            staff_unread=True,
        )
        TicketMessage.objects.create(
            ticket=ticket,
            sender=request.user,
            message=message,
            is_staff_reply=False,
        )
        from main.notifications import send_ticket_opened_email
        send_ticket_opened_email(ticket, message)
        return redirect('ticket-detail', pk=ticket.pk)
    return render(request, 'support/create.html')


@login_required(login_url='login')
def ticket_detail(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk, user=request.user)

    if ticket.user_unread:
        ticket.user_unread = False
        ticket.save(update_fields=['user_unread'])

    if request.method == 'POST':
        message = request.POST.get('message', '').strip()
        if message and ticket.status not in ('RESOLVED', 'CLOSED'):
            TicketMessage.objects.create(
                ticket=ticket, sender=request.user,
                message=message, is_staff_reply=False,
            )
            ticket.staff_unread = True
            if ticket.status == 'RESOLVED':
                ticket.status = 'OPEN'
            ticket.save()
        return redirect('ticket-detail', pk=ticket.pk)

    msgs = ticket.messages.select_related('sender').all()
    return render(request, 'support/detail.html', {'ticket': ticket, 'ticket_messages': msgs})


@login_required(login_url='login')
def ticket_poll(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk, user=request.user)
    try:
        since_id = int(request.GET.get('since', 0))
    except (TypeError, ValueError):
        since_id = 0

    if ticket.user_unread:
        ticket.user_unread = False
        ticket.save(update_fields=['user_unread'])

    msgs = ticket.messages.filter(id__gt=since_id).select_related('sender')
    return JsonResponse({
        'messages': [
            {
                'id': m.id,
                'message': m.message,
                'is_staff_reply': m.is_staff_reply,
                'created_at': m.created_at.strftime('%d %b, %H:%M'),
            }
            for m in msgs
        ],
        'status': ticket.status,
        'status_display': ticket.get_status_display(),
    })


@login_required(login_url='login')
def ticket_send(request, pk):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    ticket = get_object_or_404(Ticket, pk=pk, user=request.user)
    if ticket.status in ('RESOLVED', 'CLOSED'):
        return JsonResponse({'ok': False, 'error': 'Ticket is closed'}, status=400)

    try:
        body = json.loads(request.body)
        message = body.get('message', '').strip()
    except Exception:
        message = request.POST.get('message', '').strip()

    if not message:
        return JsonResponse({'ok': False, 'error': 'Message required'}, status=400)

    msg = TicketMessage.objects.create(
        ticket=ticket, sender=request.user, message=message, is_staff_reply=False
    )
    ticket.staff_unread = True
    if ticket.status == 'RESOLVED':
        ticket.status = 'OPEN'
    ticket.save()

    from main.notifications import send_user_reply_email
    send_user_reply_email(ticket, message)

    return JsonResponse({
        'ok': True,
        'message': {
            'id': msg.id,
            'message': msg.message,
            'is_staff_reply': False,
            'created_at': msg.created_at.strftime('%d %b, %H:%M'),
        }
    })


# ══════════════════════════════════════════════════
# WIDGET (floating chat bubble)
# ══════════════════════════════════════════════════

@login_required(login_url='login')
def widget_state(request):
    ticket = (
        Ticket.objects
        .filter(user=request.user)
        .exclude(status__in=['RESOLVED', 'CLOSED'])
        .order_by('-updated_at')
        .first()
    )
    if not ticket:
        return JsonResponse({'has_ticket': False})

    if ticket.user_unread:
        ticket.user_unread = False
        ticket.save(update_fields=['user_unread'])

    msgs = ticket.messages.select_related('sender').all()
    return JsonResponse({
        'has_ticket': True,
        'ticket_id': ticket.pk,
        'ticket_subject': ticket.subject,
        'ticket_status': ticket.status,
        'ticket_status_display': ticket.get_status_display(),
        'ticket_closed': False,
        'messages': [
            {
                'id': m.id,
                'message': m.message,
                'is_staff_reply': m.is_staff_reply,
                'created_at': m.created_at.strftime('%d %b, %H:%M'),
            }
            for m in msgs
        ],
    })


@login_required(login_url='login')
def widget_create(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)

    try:
        body    = json.loads(request.body)
        subject = body.get('subject', '').strip() or 'Support Request'
        message = body.get('message', '').strip()
        category = body.get('category', 'OTHER')
    except Exception:
        subject  = request.POST.get('subject', 'Support Request').strip()
        message  = request.POST.get('message', '').strip()
        category = request.POST.get('category', 'OTHER')

    if not message:
        return JsonResponse({'ok': False, 'error': 'Message required'}, status=400)

    ticket = Ticket.objects.create(
        user=request.user, subject=subject,
        category=category, staff_unread=True,
    )
    msg = TicketMessage.objects.create(
        ticket=ticket, sender=request.user,
        message=message, is_staff_reply=False,
    )
    from main.notifications import send_ticket_opened_email
    send_ticket_opened_email(ticket, message)

    return JsonResponse({
        'ok': True,
        'ticket_id': ticket.pk,
        'ticket_subject': ticket.subject,
        'ticket_status': ticket.status,
        'ticket_status_display': ticket.get_status_display(),
        'message': {
            'id': msg.id,
            'message': msg.message,
            'is_staff_reply': False,
            'created_at': msg.created_at.strftime('%d %b, %H:%M'),
        },
    })


# ══════════════════════════════════════════════════
# ADMIN / MANAGE
# ══════════════════════════════════════════════════

@login_required(login_url='login')
@staff_required
def manage_dashboard(request):
    User = get_user_model()
    today = timezone.now().date()

    total_users    = User.objects.count()
    today_users    = User.objects.filter(date_joined__date=today).count()

    total_orders   = Order.objects.count()
    today_orders   = Order.objects.filter(created_at__date=today).count()
    pending_orders = Order.objects.filter(status='PENDING').count()

    total_revenue  = Transaction.objects.filter(
        type='CREDIT', description__icontains='confirmed'
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    today_revenue  = Transaction.objects.filter(
        type='CREDIT', description__icontains='confirmed',
        created_at__date=today
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    total_wallet_balance = User.objects.aggregate(
        t=Sum('wallet_balance'))['t'] or Decimal('0')

    open_tickets   = Ticket.objects.filter(status__in=['OPEN', 'IN_PROGRESS']).count()

    recent_users   = User.objects.order_by('-date_joined')[:8]
    recent_orders  = Order.objects.select_related('user').order_by('-created_at')[:10]
    new_tickets    = Ticket.objects.filter(staff_unread=True).select_related('user').order_by('-updated_at')[:6]

    return render(request, 'manage/dashboard.html', {
        'total_users':          total_users,
        'today_users':          today_users,
        'total_orders':         total_orders,
        'today_orders':         today_orders,
        'pending_orders':       pending_orders,
        'total_revenue':        total_revenue,
        'today_revenue':        today_revenue,
        'total_wallet_balance': total_wallet_balance,
        'open_tickets':         open_tickets,
        'recent_users':         recent_users,
        'recent_orders':        recent_orders,
        'new_tickets':          new_tickets,
    })


@login_required(login_url='login')
@staff_required
def manage_users(request):
    User = get_user_model()
    q = request.GET.get('q', '').strip()
    users = User.objects.annotate(order_count=Count('order', distinct=True)).order_by('-date_joined')
    if q:
        users = users.filter(Q(username__icontains=q) | Q(email__icontains=q))
    page = Paginator(users, 25).get_page(request.GET.get('page', 1))
    return render(request, 'manage/users.html', {'page_obj': page, 'query': q})


@login_required(login_url='login')
@staff_required
def manage_user_detail(request, pk):
    User   = get_user_model()
    target = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        if not _is_admin(request.user):
            return redirect('manage-user-detail', pk=pk)
        if action == 'adjust_balance':
            try:
                amount = Decimal(request.POST.get('amount', '0'))
                note   = request.POST.get('note', 'Admin adjustment').strip() or 'Admin adjustment'
                target.wallet_balance = (target.wallet_balance or Decimal('0')) + amount
                target.save(update_fields=['wallet_balance'])
                Transaction.objects.create(
                    user=target,
                    amount=abs(amount),
                    type='CREDIT' if amount >= 0 else 'DEBIT',
                    reference=f'admin-{int(timezone.now().timestamp())}-{pk}',
                    description=f'Admin: {note}',
                )
            except Exception:
                pass
        elif action == 'toggle_active':
            target.is_active = not target.is_active
            target.save(update_fields=['is_active'])
        return redirect('manage-user-detail', pk=pk)

    orders       = Order.objects.filter(user=target).order_by('-created_at')[:20]
    transactions = Transaction.objects.filter(user=target).order_by('-created_at')[:20]
    tickets      = Ticket.objects.filter(user=target).order_by('-updated_at')[:10]
    return render(request, 'manage/user_detail.html', {
        'target': target, 'orders': orders,
        'transactions': transactions, 'tickets': tickets,
    })


@login_required(login_url='login')
@staff_required
def manage_tickets(request):
    status_filter = request.GET.get('status', '')
    q = request.GET.get('q', '').strip()

    tickets = Ticket.objects.select_related('user').order_by('-updated_at')
    if status_filter:
        tickets = tickets.filter(status=status_filter)
    if q:
        tickets = tickets.filter(
            Q(subject__icontains=q) | Q(user__username__icontains=q) | Q(user__email__icontains=q)
        )

    counts = {s: Ticket.objects.filter(status=s).count() for s, _ in Ticket.STATUS_CHOICES}
    counts['ALL'] = Ticket.objects.count()

    page = Paginator(tickets, 25).get_page(request.GET.get('page', 1))
    return render(request, 'manage/tickets.html', {
        'page_obj': page, 'status_filter': status_filter, 'query': q, 'counts': counts,
    })


@login_required(login_url='login')
@staff_required
def manage_ticket_detail(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)

    if ticket.staff_unread:
        ticket.staff_unread = False
        ticket.save(update_fields=['staff_unread'])

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'reply':
            message    = request.POST.get('message', '').strip()
            new_status = request.POST.get('status', ticket.status)
            if message:
                TicketMessage.objects.create(
                    ticket=ticket, sender=request.user,
                    message=message, is_staff_reply=True,
                )
                ticket.user_unread = True
                ticket.status      = new_status
                ticket.save()
        elif action == 'change_meta':
            ticket.status   = request.POST.get('status', ticket.status)
            ticket.priority = request.POST.get('priority', ticket.priority)
            ticket.save()
        return redirect('manage-ticket-detail', pk=pk)

    msgs = ticket.messages.select_related('sender').all()
    return render(request, 'manage/ticket_detail.html', {'ticket': ticket, 'messages': msgs})


@login_required(login_url='login')
@staff_required
def manage_ticket_poll(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    try:
        since_id = int(request.GET.get('since', 0))
    except (TypeError, ValueError):
        since_id = 0

    if ticket.staff_unread:
        ticket.staff_unread = False
        ticket.save(update_fields=['staff_unread'])

    msgs = ticket.messages.filter(id__gt=since_id).select_related('sender')
    return JsonResponse({
        'messages': [
            {
                'id': m.id,
                'sender': m.sender.username,
                'message': m.message,
                'is_staff_reply': m.is_staff_reply,
                'created_at': m.created_at.strftime('%d %b, %H:%M'),
            }
            for m in msgs
        ],
        'status': ticket.status,
        'status_display': ticket.get_status_display(),
    })


@login_required(login_url='login')
@staff_required
def manage_ticket_send(request, pk):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    ticket = get_object_or_404(Ticket, pk=pk)

    try:
        body = json.loads(request.body)
        message    = body.get('message', '').strip()
        new_status = body.get('status', ticket.status)
    except Exception:
        message    = request.POST.get('message', '').strip()
        new_status = request.POST.get('status', ticket.status)

    if not message:
        return JsonResponse({'ok': False, 'error': 'Message required'}, status=400)

    msg = TicketMessage.objects.create(
        ticket=ticket, sender=request.user, message=message, is_staff_reply=True
    )
    ticket.user_unread = True
    ticket.status      = new_status
    ticket.save()

    from main.notifications import send_staff_reply_email
    send_staff_reply_email(ticket, message)

    return JsonResponse({
        'ok': True,
        'message': {
            'id': msg.id,
            'sender': msg.sender.username,
            'message': msg.message,
            'is_staff_reply': True,
            'created_at': msg.created_at.strftime('%d %b, %H:%M'),
        }
    })


@login_required(login_url='login')
@staff_required
def manage_orders(request):
    service_filter = request.GET.get('service', '')
    status_filter  = request.GET.get('status', '')
    q = request.GET.get('q', '').strip()

    orders = Order.objects.select_related('user').order_by('-created_at')
    if service_filter:
        orders = orders.filter(service_type=service_filter)
    if status_filter:
        orders = orders.filter(status=status_filter)
    if q:
        orders = orders.filter(
            Q(user__username__icontains=q) | Q(user__email__icontains=q) | Q(product__icontains=q)
        )

    status_counts = [
        (code, label, Order.objects.filter(status=code).count())
        for code, label in Order.STATUS_CHOICES
    ]
    total_count = Order.objects.count()

    page = Paginator(orders, 25).get_page(request.GET.get('page', 1))
    return render(request, 'manage/orders.html', {
        'page_obj':       page,
        'status_filter':  status_filter,
        'service_filter': service_filter,
        'query':          q,
        'status_counts':  status_counts,
        'total_count':    total_count,
        'service_types':  Order.SERVICE_TYPES,
        'status_choices': Order.STATUS_CHOICES,
    })


@login_required(login_url='login')
@staff_required
def manage_transactions(request):
    type_filter = request.GET.get('type', '')
    q = request.GET.get('q', '').strip()

    txns = Transaction.objects.select_related('user').order_by('-created_at')
    if type_filter:
        txns = txns.filter(type=type_filter)
    if q:
        txns = txns.filter(
            Q(user__username__icontains=q) | Q(user__email__icontains=q) | Q(reference__icontains=q)
        )

    total_credits = Transaction.objects.filter(type='CREDIT').aggregate(t=Sum('amount'))['t'] or Decimal('0')
    total_debits  = Transaction.objects.filter(type='DEBIT').aggregate(t=Sum('amount'))['t'] or Decimal('0')
    net_flow      = total_credits - total_debits

    page = Paginator(txns, 25).get_page(request.GET.get('page', 1))
    return render(request, 'manage/transactions.html', {
        'page_obj':      page,
        'type_filter':   type_filter,
        'query':         q,
        'total_credits': total_credits,
        'total_debits':  total_debits,
        'net_flow':      net_flow,
    })


@login_required(login_url='login')
@admin_required
def manage_agents(request):
    User = get_user_model()
    error = None

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create':
            username  = request.POST.get('username', '').strip()
            email     = request.POST.get('email', '').strip()
            password  = request.POST.get('password', '')
            password2 = request.POST.get('password2', '')
            fname     = request.POST.get('first_name', '').strip()
            lname     = request.POST.get('last_name', '').strip()

            if not username or not email or not password:
                error = 'Username, email, and password are required.'
            elif password != password2:
                error = 'Passwords do not match.'
            elif User.objects.filter(username=username).exists():
                error = f'Username "{username}" is already taken.'
            elif User.objects.filter(email=email).exists():
                error = f'Email "{email}" is already registered.'
            else:
                agent = User.objects.create_user(
                    username=username, email=email, password=password,
                    first_name=fname, last_name=lname,
                    is_agent=True, is_staff=False,
                )
                from main.notifications import send_agent_credentials_email
                send_agent_credentials_email(agent, password)
                return redirect('manage-agents')

        elif action == 'revoke':
            try:
                agent = User.objects.get(pk=request.POST.get('agent_id'), is_agent=True)
                agent.is_agent = False
                agent.save(update_fields=['is_agent'])
            except User.DoesNotExist:
                pass
            return redirect('manage-agents')

        elif action == 'reset_password':
            try:
                agent     = User.objects.get(pk=request.POST.get('agent_id'), is_agent=True)
                new_pass  = request.POST.get('new_password', '').strip()
                new_pass2 = request.POST.get('new_password2', '').strip()
                if not new_pass:
                    error = 'New password cannot be empty.'
                elif new_pass != new_pass2:
                    error = 'Passwords do not match.'
                else:
                    agent.set_password(new_pass)
                    agent.save()
                    return redirect('manage-agents')
            except User.DoesNotExist:
                pass

    agents = User.objects.filter(is_agent=True).order_by('-date_joined')
    return render(request, 'manage/agents.html', {'agents': agents, 'error': error})


@login_required(login_url='login')
@admin_required
def manage_broadcast(request):
    User = get_user_model()
    EMAIL_TYPES = [
        ('newsletter',     'Newsletter'),
        ('service_update', 'Service Update'),
        ('new_feature',    'New Feature'),
        ('promotion',      'Promotion'),
        ('holiday',        'Holiday Notice'),
        ('maintenance',    'Maintenance'),
    ]
    sent = False
    error = ''
    preview_html = ''
    form_data = {}

    if request.method == 'POST':
        action     = request.POST.get('action')
        subject    = request.POST.get('subject', '').strip()
        message    = request.POST.get('message', '').strip()
        email_type = request.POST.get('email_type', 'newsletter')
        audience   = request.POST.get('audience', 'all')
        cta_text   = request.POST.get('cta_text', '').strip()
        cta_url    = request.POST.get('cta_url', '').strip()

        form_data = {
            'subject': subject, 'message': message, 'email_type': email_type,
            'audience': audience, 'cta_text': cta_text, 'cta_url': cta_url,
        }

        if not subject or not message:
            error = 'Subject and message are required.'
        else:
            qs = User.objects.filter(is_active=True, is_staff=False, is_superuser=False)
            if audience == 'agents_excluded':
                qs = qs.filter(is_agent=False)

            if action == 'preview':
                from main.notifications import TYPE_BADGE, _wrap, _btn
                color, label = TYPE_BADGE.get(email_type, ('#7c3aed', 'Announcement'))
                paragraphs = ''.join(
                    f'<p style="margin:0 0 14px;font-size:15px;color:#52525b;line-height:1.7;">{p.strip()}</p>'
                    for p in message.split('\n') if p.strip()
                )
                cta_block = _btn(cta_text, cta_url) if cta_text and cta_url else ''
                badge = (f'<span style="display:inline-block;background:{color};color:#fff;'
                         f'font-size:11px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;'
                         f'padding:3px 10px;border-radius:20px;margin-bottom:16px;">{label}</span>')
                inner = f'{badge}<h2 style="margin:0 0 16px;font-size:22px;font-weight:800;color:#18181b;">{subject}</h2>{paragraphs}{cta_block}'
                preview_html = _wrap(inner, preheader=subject)

            elif action == 'send':
                users = list(qs)
                from main.notifications import send_broadcast_email
                send_broadcast_email(users, subject, message, email_type, cta_text, cta_url)
                sent = True

    total_users = User.objects.filter(is_active=True, is_staff=False, is_superuser=False).count()
    return render(request, 'manage/broadcast.html', {
        'email_types': EMAIL_TYPES,
        'sent': sent,
        'error': error,
        'preview_html': preview_html,
        'form_data': form_data,
        'total_users': total_users,
    })


# ── Blog management ────────────────────────────────────────────────────────────

@login_required(login_url='login')
@staff_required
def manage_blog_list(request):
    from blog.models import Post
    posts = Post.objects.order_by('-created_at')
    return render(request, 'manage/blog_list.html', {'posts': posts})


@login_required(login_url='login')
@staff_required
def manage_blog_create(request):
    from blog.models import Post
    from django.utils.text import slugify
    error = ''
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        slug = request.POST.get('slug', '').strip() or slugify(title)
        excerpt = request.POST.get('excerpt', '').strip()
        body = request.POST.get('body', '').strip()
        meta_description = request.POST.get('meta_description', '').strip()
        is_published = request.POST.get('is_published') == '1'
        if not title or not body:
            error = 'Title and body are required.'
        elif Post.objects.filter(slug=slug).exists():
            error = f'A post with slug "{slug}" already exists.'
        else:
            post = Post.objects.create(
                title=title, slug=slug, excerpt=excerpt, body=body,
                meta_description=meta_description, is_published=is_published,
            )
            return redirect('manage-blog-edit', pk=post.pk)
    return render(request, 'manage/blog_form.html', {'error': error, 'post': None})


@login_required(login_url='login')
@staff_required
def manage_blog_edit(request, pk):
    from blog.models import Post
    post = get_object_or_404(Post, pk=pk)
    error = ''
    saved = False
    if request.method == 'POST':
        post.title = request.POST.get('title', '').strip()
        post.slug = request.POST.get('slug', '').strip()
        post.excerpt = request.POST.get('excerpt', '').strip()
        post.body = request.POST.get('body', '').strip()
        post.meta_description = request.POST.get('meta_description', '').strip()
        post.is_published = request.POST.get('is_published') == '1'
        if not post.title or not post.body:
            error = 'Title and body are required.'
        elif Post.objects.filter(slug=post.slug).exclude(pk=pk).exists():
            error = f'Another post already uses the slug "{post.slug}".'
        else:
            post.save()
            saved = True
    return render(request, 'manage/blog_form.html', {'post': post, 'error': error, 'saved': saved})


@login_required(login_url='login')
@staff_required
def manage_blog_toggle(request, pk):
    from blog.models import Post
    if request.method == 'POST':
        post = get_object_or_404(Post, pk=pk)
        post.is_published = not post.is_published
        post.save()
    return redirect('manage-blog-list')


@login_required(login_url='login')
@staff_required
def manage_blog_delete(request, pk):
    from blog.models import Post
    if request.method == 'POST':
        get_object_or_404(Post, pk=pk).delete()
    return redirect('manage-blog-list')