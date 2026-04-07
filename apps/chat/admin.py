"""
apps/chat/admin.py
==================
Django admin configuration for the ChatMessage model.

Features
--------
- List view: sender, receiver, content preview, is_read badge, timestamp
- Filters by is_read status, sender role, and receiver role
- Search across sender/receiver username and message content
- Custom action: mark_as_read_selected (bulk mark read)
- Custom action: export_as_csv
- Read-only content (messages are immutable — only is_read may change)
- Per-conversation stats in the change list header
"""

import csv

from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html

from .models import ChatMessage


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):

    # ── List view ────────────────────────────────────────────────────────
    list_display  = (
        'id',
        'sender_display',
        'receiver_display',
        'content_preview',
        'read_badge',
        'create_time',
    )
    list_filter   = ('is_read', 'sender__role', 'receiver__role')
    search_fields = (
        'sender__username',   'sender__name',
        'receiver__username', 'receiver__name',
        'content',
    )
    ordering      = ('-create_time',)
    list_per_page = 50
    list_select_related = ('sender', 'receiver')
    date_hierarchy = 'create_time'

    # ── Detail view ──────────────────────────────────────────────────────
    # Content and participants are immutable after creation.
    # Only is_read may be changed (e.g. admin marks a message as unread
    # for investigation purposes).
    fieldsets = (
        (
            'Message',
            {
                'fields': ('sender', 'receiver', 'content', 'is_read'),
            },
        ),
        (
            'Timestamps',
            {
                'classes': ('collapse',),
                'fields':  ('create_time', 'modify_time'),
            },
        ),
    )
    readonly_fields = ('sender', 'receiver', 'content', 'create_time', 'modify_time')

    # ── Custom list columns ──────────────────────────────────────────────
    @admin.display(description='From', ordering='sender__username')
    def sender_display(self, obj):
        return format_html(
            '{} <small style="color:#718096;">({})</small>',
            obj.sender.name,
            obj.sender.username,
        )

    @admin.display(description='To', ordering='receiver__username')
    def receiver_display(self, obj):
        return format_html(
            '{} <small style="color:#718096;">({})</small>',
            obj.receiver.name,
            obj.receiver.username,
        )

    @admin.display(description='Message')
    def content_preview(self, obj):
        """Truncate long messages for list readability."""
        if len(obj.content) > 70:
            return obj.content[:67] + '...'
        return obj.content

    @admin.display(description='Read', ordering='is_read', boolean=False)
    def read_badge(self, obj):
        if obj.is_read:
            return format_html(
                '<span style="background:#38a169;color:#fff;padding:2px 8px;'
                'border-radius:999px;font-size:11px;">Read</span>'
            )
        return format_html(
            '<span style="background:#e53e3e;color:#fff;padding:2px 8px;'
            'border-radius:999px;font-size:11px;font-weight:600;">Unread</span>'
        )

    # ── Admin actions ────────────────────────────────────────────────────
    actions = ['mark_as_read_selected', 'mark_as_unread_selected', 'export_as_csv']

    @admin.action(description='Mark selected messages as Read')
    def mark_as_read_selected(self, request, queryset):
        count = queryset.filter(is_read=False).update(is_read=True)
        self.message_user(request, f'{count} message(s) marked as read.')

    @admin.action(description='Mark selected messages as Unread')
    def mark_as_unread_selected(self, request, queryset):
        count = queryset.filter(is_read=True).update(is_read=False)
        self.message_user(request, f'{count} message(s) marked as unread.')

    @admin.action(description='Export selected messages as CSV')
    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="chat_messages.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'From Username', 'From Name',
            'To Username', 'To Name',
            'Content', 'Is Read', 'Sent At',
        ])
        for obj in queryset.select_related('sender', 'receiver'):
            writer.writerow([
                obj.id,
                obj.sender.username,
                obj.sender.name,
                obj.receiver.username,
                obj.receiver.name,
                obj.content,
                'Yes' if obj.is_read else 'No',
                obj.create_time.strftime('%Y-%m-%d %H:%M:%S'),
            ])
        return response
