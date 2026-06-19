def ticket_notifications(request):
    if not request.user.is_authenticated:
        return {}
    try:
        from .models import Ticket
        is_staff_member = (
            request.user.is_staff or
            request.user.is_superuser or
            getattr(request.user, 'is_agent', False)
        )
        if is_staff_member:
            return {'staff_unread_count': Ticket.objects.filter(staff_unread=True).count()}
        return {'user_unread_count': Ticket.objects.filter(user=request.user, user_unread=True).count()}
    except Exception:
        return {}
