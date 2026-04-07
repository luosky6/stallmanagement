"""
StallManagement — Global URL Configuration
==========================================
URL layout:

    /                       → Vue 3 SPA entry point (templates/index.html)
    /admin/                 → Django admin panel
    /api/auth/login/        → DRF token login  (POST)
    /api/auth/logout/       → DRF token logout (POST)
    /api/users/             → apps.user API
    /api/customers/         → apps.customer API
    /api/categories/        → apps.category API
    /api/products/          → apps.product API
    /api/stalls/            → apps.stall API
    /api/inorders/          → apps.inorder API
    /api/outorders/         → apps.outorder API
    /api/favorites/         → apps.favorite API
    /api/chat/              → apps.chat REST API (message history)
    ws/chat/<room_name>/    → WebSocket endpoint (Django Channels)

All /api/* routes require authentication unless the view explicitly
declares permission_classes = [AllowAny].
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# SPA entry point — served by common.views.IndexView
from apps.common.views import IndexView

urlpatterns = [

    # ------------------------------------------------------------------
    # 1. Vue 3 SPA — catch-all root route
    #    Vue Router runs client-side, so the server only needs to serve
    #    index.html once at /. All /api/* and /admin/* paths are excluded
    #    from this catch because they are listed first.
    # ------------------------------------------------------------------
    path('', IndexView.as_view(), name='index'),

    # ------------------------------------------------------------------
    # 2. Django admin panel
    # ------------------------------------------------------------------
    path('admin/', admin.site.urls),

    # ------------------------------------------------------------------
    # 3. DRF built-in auth endpoints
    #    POST /api/auth/login/   → obtain token  { username, password }
    #    POST /api/auth/logout/  → invalidate token (custom view in common)
    # ------------------------------------------------------------------
    path('api/auth/', include('apps.common.urls')),

    # ------------------------------------------------------------------
    # 4. REST API — per-domain sub-packages under api/
    # ------------------------------------------------------------------
    path('api/', include('api.urls')),

]

# ------------------------------------------------------------------
# 5. Serve /static/ files during development
#    In production, Nginx or another reverse proxy should handle this.
# ------------------------------------------------------------------
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
