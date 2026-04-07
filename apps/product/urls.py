"""
apps/product/urls.py
====================
URL routing for the product module.

These patterns are mounted at /api/products/ via api/product/urls.py,
which is included by the master api/urls.py router.

Final URLs
----------
    GET    /api/products/                  List products (any auth user)
    POST   /api/products/                  Create a product (admin + stall_owner)
    GET    /api/products/low_stock/        Products below stock threshold (admin + stall_owner)
    GET    /api/products/lookup/           Lightweight id+sn+name+price+stock list (admin + stall_owner)
    GET    /api/products/<id>/             Retrieve single product (any auth user)
    PATCH  /api/products/<id>/             Partial update (admin + stall_owner)
    DELETE /api/products/<id>/             Hard-delete with order-line guard (admin + stall_owner)

URL ordering note
-----------------
'low_stock/' and 'lookup/' must be declared BEFORE '<int:pk>/' so Django
does not try to cast those strings as integer primary keys.
"""

from django.urls import path
from .views import (
    ProductListCreateView,
    ProductRetrieveUpdateView,
    ProductDeleteView,
    ProductLowStockView,
    ProductLookupView,
)

app_name = 'product'

urlpatterns = [
    # ── Collection endpoints ────────────────────────────────────────────
    # GET → list (search, filter, paginate)  |  POST → create
    path('', ProductListCreateView.as_view(), name='product-list-create'),

    # ── Named action endpoints (must precede <int:pk>/) ─────────────────
    # GET → products with stock < LOW_STOCK_THRESHOLD
    path('low_stock/', ProductLowStockView.as_view(), name='product-low-stock'),

    # GET → lightweight [{id, sn, name, price, stock}] for order form dropdowns
    path('lookup/',    ProductLookupView.as_view(),   name='product-lookup'),

    # ── Single-resource endpoints ───────────────────────────────────────
    # GET → retrieve  |  PATCH → partial update (stock field is blocked)
    path('<int:pk>/', ProductRetrieveUpdateView.as_view(), name='product-detail'),

    # DELETE → hard-delete (blocked if product has any order lines)
    path('<int:pk>/delete/', ProductDeleteView.as_view(), name='product-delete'),
]
