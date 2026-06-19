from django.contrib import admin
from .models import Order, Transaction


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display  = ('id', 'user', 'service_type', 'product', 'status', 'amount_charged', 'created_at')
    list_filter   = ('service_type', 'status')
    search_fields = ('user__username', 'user__email', 'product', 'phone', 'email')
    ordering      = ('-created_at',)
    readonly_fields = ('created_at',)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display  = ('id', 'user', 'type', 'amount', 'reference', 'created_at')
    list_filter   = ('type',)
    search_fields = ('user__username', 'user__email', 'reference')
    ordering      = ('-created_at',)
    readonly_fields = ('created_at',)
