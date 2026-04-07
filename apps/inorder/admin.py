"""
apps/inorder/admin.py
=====================
Django admin configuration for InOrder and InOrderProduct models.

Features
--------
- InOrderProductInline embedded in InOrder detail — shows all line items
- Status badge and computed total_value / total_amount columns in list
- Filter by status, operator, and customer
- Search across order code and remark
- Custom actions: complete_selected, cancel_selected (with signal coordination)
- Delete guard: only draft orders can be deleted
- Export selected orders as CSV
"""

import csv

from django.contrib import admin
from django.db import transaction
from django.http import HttpResponse
from django.utils.html import format_html

from .models import InOrder, InOrderProduct


# ---------------------------------------------------------------------------
# Inline: line items within the InOrder detail page
# ---------------------------------------------------------------------------
class InOrderProductInline(admin.TabularInline):
    model         = InOrderProduct
    fields        = ('product', 'amount', 'unit_price', 'line_total_display')
    readonly_fields = ('line_total_display',)
    extra         = 1
    autocomplete_fields = ['product']

    @admin.display(description='Line Total')
    def line_total_display(self, obj):
        if obj.pk and obj.unit_price is not None:
            total = obj.amount * obj.unit_price
            return f'${total:,.2f}'
        return '—'


# ---------------------------------------------------------------------------
# InOrderAdmin
# ---------------------------------------------------------------------------
@admin.register(InOrder)
class InOrderAdmin(admin.ModelAdmin):

    # ── List view ────────────────────────────────────────────────────────
    list_display  = (
        'id', 'code', 'customer', 'operator',
        'status_badge', 'line_count', 'total_value_display', 'create_time',
    )
    list_filter   = ('status', 'operator', 'customer')
    search_fields = ('code', 'remark', 'customer__name', 'operator__username')
    ordering      = ('-create_time',)
    list_per_page = 30
    list_select_related = ('customer', 'operator')

    # ── Detail view ──────────────────────────────────────────────────────
    fieldsets = (
        (
            'Order Header',
            {
                'fields': ('code', 'customer', 'operator', 'status', 'remark'),
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
    inlines = [InOrderProductInline]

    # ── Custom list columns ──────────────────────────────────────────────
    @admin.display(description='Status')
    def status_badge(self, obj):
        colour_map = {
            'draft':     '#ed8936',
            'completed': '#38a169',
            'cancelled': '#718096',
        }
        colour = colour_map.get(obj.status, '#718096')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:999px;font-size:11px;font-weight:600;">{}</span>',
            colour, obj.get_status_display(),
        )

    @admin.display(description='Lines')
    def line_count(self, obj):
        return obj.lines.count()

    @admin.display(description='Total Value')
    def total_value_display(self, obj):
        total = obj.total_value
        if total == 0:
            return '—'
        return f'${total:,.2f}'

    # ── Admin actions ─────────────────────────────────────────────────────
    actions = ['complete_selected', 'cancel_selected', 'export_as_csv']

    @admin.action(description='Mark selected draft orders as COMPLETED (increases stock)')
    def complete_selected(self, request, queryset):
        draft_orders = queryset.filter(status=InOrder.Status.DRAFT)
        completed = 0
        skipped   = 0
        for order in draft_orders:
            if not order.lines.exists():
                skipped += 1
                continue
            with transaction.atomic():
                order._previous_status = order.status
                order.status = InOrder.Status.COMPLETED
                order.save(update_fields=['status', 'modify_time'])
            completed += 1
        non_draft = queryset.exclude(status=InOrder.Status.DRAFT).count()
        msg = f'{completed} order(s) completed (stock increased).'
        if skipped:
            msg += f' {skipped} skipped (no line items).'
        if non_draft:
            msg += f' {non_draft} skipped (not draft).'
        self.message_user(request, msg)

    @admin.action(description='Mark selected draft orders as CANCELLED')
    def cancel_selected(self, request, queryset):
        draft_orders = queryset.filter(status=InOrder.Status.DRAFT)
        count = 0
        for order in draft_orders:
            with transaction.atomic():
                order._previous_status = order.status
                order.status = InOrder.Status.CANCELLED
                order.save(update_fields=['status', 'modify_time'])
            count += 1
        self.message_user(request, f'{count} order(s) cancelled.')

    @admin.action(description='Export selected orders as CSV')
    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="inorders.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Code', 'Supplier', 'Operator',
            'Status', 'Remark', 'Lines', 'Total Value', 'Created',
        ])
        for obj in queryset.select_related('customer', 'operator'):
            writer.writerow([
                obj.id, obj.code,
                obj.customer.name, obj.operator.username,
                obj.get_status_display(), obj.remark,
                obj.lines.count(),
                f'{obj.total_value:.2f}',
                obj.create_time.strftime('%Y-%m-%d %H:%M:%S'),
            ])
        return response

    # ── Deletion guard ───────────────────────────────────────────────────
    def delete_model(self, request, obj):
        if not obj.is_editable:
            self.message_user(
                request,
                f'Cannot delete inbound order "{obj.code}": '
                f'status is "{obj.status}". Only draft orders can be deleted.',
                level='error',
            )
            return
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        protected = queryset.exclude(status=InOrder.Status.DRAFT)
        deletable = queryset.filter(status=InOrder.Status.DRAFT)
        count = deletable.count()
        deletable.delete()
        if protected.exists():
            codes = ', '.join(f'"{o.code}"' for o in protected)
            self.message_user(
                request,
                f'{count} draft order(s) deleted. '
                f'Skipped non-draft orders: {codes}.',
                level='warning',
            )
        else:
            self.message_user(request, f'{count} draft order(s) deleted.')


# ---------------------------------------------------------------------------
# InOrderProductAdmin — optional standalone view for line items
# ---------------------------------------------------------------------------
@admin.register(InOrderProduct)
class InOrderProductAdmin(admin.ModelAdmin):
    list_display  = ('id', 'inorder', 'product', 'amount', 'unit_price', 'line_total_display')
    list_filter   = ('inorder__status',)
    search_fields = ('inorder__code', 'product__name', 'product__sn')
    list_select_related = ('inorder', 'product')
    list_per_page = 50

    @admin.display(description='Line Total')
    def line_total_display(self, obj):
        if obj.unit_price is not None:
            return f'${obj.amount * obj.unit_price:,.2f}'
        return '—'
