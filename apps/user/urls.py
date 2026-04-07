"""
apps/user/urls.py
=================
URL routing for the user management module.

These patterns are mounted at /api/users/ via api/user/urls.py, which is
included by the master api/urls.py router.

Final URLs
----------
    GET    /api/users/                      List all users (admin only)
    POST   /api/users/                      Create a new user (admin only)
    POST   /api/users/change_password/      Change own password (any auth user)
    GET    /api/users/<id>/                 Retrieve a single user (admin only)
    PATCH  /api/users/<id>/                 Update a user (admin only)
    DELETE /api/users/<id>/                 Soft-delete a user (admin only)
    POST   /api/users/<id>/restore/         Restore a soft-deleted user (admin only)

Note on URL ordering
--------------------
'change_password/' must be declared BEFORE '<int:pk>/' so Django does not
try to cast the string "change_password" as an integer primary key.
"""

from django.urls import path
from .views import (
    UserListCreateView,
    UserRetrieveUpdateView,
    UserSoftDeleteView,
    UserRestoreView,
    ChangePasswordView,
)

app_name = 'user'

urlpatterns = [
    # ── Collection endpoints ────────────────────────────────────────────
    # GET  → list   |   POST → create
    path('', UserListCreateView.as_view(), name='user-list-create'),

    # ── Action endpoint (no PK — must come before <int:pk>/) ───────────
    # POST { current_password, new_password, new_password_confirm }
    path('change_password/', ChangePasswordView.as_view(), name='change-password'),

    # ── Single-resource endpoints ───────────────────────────────────────
    # GET → retrieve   |   PATCH → partial update
    path('<int:pk>/', UserRetrieveUpdateView.as_view(), name='user-detail'),

    # DELETE → soft-delete
    path('<int:pk>/delete/',  UserSoftDeleteView.as_view(), name='user-delete'),

    # POST → restore soft-deleted user
    path('<int:pk>/restore/', UserRestoreView.as_view(),    name='user-restore'),
]
