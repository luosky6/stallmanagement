"""
apps/common/urls.py
===================
URL routing for the common app.

These patterns are mounted at /api/auth/ via the global urls.py:
    path('api/auth/', include('apps.common.urls'))

Final URLs
----------
    POST   /api/auth/login/     → LoginView
    POST   /api/auth/logout/    → LogoutView
    GET    /api/auth/me/        → UserProfileView

Note: The SPA root (GET /) is registered directly in the global urls.py
(StallManagement/urls.py) rather than here, because it sits at the top-level
path and is not part of the /api/auth/ prefix group.
"""

from django.urls import path
from .views import ForgotPasswordView, LoginView, LogoutView, RegisterView, UserProfileView

app_name = 'common'

urlpatterns = [
    # ── Authentication ─────────────────────────────────────────────────────
    # POST { "username": "...", "password": "..." }
    # Returns: { token, user: { id, username, name, role } }
    path('login/',  LoginView.as_view(),       name='login'),

    # POST { username, name, password, password_confirm }
    # Public self-registration; always creates a customer account.
    path('register/', RegisterView.as_view(), name='register'),

    # POST { username, name, new_password, new_password_confirm }
    # Local account recovery flow for the current no-email user schema.
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),

    # POST (no body required — token is read from Authorization header / session)
    # Deletes the auth token and clears the Django session
    path('logout/', LogoutView.as_view(),      name='logout'),

    # GET — returns the current user's profile from session / token
    # Used by the Vue SPA on page reload to restore auth state
    path('me/',     UserProfileView.as_view(), name='me'),
]
