"""
apps/favorite/urls.py
=====================
URL routing for the favourites module.

Mounted at /api/favorites/ via api/favorite/urls.py.

Final URLs
----------
    GET    /api/favorites/                     List own favourites (paginated, filterable)
    DELETE /api/favorites/clear/               Remove ALL own favourites in one call
    POST   /api/favorites/toggle/<product_id>/ Toggle a product in/out of favourites
    GET    /api/favorites/check/<product_id>/  Check if a product is favourited

URL ordering note
-----------------
'clear/' must be declared BEFORE '<int:product_id>/' to prevent Django
from trying to cast the string "clear" as an integer.

All endpoints operate exclusively on the requesting user's own data —
no admin override to view another user's favourites is provided.
"""

from django.urls import path
from .views import (
    FavoriteListView,
    FavoriteToggleView,
    FavoriteCheckView,
    FavoriteClearView,
)

app_name = 'favorite'

urlpatterns = [
    # ── Collection endpoint ─────────────────────────────────────────────
    # GET → paginated list of own favourites with full product snapshots
    path('', FavoriteListView.as_view(), name='favorite-list'),

    # ── Named action (must precede <int:product_id>/) ───────────────────
    # DELETE → remove all favourites for the requesting user
    path('clear/', FavoriteClearView.as_view(), name='favorite-clear'),

    # ── Per-product action endpoints ────────────────────────────────────
    # POST → toggle: add if absent, remove if present (idempotent)
    path(
        'toggle/<int:product_id>/',
        FavoriteToggleView.as_view(),
        name='favorite-toggle',
    ),

    # GET → { product_id, is_favourite, favorite_id }
    path(
        'check/<int:product_id>/',
        FavoriteCheckView.as_view(),
        name='favorite-check',
    ),
]
