"""
apps/category/admin.py
======================
Django admin configuration for the Category model.

Features
--------
- List view with product count column and timestamps
- Search on name and description
- Inline display of products that belong to each category (read-only)
- Deletion guard: overrides delete_model and delete_queryset to prevent
  removal of categories that still have assigned products (mirrors the
  DB-level ON DELETE RESTRICT on products.category_id)
- Custom action: export selected categories as CSV
"""

import csv

from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html

from .models import Category


# ---------------------------------------------------------------------------
# Inline: show products assigned to this category (read-only, in detail view)
# ---------------------------------------------------------------------------
class ProductInline(admin.TabularInline):
    """
    Shows the products assigned to a category directly on the category
    detail page.  Read-only — products are managed in the product admin.
    """
    # Import inside the class to avoid circular imports at module load time.
    from apps.product.models import Product
    model        = Product
    fields       = ('sn', 'name', 'price', 'stock')
    readonly_fields = ('sn', 'name', 'price', 'stock')
    extra        = 0
    can_delete   = False
    show_change_link = True
    verbose_name = 'Assigned Product'
    verbose_name_plural = 'Assigned Products'


# ---------------------------------------------------------------------------
# CategoryAdmin
# ---------------------------------------------------------------------------
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):

    # ── List view ───────────────────────────────────────────────────────
    list_display  = ('id', 'name', 'description_short', 'product_count_display', 'create_time', 'modify_time')
    search_fields = ('name', 'description')
    ordering      = ('name',)
    list_per_page = 30

    # ── Detail / change view ─────────────────────────────────────────────
    fieldsets = (
        (
            'Category Information',
            {
                'fields': ('name', 'description'),
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
    inlines = [ProductInline]

    # ── Custom list display columns ──────────────────────────────────────
    @admin.display(description='Description')
    def description_short(self, obj):
        """Truncate long descriptions to 60 characters in the list view."""
        if not obj.description:
            return format_html('<span style="color:#a0aec0;">—</span>')
        if len(obj.description) > 60:
            return obj.description[:57] + '...'
        return obj.description

    @admin.display(description='Products')
    def product_count_display(self, obj):
        """
        Show the product count as a coloured badge.
        Zero products is highlighted in grey to draw attention to
        empty categories that could be cleaned up.
        """
        count = obj.product_set.count()
        if count == 0:
            return format_html(
                '<span style="background:#e2e8f0;color:#718096;padding:2px 8px;'
                'border-radius:999px;font-size:11px;">0 products</span>'
            )
        return format_html(
            '<span style="background:#ebf8ff;color:#2b6cb0;padding:2px 8px;'
            'border-radius:999px;font-size:11px;font-weight:600;">{} product{}</span>',
            count,
            's' if count != 1 else '',
        )

    # ── Admin actions ────────────────────────────────────────────────────
    actions = ['export_as_csv']

    @admin.action(description='Export selected categories as CSV')
    def export_as_csv(self, request, queryset):
        """Download selected Category records as a CSV file."""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="categories.csv"'

        writer = csv.writer(response)
        writer.writerow(['ID', 'Name', 'Description', 'Product Count', 'Created', 'Modified'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.name,
                obj.description,
                obj.product_set.count(),
                obj.create_time.strftime('%Y-%m-%d %H:%M:%S'),
                obj.modify_time.strftime('%Y-%m-%d %H:%M:%S'),
            ])
        return response

    # ── Deletion guards ──────────────────────────────────────────────────
    def delete_model(self, request, obj):
        """
        Override single-object deletion in admin.
        Refuse if any products are still assigned to this category.
        """
        if obj.has_products:
            count = obj.product_set.count()
            self.message_user(
                request,
                f'Cannot delete category "{obj.name}": '
                f'{count} product(s) are still assigned to it. '
                'Reassign or delete those products first.',
                level='error',
            )
            return
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        """
        Override bulk deletion in admin.
        Skips categories that still have products and reports the skipped ones.
        """
        protected  = [obj for obj in queryset if obj.has_products]
        deletable  = queryset.exclude(pk__in=[obj.pk for obj in protected])

        deleted_count = deletable.count()
        deletable.delete()

        if protected:
            names = ', '.join(f'"{obj.name}"' for obj in protected)
            self.message_user(
                request,
                f'{deleted_count} categor{"y" if deleted_count == 1 else "ies"} deleted. '
                f'Skipped {len(protected)} with assigned products: {names}.',
                level='warning',
            )
        else:
            self.message_user(
                request,
                f'{deleted_count} categor{"y" if deleted_count == 1 else "ies"} deleted.',
            )
