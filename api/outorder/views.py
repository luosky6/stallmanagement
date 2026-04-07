"""
api/outorder/views.py
=====================
Outbound (sales) order API sub-package — view registry and documentation.

This module re-exports all outbound order views from apps/outorder/views.py
and serves as the single import point for the sub-package's urls.py.

All business logic, permission checks, signal coordination, and atomic
stock deduction live in apps/outorder/views.py.  This layer adds:
  - A consolidated docstring describing the full API surface
  - An OutOrderViewSet class that groups all views for discoverability
    (used by the DRF browsable API and API documentation tools)

Full API surface for /api/outorders/
--------------------------------------
Method  URL                              Permission              Description
------  ----------------------------     --------------------    ---------------------
GET     /api/outorders/                  Admin + StallOwner      List orders (filterable,
                                                                  paginated, searchable)
POST    /api/outorders/                  Admin + StallOwner      Create a new draft order
                                                                  with line items in one
                                                                  request body
GET     /api/outorders/<id>/             Admin + StallOwner      Retrieve a single order
                                                                  with all line details
PATCH   /api/outorders/<id>/             Admin + StallOwner      Update draft order
                                                                  (remark and/or lines);
                                                                  stock field is blocked
DELETE  /api/outorders/<id>/delete/      Admin + StallOwner      Hard-delete a draft order
                                                                  (completed orders must be
                                                                  cancelled instead)
POST    /api/outorders/<id>/complete/    Admin + StallOwner      Draft → completed
                                                                  • select_for_update() stock
                                                                    check inside atomic()
                                                                  • signal deducts stock
                                                                  • rolls back if insufficient
POST    /api/outorders/<id>/cancel/      Admin + StallOwner      Draft → cancelled (no stock
                                                                  change); Completed →
                                                                  cancelled (ADMIN ONLY,
                                                                  stock restored via signal)

Request / Response examples
----------------------------
POST /api/outorders/
    Request body:
        {
            "code":        "OUT20241201001",
            "customer_id": 3,
            "remark":      "Urgent delivery",
            "lines": [
                { "product_id": 1, "amount": 20, "unit_price": 59.99 },
                { "product_id": 2, "amount": 15, "unit_price": 129.99 }
            ]
        }
    Success response (201):
        {
            "success": true,
            "code":    201,
            "message": "Outbound order \"OUT20241201001\" created successfully.",
            "data": {
                "id": 3,
                "code": "OUT20241201001",
                "customer": { "id": 3, "name": "Buyer C", "customer_type": "buyer" },
                "operator_name": "Stall Owner Li",
                "status": "draft",
                "is_editable": true,
                "lines": [
                    { "product": { "id": 1, "sn": "CLT-001", ... }, "amount": 20, ... }
                ],
                "total_amount": 35,
                "total_value": "3149.65"
            }
        }

POST /api/outorders/<id>/complete/
    Stock-check failure response (400):
        {
            "success": false,
            "code":    400,
            "message": "Insufficient stock for one or more products.",
            "data": [
                {
                    "product_id":   1,
                    "product_sn":   "CLT-001",
                    "product_name": "Men's T-Shirt",
                    "stock":        5,
                    "requested":    20,
                    "shortfall":    15
                }
            ]
        }

Query parameters for GET /api/outorders/
    status          draft | completed | cancelled
    customer_id     integer FK (buyer)
    search          order code or remark (case-insensitive contains)
    ordering        code | -code | create_time | -create_time | status
    page            integer (default: 1)
    page_size       integer (default: 20, max: 100)
"""

# ---------------------------------------------------------------------------
# Re-exports — all logic lives in apps/outorder/views.py
# ---------------------------------------------------------------------------
from apps.outorder.views import (       # noqa: F401
    OutOrderListCreateView,
    OutOrderRetrieveUpdateView,
    OutOrderDeleteView,
    OutOrderCompleteView,
    OutOrderCancelView,
)


# ---------------------------------------------------------------------------
# OutOrderViewSet — logical grouping for documentation and tooling
# ---------------------------------------------------------------------------
class OutOrderViewSet:
    """
    Logical grouping of all outbound order views.

    Not a DRF ViewSet (the project uses APIView throughout for explicit
    control over actions).  This class exists purely as a registry so
    that API documentation tools (drf-spectacular, drf-yasg) and IDE
    navigation can discover all related views in one place.

    Views
    -----
    list_create     OutOrderListCreateView      GET + POST   /api/outorders/
    detail_update   OutOrderRetrieveUpdateView  GET + PATCH  /api/outorders/<id>/
    delete          OutOrderDeleteView          DELETE       /api/outorders/<id>/delete/
    complete        OutOrderCompleteView        POST         /api/outorders/<id>/complete/
    cancel          OutOrderCancelView          POST         /api/outorders/<id>/cancel/

    Stock safety model
    ------------------
    The complete action is the most safety-critical endpoint in the project:

    1.  View receives POST /api/outorders/<id>/complete/
    2.  Validates the order is still in draft status.
    3.  Opens transaction.atomic()
    4.  Re-fetches the order with select_for_update() (row lock).
    5.  Re-validates draft status under the lock (concurrent-request guard).
    6.  Calls _check_stock_for_lines() which:
            a. Locks all affected product rows with select_for_update()
            b. Aggregates total quantity per product_id
            c. Raises InsufficientStockError if any product is under-stocked
    7.  Attaches instance._previous_status = 'draft' to the order.
    8.  Sets order.status = 'completed' and calls save().
    9.  post_save signal fires (inside the same transaction).
    10. Signal calls utils.helpers.adjust_stock(-amount) per line.
    11. All DB changes commit atomically.
        If any step 6-10 raises, the entire transaction rolls back.

    Completed to Cancelled reversal
    --------------------------------
    Only admins can cancel a completed outbound order.
    The post_save signal detects the 'completed' to 'cancelled' transition
    (via instance._previous_status) and calls adjust_stock(+amount) per
    line to restore the stock.
    """

    list_create   = OutOrderListCreateView
    detail_update = OutOrderRetrieveUpdateView
    delete        = OutOrderDeleteView
    complete      = OutOrderCompleteView
    cancel        = OutOrderCancelView