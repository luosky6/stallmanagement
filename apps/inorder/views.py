"""
apps/inorder/views.py
=====================
Inbound (purchase) order management views.

Transaction safety
------------------
Every write operation (create, update, delete, complete, cancel) is
wrapped in django.db.transaction.atomic().  This means:

  Create order + lines    → single atomic unit
  Update order + replace lines → single atomic unit
  Complete order → save + signal fires → stock adjusted → all in one unit
  Cancel order → single atomic unit (no stock reversal for completed orders)
  Delete order → single atomic unit

If any step fails (validation error, DB error, stock adjustment error),
the entire transaction rolls back and the database is left unchanged.

Signal coordination
-------------------
Before saving a status change, the view attaches instance._previous_status
to the InOrder instance.  The post_save signal in signals.py reads this
attribute to determine whether to trigger a stock increase.  This pattern
avoids a second DB query inside the signal to find the old status.

Permission model
----------------
GET  (list / retrieve)  →  admin + stall_owner
POST (create)           →  admin + stall_owner
PATCH                   →  admin + stall_owner (draft orders only)
DELETE                  →  admin + stall_owner (draft orders only)
complete / cancel       →  admin + stall_owner

Views
-----
InOrderListCreateView       GET  /api/inorders/               List / Create
InOrderRetrieveUpdateView   GET  /api/inorders/<id>/          Retrieve / Update header
InOrderDeleteView           DELETE /api/inorders/<id>/        Delete draft order
InOrderCompleteView         POST /api/inorders/<id>/complete/ Mark completed → stock up
InOrderCancelView           POST /api/inorders/<id>/cancel/   Mark cancelled
"""

import logging

from django.db import transaction
from django.db.models import Q, Prefetch
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import InOrder, InOrderProduct
from .serializers import (
    InOrderReadSerializer,
    InOrderCreateSerializer,
    InOrderUpdateSerializer,
)
from api.permissions import IsAdminOrStallOwnerRole

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
# Shared queryset builder
# ---------------------------------------------------------------------------
def _base_qs():
    """
    Base queryset with select_related and prefetch for performance.
    Avoids N+1 queries when serialising orders with nested lines.
    """
    return (
        InOrder.objects
        .select_related('customer', 'operator')
        .prefetch_related(
            Prefetch(
                'lines',
                queryset=InOrderProduct.objects.select_related(
                    'product', 'product__category'
                ),
            )
        )
    )


# ---------------------------------------------------------------------------
# Shared line-replacement helper
# ---------------------------------------------------------------------------
def _replace_lines(order, lines_data):
    """
    Delete all existing lines for an order and create new ones from lines_data.
    Must be called inside a transaction.atomic() block.

    Parameters
    ----------
    order       : InOrder instance
    lines_data  : list of validated dicts from InOrderProductWriteSerializer
    """
    order.lines.all().delete()
    InOrderProduct.objects.bulk_create([
        InOrderProduct(
            inorder    = order,
            product_id = line['product_id'],
            amount     = line['amount'],
            unit_price = line.get('unit_price'),
        )
        for line in lines_data
    ])


# ---------------------------------------------------------------------------
# 1. InOrderListCreateView — GET /api/inorders/   POST /api/inorders/
# ---------------------------------------------------------------------------
class InOrderListCreateView(APIView):
    """
    GET  /api/inorders/   → paginated, filtered list of inbound orders
    POST /api/inorders/   → create a new draft inbound order with line items

    Query parameters (GET)
    ----------------------
    status          Filter by status  (draft | completed | cancelled)
    customer_id     Filter by supplier ID
    search          Search order code or remark (case-insensitive)
    ordering        code | -code | create_time | -create_time  (default: -create_time)
    page / page_size
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    # ── GET ─────────────────────────────────────────────────────────────
    def get(self, request):
        qs = _base_qs().all()

        # ── Filters ─────────────────────────────────────────────────────
        status_filter = request.query_params.get('status', '').strip()
        if status_filter:
            valid = [s.value for s in InOrder.Status]
            if status_filter not in valid:
                return fail(f'Invalid status. Choose from: {valid}.', code=400)
            qs = qs.filter(status=status_filter)

        customer_id = request.query_params.get('customer_id', '').strip()
        if customer_id:
            try:
                qs = qs.filter(customer_id=int(customer_id))
            except ValueError:
                return fail('customer_id must be an integer.', code=400)

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(code__icontains=search) | Q(remark__icontains=search)
            )

        # ── Ordering ─────────────────────────────────────────────────────
        allowed_ordering = {'code', '-code', 'create_time', '-create_time',
                            'status', '-status'}
        ordering = request.query_params.get('ordering', '-create_time')
        if ordering not in allowed_ordering:
            ordering = '-create_time'
        qs = qs.order_by(ordering)

        # ── Pagination ───────────────────────────────────────────────────
        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 20))))
        except (ValueError, TypeError):
            return fail('page and page_size must be integers.', code=400)

        total   = qs.count()
        offset  = (page - 1) * page_size
        orders  = qs[offset: offset + page_size]

        return ok(
            data={
                'total':     total,
                'page':      page,
                'page_size': page_size,
                'results':   InOrderReadSerializer(orders, many=True).data,
            },
            message=f'{total} inbound order(s) found.',
        )

    # ── POST ─────────────────────────────────────────────────────────────
    def post(self, request):
        serializer = InOrderCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        data = serializer.validated_data

        with transaction.atomic():
            order = InOrder.objects.create(
                code        = data['code'],
                customer_id = data['customer_id'],
                operator    = request.user,
                remark      = data.get('remark', ''),
                status      = InOrder.Status.DRAFT,
            )
            _replace_lines(order, data['lines'])

        logger.info(
            'InOrderListCreateView: user "%s" created inbound order "%s" (id=%d) '
            'with %d line(s).',
            request.user.username, order.code, order.id, len(data['lines']),
        )
        return ok(
            data=InOrderReadSerializer(_base_qs().get(pk=order.pk)).data,
            message=f'Inbound order "{order.code}" created successfully.',
            code=201,
        )


# ---------------------------------------------------------------------------
# 2. InOrderRetrieveUpdateView — GET /api/inorders/<id>/
#                                 PATCH /api/inorders/<id>/
# ---------------------------------------------------------------------------
class InOrderRetrieveUpdateView(APIView):
    """
    GET   /api/inorders/<id>/  → retrieve full order with lines
    PATCH /api/inorders/<id>/  → update draft order (header fields and/or lines)

    PATCH rules
    -----------
    - Only draft orders can be updated.
    - 'code' and 'customer_id' cannot be changed after creation.
    - If 'lines' is provided in the payload, the entire lines list is
      replaced (delete all existing → bulk create new ones).
    - Status transitions (draft → completed / cancelled) are done via
      the dedicated /complete/ and /cancel/ action endpoints, NOT here.
      Providing 'status' in the PATCH payload is rejected.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def _get_order(self, pk):
        return get_object_or_404(_base_qs(), pk=pk)

    # ── GET ─────────────────────────────────────────────────────────────
    def get(self, request, pk):
        order = self._get_order(pk)
        return ok(
            data=InOrderReadSerializer(order).data,
            message='Inbound order retrieved successfully.',
        )

    # ── PATCH ───────────────────────────────────────────────────────────
    def patch(self, request, pk):
        order = self._get_order(pk)

        # ── Immutability guard ───────────────────────────────────────────
        if not order.is_editable:
            return fail(
                f'Inbound order "{order.code}" has status "{order.status}" '
                'and cannot be edited. Only draft orders are editable.',
                code=400,
            )

        # ── Block direct status change via PATCH ─────────────────────────
        if 'status' in request.data:
            return fail(
                'Status cannot be changed via PATCH. '
                'Use /complete/ or /cancel/ endpoints instead.',
                code=400,
            )

        serializer = InOrderUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        data = serializer.validated_data

        with transaction.atomic():
            # Update header fields
            if 'remark' in data:
                order.remark = data['remark']
            order.save(update_fields=['remark', 'modify_time'])

            # Replace lines if provided
            if 'lines' in data:
                _replace_lines(order, data['lines'])

        logger.info(
            'InOrderRetrieveUpdateView: user "%s" updated inbound order "%s" (id=%d).',
            request.user.username, order.code, order.id,
        )
        return ok(
            data=InOrderReadSerializer(_base_qs().get(pk=order.pk)).data,
            message=f'Inbound order "{order.code}" updated successfully.',
        )


# ---------------------------------------------------------------------------
# 3. InOrderDeleteView — DELETE /api/inorders/<id>/
# ---------------------------------------------------------------------------
class InOrderDeleteView(APIView):
    """
    DELETE /api/inorders/<id>/

    Hard-deletes a draft inbound order and its lines (CASCADE in DB).
    Only draft orders can be deleted — completed orders are permanent
    records of stock increases and cannot be removed.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def delete(self, request, pk):
        order = get_object_or_404(InOrder, pk=pk)

        if not order.is_editable:
            return fail(
                f'Inbound order "{order.code}" has status "{order.status}" '
                'and cannot be deleted. Only draft orders can be deleted.',
                code=400,
            )

        code = order.code
        with transaction.atomic():
            order.delete()

        logger.info(
            'InOrderDeleteView: user "%s" deleted draft inbound order "%s" (id=%d).',
            request.user.username, code, pk,
        )
        return ok(message=f'Inbound order "{code}" deleted successfully.')


# ---------------------------------------------------------------------------
# 4. InOrderCompleteView — POST /api/inorders/<id>/complete/
# ---------------------------------------------------------------------------
class InOrderCompleteView(APIView):
    """
    POST /api/inorders/<id>/complete/

    Transitions the order status from 'draft' → 'completed'.

    What happens inside transaction.atomic()
    -----------------------------------------
    1. instance._previous_status is set to the current status ('draft').
    2. instance.status is changed to 'completed'.
    3. instance.save() is called.
    4. The post_save signal (signals.py on_inorder_saved) fires.
    5. The signal calls utils.helpers.adjust_stock(+amount) for each line.
    6. All changes commit together — or all roll back if any step fails.

    Guards
    ------
    - Only draft orders can be completed.
    - The order must have at least one line item.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def post(self, request, pk):
        order = get_object_or_404(_base_qs(), pk=pk)

        if not order.is_draft:
            return fail(
                f'Inbound order "{order.code}" has status "{order.status}". '
                'Only draft orders can be completed.',
                code=400,
            )

        if not order.lines.exists():
            return fail(
                f'Inbound order "{order.code}" has no line items. '
                'Add at least one product line before completing the order.',
                code=400,
            )

        with transaction.atomic():
            # Attach previous status for the signal idempotency guard
            order._previous_status = order.status
            order.status = InOrder.Status.COMPLETED
            order.save(update_fields=['status', 'modify_time'])
            # ↑ post_save signal fires here, inside the transaction

        logger.info(
            'InOrderCompleteView: user "%s" completed inbound order "%s" (id=%d). '
            'Stock increased for %d product(s).',
            request.user.username, order.code, order.id, order.lines.count(),
        )
        return ok(
            data=InOrderReadSerializer(_base_qs().get(pk=order.pk)).data,
            message=(
                f'Inbound order "{order.code}" completed. '
                f'Stock has been increased for {order.lines.count()} product(s).'
            ),
        )


# ---------------------------------------------------------------------------
# 5. InOrderCancelView — POST /api/inorders/<id>/cancel/
# ---------------------------------------------------------------------------
class InOrderCancelView(APIView):
    """
    POST /api/inorders/<id>/cancel/

    Transitions the order status from 'draft' → 'cancelled'.

    Stock is NOT adjusted on cancellation.
    If a completed order needs to be reversed, a new outbound order
    should be created instead (business rule: orders are audit records).

    Guard: only draft orders can be cancelled.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def post(self, request, pk):
        order = get_object_or_404(InOrder, pk=pk)

        if not order.is_draft:
            return fail(
                f'Inbound order "{order.code}" has status "{order.status}". '
                'Only draft orders can be cancelled.',
                code=400,
            )

        with transaction.atomic():
            order._previous_status = order.status
            order.status = InOrder.Status.CANCELLED
            order.save(update_fields=['status', 'modify_time'])

        logger.info(
            'InOrderCancelView: user "%s" cancelled inbound order "%s" (id=%d).',
            request.user.username, order.code, order.id,
        )
        return ok(
            data=InOrderReadSerializer(_base_qs().get(pk=order.pk)).data,
            message=f'Inbound order "{order.code}" has been cancelled.',
        )
