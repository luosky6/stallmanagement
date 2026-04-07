"""
api/urls.py
===========
Master REST API URL router for the StallManagement project.

Mounted at /api/ in the global StallManagement/urls.py:
    path('api/', include('api.urls'))

This file simply fans out to each domain sub-package's urls.py.
All business-logic URL patterns live in apps/<domain>/urls.py.
The sub-packages under api/<domain>/urls.py are thin wrappers that
add the resource prefix (e.g. 'users/', 'products/') before delegating.

Final URL map (relative to /api/)
----------------------------------
Auth (handled directly by global urls.py at /api/auth/):
    POST   /api/auth/login/
    POST   /api/auth/logout/
    GET    /api/auth/me/

Users:
    GET    /api/users/
    POST   /api/users/
    POST   /api/users/change_password/
    GET    /api/users/<id>/
    PATCH  /api/users/<id>/
    DELETE /api/users/<id>/delete/
    POST   /api/users/<id>/restore/

Customers (external contacts):
    GET    /api/customers/
    POST   /api/customers/
    GET    /api/customers/types/
    GET    /api/customers/<id>/
    PATCH  /api/customers/<id>/
    DELETE /api/customers/<id>/delete/

Categories:
    GET    /api/categories/
    POST   /api/categories/
    GET    /api/categories/lookup/
    GET    /api/categories/<id>/
    PATCH  /api/categories/<id>/
    DELETE /api/categories/<id>/delete/

Products:
    GET    /api/products/
    POST   /api/products/
    GET    /api/products/low_stock/
    GET    /api/products/lookup/
    GET    /api/products/<id>/
    PATCH  /api/products/<id>/
    DELETE /api/products/<id>/delete/

Stalls:
    GET    /api/stalls/
    POST   /api/stalls/
    GET    /api/stalls/status_choices/
    GET    /api/stalls/<id>/
    PATCH  /api/stalls/<id>/
    DELETE /api/stalls/<id>/delete/
    POST   /api/stalls/<id>/activate/
    POST   /api/stalls/<id>/deactivate/
    POST   /api/stalls/<id>/suspend/

Inbound Orders:
    GET    /api/inorders/
    POST   /api/inorders/
    GET    /api/inorders/<id>/
    PATCH  /api/inorders/<id>/
    DELETE /api/inorders/<id>/delete/
    POST   /api/inorders/<id>/complete/
    POST   /api/inorders/<id>/cancel/

Outbound Orders:
    GET    /api/outorders/
    POST   /api/outorders/
    GET    /api/outorders/<id>/
    PATCH  /api/outorders/<id>/
    DELETE /api/outorders/<id>/delete/
    POST   /api/outorders/<id>/complete/
    POST   /api/outorders/<id>/cancel/

Favourites:
    GET    /api/favorites/
    DELETE /api/favorites/clear/
    POST   /api/favorites/toggle/<product_id>/
    GET    /api/favorites/check/<product_id>/

Chat (REST):
    GET    /api/chat/inbox/
    GET    /api/chat/unread_count/
    POST   /api/chat/send/
    GET    /api/chat/history/<other_user_id>/
    POST   /api/chat/mark_read/<other_user_id>/

Chat (WebSocket — handled by asgi.py / apps/chat/routing.py):
    ws://  /ws/chat/<other_user_id>/
"""

from django.urls import path, include

urlpatterns = [
    # ── User management ─────────────────────────────────────────────────
    path('', include('api.user.urls')),

    # ── External contacts (suppliers & buyers) ──────────────────────────
    path('', include('api.customer.urls')),

    # ── Product categories ───────────────────────────────────────────────
    path('', include('api.category.urls')),

    # ── Products ─────────────────────────────────────────────────────────
    path('', include('api.product.urls')),

    # ── Stalls ───────────────────────────────────────────────────────────
    path('', include('api.stall.urls')),

    # ── Inbound (purchase) orders ────────────────────────────────────────
    path('', include('api.inorder.urls')),

    # ── Outbound (sales) orders ──────────────────────────────────────────
    path('', include('api.outorder.urls')),

    # ── Favourites ───────────────────────────────────────────────────────
    path('', include('api.favorite.urls')),

    # ── Chat (REST history / send / inbox) ───────────────────────────────
    path('', include('api.chat.urls')),
]