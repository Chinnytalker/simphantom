from django.contrib import admin
from .models import Order, Transaction, ProviderStats


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display  = ('id', 'user', 'service_type', 'product', 'status', 'amount_charged', 'created_at')
    list_filter   = ('service_type', 'status')
    search_fields = ('user__username', 'user__email', 'product', 'phone', 'email')
    ordering      = ('-created_at',)
    readonly_fields = ('created_at',)


@admin.register(ProviderStats)
class ProviderStatsAdmin(admin.ModelAdmin):
    list_display  = ('provider', 'product', 'country', 'total_orders', 'successful', 'rate', 'updated_at')
    list_filter   = ('provider',)
    search_fields = ('product', 'country')
    ordering      = ('-total_orders',)

    @admin.display(description='Success rate')
    def rate(self, obj):
        return f"{obj.success_rate:.0%}"


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display  = ('id', 'user', 'type', 'amount', 'reference', 'created_at')
    list_filter   = ('type',)
    search_fields = ('user__username', 'user__email', 'reference')
    ordering      = ('-created_at',)
    readonly_fields = ('created_at',)
