"""
apps/category/urls.py
=====================
URL routing for the category module.

These patterns are mounted at /api/categories/ via api/category/urls.py,
which is included by the master api/urls.py router.

Final URLs
----------
    GET    /api/categories/            List all categories (any auth user)
    POST   /api/categories/            Create a category (admin + stall_owner)
    GET    /api/categories/lookup/     Lightweight id+name list (any auth user)
    GET    /api/categories/<id>/       Retrieve a single category (any auth user)
    PATCH  /api/categories/<id>/       Partial update (admin + stall_owner)
    DELETE /api/categories/<id>/       Delete (admin + stall_owner, product guard)

URL ordering note
-----------------
'lookup/' must be declared BEFORE '<int:pk>/' so Django does not try to
cast the string "lookup" as an integer primary key and raise a 404.
"""

from django.urls import path
from .views import (
    CategoryListCreateView,
    CategoryRetrieveUpdateView,
    CategoryDeleteView,
    CategoryLookupView,
)

app_name = 'category'

urlpatterns = [
    # ── Collection endpoints ────────────────────────────────────────────
    # GET  → list (searchable, orderable, with optional product_count)
    # POST → create
    path('', CategoryListCreateView.as_view(), name='category-list-create'),

    # ── Lookup endpoint (no PK — must come before <int:pk>/) ───────────
    # GET → [{ id, name }, ...] — used by product form dropdown and
    #                              inventory filter pill row in Vue
    path('lookup/', CategoryLookupView.as_view(), name='category-lookup'),

    # ── Single-resource endpoints ───────────────────────────────────────
    # GET → retrieve with product_count  |  PATCH → partial update
    path('<int:pk>/', CategoryRetrieveUpdateView.as_view(), name='category-detail'),

    # DELETE → hard-delete (refused if products are still assigned)
    path('<int:pk>/delete/', CategoryDeleteView.as_view(), name='category-delete'),
]
