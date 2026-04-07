"""
api/customer/views.py
=====================
Pass-through re-exports for the customer API sub-package.
"""

from apps.customer.views import (       # noqa: F401
    CustomerListCreateView,
    CustomerRetrieveUpdateView,
    CustomerDeleteView,
    CustomerTypeListView,
)