"""
apps/stall/views.py
===================
Stall management views including CRUD and status-change actions.

Permission model
----------------
GET  (list / retrieve)
    → admin + stall_owner
    Stall owners need to see their own stall details.
    Customers do not interact with the stall management module.

POST (create)
    → admin only
    Only admins register new stalls in the system.

PATCH (update name / description / owner)
    → admin only
    Structural stall changes are admin operations.

activate / deactivate
    → admin + stall_owner
    A stall owner may temporarily close (deactivate) or reopen (activate)
    their own stall. An admin may act on any stall.

suspend
    → admin only
    Suspension is an administrative penalty action. Only an admin can
    suspend a stall or lift a suspension.

Views
-----
StallListCreateView         GET  /api/stalls/                    List / Create
StallRetrieveUpdateView     GET  /api/stalls/<id>/               Retrieve / Update
StallDeleteView             DELETE /api/stalls/<id>/             Delete
StallActivateView           POST /api/stalls/<id>/activate/      Set status → active
StallDeactivateView         POST /api/stalls/<id>/deactivate/    Set status → inactive
StallSuspendView            POST /api/stalls/<id>/suspend/       Set status → suspended (admin only)
StallStatusChoicesView      GET  /api/stalls/status_choices/     Lookup list of valid statuses

Response envelope
-----------------
{ "success": bool, "code": int, "message": str, "data": obj | list | null }
"""

import logging

from django.db.models import Q
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Stall
from .serializers import StallReadSerializer, StallWriteSerializer
from apps.user.models import User
from api.permissions import IsAdminRole, IsAdminOrStallOwnerRole

logger = logging.getLogger('apps')


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def ok(data=None, message='Success', code=200):
    return Response(
        {'success': True, 'code': code, 'message': message, 'data': data},
        status=code,
    )

def fail(message='Error', code=400, data=None):
    return Response(
        {'success': False, 'code': code, 'message': message, 'data': data},
        status=code,
    )


# ---------------------------------------------------------------------------
# Helper: check whether the requesting user may act on this stall
# ---------------------------------------------------------------------------
def _user_may_manage(request_user, stall):
    """
    Return True if the requesting user has management rights over the stall.
    - Admin: always True.
    - Stall owner: only if they own this specific stall.
    """
    if request_user.is_admin:
        return True
    if request_user.is_stall_owner and stall.owner_id == request_user.id:
        return True
    return False


# ---------------------------------------------------------------------------
# 1. StallListCreateView — GET /api/stalls/   POST /api/stalls/
# ---------------------------------------------------------------------------
class StallListCreateView(APIView):
    """
    GET  /api/stalls/   → paginated list of stalls (admin + stall_owner)
    POST /api/stalls/   → create a new stall (admin only)

    A stall_owner calling GET receives only their own stall(s).
    An admin calling GET receives all stalls across the system.

    Query parameters (GET)
    ----------------------
    status      Filter by status  (active | inactive | suspended)
    search      Case-insensitive search on stall name and description
    owner_id    Filter by owner user ID (admin only; ignored for stall_owner)
    page / page_size
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsAdminRole()]
        return [IsAuthenticated(), IsAdminOrStallOwnerRole()]

    # ── GET ─────────────────────────────────────────────────────────────
    def get(self, request):
        qs = Stall.objects.select_related('owner').all()

        # Stall owners only see their own stalls
        if request.user.is_stall_owner:
            qs = qs.filter(owner=request.user)

        # ── Filters ─────────────────────────────────────────────────────
        status_filter = request.query_params.get('status', '').strip()
        if status_filter:
            valid = [s.value for s in Stall.Status]
            if status_filter not in valid:
                return fail(f'Invalid status. Choose from: {valid}.', code=400)
            qs = qs.filter(status=status_filter)

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search) | Q(description__icontains=search)
            )

        # owner_id filter is admin-only (stall_owner already scoped to self)
        owner_id = request.query_params.get('owner_id', '').strip()
        if owner_id and request.user.is_admin:
            try:
                qs = qs.filter(owner_id=int(owner_id))
            except ValueError:
                return fail('owner_id must be an integer.', code=400)

        # ── Pagination ───────────────────────────────────────────────────
        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 20))))
        except (ValueError, TypeError):
            return fail('page and page_size must be integers.', code=400)

        total  = qs.count()
        offset = (page - 1) * page_size
        stalls = qs.order_by('name')[offset: offset + page_size]

        return ok(
            data={
                'total':     total,
                'page':      page,
                'page_size': page_size,
                'results':   StallReadSerializer(stalls, many=True).data,
            },
            message=f'{total} stall(s) found.',
        )

    # ── POST ─────────────────────────────────────────────────────────────
    def post(self, request):
        serializer = StallWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        stall = serializer.save()
        logger.info(
            'StallListCreateView: admin "%s" created stall "%s" (id=%d) for owner "%s".',
            request.user.username, stall.name, stall.id, stall.owner.username,
        )
        return ok(
            data=StallReadSerializer(stall).data,
            message=f'Stall "{stall.name}" created successfully.',
            code=201,
        )


# ---------------------------------------------------------------------------
# 2. StallRetrieveUpdateView — GET /api/stalls/<id>/   PATCH /api/stalls/<id>/
# ---------------------------------------------------------------------------
class StallRetrieveUpdateView(APIView):
    """
    GET   /api/stalls/<id>/  → retrieve stall details
    PATCH /api/stalls/<id>/  → update name, description, or owner (admin only)

    A stall_owner may only GET their own stall.
    PATCH (structural changes: name, description, owner) is admin-only.
    Status changes must go through the dedicated action endpoints.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def _get_stall(self, request, pk):
        """Fetch stall; enforce stall_owner ownership scope."""
        stall = get_object_or_404(Stall.objects.select_related('owner'), pk=pk)
        if request.user.is_stall_owner and stall.owner_id != request.user.id:
            return None, fail(
                'You do not have permission to access this stall.', code=403
            )
        return stall, None

    # ── GET ─────────────────────────────────────────────────────────────
    def get(self, request, pk):
        stall, err = self._get_stall(request, pk)
        if err:
            return err
        return ok(
            data=StallReadSerializer(stall).data,
            message='Stall retrieved successfully.',
        )

    # ── PATCH ───────────────────────────────────────────────────────────
    def patch(self, request, pk):
        # Structural updates are admin-only
        if not request.user.is_admin:
            return fail(
                'Only admins can update stall details. '
                'Use the activate/deactivate endpoints to change stall status.',
                code=403,
            )

        stall = get_object_or_404(Stall, pk=pk)

        # Prevent direct status changes via PATCH — use action endpoints
        if 'status' in request.data:
            return fail(
                'Status cannot be changed via PATCH. '
                'Use /activate/, /deactivate/, or /suspend/ instead.',
                code=400,
            )

        serializer = StallWriteSerializer(stall, data=request.data, partial=True)
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        updated = serializer.save()
        logger.info(
            'StallRetrieveUpdateView: admin "%s" updated stall "%s" (id=%d).',
            request.user.username, updated.name, updated.id,
        )
        return ok(
            data=StallReadSerializer(
                Stall.objects.select_related('owner').get(pk=updated.pk)
            ).data,
            message=f'Stall "{updated.name}" updated successfully.',
        )


# ---------------------------------------------------------------------------
# 3. StallDeleteView — DELETE /api/stalls/<id>/
# ---------------------------------------------------------------------------
class StallDeleteView(APIView):
    """
    DELETE /api/stalls/<id>/

    Hard-deletes the stall. Admin only.

    Note: The SQL schema uses ON DELETE CASCADE on stalls (from owner FK),
    but the stall itself has no cascade outward to orders or products.
    Stalls are organisational containers — deleting one does not cascade
    to inventory or orders, which remain intact.
    """

    permission_classes = [IsAuthenticated, IsAdminRole]

    def delete(self, request, pk):
        stall = get_object_or_404(Stall, pk=pk)
        name = stall.name
        stall.delete()

        logger.info(
            'StallDeleteView: admin "%s" deleted stall "%s" (id=%d).',
            request.user.username, name, pk,
        )
        return ok(message=f'Stall "{name}" deleted successfully.')


# ---------------------------------------------------------------------------
# 4. StallActivateView — POST /api/stalls/<id>/activate/
# ---------------------------------------------------------------------------
class StallActivateView(APIView):
    """
    POST /api/stalls/<id>/activate/

    Transitions status → 'active'.

    Rules
    -----
    - Admin: may activate any stall from any status.
    - Stall owner: may activate only their own stall, and only if it is
      currently 'inactive' (not suspended — only admin can unsuspend).
    - A suspended stall cannot be activated by its owner.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def post(self, request, pk):
        stall = get_object_or_404(Stall.objects.select_related('owner'), pk=pk)

        # Ownership scope for stall_owner
        if not _user_may_manage(request.user, stall):
            return fail('You do not have permission to manage this stall.', code=403)

        # Stall owner cannot unsuspend
        if stall.is_suspended and not request.user.is_admin:
            return fail(
                f'Stall "{stall.name}" is suspended. '
                'Only an admin can lift a suspension.',
                code=403,
            )

        if stall.is_active:
            return fail(
                f'Stall "{stall.name}" is already active.', code=400
            )

        stall.activate()
        logger.info(
            'StallActivateView: user "%s" activated stall "%s" (id=%d).',
            request.user.username, stall.name, stall.id,
        )
        return ok(
            data=StallReadSerializer(stall).data,
            message=f'Stall "{stall.name}" is now active.',
        )


# ---------------------------------------------------------------------------
# 5. StallDeactivateView — POST /api/stalls/<id>/deactivate/
# ---------------------------------------------------------------------------
class StallDeactivateView(APIView):
    """
    POST /api/stalls/<id>/deactivate/

    Transitions status → 'inactive'.

    Rules
    -----
    - Admin: may deactivate any stall.
    - Stall owner: may deactivate only their own stall.
    - A suspended stall is already non-operational; further deactivation
      is rejected to avoid obscuring the suspension.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def post(self, request, pk):
        stall = get_object_or_404(Stall.objects.select_related('owner'), pk=pk)

        if not _user_may_manage(request.user, stall):
            return fail('You do not have permission to manage this stall.', code=403)

        if stall.is_suspended:
            return fail(
                f'Stall "{stall.name}" is suspended. '
                'An admin must handle suspended stalls.',
                code=400,
            )

        if stall.is_inactive:
            return fail(
                f'Stall "{stall.name}" is already inactive.', code=400
            )

        stall.deactivate()
        logger.info(
            'StallDeactivateView: user "%s" deactivated stall "%s" (id=%d).',
            request.user.username, stall.name, stall.id,
        )
        return ok(
            data=StallReadSerializer(stall).data,
            message=f'Stall "{stall.name}" has been deactivated.',
        )


# ---------------------------------------------------------------------------
# 6. StallSuspendView — POST /api/stalls/<id>/suspend/    (admin only)
# ---------------------------------------------------------------------------
class StallSuspendView(APIView):
    """
    POST /api/stalls/<id>/suspend/

    Transitions status → 'suspended'. Admin only.

    A suspended stall cannot process orders and its owner cannot
    change its status — only an admin can call /activate/ to lift the
    suspension.

    Optional body: { "reason": "..." }
    The reason is logged but not persisted (there is no reason column
    in the DB schema). In a future extension a StallSuspensionLog table
    could be added to track suspension history.
    """

    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request, pk):
        stall = get_object_or_404(Stall.objects.select_related('owner'), pk=pk)

        if stall.is_suspended:
            return fail(
                f'Stall "{stall.name}" is already suspended.', code=400
            )

        reason = request.data.get('reason', '(no reason provided)').strip()
        stall.suspend()

        logger.warning(
            'StallSuspendView: admin "%s" SUSPENDED stall "%s" (id=%d). Reason: %s',
            request.user.username, stall.name, stall.id, reason,
        )
        return ok(
            data=StallReadSerializer(stall).data,
            message=f'Stall "{stall.name}" has been suspended.',
        )


# ---------------------------------------------------------------------------
# 7. StallStatusChoicesView — GET /api/stalls/status_choices/
# ---------------------------------------------------------------------------
class StallStatusChoicesView(APIView):
    """
    GET /api/stalls/status_choices/

    Returns the three valid status values as a lookup list.
    Used by the Vue frontend status dropdown without hard-coding values.

    Permission: admin + stall_owner.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def get(self, request):
        choices = [
            {'value': s.value, 'label': s.label}
            for s in Stall.Status
        ]
        return ok(data=choices, message='Stall status choices retrieved.')
