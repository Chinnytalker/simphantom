from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model


class SocialAccountAdapter(DefaultSocialAccountAdapter):

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        if not user.username and user.email:
            User = get_user_model()
            base = user.email.split('@')[0]
            username = base
            n = 1
            while User.objects.filter(username=username).exists():
                username = f"{base}{n}"
                n += 1
            user.username = username
        return user

    def save_user(self, request, sociallogin, form=None):
        is_new = not sociallogin.is_existing
        user = super().save_user(request, sociallogin, form)
        if is_new:
            try:
                from main.notifications import send_welcome_email
                send_welcome_email(user)
            except Exception:
                pass
        return user
