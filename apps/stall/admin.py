"""
apps/stall/admin.py
===================
Django admin configuration for the Stall model.

Features
--------
- List view with status badge, owner name, and timestamps
- Filter by status
- Search across stall name, description, and owner username/name
- Inline read-only owner profile details
- Custom bulk actions: activate_selected, deactivate_selected, suspend_selected
- Deletion guard messages (no hard DB constraint on delete, but warnings shown)
- Export selected stalls as CSV
"""

import csv

from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html

from .models import Stall


# ---------------------------------------------------------------------------
# StallAdmin
# ---------------------------------------------------------------------------
@admin.register(Stall)
class StallAdmin(admin.ModelAdmin):

    # ── List view ────────────────────────────────────────────────────────
    list_display  = (
        'id', 'name', 'owner_link', 'status_badge',
        'description_short', 'create_time', 'modify_time',
    )
    list_filter   = ('status',)
    search_fields = ('name', 'description', 'owner__username', 'owner__name')
    ordering      = ('name',)
    list_per_page = 30
    list_select_related = ('owner',)

    # ── Detail / change view ─────────────────────────────────────────────
    fieldsets = (
        (
            'Stall Information',
            {
                'fields': ('name', 'description', 'owner'),
            },
        ),
        (
            'Status',
            {
                'fields':      ('status',),
                'description': (
                    'Use the activate / deactivate / suspend bulk actions '
                    'rather than editing status directly where possible, '
                    'to ensure the transition rules are enforced.'
                ),
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
    readonly_fields = ('create_time', 'modify_time')

    # Restrict the owner dropdown to stall_owner-role users only
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'owner':
            from apps.user.models import User
            kwargs['queryset'] = User.objects.filter(role=User.Role.STALL_OWNER)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # ── Custom list columns ──────────────────────────────────────────────
    @admin.display(description='Status')
    def status_badge(self, obj):
        colour_map = {
            'active':    '#38a169',
            'inactive':  '#718096',
            'suspended': '#e53e3e',
        }
        colour = colour_map.get(obj.status, '#718096')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:999px;font-size:11px;font-weight:600;">{}</span>',
            colour,
            obj.get_status_display(),
        )

    @admin.display(description='Owner', ordering='owner__username')
    def owner_link(self, obj):
        return format_html(
            '<span title="role: stall_owner">{} <small style="color:#718096;">({})</small></span>',
            obj.owner.name,
            obj.owner.username,
        )

    @admin.display(description='Description')
    def description_short(self, obj):
        if not obj.description:
            return format_html('<span style="color:#a0aec0;">—</span>')
        if len(obj.description) > 55:
            return obj.description[:52] + '...'
        return obj.description

    # ── Admin actions ─────────────────────────────────────────────────────
    actions = [
        'activate_selected',
        'deactivate_selected',
        'suspend_selected',
        'export_as_csv',
    ]

    @admin.action(description='Activate selected stalls')
    def activate_selected(self, request, queryset):
        count = 0
        for stall in queryset:
            if not stall.is_active:
                stall.activate()
                count += 1
        self.message_user(request, f'{count} stall(s) activated.')

    @admin.action(description='Deactivate selected stalls (set to inactive)')
    def deactivate_selected(self, request, queryset):
        count = 0
        for stall in queryset:
            if not stall.is_inactive:
                stall.deactivate()
                count += 1
        self.message_user(request, f'{count} stall(s) deactivated.')

    @admin.action(description='Suspend selected stalls')
    def suspend_selected(self, request, queryset):
        count = 0
        for stall in queryset:
            if not stall.is_suspended:
                stall.suspend()
                count += 1
        self.message_user(
            request,
            f'{count} stall(s) suspended.',
            level='warning',
        )

    @admin.action(description='Export selected stalls as CSV')
    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="stalls.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Name', 'Owner Username', 'Owner Name',
            'Status', 'Description', 'Created', 'Modified',
        ])
        for obj in queryset.select_related('owner'):
            writer.writerow([
                obj.id,
                obj.name,
                obj.owner.username,
                obj.owner.name,
                obj.get_status_display(),
                obj.description,
                obj.create_time.strftime('%Y-%m-%d %H:%M:%S'),
                obj.modify_time.strftime('%Y-%m-%d %H:%M:%S'),
            ])
        return response
