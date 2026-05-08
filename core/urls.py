from django.urls import path
from . import views
from webhook_bot import webhook, set_webhook, delete_webhook

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('webhook/', webhook, name='webhook'),
    path('webhook/set/', set_webhook, name='set_webhook'),
    path('webhook/delete/', delete_webhook, name='delete_webhook'),
    path('gruplar/', views.group_list, name='groups'),
    path('gruplar/ekle/', views.group_add, name='group_add'),
    path('gruplar/sil/<int:pk>/', views.group_delete, name='group_delete'),
    path('gruplar/durum/<int:pk>/', views.group_toggle, name='group_toggle'),
    path('ayarlar/', views.settings_view, name='settings'),
    path('sablonlar/', views.templates, name='templates'),
    path('sablonlar/ekle/', views.template_add, name='template_add'),
    path('sablonlar/duzenle/<int:pk>/', views.template_edit, name='template_edit'),
    path('sablonlar/sil/<int:pk>/', views.template_delete, name='template_delete'),
    path('gonder/', views.send_message_view, name='send_message'),
    path('gonder/gonder/', views.send_message, name='send'),
    path('api/logs/', views.get_logs, name='get_logs'),
    path('api/template/<int:pk>/', views.get_template, name='get_template'),
]
