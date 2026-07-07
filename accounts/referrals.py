"""
Referral system: users share a link, and when someone they invited makes their
first funded deposit, the referrer earns wallet credit.

The reward is a small percentage of the referee's first deposit (capped), which
keeps it abuse-resistant: self-referring with tiny deposits can never net more
than it costs. Everything is idempotent so a referrer is credited exactly once
per invited user.
"""
import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction as db_transaction
from django.db.models import F
from django.contrib.auth import get_user_model

logger = logging.getLogger('accounts')

SESSION_KEY = 'referral_code'

# 5% of the referee's first deposit, capped — tune here or via settings.
REFERRAL_BONUS_PCT = Decimal(str(getattr(settings, 'REFERRAL_BONUS_PCT', '0.05')))
REFERRAL_BONUS_CAP = Decimal(str(getattr(settings, 'REFERRAL_BONUS_CAP', '500')))


def capture_referral(request):
    """Remember a ?ref=CODE from any landing page in the session until signup."""
    code = (request.GET.get('ref') or '').strip().upper()
    if code and request.session.get(SESSION_KEY) != code:
        request.session[SESSION_KEY] = code


def apply_referral(request, user):
    """
    Link a freshly-created user to their referrer using the captured code.
    Safe for both the email signup view and the Google (allauth) adapter.
    """
    code = (request.session.get(SESSION_KEY) or '').strip().upper()
    if not code or user.referred_by_id:
        return
    User = get_user_model()
    referrer = User.objects.filter(referral_code=code).exclude(pk=user.pk).first()
    if referrer:
        user.referred_by = referrer
        user.save(update_fields=['referred_by'])
        logger.info('Referral linked: user=%s referred_by=%s', user.pk, referrer.pk)
    request.session.pop(SESSION_KEY, None)


def award_referral(referee_id, deposit_amount):
    """
    Reward the referrer for `referee_id`'s first funded deposit. Idempotent:
    the referral_bonus_awarded flag is flipped with a conditional UPDATE, so
    concurrent deposit confirmations can never pay the bonus twice.
    Returns the awarded amount (Decimal) or None.
    """
    User = get_user_model()
    try:
        referee = User.objects.get(pk=referee_id)
    except User.DoesNotExist:
        return None

    if not referee.referred_by_id or referee.referral_bonus_awarded:
        return None

    bonus = min(Decimal(str(deposit_amount)) * REFERRAL_BONUS_PCT, REFERRAL_BONUS_CAP)
    bonus = bonus.quantize(Decimal('0.01'))
    if bonus <= 0:
        return None

    from orders.models import Transaction
    with db_transaction.atomic():
        claimed = User.objects.filter(
            pk=referee_id, referral_bonus_awarded=False, referred_by__isnull=False
        ).update(referral_bonus_awarded=True)
        if not claimed:
            return None
        User.objects.filter(pk=referee.referred_by_id).update(
            wallet_balance=F('wallet_balance') + bonus
        )
        Transaction.objects.get_or_create(
            reference=f'REFERRAL-{referee_id}',
            defaults={
                'user_id': referee.referred_by_id,
                'amount': bonus,
                'type': 'CREDIT',
                'status': 'COMPLETED',
                'description': f'Referral bonus — {referee.username} joined and funded their wallet',
            },
        )
    logger.info('Referral bonus ₦%s to user=%s for referee=%s',
                bonus, referee.referred_by_id, referee_id)
    return bonus
