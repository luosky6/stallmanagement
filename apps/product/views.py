"""
apps/product/views.py
=====================
Product management views.

Permission model
----------------
GET  (list / retrieve / low-stock / lookup)
    →  any authenticated user
    Customers need to browse the inventory and view product details.

POST / PATCH / DELETE
    →  admin + stall_owner only

Views
-----
ProductListCreateView       GET  /api/products/                List / Create
ProductRetrieveUpdateView   GET  /api/products/<id>/           Retrieve / Update
ProductDeleteView           DELETE /api/products/<id>/         Delete (order-line guard)
ProductLowStockView         GET  /api/products/low_stock/      Products below threshold
ProductLookupView           GET  /api/products/lookup/         Lightweight id+sn+name list

Search & filter (GET /api/products/)
--------------------------------------
search          Free-text search across sn, name, description
category_id     Filter by category FK
stock_status    'ok' | 'low' | 'out'
price_min       Minimum price (inclusive)
price_max       Maximum price (inclusive)
ordering        name | -name | price | -price | stock | -stock | create_time | -create_time
page / page_size

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

from .models import Product, LOW_STOCK_THRESHOLD
from .serializers import (
    ProductReadSerializer,
    ProductWriteSerializer,
    ProductSummarySerializer,
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
# Shared queryset builder — reused by list and low_stock views
# ---------------------------------------------------------------------------
def _build_product_qs(query_params):
    """
    Apply filters and ordering to the base Product queryset based on the
    request query parameters.

    Returns (queryset, error_message | None).
    """
    qs = Product.objects.select_related('category').all()

    # ── Free-text search ─────────────────────────────────────────────────
    search = query_params.get('search', '').strip()
    if search:
        qs = qs.filter(
            Q(sn__icontains=search)          |
            Q(name__icontains=search)        |
            Q(description__icontains=search)
        )

    # ── Category filter ───────────────────────────────────────────────────
    category_id = query_params.get('category_id', '').strip()
    if category_id:
        try:
            qs = qs.filter(category_id=int(category_id))
        except ValueError:
            return None, 'category_id must be an integer.'

    # ── Stock status filter ───────────────────────────────────────────────
    stock_status = query_params.get('stock_status', '').strip().lower()
    if stock_status == 'out':
        qs = qs.filter(stock=0)
    elif stock_status == 'low':
        qs = qs.filter(stock__gt=0, stock__lt=LOW_STOCK_THRESHOLD)
    elif stock_status == 'ok':
        qs = qs.filter(stock__gte=LOW_STOCK_THRESHOLD)
    elif stock_status:
        return None, "stock_status must be 'ok', 'low', or 'out'."

    # ── Price range filter ────────────────────────────────────────────────
    price_min = query_params.get('price_min', '').strip()
    price_max = query_params.get('price_max', '').strip()
    if price_min:
        try:
            qs = qs.filter(price__gte=float(price_min))
        except ValueError:
            return None, 'price_min must be a number.'
    if price_max:
        try:
            qs = qs.filter(price__lte=float(price_max))
        except ValueError:
            return None, 'price_max must be a number.'

    # ── Ordering ─────────────────────────────────────────────────────────
    allowed_ordering = {
        'name', '-name',
        'price', '-price',
        'stock', '-stock',
        'create_time', '-create_time',
        'sn', '-sn',
    }
    ordering = query_params.get('ordering', 'category')
    if ordering not in allowed_ordering:
        ordering = 'name'
    qs = qs.order_by(ordering)

    return qs, None


# ---------------------------------------------------------------------------
# 1. ProductListCreateView — GET /api/products/   POST /api/products/
# ---------------------------------------------------------------------------
class ProductListCreateView(APIView):
    """
    GET  /api/products/  → paginated, filtered, searchable product list
    POST /api/products/  → create a new product (admin + stall_owner)
    """

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsAdminOrStallOwnerRole()]

    # ── GET ─────────────────────────────────────────────────────────────
    def get(self, request):
        qs, error = _build_product_qs(request.query_params)
        if error:
            return fail(error, code=400)

        # ── Pagination ───────────────────────────────────────────────────
        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 20))))
        except (ValueError, TypeError):
            return fail('page and page_size must be integers.', code=400)

        total    = qs.count()
        offset   = (page - 1) * page_size
        products = qs[offset: offset + page_size]

        serializer = ProductReadSerializer(products, many=True)
        return ok(
            data={
                'total':               total,
                'page':                page,
                'page_size':           page_size,
                'low_stock_threshold': LOW_STOCK_THRESHOLD,
                'results':             serializer.data,
            },
            message=f'{total} product(s) found.',
        )

    # ── POST ─────────────────────────────────────────────────────────────
    def post(self, request):
        serializer = ProductWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        product = serializer.save()
        logger.info(
            'ProductListCreateView: user "%s" created product [%s] "%s" (id=%d).',
            request.user.username, product.sn, product.name, product.id,
        )
        return ok(
            data=ProductReadSerializer(product).data,
            message=f'Product "{product.name}" created successfully.',
            code=201,
        )


# ---------------------------------------------------------------------------
# 2. ProductRetrieveUpdateView — GET /api/products/<id>/
#                                 PATCH /api/products/<id>/
# ---------------------------------------------------------------------------
class ProductRetrieveUpdateView(APIView):
    """
    GET   /api/products/<id>/  → retrieve single product with full details
    PATCH /api/products/<id>/  → partial update any fields except stock
                                  (stock is managed by order signals only)
    """

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsAdminOrStallOwnerRole()]

    # ── GET ─────────────────────────────────────────────────────────────
    def get(self, request, pk):
        product = get_object_or_404(
            Product.objects.select_related('category'), pk=pk
        )
        return ok(
            data=ProductReadSerializer(product).data,
            message='Product retrieved successfully.',
        )

    # ── PATCH ───────────────────────────────────────────────────────────
    def patch(self, request, pk):
        product = get_object_or_404(Product, pk=pk)

        # ── Stock write guard ────────────────────────────────────────────
        # Stock must only be modified via inbound/outbound order signals
        # (utils.helpers.adjust_stock wrapped in transaction.atomic).
        # Direct stock writes through this endpoint are blocked to prevent
        # race conditions and broken order history.
        if 'stock' in request.data:
            return fail(
                'Stock cannot be edited directly. '
                'Create an inbound or outbound order to adjust stock levels.',
                code=400,
            )

        serializer = ProductWriteSerializer(product, data=request.data, partial=True)
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        updated = serializer.save()
        logger.info(
            'ProductRetrieveUpdateView: user "%s" updated product [%s] "%s" (id=%d).',
            request.user.username, updated.sn, updated.name, updated.id,
        )
        return ok(
            data=ProductReadSerializer(
                Product.objects.select_related('category').get(pk=updated.pk)
            ).data,
            message=f'Product "{updated.name}" updated successfully.',
        )


# ---------------------------------------------------------------------------
# 3. ProductDeleteView — DELETE /api/products/<id>/
# ---------------------------------------------------------------------------
class ProductDeleteView(APIView):
    """
    DELETE /api/products/<id>/

    Hard-deletes the product.

    Guard — refuses deletion if the product is referenced by any
    inbound or outbound order line.  Deleting a product that appears in
    historical orders would corrupt the order history.  The admin must
    first delete all linked orders before the product can be removed.

    Permission: admin + stall_owner only.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def delete(self, request, pk):
        product = get_object_or_404(Product, pk=pk)

        # ── Order-line guard ─────────────────────────────────────────────
        inbound_count  = product.inorderproduct_set.count()
        outbound_count = product.outorderproduct_set.count()

        if inbound_count > 0 or outbound_count > 0:
            return fail(
                f'Cannot delete product "{product.name}" [{product.sn}]: '
                f'it is referenced by {inbound_count} inbound order line(s) and '
                f'{outbound_count} outbound order line(s). '
                'Delete those orders first.',
                code=400,
                data={
                    'inbound_order_line_count':  inbound_count,
                    'outbound_order_line_count': outbound_count,
                },
            )

        name = product.name
        sn   = product.sn
        product.delete()

        logger.info(
            'ProductDeleteView: user "%s" deleted product [%s] "%s" (id=%d).',
            request.user.username, sn, name, pk,
        )
        return ok(message=f'Product "{name}" [{sn}] deleted successfully.')


# ---------------------------------------------------------------------------
# 4. ProductLowStockView — GET /api/products/low_stock/
# ---------------------------------------------------------------------------
class ProductLowStockView(APIView):
    """
    GET /api/products/low_stock/

    Returns all products whose stock is below LOW_STOCK_THRESHOLD (20).
    Supports the same search / category_id / ordering / pagination params
    as the main product list.

    Used by the Vue Dashboard's summary card ("Low Stock Items") and the
    inventory row colouring (tr.row-low).

    Permission: admin + stall_owner (customers do not see stock alerts).
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def get(self, request):
        qs, error = _build_product_qs(request.query_params)
        if error:
            return fail(error, code=400)

        # Override any stock_status filter — this endpoint always returns low stock
        qs = qs.filter(stock__lt=LOW_STOCK_THRESHOLD)

        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 20))))
        except (ValueError, TypeError):
            return fail('page and page_size must be integers.', code=400)

        total    = qs.count()
        offset   = (page - 1) * page_size
        products = qs[offset: offset + page_size]

        serializer = ProductReadSerializer(products, many=True)
        return ok(
            data={
                'total':               total,
                'page':                page,
                'page_size':           page_size,
                'low_stock_threshold': LOW_STOCK_THRESHOLD,
                'results':             serializer.data,
            },
            message=(
                f'{total} product(s) with stock below {LOW_STOCK_THRESHOLD} units.'
                if total else
                'All products have adequate stock levels.'
            ),
        )


# ---------------------------------------------------------------------------
# 5. ProductLookupView — GET /api/products/lookup/
# ---------------------------------------------------------------------------
class ProductLookupView(APIView):
    """
    GET /api/products/lookup/

    Returns a lightweight list of { id, sn, name, price, stock } for all
    products.  Used by:
      - Inbound order form → supplier line-item product dropdown
      - Outbound order form → buyer line-item product dropdown
        (stock is included so the form can show available quantity)

    Optionally filtered by category_id and stock_status query params.
    No pagination — the dropdown needs all relevant options at once.

    Permission: admin + stall_owner (order forms are not accessible to customers).
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def get(self, request):
        qs = Product.objects.all().order_by('category', 'name')

        category_id = request.query_params.get('category_id', '').strip()
        if category_id:
            try:
                qs = qs.filter(category_id=int(category_id))
            except ValueError:
                return fail('category_id must be an integer.', code=400)

        # Optionally exclude out-of-stock products from outbound order lookup
        exclude_out_of_stock = request.query_params.get('exclude_out_of_stock', '').lower()
        if exclude_out_of_stock == 'true':
            qs = qs.filter(stock__gt=0)

        serializer = ProductSummarySerializer(qs, many=True)
        return ok(
            data=serializer.data,
            message=f'{len(serializer.data)} product(s) available.',
        )
