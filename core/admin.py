from django.contrib import admin
from django.utils.html import format_html
from .models import TelegramGroup, MessageTemplate, MessageLog, Settings, ScheduledTask


@admin.register(TelegramGroup)
class TelegramGroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'chat_id', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'chat_id']
    ordering = ['-created_at']
    list_editable = ['is_active']
    
    fieldsets = (
        ('Grup Bilgileri', {
            'fields': ('name', 'chat_id', 'description')
        }),
        ('Durum', {
            'fields': ('is_active',)
        }),
    )


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'content']
    ordering = ['-created_at']
    list_editable = ['is_active']
    
    fieldsets = (
        ('Şablon Bilgileri', {
            'fields': ('name', 'content', 'description')
        }),
        ('Durum', {
            'fields': ('is_active',)
        }),
    )


@admin.register(MessageLog)
class MessageLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'status_display', 'sent_count', 'failed_count', 'created_at', 'sent_at']
    list_filter = ['status', 'created_at']
    search_fields = ['message_content']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'message_content']
    
    def status_display(self, obj):
        colors = {
            'success': '#10b981',
            'failed': '#ef4444',
            'pending': '#f59e0b'
        }
        return format_html(
            '<span style="padding: 4px 10px; border-radius: 6px; background: {}; color: white; font-weight: 600;">{}</span>',
            colors.get(obj.status, '#64748b'),
            obj.get_status_display()
        )
    status_display.short_description = 'Durum'


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    list_display = ['key', 'value', 'updated_at']
    search_fields = ['key', 'value']
    ordering = ['key']


@admin.register(ScheduledTask)
class ScheduledTaskAdmin(admin.ModelAdmin):
    list_display = ['name', 'template', 'interval_display', 'is_active', 'last_run', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'template__name']
    ordering = ['-created_at']
    list_editable = ['is_active']
    filter_horizontal = ['groups']
    
    fieldsets = (
        ('Görev Bilgileri', {
            'fields': ('name', 'template', 'interval_minutes')
        }),
        ('Hedef Gruplar', {
            'fields': ('groups',)
        }),
        ('Durum', {
            'fields': ('is_active', 'last_run')
        }),
    )
    
    def interval_display(self, obj):
        return f"{obj.interval_minutes} dk"
    interval_display.short_description = 'Aralık'