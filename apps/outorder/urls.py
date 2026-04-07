"""
apps/outorder/urls.py
=====================
URL routing for the outbound order module.

Mounted at /api/outorders/ via api/outorder/urls.py.

Final URLs
----------
    GET    /api/outorders/                   List orders
    POST   /api/outorders/                   Create a draft order + lines
    GET    /api/outorders/<id>/              Retrieve with full line details
    PATCH  /api/outorders/<id>/              Update draft order (remark / lines)
    DELETE /api/outorders/<id>/              Delete a draft order (hard delete)
    POST   /api/outorders/<id>/complete/     draft → completed (stock deducted)
    POST   /api/outorders/<id>/cancel/       draft → cancelled  (no stock change)
                                             completed → cancelled (stock restored, admin only)
"""

from django.urls import path
from .views import (
    OutOrderListCreateView,
    OutOrderRetrieveUpdateView,
    OutOrderDeleteView,
    OutOrderCompleteView,
    OutOrderCancelView,
)

app_name = 'outorder'

urlpatterns = [
    # ── Collection endpoints ────────────────────────────────────────────
    path('', OutOrderListCreateView.as_view(), name='outorder-list-create'),

    # ── Single-resource endpoints ───────────────────────────────────────
    path('<int:pk>/', OutOrderRetrieveUpdateView.as_view(), name='outorder-detail'),
    path('<int:pk>/delete/',   OutOrderDeleteView.as_view(),   name='outorder-delete'),

    # ── Status action endpoints ─────────────────────────────────────────
    path('<int:pk>/complete/', OutOrderCompleteView.as_view(), name='outorder-complete'),
    path('<int:pk>/cancel/',   OutOrderCancelView.as_view(),   name='outorder-cancel'),
]
