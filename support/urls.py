from django.urls import path
from . import views

urlpatterns = [
    # Widget
    path('support/widget/',                       views.widget_state,           name='widget-state'),
    path('support/widget/create/',                views.widget_create,          name='widget-create'),
    # User support
    path('support/',                              views.support_list,           name='support'),
    path('support/new/',                          views.create_ticket,          name='create-ticket'),
    path('support/ticket/<int:pk>/',              views.ticket_detail,          name='ticket-detail'),
    path('support/ticket/<int:pk>/poll/',         views.ticket_poll,            name='ticket-poll'),
    path('support/ticket/<int:pk>/send/',         views.ticket_send,            name='ticket-send'),
    # Admin manage
    path('manage/',                               views.manage_dashboard,       name='manage-dashboard'),
    path('manage/users/',                         views.manage_users,           name='manage-users'),
    path('manage/users/<int:pk>/',                views.manage_user_detail,     name='manage-user-detail'),
    path('manage/orders/',                        views.manage_orders,          name='manage-orders'),
    path('manage/transactions/',                  views.manage_transactions,    name='manage-transactions'),
    path('manage/tickets/',                       views.manage_tickets,         name='manage-tickets'),
    path('manage/tickets/<int:pk>/',              views.manage_ticket_detail,   name='manage-ticket-detail'),
    path('manage/tickets/<int:pk>/poll/',         views.manage_ticket_poll,     name='manage-ticket-poll'),
    path('manage/tickets/<int:pk>/send/',         views.manage_ticket_send,     name='manage-ticket-send'),
    path('manage/agents/',                        views.manage_agents,          name='manage-agents'),
    path('manage/broadcast/',                     views.manage_broadcast,       name='manage-broadcast'),
    # Blog
    path('manage/blog/',                          views.manage_blog_list,       name='manage-blog-list'),
    path('manage/blog/new/',                      views.manage_blog_create,     name='manage-blog-create'),
    path('manage/blog/<int:pk>/edit/',            views.manage_blog_edit,       name='manage-blog-edit'),
    path('manage/blog/<int:pk>/toggle/',          views.manage_blog_toggle,     name='manage-blog-toggle'),
    path('manage/blog/<int:pk>/delete/',          views.manage_blog_delete,     name='manage-blog-delete'),
]