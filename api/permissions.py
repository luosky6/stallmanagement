"""
api/permissions.py
==================
Custom DRF permission classes for the StallManagement project.

These are the primary access-control layer for all API views.
They sit INSIDE the DRF request lifecycle (after authentication,
before the view body runs), and return 403 JSON responses when access
is denied — consistent with the project's standard envelope.

The RoleCheckMiddleware in apps/common/middleware.py is the outer guard
(URL-prefix level, fires before routing). These classes are the inner
guard (view level, fires after routing and authentication).

Usage in a view:
    class MyView(APIView):
        permission_classes = [IsAuthenticated, IsAdminRole]

Classes
-------
IsAdminRole                 request.user.role == 'admin'
IsStallOwnerRole            request.user.role == 'stall_owner'
IsCustomerRole              request.user.role == 'customer'
IsAdminOrStallOwnerRole     role in ('admin', 'stall_owner')
IsOwnerOrAdmin              request.user == target object's owner, OR admin
ReadOnlyOrAdminOrStallOwner GET is open to all auth users; write needs admin/stall_owner
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS


# ---------------------------------------------------------------------------
# Role constants (avoid string literals in permission checks)
# ---------------------------------------------------------------------------
_ADMIN       = 'admin'
_STALL_OWNER = 'stall_owner'
_CUSTOMER    = 'customer'


# ---------------------------------------------------------------------------
# 1. IsAdminRole
# ---------------------------------------------------------------------------
class IsAdminRole(BasePermission):
    """
    Allows access only to users with role='admin'.

    Used by:
        UserListCreateView      (create/list users)
        UserSoftDeleteView      (soft-delete a user)
        UserRestoreView         (restore a user)
        StallListCreateView     (create a stall)
        StallDeleteView         (delete a stall)
        StallSuspendView        (suspend a stall)
    """
    message = 'Access denied. Admin role is required.'

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'role', None) == _ADMIN
        )


# ---------------------------------------------------------------------------
# 2. IsStallOwnerRole
# ---------------------------------------------------------------------------
class IsStallOwnerRole(BasePermission):
    """
    Allows access only to users with role='stall_owner'.

    Used by views that are exclusively for stall owners and should not
    be accessible by admins (rare — most admin-exclusive views use
    IsAdminRole, and most stall-owner views also allow admin via
    IsAdminOrStallOwnerRole).
    """
    message = 'Access denied. Stall Owner role is required.'

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'role', None) == _STALL_OWNER
        )


# ---------------------------------------------------------------------------
# 3. IsCustomerRole
# ---------------------------------------------------------------------------
class IsCustomerRole(BasePermission):
    """
    Allows access only to users with role='customer'.

    Used by views exclusive to customer-role users (currently rare —
    most customer-accessible endpoints also allow other roles).
    """
    message = 'Access denied. Customer role is required.'

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'role', None) == _CUSTOMER
        )


# ---------------------------------------------------------------------------
# 4. IsAdminOrStallOwnerRole  ← most commonly used
# ---------------------------------------------------------------------------
class IsAdminOrStallOwnerRole(BasePermission):
    """
    Allows access to users with role='admin' OR role='stall_owner'.
    Denies access to customers.

    Used by:
        Product CRUD
        Category CRUD
        Customer (contacts) CRUD
        InOrder CRUD
        OutOrder CRUD
        Stall list / retrieve / update
        Low-stock alerts
        Order action endpoints (complete / cancel)
    """
    message = 'Access denied. Admin or Stall Owner role is required.'

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'role', None) in (_ADMIN, _STALL_OWNER)
        )


# ---------------------------------------------------------------------------
# 5. IsOwnerOrAdmin
# ---------------------------------------------------------------------------
class IsOwnerOrAdmin(BasePermission):
    """
    Object-level permission.

    Allows access if:
      a) The requesting user is an admin (unrestricted), OR
      b) The requesting user IS the owner of the object.

    The object must expose an `owner` or `user` attribute that is a
    User instance (or FK).  The check tries `obj.owner` first, then
    `obj.user`, then `obj` itself (for User objects).

    Usage in a view:
        def get_object(self):
            obj = super().get_object()
            self.check_object_permissions(self.request, obj)
            return obj
    """
    message = 'Access denied. You do not have permission to access this resource.'

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        # Admin can access any object
        if getattr(request.user, 'role', None) == _ADMIN:
            return True

        # Try common owner field patterns
        owner = (
            getattr(obj, 'owner',    None) or
            getattr(obj, 'user',     None) or
            getattr(obj, 'operator', None)
        )

        if owner is None:
            # If no owner field, treat the object itself as a User
            owner = obj

        # Compare PKs to avoid equality issues with unsaved instances
        return getattr(owner, 'pk', None) == request.user.pk


# ---------------------------------------------------------------------------
# 6. ReadOnlyOrAdminOrStallOwner
# ---------------------------------------------------------------------------
class ReadOnlyOrAdminOrStallOwner(BasePermission):
    """
    Tiered permission:

      GET / HEAD / OPTIONS (SAFE_METHODS)
          → any authenticated user (customers can browse)

      POST / PATCH / PUT / DELETE
          → admin or stall_owner only

    Used by:
        Product list/retrieve  (customers can browse products)
        Category list/retrieve (customers need categories for filtering)
    """
    message = 'Access denied. Write operations require Admin or Stall Owner role.'

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False

        # Safe methods: all authenticated users
        if request.method in SAFE_METHODS:
            return True

        # Write methods: admin or stall_owner only
        return getattr(request.user, 'role', None) in (_ADMIN, _STALL_OWNER)