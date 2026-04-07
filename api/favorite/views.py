"""
api/favorite/views.py
=====================
Favourite API sub-package — view registry and documentation.

This module re-exports all favourite views from apps/favorite/views.py
and serves as the single import point for the sub-package's urls.py.

Design: Toggle-centric, user-scoped
-------------------------------------
Favourites are toggled with a single POST endpoint — no separate
add/remove endpoints.  Every queryset is automatically scoped to
request.user, so users can only see and manage their own favourites.

Full API surface for /api/favorites/
--------------------------------------
Method  URL                                  Permission       Description
------  --------------------------------     -------------    ---------------------
GET     /api/favorites/                      Any auth user    List own favourites
                                                              (paginated, filterable
                                                              on nested product fields)
DELETE  /api/favorites/clear/               Any auth user    Remove ALL own favourites
                                                              in one call; returns
                                                              { removed_count: N }
POST    /api/favorites/toggle/<product_id>/ Any auth user    Idempotent toggle:
                                                              • Not favourited → add (201)
                                                              • Already favourited → remove (200)
GET     /api/favorites/check/<product_id>/  Any auth user    Check if a specific product
                                                              is in the user's favourites

Request / Response examples
----------------------------
POST /api/favorites/toggle/1/   (product not yet favourited)
    Response (201):
        {
            "success": true,
            "code":    201,
            "message": "\"Men's T-Shirt\" added to your favourites.",
            "data": {
                "action":       "added",
                "is_favourite": true,
                "product_id":   1,
                "favorite_id":  7
            }
        }

POST /api/favorites/toggle/1/   (product already favourited)
    Response (200):
        {
            "success": true,
            "code":    200,
            "message": "\"Men's T-Shirt\" removed from your favourites.",
            "data": {
                "action":       "removed",
                "is_favourite": false,
                "product_id":   1,
                "favorite_id":  null
            }
        }

GET /api/favorites/check/5/
    Response (200):
        {
            "success": true,
            "data": {
                "product_id":   5,
                "is_favourite": true,
                "favorite_id":  3
            }
        }

GET /api/favorites/
    Response (200):
        {
            "success": true,
            "data": {
                "total": 3,
                "page": 1,
                "page_size": 20,
                "results": [
                    {
                        "id": 3,
                        "is_favourite": true,
                        "create_time": "2024-11-27T10:00:00Z",
                        "product": {
                            "id": 5,
                            "sn": "ELEC-001",
                            "name": "Wireless Bluetooth Earbuds",
                            "price": "299.99",
                            "stock": 100,
                            "category_name": "Electronics",
                            "stock_status": "ok",
                            "is_low_stock": false
                        }
                    },
                    ...
                ]
            }
        }

Query parameters for GET /api/favorites/
    search          Product name, SN, or description (case-insensitive)
    category_id     Filter by product category FK
    stock_status    'ok' | 'low' | 'out'
    page            integer (default: 1)
    page_size       integer (default: 20, max: 100)

Atomicity note
--------------
The toggle uses get_or_create() which is atomic at the DB level
(single INSERT ... ON DUPLICATE KEY UPDATE equivalent), preventing
race conditions where two simultaneous toggle POSTs both see
"not favourited" and both try to insert.
"""

# ---------------------------------------------------------------------------
# Re-exports — all logic lives in apps/favorite/views.py
# ---------------------------------------------------------------------------
from apps.favorite.views import (       # noqa: F401
    FavoriteListView,
    FavoriteToggleView,
    FavoriteCheckView,
    FavoriteClearView,
)


# ---------------------------------------------------------------------------
# FavoriteViewSet — logical grouping for documentation and tooling
# ---------------------------------------------------------------------------
class FavoriteViewSet:
    """
    Logical grouping of all favourite views.

    Not a DRF ViewSet — uses APIView throughout for explicit control.
    This class is a registry for documentation tools and IDE navigation.

    Views
    -----
    list        FavoriteListView    GET     /api/favorites/
    clear       FavoriteClearView   DELETE  /api/favorites/clear/
    toggle      FavoriteToggleView  POST    /api/favorites/toggle/<product_id>/
    check       FavoriteCheckView   GET     /api/favorites/check/<product_id>/

    All views automatically scope to request.user — users cannot
    access or modify another user's favourites through these endpoints.
    Admin users are subject to the same scoping (they see their own
    favourites, not all users' favourites).
    """

    list   = FavoriteListView
    clear  = FavoriteClearView
    toggle = FavoriteToggleView
    check  = FavoriteCheckView