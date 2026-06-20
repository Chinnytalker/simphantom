import logging
import threading
from datetime import date
from django.core.mail import EmailMultiAlternatives
from django.conf import settings

logger = logging.getLogger(__name__)

BRAND       = 'SimPhantom'
ADMIN_EMAIL = getattr(settings, 'ADMIN_NOTIFY_EMAIL', 'simphantom1@gmail.com')


# ── Internal helpers ──────────────────────────────────────────────────────────

def _from():
    return getattr(settings, 'DEFAULT_FROM_EMAIL', f'{BRAND} <noreply@simphantom.com>')


def _send(subject, text, html, recipients):
    """Fire-and-forget: send email in a daemon thread so the request never waits."""
    if not recipients or not getattr(settings, 'EMAIL_HOST_USER', ''):
        return  # email not configured — skip silently

    def _worker():
        import socket
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(20)
        try:
            msg = EmailMultiAlternatives(subject, text, _from(), recipients)
            msg.attach_alternative(html, 'text/html')
            msg.send(fail_silently=False)
            logger.info('[%s] Email sent to %s: %s', BRAND, recipients, subject)
        except Exception as exc:
            logger.error('[%s] Email send failed to %s: %s', BRAND, recipients, exc)
        finally:
            socket.setdefaulttimeout(old_timeout)

    threading.Thread(target=_worker, daemon=True).start()


def _wrap(inner_html, *, preheader='', footer_note=''):
    """Wrap content in a consistent branded email shell."""
    year = date.today().year
    note = footer_note or f'You received this email because you have an account with {BRAND}.'
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{BRAND}</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
{f'<span style="display:none;max-height:0;overflow:hidden;">{preheader}</span>' if preheader else ''}
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:32px 16px;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

      <!-- Header -->
      <tr><td style="background:#18181b;border-radius:16px 16px 0 0;padding:24px 32px;text-align:center;">
        <span style="color:#fff;font-size:22px;font-weight:800;letter-spacing:-0.5px;">{BRAND}</span>
      </td></tr>

      <!-- Body -->
      <tr><td style="background:#ffffff;padding:32px 32px 24px;border-left:1px solid #e4e4e7;border-right:1px solid #e4e4e7;">
        {inner_html}
      </td></tr>

      <!-- Footer -->
      <tr><td style="background:#f4f4f5;border-radius:0 0 16px 16px;padding:20px 32px;text-align:center;border:1px solid #e4e4e7;border-top:none;">
        <p style="margin:0;font-size:12px;color:#71717a;">
          &copy; {year} {BRAND}. All rights reserved.<br/>
          {note}
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>'''


def _row(label, value):
    return f'''<tr>
      <td style="padding:8px 0;font-size:13px;color:#71717a;width:40%;">{label}</td>
      <td style="padding:8px 0;font-size:13px;color:#18181b;font-weight:600;">{value}</td>
    </tr>'''


def _detail_table(rows):
    inner = ''.join(_row(l, v) for l, v in rows)
    return f'''<table width="100%" cellpadding="0" cellspacing="0"
        style="background:#f9f9fb;border:1px solid #e4e4e7;border-radius:12px;padding:16px 20px;margin:20px 0;">
      {inner}
    </table>'''


def _btn(text, href):
    return f'''<div style="text-align:center;margin:24px 0 8px;">
      <a href="{href}" style="background:#7c3aed;color:#fff;text-decoration:none;
         font-size:14px;font-weight:700;padding:14px 32px;border-radius:10px;display:inline-block;">
        {text}
      </a>
    </div>'''


# ── Public email functions ────────────────────────────────────────────────────

def send_welcome_email(user):
    name = user.first_name or user.username
    subject = f'Welcome to {BRAND}! Your account is ready'
    preheader = f'Hi {name}, your {BRAND} account has been created.'

    inner = f'''
    <h2 style="margin:0 0 8px;font-size:22px;font-weight:800;color:#18181b;">Welcome, {name}! 🎉</h2>
    <p style="margin:0 0 20px;font-size:15px;color:#52525b;line-height:1.6;">
      Your <strong>{BRAND}</strong> account is ready. You can now top up your wallet and
      access virtual numbers, OTP services, eSIM plans, residential proxies, bulk SMS, and more.
    </p>
    {_detail_table([
        ('Username', user.username),
        ('Email', user.email),
        ('Account type', 'Standard'),
    ])}
    <p style="margin:16px 0 0;font-size:13px;color:#71717a;">
      Keep your login credentials safe. If you didn't create this account, please contact support immediately.
    </p>'''

    text = f'Welcome to {BRAND}, {name}!\n\nUsername: {user.username}\nEmail: {user.email}\n\nTop up your wallet and start using our services.'
    _send(subject, text, _wrap(inner, preheader=preheader), [user.email])


def send_deposit_confirmed_email(user, amount, new_balance):
    name = user.first_name or user.username
    subject = f'{BRAND} — Wallet top-up confirmed ₦{amount:,.0f}'
    preheader = f'₦{amount:,.0f} has been added to your {BRAND} wallet.'

    inner = f'''
    <h2 style="margin:0 0 8px;font-size:22px;font-weight:800;color:#18181b;">Deposit Confirmed ✅</h2>
    <p style="margin:0 0 20px;font-size:15px;color:#52525b;line-height:1.6;">
      Hi {name}, your wallet has been topped up successfully.
    </p>
    {_detail_table([
        ('Amount deposited', f'₦{amount:,.2f}'),
        ('New wallet balance', f'₦{new_balance:,.2f}'),
        ('Payment method', 'Paystack'),
        ('Status', '✅ Confirmed'),
    ])}
    <p style="margin:16px 0 0;font-size:13px;color:#71717a;">
      Your funds are available immediately. If you did not initiate this payment, contact support.
    </p>'''

    text = f'Hi {name},\n\nYour wallet has been topped up.\nAmount: ₦{amount:,.2f}\nNew balance: ₦{new_balance:,.2f}'
    _send(subject, text, _wrap(inner, preheader=preheader), [user.email])


def send_purchase_email(user, service_name, detail_rows, order_id, amount):
    """
    Generic service purchase confirmation.
    detail_rows: list of (label, value) tuples specific to the service.
    """
    name = user.first_name or user.username
    subject = f'{BRAND} — {service_name} purchase confirmed'
    preheader = f'Your {service_name} order #{order_id} is ready.'

    rows = [('Order #', str(order_id)), ('Service', service_name)] + list(detail_rows) + [('Amount charged', f'₦{amount:,.2f}')]

    inner = f'''
    <h2 style="margin:0 0 8px;font-size:22px;font-weight:800;color:#18181b;">Order Confirmed ✅</h2>
    <p style="margin:0 0 20px;font-size:15px;color:#52525b;line-height:1.6;">
      Hi {name}, your <strong>{service_name}</strong> purchase was successful. Details below:
    </p>
    {_detail_table(rows)}
    <p style="margin:16px 0 0;font-size:13px;color:#71717a;">
      Log into your dashboard to manage this order. Contact support if you have any issues.
    </p>'''

    text = f'Hi {name},\n\nYour {service_name} order #{order_id} is confirmed.\nAmount: ₦{amount:,.2f}\n\nView your dashboard for full details.'
    _send(subject, text, _wrap(inner, preheader=preheader), [user.email])


def send_ticket_opened_email(ticket, first_message):
    """Notify admin when a user opens a new support ticket."""
    subject = f'[{BRAND} Support] New ticket #{ticket.pk} — {ticket.subject}'

    inner = f'''
    <h2 style="margin:0 0 8px;font-size:20px;font-weight:800;color:#18181b;">New Support Ticket</h2>
    {_detail_table([
        ('Ticket #', str(ticket.pk)),
        ('Subject', ticket.subject),
        ('Category', ticket.get_category_display()),
        ('Priority', ticket.priority),
        ('From', f'{ticket.user.username} ({ticket.user.email})'),
    ])}
    <div style="background:#f9f9fb;border-left:4px solid #7c3aed;border-radius:0 8px 8px 0;padding:14px 18px;margin:16px 0;">
      <p style="margin:0;font-size:14px;color:#18181b;line-height:1.6;">{first_message}</p>
    </div>'''

    text = f'New ticket #{ticket.pk}: {ticket.subject}\nFrom: {ticket.user.username} ({ticket.user.email})\n\n{first_message}'
    _send(subject, text, _wrap(inner), [ADMIN_EMAIL])


def send_user_reply_email(ticket, reply_message):
    """Notify admin when a user replies to an existing ticket."""
    subject = f'[{BRAND} Support] Reply on ticket #{ticket.pk} — {ticket.subject}'

    inner = f'''
    <h2 style="margin:0 0 8px;font-size:20px;font-weight:800;color:#18181b;">User Replied to Ticket #{ticket.pk}</h2>
    {_detail_table([
        ('Subject', ticket.subject),
        ('Status', ticket.get_status_display()),
        ('From', f'{ticket.user.username} ({ticket.user.email})'),
    ])}
    <div style="background:#f9f9fb;border-left:4px solid #7c3aed;border-radius:0 8px 8px 0;padding:14px 18px;margin:16px 0;">
      <p style="margin:0;font-size:14px;color:#18181b;line-height:1.6;">{reply_message}</p>
    </div>'''

    text = f'Reply on ticket #{ticket.pk} from {ticket.user.username}:\n\n{reply_message}'
    _send(subject, text, _wrap(inner), [ADMIN_EMAIL])


def send_staff_reply_email(ticket, reply_message):
    """Notify the user when support staff replies to their ticket."""
    name = ticket.user.first_name or ticket.user.username
    subject = f'[{BRAND} Support] Update on your ticket #{ticket.pk}'
    preheader = f'Support has replied to your ticket: {ticket.subject}'

    inner = f'''
    <h2 style="margin:0 0 8px;font-size:20px;font-weight:800;color:#18181b;">Support Replied to Your Ticket</h2>
    <p style="margin:0 0 16px;font-size:15px;color:#52525b;">Hi {name}, the support team has responded to your ticket.</p>
    {_detail_table([
        ('Ticket #', str(ticket.pk)),
        ('Subject', ticket.subject),
        ('Status', ticket.get_status_display()),
    ])}
    <div style="background:#f9f9fb;border-left:4px solid #7c3aed;border-radius:0 8px 8px 0;padding:14px 18px;margin:16px 0;">
      <p style="margin:0 0 4px;font-size:11px;font-weight:600;color:#71717a;text-transform:uppercase;">Support reply</p>
      <p style="margin:0;font-size:14px;color:#18181b;line-height:1.6;">{reply_message}</p>
    </div>
    <p style="margin:16px 0 0;font-size:13px;color:#71717a;">
      Log in to your account to continue the conversation.
    </p>'''

    text = f'Hi {name},\n\nSupport has replied to your ticket #{ticket.pk}:\n\n{reply_message}\n\nLog in to reply.'
    _send(subject, text, _wrap(inner, preheader=preheader), [ticket.user.email])


def send_password_reset_email(user, reset_url):
    name = user.first_name or user.username
    subject = 'Reset your SimPhantom password'
    preheader = 'Reset your SimPhantom password — link valid for 24 hours.'

    inner = f'''
    <h2 style="margin:0 0 8px;font-size:22px;font-weight:800;color:#18181b;">Reset your password</h2>
    <p style="margin:0 0 20px;font-size:15px;color:#52525b;line-height:1.6;">
      Hi {name}, we received a request to reset the password on your <strong>{BRAND}</strong> account.
      Click the button below to choose a new password. This link is valid for <strong>24 hours</strong>.
    </p>
    {_btn("Reset Password", reset_url)}
    <p style="margin:20px 0 0;font-size:13px;color:#71717a;line-height:1.6;">
      If the button doesn't work, copy and paste this link into your browser:<br/>
      <a href="{reset_url}" style="color:#7c3aed;word-break:break-all;">{reset_url}</a>
    </p>
    <div style="background:#fef9c3;border:1px solid #fde047;border-radius:10px;padding:12px 16px;margin:20px 0 0;">
      <p style="margin:0;font-size:13px;color:#713f12;">
        If you didn't request a password reset, ignore this email. Your password will not change.
      </p>
    </div>'''

    text = f'Hi {name},\n\nReset your SimPhantom password by visiting:\n{reset_url}\n\nThis link is valid for 24 hours. If you didn\'t request this, ignore this email.'
    _send(subject, text, _wrap(inner, preheader=preheader,
          footer_note='You received this email because a password reset was requested for your SimPhantom account.'),
          [user.email])


def send_agent_credentials_email(agent, plain_password):
    """Send login credentials to a newly created support agent."""
    name = agent.first_name or agent.username
    subject = f'Your {BRAND} support team account'
    preheader = f'Welcome to the {BRAND} support team, {name}!'

    inner = f'''
    <h2 style="margin:0 0 8px;font-size:22px;font-weight:800;color:#18181b;">You've been added to the support team 👋</h2>
    <p style="margin:0 0 20px;font-size:15px;color:#52525b;line-height:1.6;">
      Hi {name}, an admin has created a support agent account for you on <strong>{BRAND}</strong>.
      Use the credentials below to log in and start handling support tickets.
    </p>
    {_detail_table([
        ('Username', agent.username),
        ('Email', agent.email),
        ('Temporary password', plain_password),
        ('Role', 'Support Agent'),
    ])}
    <div style="background:#fef9c3;border:1px solid #fde047;border-radius:10px;padding:12px 16px;margin:16px 0;">
      <p style="margin:0;font-size:13px;color:#713f12;">
        ⚠️ <strong>Change your password</strong> after your first login. Keep these credentials private.
      </p>
    </div>
    <p style="margin:0;font-size:13px;color:#71717a;">
      As a support agent you can view and reply to customer tickets, view orders, and manage transactions.
      You cannot adjust wallet balances or change account status — those actions require admin access.
    </p>'''

    text = f'Hi {name},\n\nWelcome to the {BRAND} support team!\n\nUsername: {agent.username}\nPassword: {plain_password}\n\nPlease change your password after logging in.'
    _send(subject, text, _wrap(inner, preheader=preheader,
          footer_note=f'You received this email because an admin added you as a support agent on {BRAND}.'),
          [agent.email])
