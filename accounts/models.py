import secrets

from django.contrib.auth.models import AbstractUser
from django.db import models


def _generate_referral_code():
    # Unambiguous alphabet (no O/0/I/1) — easy to read and share aloud.
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return ''.join(secrets.choice(alphabet) for _ in range(8))


class User(AbstractUser):
    email = models.EmailField(unique=True)
    wallet_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_agent = models.BooleanField(default=False)

    # ── Referrals ──────────────────────────────────────────────────────────
    referral_code = models.CharField(max_length=12, unique=True, blank=True, null=True)
    referred_by = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='referrals'
    )
    # Guard so a referrer is rewarded at most once per referred user.
    referral_bonus_awarded = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.referral_code:
            code = _generate_referral_code()
            while User.objects.filter(referral_code=code).exists():
                code = _generate_referral_code()
            self.referral_code = code
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username
