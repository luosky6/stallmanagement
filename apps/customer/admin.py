"""
apps/customer/admin.py
======================
Django admin configuration for the Customer model.

Features
--------
- List view with type badge, order counts, and timestamps
- Filters by customer_type
- Search across name, phone, address
- Read-only order count columns (computed, not stored in DB)
- Custom action: export selected contacts as CSV (convenience tool for admins)
- Deletion guard: overrides delete_queryset and delete_model to prevent
  removal of contacts that still have linked orders
"""

import csv

from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):

    # ── List view ───────────────────────────────────────────────────────
    list_display  = (
        'id', 'name', 'phone', 'address',
        'type_badge', 'inbound_orders', 'outbound_orders', 'create_time',
    )
    list_filter   = ('customer_type',)
    search_fields = ('name', 'phone', 'address')
    ordering      = ('customer_type', 'name')
    list_per_page = 30

    # ── Detail view ──────────────────────────────────────────────────────
    fieldsets = (
        (
            'Contact Information',
            {
                'fields': ('name', 'phone', 'address', 'customer_type'),
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

    # ── Custom display columns ───────────────────────────────────────────
    @admin.display(description='Type')
    def type_badge(self, obj):
        """Coloured badge for the customer_type field."""
        colour = '#ed8936' if obj.is_supplier else '#4299e1'
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:999px;font-size:11px;">{}</span>',
            colour,
            obj.get_customer_type_display(),
        )

    @admin.display(description='Inbound Orders')
    def inbound_orders(self, obj):
        """Number of inbound (purchase) orders linked to this supplier."""
        count = obj.inorder_set.count()
        if count == 0:
            return '—'
        return format_html(
            '<span style="color:#2b6cb0;font-weight:600;">{}</span>', count
        )

    @admin.display(description='Outbound Orders')
    def outbound_orders(self, obj):
        """Number of outbound (sales) orders linked to this buyer."""
        count = obj.outorder_set.count()
        if count == 0:
            return '—'
        return format_html(
            '<span style="color:#2b6cb0;font-weight:600;">{}</span>', count
        )

    # ── Admin actions ────────────────────────────────────────────────────
    actions = ['export_as_csv']

    @admin.action(description='Export selected contacts as CSV')
    def export_as_csv(self, request, queryset):
        """Download selected Customer records as a CSV file."""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="customers.csv"'

        writer = csv.writer(response)
        writer.writerow(['ID', 'Name', 'Phone', 'Address', 'Type', 'Created'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.name,
                obj.phone,
                obj.address,
                obj.get_customer_type_display(),
                obj.create_time.strftime('%Y-%m-%d %H:%M:%S'),
            ])
        return response

    # ── Deletion guards ──────────────────────────────────────────────────
    def delete_model(self, request, obj):
        """
        Override single-object deletion in admin.
        Refuse if the contact has any linked orders.
        """
        if obj.has_any_orders:
            self.message_user(
                request,
                f'Cannot delete "{obj.name}": '
                f'this contact has linked inbound or outbound orders. '
                'Remove those orders first.',
                level='error',
            )
            return
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        """
        Override bulk deletion in admin.
        Skips contacts that have linked orders and reports how many were skipped.
        """
        protected = [obj for obj in queryset if obj.has_any_orders]
        deletable = queryset.exclude(pk__in=[obj.pk for obj in protected])

        deleted_count = deletable.count()
        deletable.delete()

        if protected:
            names = ', '.join(f'"{obj.name}"' for obj in protected)
            self.message_user(
                request,
                f'{deleted_count} contact(s) deleted. '
                f'Skipped {len(protected)} contact(s) with linked orders: {names}.',
                level='warning',
            )
        else:
            self.message_user(request, f'{deleted_count} contact(s) deleted.')
