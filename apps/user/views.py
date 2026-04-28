"""
apps/user/views.py
==================
User management views — accessible to admin-role users only.

Views
-----
UserListCreateView      GET  /api/users/           List all users / Create a user
UserRetrieveUpdateView  GET  /api/users/<id>/      Retrieve a user
                        PATCH /api/users/<id>/     Update a user (name, role, is_active, password)
UserSoftDeleteView      DELETE /api/users/<id>/    Soft-delete a user
UserRestoreView         POST /api/users/<id>/restore/  Restore a soft-deleted user
ChangePasswordView      POST /api/users/change_password/  Change own password (any auth user)

Permission model
----------------
- All views except ChangePasswordView require role='admin'.
- ChangePasswordView requires IsAuthenticated (any role can change their own password).
- The RoleCheckMiddleware in apps/common/middleware.py enforces /api/users/ → admin only
  at the routing level; IsAdminUser here is the secondary DRF-level guard.

Response envelope (consistent with common/views.py)
----------------------------------------------------
    { "success": bool, "code": int, "message": str, "data": obj | list | null }
"""

import logging

from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .models import User
from .serializers import (
    UserReadSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
    UserChangePasswordSerializer,
)
from api.permissions import IsAdminRole

logger = logging.getLogger('apps')


# ---------------------------------------------------------------------------
# Envelope helpers (mirrors common/views.py — kept local to avoid circular
# imports; in larger projects these would live in utils/response.py)
# ---------------------------------------------------------------------------
def ok(data=None, message='Success', code=200):
    return Response({'success': True,  'code': code, 'message': message, 'data': data}, status=code)

def fail(message='Error', code=400, data=None):
    return Response({'success': False, 'code': code, 'message': message, 'data': data}, status=code)


# ---------------------------------------------------------------------------
# 1. UserListCreateView — GET /api/users/   POST /api/users/
# ---------------------------------------------------------------------------
class UserListCreateView(APIView):
    """
    GET  /api/users/     → paginated list of all non-deleted users
    POST /api/users/     → create a new user

    Query parameters (GET)
    ----------------------
    role        Filter by role  (admin | stall_owner | customer)
    is_active   Filter by active status  (true | false)
    search      Search username or name (case-insensitive contains)
    page        Page number (default: 1)
    page_size   Items per page (default: 20, max: 100)
    """

    permission_classes = [IsAuthenticated, IsAdminRole]

    # ── GET ─────────────────────────────────────────────────────────────
    def get(self, request):
        include_deleted = request.query_params.get('include_deleted', 'false').lower() == 'true'
        deleted_only = request.query_params.get('deleted_only', 'false').lower() == 'true'

        manager = User.all_objects if include_deleted or deleted_only else User.objects
        qs = manager.all().order_by('username')

        if deleted_only:
            qs = qs.filter(is_deleted=True)

        # ── Filters ─────────────────────────────────────────────────────
        role      = request.query_params.get('role')
        is_active = request.query_params.get('is_active')
        search    = request.query_params.get('search', '').strip()

        if role:
            valid_roles = [r.value for r in User.Role]
            if role not in valid_roles:
                return fail(f'Invalid role filter. Choose from: {valid_roles}.')
            qs = qs.filter(role=role)

        if is_active is not None:
            qs = qs.filter(is_active=(is_active.lower() == 'true'))

        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(username__icontains=search) | Q(name__icontains=search)
            )

        # ── Pagination ───────────────────────────────────────────────────
        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 20))))
        except (ValueError, TypeError):
            return fail('page and page_size must be integers.')

        total  = qs.count()
        offset = (page - 1) * page_size
        users  = qs[offset: offset + page_size]

        serializer = UserReadSerializer(users, many=True)
        return ok(
            data={
                'total':     total,
                'page':      page,
                'page_size': page_size,
                'results':   serializer.data,
            },
            message=f'{total} user(s) found.',
        )

    # ── POST ─────────────────────────────────────────────────────────────
    def post(self, request):
        serializer = UserCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        user = serializer.save()
        logger.info(
            'UserListCreateView: admin "%s" created user "%s" (role=%s).',
            request.user.username, user.username, user.role,
        )
        return ok(
            data=UserReadSerializer(user).data,
            message=f'User "{user.username}" created successfully.',
            code=201,
        )


# ---------------------------------------------------------------------------
# 2. UserRetrieveUpdateView — GET /api/users/<id>/   PATCH /api/users/<id>/
# ---------------------------------------------------------------------------
class UserRetrieveUpdateView(APIView):
    """
    GET   /api/users/<id>/   → retrieve a single user's details
    PATCH /api/users/<id>/   → partial update (name, role, is_active, password)
    """

    permission_classes = [IsAuthenticated, IsAdminRole]

    def _get_user(self, pk):
        """Fetch user by PK from the non-deleted pool, or raise 404."""
        return get_object_or_404(User, pk=pk)

    # ── GET ─────────────────────────────────────────────────────────────
    def get(self, request, pk):
        user = self._get_user(pk)
        return ok(
            data=UserReadSerializer(user).data,
            message='User retrieved successfully.',
        )

    # ── PATCH ───────────────────────────────────────────────────────────
    def patch(self, request, pk):
        user = self._get_user(pk)

        # Prevent an admin from demoting themselves accidentally
        if user == request.user and 'role' in request.data:
            new_role = request.data.get('role')
            if new_role != User.Role.ADMIN:
                return fail(
                    'You cannot change your own role away from admin.',
                    code=403,
                )

        serializer = UserUpdateSerializer(user, data=request.data, partial=True)
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        updated_user = serializer.save()
        logger.info(
            'UserRetrieveUpdateView: admin "%s" updated user "%s".',
            request.user.username, updated_user.username,
        )
        return ok(
            data=UserReadSerializer(updated_user).data,
            message=f'User "{updated_user.username}" updated successfully.',
        )


# ---------------------------------------------------------------------------
# 3. UserSoftDeleteView — DELETE /api/users/<id>/
# ---------------------------------------------------------------------------
class UserSoftDeleteView(APIView):
    """
    DELETE /api/users/<id>/

    Soft-deletes the user (sets is_deleted=True via SoftDeleteMixin.delete()).
    The user's data remains in the database and can be restored.

    Guards
    ------
    - Admin cannot delete their own account.
    - Cannot delete a user who is already soft-deleted.
    """

    permission_classes = [IsAuthenticated, IsAdminRole]

    def delete(self, request, pk):
        user = get_object_or_404(User, pk=pk)

        if user == request.user:
            return fail('You cannot delete your own account.', code=403)

        if user.is_deleted:
            return fail(
                f'User "{user.username}" is already deleted.',
                code=400,
            )

        # SoftDeleteMixin.delete() sets is_deleted=True and records deleted_at
        user.delete()
        logger.info(
            'UserSoftDeleteView: admin "%s" soft-deleted user "%s".',
            request.user.username, user.username,
        )
        return ok(message=f'User "{user.username}" has been soft-deleted.')


# ---------------------------------------------------------------------------
# 4. UserRestoreView — POST /api/users/<id>/restore/
# ---------------------------------------------------------------------------
class UserRestoreView(APIView):
    """
    POST /api/users/<id>/restore/

    Restores a soft-deleted user (sets is_deleted=False via SoftDeleteMixin.restore()).
    Must query User.all_objects to find deleted users (not in default manager).
    """

    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request, pk):
        # Use all_objects to find deleted users (excluded from User.objects)
        try:
            user = User.all_objects.get(pk=pk)
        except User.DoesNotExist:
            return fail(f'User with id={pk} not found.', code=404)

        if not user.is_deleted:
            return fail(
                f'User "{user.username}" is not deleted and does not need restoring.',
                code=400,
            )

        user.restore()
        logger.info(
            'UserRestoreView: admin "%s" restored user "%s".',
            request.user.username, user.username,
        )
        return ok(
            data=UserReadSerializer(user).data,
            message=f'User "{user.username}" has been restored successfully.',
        )


# ---------------------------------------------------------------------------
# 5. ChangePasswordView — POST /api/users/change_password/
# ---------------------------------------------------------------------------
class ChangePasswordView(APIView):
    """
    POST /api/users/change_password/

    Any authenticated user (not admin-only) can change their own password.
    Body: { "current_password": "...", "new_password": "...", "new_password_confirm": "..." }

    After a successful password change the user's DRF token is rotated
    (old token deleted, new one created) to invalidate any other active sessions.
    """

    permission_classes = [IsAuthenticated]   # any role, not admin-only

    def post(self, request):
        serializer = UserChangePasswordSerializer(
            data=request.data,
            context={'request': request},
        )
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        serializer.save()

        # Rotate the DRF token so existing sessions using the old token are invalidated
        from rest_framework.authtoken.models import Token
        Token.objects.filter(user=request.user).delete()
        new_token = Token.objects.create(user=request.user)

        logger.info(
            'ChangePasswordView: user "%s" changed their password; token rotated.',
            request.user.username,
        )
        return ok(
            data={'token': new_token.key},
            message='Password changed successfully. Please use the new token for future requests.',
        )
