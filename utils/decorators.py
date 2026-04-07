"""
utils/decorators.py
===================
Role-check decorators for view functions and class-based views.

These decorators complement the DRF permission classes defined in
api/permissions.py.  They are useful when you need role enforcement
outside of DRF viewsets (e.g. in plain Django views, management commands,
or utility functions called from multiple places).

Decorators
----------
admin_required
    The decorated view is only callable by users with role='admin'.

stall_owner_required
    The decorated view is only callable by users with role='stall_owner'.

admin_or_stall_owner_required
    The decorated view is callable by admin or stall_owner role users.

own_resource_or_admin
    The decorated view is callable if the requesting user's pk matches
    a URL kwarg (e.g. the user is viewing their own profile) OR if they
    are an admin.

Usage — function-based views
------------------------------
    @admin_required
    def some_admin_view(request):
        ...

Usage — class-based views (method decorator)
---------------------------------------------
    from django.utils.decorators import method_decorator

    @method_decorator(admin_required, name='dispatch')
    class AdminOnlyView(View):
        ...

Usage — DRF APIView (apply to dispatch)
----------------------------------------
    Note: For DRF views, prefer the permission classes in api/permissions.py.
    These decorators are provided as an alternative for non-DRF views and
    for decorating specific methods on mixed views.
"""

import logging
from functools import wraps

from django.http import JsonResponse
from rest_framework import status

logger = logging.getLogger('apps')


# ---------------------------------------------------------------------------
# Internal: build a JSON 403 response (consistent envelope)
# ---------------------------------------------------------------------------
def _forbidden(message: str) -> JsonResponse:
    return JsonResponse(
        {
            'success': False,
            'code':    status.HTTP_403_FORBIDDEN,
            'message': message,
            'data':    None,
        },
        status=status.HTTP_403_FORBIDDEN,
    )


def _unauthorized(message: str = 'Authentication required.') -> JsonResponse:
    return JsonResponse(
        {
            'success': False,
            'code':    status.HTTP_401_UNAUTHORIZED,
            'message': message,
            'data':    None,
        },
        status=status.HTTP_401_UNAUTHORIZED,
    )


# ---------------------------------------------------------------------------
# Internal: shared authentication check
# ---------------------------------------------------------------------------
def _require_authenticated(request):
    """Return an error response if the user is not authenticated, else None."""
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return _unauthorized()
    return None


# ---------------------------------------------------------------------------
# 1. admin_required
# ---------------------------------------------------------------------------
def admin_required(view_func):
    """
    Decorator that restricts a view to users with role='admin'.

    Returns 401 if the user is not authenticated.
    Returns 403 if the user is authenticated but not an admin.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        err = _require_authenticated(request)
        if err:
            return err

        if not request.user.is_admin:
            logger.warning(
                'admin_required: user "%s" (role=%s) denied access.',
                request.user.username,
                request.user.role,
            )
            return _forbidden(
                f'Access denied. Admin role required. '
                f'Your role: "{request.user.role}".'
            )

        return view_func(request, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# 2. stall_owner_required
# ---------------------------------------------------------------------------
def stall_owner_required(view_func):
    """
    Decorator that restricts a view to users with role='stall_owner'.

    Returns 401 if not authenticated.
    Returns 403 if authenticated but not a stall_owner.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        err = _require_authenticated(request)
        if err:
            return err

        if not request.user.is_stall_owner:
            logger.warning(
                'stall_owner_required: user "%s" (role=%s) denied access.',
                request.user.username,
                request.user.role,
            )
            return _forbidden(
                f'Access denied. Stall Owner role required. '
                f'Your role: "{request.user.role}".'
            )

        return view_func(request, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# 3. admin_or_stall_owner_required
# ---------------------------------------------------------------------------
def admin_or_stall_owner_required(view_func):
    """
    Decorator that restricts a view to admin or stall_owner role users.

    Returns 401 if not authenticated.
    Returns 403 if authenticated but role is 'customer'.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        err = _require_authenticated(request)
        if err:
            return err

        allowed_roles = ('admin', 'stall_owner')
        if request.user.role not in allowed_roles:
            logger.warning(
                'admin_or_stall_owner_required: user "%s" (role=%s) denied.',
                request.user.username,
                request.user.role,
            )
            return _forbidden(
                f'Access denied. Admin or Stall Owner role required. '
                f'Your role: "{request.user.role}".'
            )

        return view_func(request, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# 4. own_resource_or_admin
# ---------------------------------------------------------------------------
def own_resource_or_admin(pk_url_kwarg: str = 'pk'):
    """
    Decorator factory that allows access if:
      a) The requesting user's ID matches the URL kwarg named `pk_url_kwarg`, OR
      b) The requesting user is an admin.

    Useful for endpoints like GET /api/users/<pk>/ where a user should be
    able to view their own profile but not another user's.

    Usage:
        @own_resource_or_admin(pk_url_kwarg='pk')
        def my_view(request, pk):
            ...

    Parameters
    ----------
    pk_url_kwarg : str
        Name of the URL keyword argument that holds the target resource's
        user ID (default: 'pk').
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            err = _require_authenticated(request)
            if err:
                return err

            target_id = kwargs.get(pk_url_kwarg)

            # Admin bypasses ownership check
            if request.user.is_admin:
                return view_func(request, *args, **kwargs)

            # Check ownership
            try:
                if int(target_id) != request.user.id:
                    logger.warning(
                        'own_resource_or_admin: user "%s" (id=%d) tried to access '
                        'resource with %s=%s. Denied.',
                        request.user.username,
                        request.user.id,
                        pk_url_kwarg,
                        target_id,
                    )
                    return _forbidden(
                        'Access denied. You can only access your own resources.'
                    )
            except (TypeError, ValueError):
                return _forbidden('Invalid resource identifier.')

            return view_func(request, *args, **kwargs)

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 5. log_access — lightweight audit decorator (non-blocking)
# ---------------------------------------------------------------------------
def log_access(view_func):
    """
    Decorator that logs the method, path, and user for every request to
    the decorated view.  Does NOT restrict access — purely for auditing.

    Useful on sensitive views (e.g. user export, bulk delete) where you
    want an explicit audit trail beyond what RequestLoggingMiddleware provides.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user_label = (
            f'{request.user.username} (role={request.user.role})'
            if hasattr(request, 'user') and request.user.is_authenticated
            else 'anonymous'
        )
        logger.info(
            'ACCESS [%s] %s — user: %s',
            request.method,
            request.path,
            user_label,
        )
        return view_func(request, *args, **kwargs)

    return wrapper
