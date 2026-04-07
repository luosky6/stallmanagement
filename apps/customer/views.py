"""
apps/customer/views.py
======================
Customer management views — accessible to admin and stall_owner roles.

Views
-----
CustomerListCreateView      GET  /api/customers/         List / Create
CustomerRetrieveUpdateView  GET  /api/customers/<id>/    Retrieve / Update
CustomerDeleteView          DELETE /api/customers/<id>/  Hard-delete (with order guard)

Permission model
----------------
- RoleCheckMiddleware already restricts /api/customers/ to admin + stall_owner.
- DRF permission class IsAdminOrStallOwner is applied as the secondary guard.
- Customers (role='customer') have no access to this module — they interact
  with the stall as buyers, but they cannot manage the contacts directory.

Hard delete vs soft delete
--------------------------
The `customer` table in db_market.sql has no `is_deleted` column, so we
perform genuine hard deletes.  However, before deleting a contact, we check
whether any inbound or outbound orders still reference it.  If they do,
deletion is refused to protect referential integrity beyond what the DB
ON DELETE CASCADE would do (we prefer to keep the order history intact).

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

from .models import Customer
from .serializers import CustomerReadSerializer, CustomerWriteSerializer
from api.permissions import IsAdminOrStallOwnerRole

logger = logging.getLogger('apps')


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def ok(data=None, message='Success', code=200):
    return Response({'success': True,  'code': code, 'message': message, 'data': data}, status=code)

def fail(message='Error', code=400, data=None):
    return Response({'success': False, 'code': code, 'message': message, 'data': data}, status=code)


# ---------------------------------------------------------------------------
# 1. CustomerListCreateView — GET /api/customers/   POST /api/customers/
# ---------------------------------------------------------------------------
class CustomerListCreateView(APIView):
    """
    GET  /api/customers/   → paginated, filtered list of all contacts
    POST /api/customers/   → create a new supplier or buyer contact

    Query parameters (GET)
    ----------------------
    customer_type   Filter by type     (supplier | buyer)
    search          Case-insensitive search on name, phone, address
    page            Page number        (default: 1)
    page_size       Items per page     (default: 20, max: 100)
    ordering        Sort field         (name | customer_type | create_time)
                    Prefix with '-' to reverse, e.g. -create_time
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    # ── GET ─────────────────────────────────────────────────────────────
    def get(self, request):
        qs = Customer.objects.all()

        # ── Filters ─────────────────────────────────────────────────────
        customer_type = request.query_params.get('customer_type', '').strip()
        search        = request.query_params.get('search', '').strip()
        ordering      = request.query_params.get('ordering', 'customer_type')

        if customer_type:
            valid_types = [ct.value for ct in Customer.CustomerType]
            if customer_type not in valid_types:
                return fail(
                    f'Invalid customer_type. Choose from: {valid_types}.',
                    code=400,
                )
            qs = qs.filter(customer_type=customer_type)

        if search:
            qs = qs.filter(
                Q(name__icontains=search)    |
                Q(phone__icontains=search)   |
                Q(address__icontains=search)
            )

        # ── Ordering ─────────────────────────────────────────────────────
        allowed_ordering = {'name', '-name', 'customer_type', '-customer_type',
                            'create_time', '-create_time'}
        if ordering not in allowed_ordering:
            ordering = 'customer_type'
        qs = qs.order_by(ordering)

        # ── Pagination ───────────────────────────────────────────────────
        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 20))))
        except (ValueError, TypeError):
            return fail('page and page_size must be integers.', code=400)

        total     = qs.count()
        offset    = (page - 1) * page_size
        customers = qs[offset: offset + page_size]

        serializer = CustomerReadSerializer(customers, many=True)
        return ok(
            data={
                'total':     total,
                'page':      page,
                'page_size': page_size,
                'results':   serializer.data,
            },
            message=f'{total} contact(s) found.',
        )

    # ── POST ─────────────────────────────────────────────────────────────
    def post(self, request):
        serializer = CustomerWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        customer = serializer.save()
        logger.info(
            'CustomerListCreateView: user "%s" created %s "%s" (id=%d).',
            request.user.username,
            customer.customer_type,
            customer.name,
            customer.id,
        )
        return ok(
            data=CustomerReadSerializer(customer).data,
            message=f'{customer.get_customer_type_display()} "{customer.name}" created successfully.',
            code=201,
        )


# ---------------------------------------------------------------------------
# 2. CustomerRetrieveUpdateView — GET /api/customers/<id>/   PATCH /api/customers/<id>/
# ---------------------------------------------------------------------------
class CustomerRetrieveUpdateView(APIView):
    """
    GET   /api/customers/<id>/   → retrieve a single contact's full details
    PATCH /api/customers/<id>/   → partial update (any combination of fields)

    Notes on type change
    --------------------
    Changing customer_type from 'supplier' to 'buyer' (or vice versa) is
    allowed only if the contact has no orders of the conflicting type.
    For example, a supplier that has existing inbound orders cannot be changed
    to a buyer, as that would make those inbound orders reference a buyer
    instead of a supplier, which is logically inconsistent.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    # ── GET ─────────────────────────────────────────────────────────────
    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        return ok(
            data=CustomerReadSerializer(customer).data,
            message='Contact retrieved successfully.',
        )

    # ── PATCH ───────────────────────────────────────────────────────────
    def patch(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)

        # ── Guard: type change conflicts with existing orders ────────────
        new_type = request.data.get('customer_type')
        if new_type and new_type != customer.customer_type:
            if new_type == Customer.CustomerType.BUYER and customer.has_inbound_orders:
                return fail(
                    f'Cannot change "{customer.name}" from supplier to buyer: '
                    'this contact has existing inbound (purchase) orders. '
                    'Remove or reassign those orders first.',
                    code=400,
                )
            if new_type == Customer.CustomerType.SUPPLIER and customer.has_outbound_orders:
                return fail(
                    f'Cannot change "{customer.name}" from buyer to supplier: '
                    'this contact has existing outbound (sales) orders. '
                    'Remove or reassign those orders first.',
                    code=400,
                )

        serializer = CustomerWriteSerializer(
            customer, data=request.data, partial=True
        )
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        updated = serializer.save()
        logger.info(
            'CustomerRetrieveUpdateView: user "%s" updated %s "%s" (id=%d).',
            request.user.username,
            updated.customer_type,
            updated.name,
            updated.id,
        )
        return ok(
            data=CustomerReadSerializer(updated).data,
            message=f'Contact "{updated.name}" updated successfully.',
        )


# ---------------------------------------------------------------------------
# 3. CustomerDeleteView — DELETE /api/customers/<id>/
# ---------------------------------------------------------------------------
class CustomerDeleteView(APIView):
    """
    DELETE /api/customers/<id>/

    Hard-deletes the contact record.

    Guard — refuses deletion if the contact has any linked orders:
    - A supplier with inbound orders cannot be deleted (order history
      would lose its supplier reference).
    - A buyer with outbound orders cannot be deleted for the same reason.

    If deletion is genuinely required, the admin must first delete or
    reassign all linked orders through the inorder / outorder endpoints.

    Why hard delete?
    ----------------
    The `customer` table in db_market.sql has no is_deleted column, so
    soft-delete is not applicable here.  The order guard above ensures we
    never lose referential integrity silently.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def delete(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)

        # ── Guard: linked inbound orders ─────────────────────────────────
        inbound_count = customer.inorder_set.count()
        if inbound_count > 0:
            return fail(
                f'Cannot delete "{customer.name}": '
                f'this contact is referenced by {inbound_count} inbound order(s). '
                'Delete or reassign those orders first.',
                code=400,
            )

        # ── Guard: linked outbound orders ────────────────────────────────
        outbound_count = customer.outorder_set.count()
        if outbound_count > 0:
            return fail(
                f'Cannot delete "{customer.name}": '
                f'this contact is referenced by {outbound_count} outbound order(s). '
                'Delete or reassign those orders first.',
                code=400,
            )

        name = customer.name
        ctype = customer.get_customer_type_display()
        customer.delete()   # genuine hard delete (no SoftDeleteMixin on this model)

        logger.info(
            'CustomerDeleteView: user "%s" deleted %s "%s" (id=%d).',
            request.user.username, ctype, name, pk,
        )
        return ok(message=f'{ctype} "{name}" deleted successfully.')


# ---------------------------------------------------------------------------
# 4. CustomerTypeListView — GET /api/customers/types/
# ---------------------------------------------------------------------------
class CustomerTypeListView(APIView):
    """
    GET /api/customers/types/

    Returns the two valid customer_type choices as a lookup list.
    Used by the Vue frontend to populate the type dropdown without
    hard-coding the values in the client.

    Permission: any authenticated user.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        types = [
            {'value': ct.value, 'label': ct.label}
            for ct in Customer.CustomerType
        ]
        return ok(data=types, message='Customer types retrieved.')
