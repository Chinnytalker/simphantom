from django.contrib.auth.models import AbstractUser
from django.db import models





class User(AbstractUser):
    email = models.EmailField(unique=True)
    wallet_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_agent = models.BooleanField(default=False)

    def __str__(self):
        return self.username
