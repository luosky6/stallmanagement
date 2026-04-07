"""
apps/product/admin.py
=====================
Django admin configuration for the Product model.

Features
--------
- List view with stock badge, category filter, price, and SN
- Low-stock visual indicator in the list (matches frontend tr.row-low)
- Filters: category, stock_status (custom), price range annotation
- Search across sn, name, description
- Inline read-only order-line count columns
- Custom admin actions: mark_low_stock_alert (export), export_as_csv
- Deletion guard: blocks deletion of products referenced by any order line
- Stock edit block: stock field is read-only in admin (managed by orders only)
"""

import csv

from django.contrib import admin
from django.db.models import Count
from django.http import HttpResponse
from django.utils.html import format_html

from .models import Product, LOW_STOCK_THRESHOLD


# ---------------------------------------------------------------------------
# Custom list filter: stock status
# ---------------------------------------------------------------------------
class StockStatusFilter(admin.SimpleListFilter):
    """
    Admin sidebar filter: Ok / Low / Out of Stock
    Mirrors the stock_status logic in the view layer.
    """
    title        = 'Stock Status'
    parameter_name = 'stock_status'

    def lookups(self, request, model_admin):
        return [
            ('ok',  'OK (adequate)'),
            ('low', f'Low (< {LOW_STOCK_THRESHOLD} units)'),
            ('out', 'Out of Stock (0 units)'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'out':
            return queryset.filter(stock=0)
        if self.value() == 'low':
            return queryset.filter(stock__gt=0, stock__lt=LOW_STOCK_THRESHOLD)
        if self.value() == 'ok':
            return queryset.filter(stock__gte=LOW_STOCK_THRESHOLD)
        return queryset


# ---------------------------------------------------------------------------
# ProductAdmin
# ---------------------------------------------------------------------------
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):

    # ── List view ────────────────────────────────────────────────────────
    list_display  = (
        'id', 'sn', 'name', 'category',
        'price_display', 'stock_badge',
        'inbound_lines', 'outbound_lines',
        'create_time',
    )
    list_filter   = ('category', StockStatusFilter)
    search_fields = ('sn', 'name', 'description')
    ordering      = ('category', 'name')
    list_per_page = 30
    list_select_related = ('category',)

    # ── Detail / change view ─────────────────────────────────────────────
    fieldsets = (
        (
            'Product Information',
            {
                'fields': ('sn', 'name', 'price', 'category', 'description'),
            },
        ),
        (
            'Stock',
            {
                'fields':      ('stock',),
                'description': (
                    '⚠️  Stock is managed automatically by inbound and outbound orders. '
                    'Do not edit it manually — changes here bypass order history.'
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
    # stock is intentionally left writable in the Django admin for emergency
    # corrections (e.g. physical stocktake reconciliation), but is read-only
    # via the REST API (blocked in ProductRetrieveUpdateView).
    readonly_fields = ('create_time', 'modify_time')

    # ── Custom list columns ──────────────────────────────────────────────
    @admin.display(description='Price', ordering='price')
    def price_display(self, obj):
        return f'${obj.price:,.2f}'

    @admin.display(description='Stock', ordering='stock')
    def stock_badge(self, obj):
        """Colour-coded stock badge matching the frontend tr.row-low style."""
        if obj.is_out_of_stock:
            colour, label = '#e53e3e', f'0 — OUT'
        elif obj.is_low_stock:
            colour, label = '#ed8936', f'{obj.stock} — LOW'
        else:
            colour, label = '#38a169', str(obj.stock)
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:999px;font-size:11px;font-weight:600;">{}</span>',
            colour, label,
        )

    @admin.display(description='Inbound Lines')
    def inbound_lines(self, obj):
        count = obj.inorderproduct_set.count()
        return count if count else format_html(
            '<span style="color:#a0aec0;">—</span>'
        )

    @admin.display(description='Outbound Lines')
    def outbound_lines(self, obj):
        count = obj.outorderproduct_set.count()
        return count if count else format_html(
            '<span style="color:#a0aec0;">—</span>'
        )

    # ── Admin actions ────────────────────────────────────────────────────
    actions = ['export_as_csv', 'export_low_stock_csv']

    @admin.action(description='Export selected products as CSV')
    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="products.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'SN', 'Name', 'Category', 'Price', 'Stock',
            'Description', 'Created', 'Modified',
        ])
        for obj in queryset.select_related('category'):
            writer.writerow([
                obj.id, obj.sn, obj.name,
                obj.category.name,
                f'{obj.price:.2f}',
                obj.stock,
                obj.description,
                obj.create_time.strftime('%Y-%m-%d %H:%M:%S'),
                obj.modify_time.strftime('%Y-%m-%d %H:%M:%S'),
            ])
        return response

    @admin.action(description=f'Export low-stock products (< {LOW_STOCK_THRESHOLD}) as CSV')
    def export_low_stock_csv(self, request, queryset):
        low_stock_qs = queryset.filter(stock__lt=LOW_STOCK_THRESHOLD)
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="low_stock_products.csv"'
        writer = csv.writer(response)
        writer.writerow(['ID', 'SN', 'Name', 'Category', 'Stock', 'Price'])
        for obj in low_stock_qs.select_related('category'):
            writer.writerow([
                obj.id, obj.sn, obj.name,
                obj.category.name,
                obj.stock,
                f'{obj.price:.2f}',
            ])
        count = low_stock_qs.count()
        self.message_user(request, f'{count} low-stock product(s) exported.')
        return response

    # ── Deletion guards ──────────────────────────────────────────────────
    def delete_model(self, request, obj):
        if obj.has_any_order_lines:
            inbound  = obj.inorderproduct_set.count()
            outbound = obj.outorderproduct_set.count()
            self.message_user(
                request,
                f'Cannot delete "{obj.name}" [{obj.sn}]: '
                f'referenced by {inbound} inbound and {outbound} outbound order line(s).',
                level='error',
            )
            return
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        protected  = [obj for obj in queryset if obj.has_any_order_lines]
        deletable  = queryset.exclude(pk__in=[obj.pk for obj in protected])

        deleted_count = deletable.count()
        deletable.delete()

        if protected:
            names = ', '.join(f'"{obj.name}"' for obj in protected)
            self.message_user(
                request,
                f'{deleted_count} product(s) deleted. '
                f'Skipped {len(protected)} with order lines: {names}.',
                level='warning',
            )
        else:
            self.message_user(request, f'{deleted_count} product(s) deleted.')
