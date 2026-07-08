from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameBackend(ModelBackend):
    """Authenticate with either username or email, case-insensitively."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        UserModel = get_user_model()
        identifier = username.strip()
        users = UserModel.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        )
        user = users.order_by('id').first()
        if user is None:
            # Run the hasher anyway so response timing doesn't reveal
            # whether the account exists.
            UserModel().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
