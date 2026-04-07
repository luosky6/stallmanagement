"""
apps/common/middleware.py
=========================
Custom Django middleware for the StallManagement project.

Middleware classes registered here must also be listed in
settings.MIDDLEWARE in the correct order.

Classes
-------
RequestLoggingMiddleware
    Logs every incoming request (method, path, user, status, duration)
    to the 'api' logger → logs/api.log.

RoleCheckMiddleware
    Enforces URL-level role restrictions defined in ROLE_PROTECTED_PREFIXES.
    Complements DRF permission classes (which apply at the view level) by
    blocking obviously mis-targeted requests before they reach the router.
"""

import time
import logging

from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

logger_api   = logging.getLogger('api')
logger_apps  = logging.getLogger('apps')


# ---------------------------------------------------------------------------
# Role → allowed URL prefix map
# ---------------------------------------------------------------------------
# Format: { 'url_prefix': [allowed_roles] }
# An empty list means "all authenticated users are allowed".
# URLs NOT in this map are publicly accessible (e.g. /, /api/auth/login/).
# ---------------------------------------------------------------------------
ROLE_PROTECTED_PREFIXES = {
    # Only admin can manage users
    '/api/users/':       ['admin'],

    # Admin and stall_owner can manage stock-related resources
    '/api/products/':    ['admin', 'stall_owner'],
    '/api/categories/':  ['admin', 'stall_owner'],
    '/api/stalls/':      ['admin', 'stall_owner'],
    '/api/customers/':   ['admin', 'stall_owner'],
    '/api/inorders/':    ['admin', 'stall_owner'],
    '/api/outorders/':   ['admin', 'stall_owner'],

    # All authenticated users can access favourites and chat
    '/api/favorites/':   ['admin', 'stall_owner', 'customer'],
    '/api/chat/':        ['admin', 'stall_owner', 'customer'],
}

# URL prefixes that never require authentication
PUBLIC_PREFIXES = [
    '/api/auth/',   # login / logout
    '/admin/',      # Django admin (has its own auth)
    '/static/',     # static assets
    '/',            # SPA root — served to anonymous users too
]


# ---------------------------------------------------------------------------
# 1. RequestLoggingMiddleware
# ---------------------------------------------------------------------------
class RequestLoggingMiddleware(MiddlewareMixin):
    """
    Logs every HTTP request to logs/api.log via the 'api' logger.

    Log format:
        [METHOD] /path/ — user: <username|anonymous> — status: 200 — 12.34ms

    Called after the response is ready so the HTTP status code is available.
    """

    def process_request(self, request):
        """Record the start time on the request object for duration tracking."""
        request._start_time = time.monotonic()

    def process_response(self, request, response):
        """Log the completed request with timing, user, and status."""
        duration_ms = (time.monotonic() - getattr(request, '_start_time', time.monotonic())) * 1000

        # Identify the user without crashing on unauthenticated requests
        if hasattr(request, 'user') and request.user.is_authenticated:
            user_label = f'{request.user.username} (role={getattr(request.user, "role", "?")})'
        else:
            user_label = 'anonymous'

        logger_api.info(
            '[%s] %s — user: %s — status: %s — %.2fms',
            request.method,
            request.path,
            user_label,
            response.status_code,
            duration_ms,
        )
        return response


# ---------------------------------------------------------------------------
# 2. RoleCheckMiddleware
# ---------------------------------------------------------------------------
class RoleCheckMiddleware(MiddlewareMixin):
    """
    URL-level role enforcement as a first line of defence.

    Decision logic
    --------------
    1. If the path matches a PUBLIC_PREFIX → allow through unconditionally.
    2. If the path matches a ROLE_PROTECTED_PREFIX:
       a. User not authenticated → 401 Unauthorized.
       b. User's role not in the allowed list → 403 Forbidden.
    3. Everything else (no matching prefix in either map) → allow through.
       DRF permission classes on the view itself are still the primary guard.

    Why middleware AND DRF permissions?
    -----------------------------------
    Middleware catches cross-cutting concerns early (before the view is even
    resolved), which is useful for logging and coarse-grained access control.
    DRF permission classes provide fine-grained, object-level checks inside
    each view.  Both layers working together give defence in depth.
    """

    @staticmethod
    def _is_public(path):
        """Return True if the path starts with any PUBLIC_PREFIX."""
        return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)

    @staticmethod
    def _get_protected_roles(path):
        """
        Return the list of allowed roles for this path, or None if the path
        is not in ROLE_PROTECTED_PREFIXES.
        """
        for prefix, roles in ROLE_PROTECTED_PREFIXES.items():
            if path.startswith(prefix):
                return roles
        return None

    def process_request(self, request):
        """
        Intercept the request before it reaches the URL router.
        Returns a JsonResponse on access denial, or None to pass through.
        """
        path = request.path

        # Rule 1 — public paths bypass all checks
        if self._is_public(path):
            return None

        allowed_roles = self._get_protected_roles(path)

        # Rule 3 — no matching protected prefix → pass through
        if allowed_roles is None:
            return None

        # Rule 2a — unauthenticated user
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            logger_apps.warning(
                'RoleCheckMiddleware: unauthenticated access attempt → %s', path
            )
            return JsonResponse(
                {
                    'success': False,
                    'code':    401,
                    'message': 'Authentication required. Please log in.',
                    'data':    None,
                },
                status=401,
            )

        # Rule 2b — authenticated but wrong role
        user_role = getattr(request.user, 'role', None)
        if user_role not in allowed_roles:
            logger_apps.warning(
                'RoleCheckMiddleware: role "%s" denied access to %s (allowed: %s)',
                user_role, path, allowed_roles,
            )
            return JsonResponse(
                {
                    'success': False,
                    'code':    403,
                    'message': (
                        f'Access denied. Your role "{user_role}" does not have '
                        f'permission to access this resource.'
                    ),
                    'data': None,
                },
                status=403,
            )

        # All checks passed
        return None
