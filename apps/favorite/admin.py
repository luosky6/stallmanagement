"""
apps/favorite/admin.py
======================
Django admin configuration for the Favorite model.

Features
--------
- List view: user, product, category, stock badge, and created timestamp
- Filters by product category and stock status
- Search across user username/name and product name/sn
- Per-user favourite count summary in the list
- Custom action: export selected favourites as CSV
- Read-only fields (favourites are toggle-only; no editable fields beyond
  the FK references, which are immutable after creation)

Note: Favourites are created/deleted, never updated.
The admin panel supports viewing and deleting favourites, but not editing
them (there are no editable fields — both FKs are set at creation time
and the record is either present or absent).
"""

import csv

from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html

from .models import Favorite
from apps.product.models import LOW_STOCK_THRESHOLD


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):

    # ── List view ────────────────────────────────────────────────────────
    list_display  = (
        'id',
        'user_display',
        'product_display',
        'category_display',
        'stock_badge',
        'create_time',
    )
    list_filter   = ('product__category', 'user__role')
    search_fields = (
        'user__username', 'user__name',
        'product__name',  'product__sn',
    )
    ordering      = ('-create_time',)
    list_per_page = 40
    list_select_related = ('user', 'product', 'product__category')

    # ── Detail view ──────────────────────────────────────────────────────
    # Favourites are immutable after creation — both FKs are read-only.
    readonly_fields = ('user', 'product', 'create_time', 'modify_time')
    fieldsets = (
        (
            'Favourite Record',
            {
                'fields': ('user', 'product'),
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

    # ── Custom list columns ──────────────────────────────────────────────
    @admin.display(description='User', ordering='user__username')
    def user_display(self, obj):
        return format_html(
            '{} <small style="color:#718096;">({})</small>',
            obj.user.name,
            obj.user.username,
        )

    @admin.display(description='Product', ordering='product__name')
    def product_display(self, obj):
        return format_html(
            '[{}] {}',
            obj.product.sn,
            obj.product.name,
        )

    @admin.display(description='Category', ordering='product__category__name')
    def category_display(self, obj):
        return obj.product.category.name if obj.product.category_id else '—'

    @admin.display(description='Stock', ordering='product__stock')
    def stock_badge(self, obj):
        """Colour-coded stock badge matching the inventory view tr.row-low style."""
        stock = obj.product.stock
        if stock == 0:
            colour, label = '#e53e3e', f'0 — OUT'
        elif stock < LOW_STOCK_THRESHOLD:
            colour, label = '#ed8936', f'{stock} — LOW'
        else:
            colour, label = '#38a169', str(stock)
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:999px;font-size:11px;font-weight:600;">{}</span>',
            colour, label,
        )

    # ── Admin actions ────────────────────────────────────────────────────
    actions = ['export_as_csv']

    @admin.action(description='Export selected favourites as CSV')
    def export_as_csv(self, request, queryset):
        """Download selected Favourite records as a CSV file."""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="favorites.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Username', 'User Name',
            'Product SN', 'Product Name', 'Category',
            'Product Stock', 'Favourited At',
        ])
        for obj in queryset.select_related('user', 'product', 'product__category'):
            writer.writerow([
                obj.id,
                obj.user.username,
                obj.user.name,
                obj.product.sn,
                obj.product.name,
                obj.product.category.name if obj.product.category_id else '',
                obj.product.stock,
                obj.create_time.strftime('%Y-%m-%d %H:%M:%S'),
            ])
        return response
