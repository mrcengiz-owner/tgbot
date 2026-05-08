from django.contrib import admin
from .models import TelegramGroup, MessageTemplate, MessageLog, Settings, ScheduledTask


@admin.register(TelegramGroup)
class TelegramGroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'chat_id', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'chat_id']
    ordering = ['-created_at']


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'content']
    ordering = ['-created_at']


@admin.register(MessageLog)
class MessageLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'status', 'sent_count', 'failed_count', 'created_at', 'sent_at']
    list_filter = ['status', 'created_at']
    search_fields = ['message_content']
    ordering = ['-created_at']
    readonly_fields = ['created_at']


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    list_display = ['key', 'value', 'updated_at']
    search_fields = ['key', 'value']
    ordering = ['key']


@admin.register(ScheduledTask)
class ScheduledTaskAdmin(admin.ModelAdmin):
    list_display = ['name', 'template', 'interval_minutes', 'is_active', 'last_run', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'template__name']
    ordering = ['-created_at']
    filter_horizontal = ['groups']
