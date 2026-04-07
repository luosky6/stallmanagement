"""
apps/customer/urls.py
=====================
URL routing for the customer (external contacts) module.

These patterns are mounted at /api/customers/ via api/customer/urls.py,
which is included by the master api/urls.py router.

Final URLs
----------
    GET    /api/customers/             List all contacts (admin + stall_owner)
    POST   /api/customers/             Create a new contact (admin + stall_owner)
    GET    /api/customers/types/       Lookup list of valid customer_type values
    GET    /api/customers/<id>/        Retrieve a single contact
    PATCH  /api/customers/<id>/        Partial update a contact
    DELETE /api/customers/<id>/        Hard-delete a contact (with order guard)

URL ordering note
-----------------
'types/' is declared BEFORE '<int:pk>/' so Django does not attempt to cast
the string "types" as an integer primary key.
"""

from django.urls import path
from .views import (
    CustomerListCreateView,
    CustomerRetrieveUpdateView,
    CustomerDeleteView,
    CustomerTypeListView,
)

app_name = 'customer'

urlpatterns = [
    # ── Collection endpoints ────────────────────────────────────────────
    # GET → list (filterable + paginated)  |  POST → create
    path('', CustomerListCreateView.as_view(), name='customer-list-create'),

    # ── Lookup endpoint (no PK — must come before <int:pk>/) ───────────
    # GET → [{ value: 'supplier', label: 'Supplier' }, ...]
    path('types/', CustomerTypeListView.as_view(), name='customer-types'),

    # ── Single-resource endpoints ───────────────────────────────────────
    # GET → retrieve  |  PATCH → partial update
    path('<int:pk>/', CustomerRetrieveUpdateView.as_view(), name='customer-detail'),

    # DELETE → hard-delete (refused if linked orders exist)
    path('<int:pk>/delete/', CustomerDeleteView.as_view(), name='customer-delete'),
]
