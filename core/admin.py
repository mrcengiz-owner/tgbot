from django.contrib import admin
from django.utils.html import format_html
from .models import (
    TelegramGroup,
    MessageTemplate,
    MessageLog,
    Settings,
    ScheduledTask,
    TxTracker,
    TxRateCache,
)


@admin.register(TelegramGroup)
class TelegramGroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'chat_id', 'is_active', 'tx_tracker_enabled', 'created_at']
    list_filter = ['is_active', 'tx_tracker_enabled', 'created_at']
    search_fields = ['name', 'chat_id']
    ordering = ['-created_at']
    list_editable = ['is_active', 'tx_tracker_enabled']

    fieldsets = (
        ('Grup Bilgileri', {
            'fields': ('name', 'chat_id', 'description')
        }),
        ('Özellikler', {
            'fields': ('is_active', 'tx_tracker_enabled')
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


@admin.register(TxTracker)
class TxTrackerAdmin(admin.ModelAdmin):
    list_display = [
        'tx_hash_short', 'detected_chain', 'asset_symbol', 'amount',
        'try_rate', 'try_value', 'status', 'group', 'created_at',
    ]
    list_filter = ['status', 'detected_chain', 'asset_symbol', 'created_at']
    search_fields = ['tx_hash', 'from_address', 'to_address', 'group__name']
    readonly_fields = [
        'tx_hash', 'detected_chain', 'asset_symbol', 'amount',
        'from_address', 'to_address', 'try_rate', 'try_value',
        'rate_source', 'explorer_url', 'group', 'message_id',
        'status', 'raw_payload', 'error_message',
        'created_at', 'resolved_at',
    ]
    ordering = ['-created_at']
    date_hierarchy = 'created_at'

    def tx_hash_short(self, obj):
        return f"{obj.tx_hash[:10]}…{obj.tx_hash[-6:]}"
    tx_hash_short.short_description = 'Tx Hash'


@admin.register(TxRateCache)
class TxRateCacheAdmin(admin.ModelAdmin):
    list_display = ['asset', 'source', 'pair', 'rate', 'fetched_at']
    list_filter = ['source', 'asset']
    search_fields = ['asset', 'source', 'pair']
    ordering = ['-fetched_at']