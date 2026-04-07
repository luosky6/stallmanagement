"""
apps/stall/urls.py
==================
URL routing for the stall management module.

These patterns are mounted at /api/stalls/ via api/stall/urls.py,
which is included by the master api/urls.py router.

Final URLs
----------
    GET    /api/stalls/                        List stalls
    POST   /api/stalls/                        Create stall (admin only)
    GET    /api/stalls/status_choices/         Lookup list of valid status values
    GET    /api/stalls/<id>/                   Retrieve stall
    PATCH  /api/stalls/<id>/                   Update name/description/owner (admin only)
    DELETE /api/stalls/<id>/                   Delete stall (admin only)
    POST   /api/stalls/<id>/activate/          Set status → active
    POST   /api/stalls/<id>/deactivate/        Set status → inactive
    POST   /api/stalls/<id>/suspend/           Set status → suspended (admin only)

URL ordering note
-----------------
'status_choices/' must be declared BEFORE '<int:pk>/' to prevent Django
from trying to cast the string "status_choices" as an integer primary key.
"""

from django.urls import path
from .views import (
    StallListCreateView,
    StallRetrieveUpdateView,
    StallDeleteView,
    StallActivateView,
    StallDeactivateView,
    StallSuspendView,
    StallStatusChoicesView,
)

app_name = 'stall'

urlpatterns = [
    # ── Collection endpoints ────────────────────────────────────────────
    # GET → list (admin sees all; stall_owner sees own)
    # POST → create (admin only)
    path('', StallListCreateView.as_view(), name='stall-list-create'),

    # ── Lookup endpoint (must precede <int:pk>/) ────────────────────────
    # GET → [{ value: 'active', label: 'Active' }, ...]
    path('status_choices/', StallStatusChoicesView.as_view(), name='stall-status-choices'),

    # ── Single-resource endpoints ───────────────────────────────────────
    # GET → retrieve  |  PATCH → structural update (admin only)
    path('<int:pk>/', StallRetrieveUpdateView.as_view(), name='stall-detail'),

    # DELETE → hard-delete (admin only)
    path('<int:pk>/delete/', StallDeleteView.as_view(), name='stall-delete'),

    # ── Status action endpoints ─────────────────────────────────────────
    # POST → set status = 'active'   (admin + own stall_owner; not suspended)
    path('<int:pk>/activate/',   StallActivateView.as_view(),   name='stall-activate'),

    # POST → set status = 'inactive' (admin + own stall_owner)
    path('<int:pk>/deactivate/', StallDeactivateView.as_view(), name='stall-deactivate'),

    # POST → set status = 'suspended' (admin only)
    path('<int:pk>/suspend/',    StallSuspendView.as_view(),    name='stall-suspend'),
]
