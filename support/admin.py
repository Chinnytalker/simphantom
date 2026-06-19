from django.contrib import admin
from .models import Ticket, TicketMessage


class TicketMessageInline(admin.TabularInline):
    model   = TicketMessage
    extra   = 0
    readonly_fields = ('sender', 'created_at')


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display  = ('id', 'user', 'subject', 'category', 'status', 'priority', 'created_at')
    list_filter   = ('status', 'category', 'priority')
    search_fields = ('user__username', 'user__email', 'subject')
    ordering      = ('-updated_at',)
    readonly_fields = ('created_at', 'updated_at')
    inlines       = [TicketMessageInline]
