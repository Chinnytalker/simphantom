from django.db import models
from django.conf import settings


class Ticket(models.Model):
    CATEGORY_CHOICES = [
        ('PAYMENT',   'Payment Issue'),
        ('ORDER',     'Order Problem'),
        ('ACCOUNT',   'Account Issue'),
        ('TECHNICAL', 'Technical Problem'),
        ('OTHER',     'Other'),
    ]
    STATUS_CHOICES = [
        ('OPEN',        'Open'),
        ('IN_PROGRESS', 'In Progress'),
        ('RESOLVED',    'Resolved'),
        ('CLOSED',      'Closed'),
    ]
    PRIORITY_CHOICES = [
        ('LOW',    'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH',   'High'),
    ]

    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tickets')
    subject    = models.CharField(max_length=200)
    category   = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='OTHER')
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    priority   = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='MEDIUM')
    user_unread  = models.BooleanField(default=False)  # True when staff replies
    staff_unread = models.BooleanField(default=True)   # True on new ticket or user reply
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"#{self.pk} {self.subject}"


class TicketMessage(models.Model):
    ticket        = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='messages')
    sender        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message       = models.TextField()
    is_staff_reply = models.BooleanField(default=False)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Ticket #{self.ticket_id} by {self.sender.username}"
