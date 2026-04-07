"""
apps/inorder/urls.py
====================
URL routing for the inbound order module.

These patterns are mounted at /api/inorders/ via api/inorder/urls.py,
which is included by the master api/urls.py router.

Final URLs
----------
    GET    /api/inorders/                   List orders (admin + stall_owner)
    POST   /api/inorders/                   Create a draft order + lines
    GET    /api/inorders/<id>/              Retrieve order with full line details
    PATCH  /api/inorders/<id>/              Update draft order header and/or lines
    DELETE /api/inorders/<id>/              Delete a draft order (hard delete)
    POST   /api/inorders/<id>/complete/     draft → completed (stock increased)
    POST   /api/inorders/<id>/cancel/       draft → cancelled (no stock change)
"""

from django.urls import path
from .views import (
    InOrderListCreateView,
    InOrderRetrieveUpdateView,
    InOrderDeleteView,
    InOrderCompleteView,
    InOrderCancelView,
)

app_name = 'inorder'

urlpatterns = [
    # ── Collection endpoints ────────────────────────────────────────────
    # GET → list (filterable, paginated)  |  POST → create with lines
    path('', InOrderListCreateView.as_view(), name='inorder-list-create'),

    # ── Single-resource endpoints ───────────────────────────────────────
    # GET → retrieve with nested lines  |  PATCH → update draft order
    path('<int:pk>/', InOrderRetrieveUpdateView.as_view(), name='inorder-detail'),

    # DELETE → hard-delete draft order (and its lines via CASCADE)
    path('<int:pk>/delete/', InOrderDeleteView.as_view(), name='inorder-delete'),

    # ── Status action endpoints ─────────────────────────────────────────
    # POST → draft → completed (triggers stock increase signal)
    path('<int:pk>/complete/', InOrderCompleteView.as_view(), name='inorder-complete'),

    # POST → draft → cancelled (no stock change)
    path('<int:pk>/cancel/',   InOrderCancelView.as_view(),  name='inorder-cancel'),
]
