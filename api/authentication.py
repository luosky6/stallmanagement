"""
api/authentication.py
=====================
Custom DRF authentication classes for the StallManagement project.

Django REST Framework is configured in settings.py with dual authentication:

    REST_FRAMEWORK = {
        'DEFAULT_AUTHENTICATION_CLASSES': [
            'rest_framework.authentication.SessionAuthentication',
            'rest_framework.authentication.TokenAuthentication',
        ],
    }

This means every API request is tried against BOTH mechanisms.  The Vue 3
SPA uses session authentication (cookie-based, set on login via common/views.py
LoginView), while external API clients (curl, Postman, mobile apps) use
token authentication (Authorization: Token <key>).

Classes defined here extend the DRF built-ins to:
  1. Enforce that soft-deleted users cannot authenticate.
  2. Log authentication events consistently.
  3. Provide a BearerTokenAuthentication alias (some clients send
     "Authorization: Bearer <token>" instead of "Authorization: Token <token>").

These classes are registered in settings.py if you want to replace the
defaults.  To keep setup simple, the defaults are used and these classes
are available for opt-in replacement.
"""

import logging

from rest_framework.authentication import (
    SessionAuthentication,
    TokenAuthentication,
)
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger('apps')


# ---------------------------------------------------------------------------
# 1. SoftDeleteAwareSessionAuthentication
# ---------------------------------------------------------------------------
class SoftDeleteAwareSessionAuthentication(SessionAuthentication):
    """
    Extends DRF's built-in SessionAuthentication.

    Additional check:
        If the user retrieved from the session has is_deleted=True
        (soft-deleted by an admin), the authentication is rejected with
        a 401 error — preventing a deleted user from accessing the API
        via a stale session cookie that was issued before deletion.

    To use:
        REST_FRAMEWORK = {
            'DEFAULT_AUTHENTICATION_CLASSES': [
                'api.authentication.SoftDeleteAwareSessionAuthentication',
                'api.authentication.BearerTokenAuthentication',
            ],
        }
    """

    def authenticate(self, request):
        result = super().authenticate(request)

        if result is None:
            return None     # not authenticated via session — try next class

        user, auth = result

        # Reject soft-deleted users
        if getattr(user, 'is_deleted', False):
            logger.warning(
                'SoftDeleteAwareSessionAuthentication: rejected soft-deleted '
                'user "%s" (id=%d).',
                user.username, user.id,
            )
            raise AuthenticationFailed(
                'Your account has been deactivated. '
                'Please contact the administrator.'
            )

        return user, auth


# ---------------------------------------------------------------------------
# 2. BearerTokenAuthentication
# ---------------------------------------------------------------------------
class BearerTokenAuthentication(TokenAuthentication):
    """
    Extends DRF's TokenAuthentication to accept BOTH formats:

        Authorization: Token <key>    (DRF default — used by Postman, curl)
        Authorization: Bearer <key>   (OAuth2 convention — used by some JS clients)

    Also rejects tokens belonging to soft-deleted users.

    To use, register in settings.py:
        'api.authentication.BearerTokenAuthentication'
    """

    # Accept both 'Token' and 'Bearer' as the keyword
    keyword = ['Token', 'Bearer']

    def authenticate(self, request):
        """
        Override to handle the list of keywords.

        DRF's default implementation only supports a single keyword string.
        We try each keyword and return the first successful match.
        """
        auth_header = request.META.get('HTTP_AUTHORIZATION', '').split()

        if not auth_header:
            return None

        # Normalise: check if the scheme matches any of our keywords
        scheme = auth_header[0]
        if scheme.lower() not in [kw.lower() for kw in self.keyword]:
            return None

        # Temporarily set keyword to the matched scheme and delegate
        original_keyword = self.keyword
        self.keyword     = scheme
        try:
            result = super().authenticate(request)
        finally:
            self.keyword = original_keyword

        if result is None:
            return None

        user, token = result

        # Reject tokens for soft-deleted users
        if getattr(user, 'is_deleted', False):
            logger.warning(
                'BearerTokenAuthentication: rejected token for soft-deleted '
                'user "%s" (id=%d).',
                user.username, user.id,
            )
            raise AuthenticationFailed(
                'Your account has been deactivated. '
                'Please contact the administrator.'
            )

        return user, token