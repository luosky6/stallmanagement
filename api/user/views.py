"""
api/user/views.py
=================
Pass-through re-exports for the user API sub-package.

All business logic lives in apps/user/views.py.
This module exists so the master api/urls.py can import from a
consistent sub-package location without coupling to apps/* paths.
"""

from apps.user.views import (           # noqa: F401  (re-export)
    UserListCreateView,
    UserRetrieveUpdateView,
    UserSoftDeleteView,
    UserRestoreView,
    ChangePasswordView,
)