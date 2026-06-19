from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display  = ('username', 'email', 'wallet_balance', 'is_agent', 'is_staff', 'date_joined')
    list_filter   = ('is_staff', 'is_agent', 'is_active')
    search_fields = ('username', 'email')
    ordering      = ('-date_joined',)
    fieldsets     = UserAdmin.fieldsets + (
        ('SimPhantom', {'fields': ('wallet_balance', 'is_agent')}),
    )
