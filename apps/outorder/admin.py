"""
apps/outorder/admin.py
======================
Django admin configuration for OutOrder and OutOrderProduct models.

Features
--------
- OutOrderProductInline in the order detail page
- Status badge, line count, and total_value in list view
- Filter by status, operator, and buyer
- Bulk actions: complete_selected (with stock check), cancel_selected
  (with stock restoration for completed orders)
- Delete guard: only draft orders can be deleted
- Export selected orders as CSV
"""

import csv

from django.contrib import admin
from django.db import transaction
from django.http import HttpResponse
from django.utils.html import format_html

from .models import OutOrder, OutOrderProduct
from utils.exceptions import InsufficientStockError


# ---------------------------------------------------------------------------
# Inline: line items within the OutOrder detail page
# ---------------------------------------------------------------------------
class OutOrderProductInline(admin.TabularInline):
    model           = OutOrderProduct
    fields          = ('product', 'amount', 'unit_price', 'line_total_display')
    readonly_fields = ('line_total_display',)
    extra           = 1
    autocomplete_fields = ['product']

    @admin.display(description='Line Total')
    def line_total_display(self, obj):
        if obj.pk and obj.unit_price is not None:
            return f'${obj.amount * obj.unit_price:,.2f}'
        return '—'


# ---------------------------------------------------------------------------
# OutOrderAdmin
# ---------------------------------------------------------------------------
@admin.register(OutOrder)
class OutOrderAdmin(admin.ModelAdmin):

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
    inlines = [OutOrderProductInline]

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
        return f'${total:,.2f}' if total else '—'

    # ── Admin actions ─────────────────────────────────────────────────────
    actions = ['complete_selected', 'cancel_selected', 'export_as_csv']

    @admin.action(description='Complete selected DRAFT orders (deducts stock, checks availability)')
    def complete_selected(self, request, queryset):
        """
        Attempt to complete each selected draft order.
        Uses the same atomic stock-check pattern as the API view.
        """
        from apps.outorder.views import _check_stock_for_lines

        completed = 0
        failed    = []
        skipped   = 0

        for order in queryset:
            if not order.is_draft:
                skipped += 1
                continue
            if not order.lines.exists():
                failed.append(f'"{order.code}" (no lines)')
                continue

            lines_data = [
                {'product_id': line.product_id, 'amount': line.amount}
                for line in order.lines.all()
            ]
            try:
                with transaction.atomic():
                    _check_stock_for_lines(lines_data)
                    order._previous_status = order.status
                    order.status = OutOrder.Status.COMPLETED
                    order.save(update_fields=['status', 'modify_time'])
                completed += 1
            except InsufficientStockError as exc:
                failed.append(f'"{order.code}" ({exc})')

        msg = f'{completed} order(s) completed (stock deducted).'
        if skipped:
            msg += f' {skipped} skipped (not draft).'
        if failed:
            msg += f' Failed: {"; ".join(failed)}.'
        level = 'warning' if failed else 'success'
        self.message_user(request, msg, level=level)

    @admin.action(description='Cancel selected orders (restores stock for completed orders)')
    def cancel_selected(self, request, queryset):
        """
        Cancel selected orders.
        - draft → cancelled: no stock change
        - completed → cancelled: stock restored (signal fires)
        """
        count = 0
        skipped = 0
        for order in queryset:
            if order.is_cancelled:
                skipped += 1
                continue
            with transaction.atomic():
                order._previous_status = order.status
                order.status = OutOrder.Status.CANCELLED
                order.save(update_fields=['status', 'modify_time'])
            count += 1
        self.message_user(
            request,
            f'{count} order(s) cancelled (stock restored where applicable). '
            f'{skipped} already-cancelled order(s) skipped.',
            level='warning',
        )

    @admin.action(description='Export selected outbound orders as CSV')
    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="outorders.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Code', 'Buyer', 'Operator',
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
                f'Cannot delete outbound order "{obj.code}": '
                f'status is "{obj.status}". Only draft orders can be deleted. '
                'Cancel the order first to restore stock.',
                level='error',
            )
            return
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        protected = queryset.exclude(status=OutOrder.Status.DRAFT)
        deletable = queryset.filter(status=OutOrder.Status.DRAFT)
        count = deletable.count()
        deletable.delete()
        if protected.exists():
            codes = ', '.join(f'"{o.code}"' for o in protected)
            self.message_user(
                request,
                f'{count} draft order(s) deleted. '
                f'Skipped non-draft orders (cancel them first): {codes}.',
                level='warning',
            )
        else:
            self.message_user(request, f'{count} draft order(s) deleted.')


# ---------------------------------------------------------------------------
# OutOrderProductAdmin — standalone line-item view
# ---------------------------------------------------------------------------
@admin.register(OutOrderProduct)
class OutOrderProductAdmin(admin.ModelAdmin):
    list_display  = (
        'id', 'outorder', 'product', 'amount', 'unit_price', 'line_total_display'
    )
    list_filter   = ('outorder__status',)
    search_fields = ('outorder__code', 'product__name', 'product__sn')
    list_select_related = ('outorder', 'product')
    list_per_page = 50

    @admin.display(description='Line Total')
    def line_total_display(self, obj):
        if obj.unit_price is not None:
            return f'${obj.amount * obj.unit_price:,.2f}'
        return '—'
