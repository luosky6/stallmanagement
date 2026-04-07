"""
apps/outorder/views.py
======================
Outbound (sales) order management views.

Critical: Stock check before completion
----------------------------------------
Unlike inbound orders, outbound orders DECREASE stock. Before marking
an order completed, we must verify that enough stock exists for every
line.  This check uses select_for_update() inside transaction.atomic()
to lock the affected product rows, preventing a TOCTOU (time-of-check
time-of-use) race condition where two concurrent orders both "see"
sufficient stock but together would overdraw it.

Flow inside InOrderCompleteView.post() → transaction.atomic():
  1. Lock product rows:  Product.objects.select_for_update().filter(...)
  2. Validate each line: if product.stock < line.amount → raise error
  3. Set _previous_status on the instance (for signal)
  4. Change status to 'completed' and call save()
  5. Signal fires → adjust_stock(-amount) per line
  6. All commits atomically — or all rolls back on any failure

Completed → Cancelled (admin action)
--------------------------------------
The signal handles stock restoration when a completed order is cancelled.
Only admins may cancel a completed order (stall_owners may only cancel
their own draft orders).

Permission model
----------------
GET  (list / retrieve)  →  admin + stall_owner
POST (create)           →  admin + stall_owner
PATCH (update draft)    →  admin + stall_owner
DELETE (draft only)     →  admin + stall_owner
complete / cancel       →  admin + stall_owner
cancel completed        →  admin only

Views
-----
OutOrderListCreateView      GET  /api/outorders/                 List / Create
OutOrderRetrieveUpdateView  GET  /api/outorders/<id>/            Retrieve / Update
OutOrderDeleteView          DELETE /api/outorders/<id>/          Delete draft
OutOrderCompleteView        POST /api/outorders/<id>/complete/   Mark completed (stock deducted)
OutOrderCancelView          POST /api/outorders/<id>/cancel/     Mark cancelled
"""

import logging

from django.db import transaction
from django.db.models import Q, Prefetch
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import OutOrder, OutOrderProduct
from .serializers import (
    OutOrderReadSerializer,
    OutOrderCreateSerializer,
    OutOrderUpdateSerializer,
)
from api.permissions import IsAdminOrStallOwnerRole, IsAdminRole
from apps.product.models import Product
from utils.exceptions import InsufficientStockError

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
# Shared queryset builder — avoids N+1 queries on serialisation
# ---------------------------------------------------------------------------
def _base_qs():
    return (
        OutOrder.objects
        .select_related('customer', 'operator')
        .prefetch_related(
            Prefetch(
                'lines',
                queryset=OutOrderProduct.objects.select_related(
                    'product', 'product__category'
                ),
            )
        )
    )


# ---------------------------------------------------------------------------
# Shared line-replacement helper (used by create and update)
# ---------------------------------------------------------------------------
def _replace_lines(order, lines_data):
    """
    Delete all existing line items and bulk-create new ones.
    Must be called inside a transaction.atomic() block.
    """
    order.lines.all().delete()
    OutOrderProduct.objects.bulk_create([
        OutOrderProduct(
            outorder   = order,
            product_id = line['product_id'],
            amount     = line['amount'],
            unit_price = line.get('unit_price'),
        )
        for line in lines_data
    ])


# ---------------------------------------------------------------------------
# Stock sufficiency check — called inside transaction.atomic() with locks
# ---------------------------------------------------------------------------
def _check_stock_for_lines(lines_data):
    """
    Verify that every product has sufficient stock for the requested quantity.

    Uses select_for_update() to lock product rows for the duration of the
    enclosing transaction, preventing concurrent orders from using the same
    stock simultaneously.

    Parameters
    ----------
    lines_data : list of dicts with keys product_id, amount

    Returns
    -------
    list of Product instances (locked)

    Raises
    ------
    InsufficientStockError if any product has insufficient stock.
    """
    product_ids = [line['product_id'] for line in lines_data]

    # Lock all affected product rows for the duration of this transaction
    products_by_id = {
        p.id: p
        for p in Product.objects.select_for_update().filter(id__in=product_ids)
    }

    # Aggregate total requested quantity per product (handles duplicates
    # that slip through serializer validation in edge cases)
    requested = {}
    for line in lines_data:
        pid = line['product_id']
        requested[pid] = requested.get(pid, 0) + line['amount']

    insufficient = []
    for pid, qty_needed in requested.items():
        product = products_by_id.get(pid)
        if product is None:
            raise InsufficientStockError(
                f'Product id={pid} not found during stock check.'
            )
        if product.stock < qty_needed:
            insufficient.append({
                'product_id':   pid,
                'product_sn':   product.sn,
                'product_name': product.name,
                'stock':        product.stock,
                'requested':    qty_needed,
                'shortfall':    qty_needed - product.stock,
            })

    if insufficient:
        raise InsufficientStockError(
            'Insufficient stock for one or more products.',
            details=insufficient,
        )

    return list(products_by_id.values())


# ---------------------------------------------------------------------------
# 1. OutOrderListCreateView — GET /api/outorders/   POST /api/outorders/
# ---------------------------------------------------------------------------
class OutOrderListCreateView(APIView):
    """
    GET  /api/outorders/   → paginated, filtered list of outbound orders
    POST /api/outorders/   → create a new draft outbound order with lines

    Query parameters (GET)
    ----------------------
    status          Filter by status  (draft | completed | cancelled)
    customer_id     Filter by buyer ID
    search          Search order code or remark (case-insensitive)
    ordering        code | -code | create_time | -create_time | status | -status
    page / page_size
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    # ── GET ─────────────────────────────────────────────────────────────
    def get(self, request):
        qs = _base_qs().all()

        # ── Filters ─────────────────────────────────────────────────────
        status_filter = request.query_params.get('status', '').strip()
        if status_filter:
            valid = [s.value for s in OutOrder.Status]
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
        allowed_ordering = {
            'code', '-code', 'create_time', '-create_time', 'status', '-status'
        }
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
                'results':   OutOrderReadSerializer(orders, many=True).data,
            },
            message=f'{total} outbound order(s) found.',
        )

    # ── POST ─────────────────────────────────────────────────────────────
    def post(self, request):
        serializer = OutOrderCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        data = serializer.validated_data

        with transaction.atomic():
            order = OutOrder.objects.create(
                code        = data['code'],
                customer_id = data['customer_id'],
                operator    = request.user,
                remark      = data.get('remark', ''),
                status      = OutOrder.Status.DRAFT,
            )
            _replace_lines(order, data['lines'])

        logger.info(
            'OutOrderListCreateView: user "%s" created outbound order "%s" (id=%d) '
            'with %d line(s).',
            request.user.username, order.code, order.id, len(data['lines']),
        )
        return ok(
            data=OutOrderReadSerializer(_base_qs().get(pk=order.pk)).data,
            message=f'Outbound order "{order.code}" created successfully.',
            code=201,
        )


# ---------------------------------------------------------------------------
# 2. OutOrderRetrieveUpdateView — GET /api/outorders/<id>/
#                                  PATCH /api/outorders/<id>/
# ---------------------------------------------------------------------------
class OutOrderRetrieveUpdateView(APIView):
    """
    GET   /api/outorders/<id>/  → retrieve full order with lines
    PATCH /api/outorders/<id>/  → update draft order (remark and/or lines)

    PATCH rules
    -----------
    - Only draft orders are editable.
    - code and customer_id cannot be changed.
    - Providing 'status' in the payload is rejected — use action endpoints.
    - If 'lines' is provided, the entire lines list is replaced.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def _get_order(self, pk):
        return get_object_or_404(_base_qs(), pk=pk)

    # ── GET ─────────────────────────────────────────────────────────────
    def get(self, request, pk):
        order = self._get_order(pk)
        return ok(
            data=OutOrderReadSerializer(order).data,
            message='Outbound order retrieved successfully.',
        )

    # ── PATCH ───────────────────────────────────────────────────────────
    def patch(self, request, pk):
        order = self._get_order(pk)

        if not order.is_editable:
            return fail(
                f'Outbound order "{order.code}" has status "{order.status}" '
                'and cannot be edited. Only draft orders are editable.',
                code=400,
            )

        if 'status' in request.data:
            return fail(
                'Status cannot be changed via PATCH. '
                'Use /complete/ or /cancel/ endpoints instead.',
                code=400,
            )

        serializer = OutOrderUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        data = serializer.validated_data

        with transaction.atomic():
            if 'remark' in data:
                order.remark = data['remark']
            order.save(update_fields=['remark', 'modify_time'])

            if 'lines' in data:
                _replace_lines(order, data['lines'])

        logger.info(
            'OutOrderRetrieveUpdateView: user "%s" updated outbound order "%s" (id=%d).',
            request.user.username, order.code, order.id,
        )
        return ok(
            data=OutOrderReadSerializer(_base_qs().get(pk=order.pk)).data,
            message=f'Outbound order "{order.code}" updated successfully.',
        )


# ---------------------------------------------------------------------------
# 3. OutOrderDeleteView — DELETE /api/outorders/<id>/
# ---------------------------------------------------------------------------
class OutOrderDeleteView(APIView):
    """
    DELETE /api/outorders/<id>/

    Hard-deletes a DRAFT outbound order and its lines (CASCADE).
    Completed orders cannot be deleted — cancel them instead (which
    also restores stock via the signal).
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def delete(self, request, pk):
        order = get_object_or_404(OutOrder, pk=pk)

        if not order.is_editable:
            return fail(
                f'Outbound order "{order.code}" has status "{order.status}". '
                'Only draft orders can be deleted. '
                'To reverse a completed order, cancel it instead (stock will be restored).',
                code=400,
            )

        code = order.code
        with transaction.atomic():
            order.delete()

        logger.info(
            'OutOrderDeleteView: user "%s" deleted draft outbound order "%s" (id=%d).',
            request.user.username, code, pk,
        )
        return ok(message=f'Outbound order "{code}" deleted successfully.')


# ---------------------------------------------------------------------------
# 4. OutOrderCompleteView — POST /api/outorders/<id>/complete/
# ---------------------------------------------------------------------------
class OutOrderCompleteView(APIView):
    """
    POST /api/outorders/<id>/complete/

    Transitions draft → completed with atomic stock check + deduction.

    Execution flow inside transaction.atomic()
    -------------------------------------------
    1. Refresh the order from DB (ensures freshness after atomic lock).
    2. Re-validate it is still a draft (concurrent request guard).
    3. Call _check_stock_for_lines() which:
         a. Locks product rows with select_for_update()
         b. Aggregates total quantity per product
         c. Raises InsufficientStockError if any product is under-stocked
    4. Attach _previous_status = 'draft' to the instance.
    5. Set status = 'completed' and call save().
    6. post_save signal fires → adjust_stock(-amount) per line.
    7. All commits together. If step 3 or 6 raises, everything rolls back.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def post(self, request, pk):
        # Fetch with lines for the response but re-check inside the transaction
        order = get_object_or_404(_base_qs(), pk=pk)

        if not order.is_draft:
            return fail(
                f'Outbound order "{order.code}" has status "{order.status}". '
                'Only draft orders can be completed.',
                code=400,
            )

        if not order.lines.exists():
            return fail(
                f'Outbound order "{order.code}" has no line items. '
                'Add at least one product line before completing.',
                code=400,
            )

        lines_data = [
            {'product_id': line.product_id, 'amount': line.amount}
            for line in order.lines.all()
        ]

        try:
            with transaction.atomic():
                # Re-fetch inside transaction to prevent stale reads
                order_locked = OutOrder.objects.select_for_update().get(pk=pk)

                # Concurrent-request guard: re-confirm draft status under lock
                if not order_locked.is_draft:
                    raise InsufficientStockError(
                        f'Order "{order.code}" was modified concurrently. '
                        'Please refresh and try again.'
                    )

                # Stock check with row-level locking
                _check_stock_for_lines(lines_data)

                # Trigger signal with transition metadata
                order_locked._previous_status = order_locked.status
                order_locked.status = OutOrder.Status.COMPLETED
                order_locked.save(update_fields=['status', 'modify_time'])
                # ↑ signal fires here → adjust_stock(-amount) per line

        except InsufficientStockError as exc:
            logger.warning(
                'OutOrderCompleteView: stock check failed for order "%s" (id=%d): %s',
                order.code, order.id, str(exc),
            )
            return fail(
                str(exc),
                code=400,
                data=getattr(exc, 'details', None),
            )

        line_count = order.lines.count()
        logger.info(
            'OutOrderCompleteView: user "%s" completed outbound order "%s" (id=%d). '
            'Stock deducted for %d product(s).',
            request.user.username, order.code, order.id, line_count,
        )
        return ok(
            data=OutOrderReadSerializer(_base_qs().get(pk=pk)).data,
            message=(
                f'Outbound order "{order.code}" completed. '
                f'Stock has been deducted for {line_count} product(s).'
            ),
        )


# ---------------------------------------------------------------------------
# 5. OutOrderCancelView — POST /api/outorders/<id>/cancel/
# ---------------------------------------------------------------------------
class OutOrderCancelView(APIView):
    """
    POST /api/outorders/<id>/cancel/

    Cancellation rules
    ------------------
    draft → cancelled
        No stock change. Any authenticated admin/stall_owner may do this.

    completed → cancelled  (ADMIN ONLY)
        Stock IS restored via the post_save signal.
        The _previous_status = 'completed' triggers Case 2 in signals.py
        which calls adjust_stock(+amount) per line.

    This mirrors the frontend's deleteOutorder() which restores stock
    when a completed outbound order is deleted.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def post(self, request, pk):
        order = get_object_or_404(_base_qs(), pk=pk)

        # ── Completed → cancelled: admin only ────────────────────────────
        if order.is_completed:
            if not request.user.is_admin:
                return fail(
                    f'Outbound order "{order.code}" is already completed. '
                    'Only an admin can cancel a completed order (stock will be restored).',
                    code=403,
                )
            # Admin cancels a completed order → stock restoration signal fires
            with transaction.atomic():
                order._previous_status = order.status   # 'completed'
                order.status = OutOrder.Status.CANCELLED
                order.save(update_fields=['status', 'modify_time'])
                # ↑ signal: completed → cancelled → adjust_stock(+amount)

            logger.warning(
                'OutOrderCancelView: admin "%s" cancelled COMPLETED outbound order '
                '"%s" (id=%d). Stock restored for %d product(s).',
                request.user.username, order.code, order.id, order.lines.count(),
            )
            return ok(
                data=OutOrderReadSerializer(_base_qs().get(pk=pk)).data,
                message=(
                    f'Completed outbound order "{order.code}" has been cancelled. '
                    f'Stock has been restored for {order.lines.count()} product(s).'
                ),
            )

        # ── Draft → cancelled: any admin/stall_owner ─────────────────────
        if order.is_draft:
            with transaction.atomic():
                order._previous_status = order.status   # 'draft'
                order.status = OutOrder.Status.CANCELLED
                order.save(update_fields=['status', 'modify_time'])
                # ↑ signal: draft → cancelled → no stock change (Case 3)

            logger.info(
                'OutOrderCancelView: user "%s" cancelled draft outbound order '
                '"%s" (id=%d). No stock change.',
                request.user.username, order.code, order.id,
            )
            return ok(
                data=OutOrderReadSerializer(_base_qs().get(pk=pk)).data,
                message=f'Outbound order "{order.code}" has been cancelled.',
            )

        # ── Already cancelled ─────────────────────────────────────────────
        return fail(
            f'Outbound order "{order.code}" is already cancelled.', code=400
        )
