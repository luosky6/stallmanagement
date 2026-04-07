"""
apps/category/views.py
======================
Category management views.

Permission model
----------------
GET  (list / retrieve / lookup)  →  any authenticated user
     Customers need to read categories to filter products in the inventory view.

POST / PATCH / DELETE            →  admin + stall_owner only
     Creating, renaming, or removing categories is a management operation.

Views
-----
CategoryListCreateView      GET  /api/categories/             List / Create
CategoryRetrieveUpdateView  GET  /api/categories/<id>/        Retrieve / Update
CategoryDeleteView          DELETE /api/categories/<id>/      Delete (product guard)
CategoryLookupView          GET  /api/categories/lookup/      Lightweight id+name list

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

from .models import Category
from .serializers import (
    CategoryReadSerializer,
    CategoryWriteSerializer,
    CategorySummarySerializer,
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
# 1. CategoryListCreateView — GET /api/categories/   POST /api/categories/
# ---------------------------------------------------------------------------
class CategoryListCreateView(APIView):
    """
    GET  /api/categories/   → list all categories (any authenticated user)
    POST /api/categories/   → create a new category (admin + stall_owner)

    Query parameters (GET)
    ----------------------
    search      Case-insensitive search on name and description
    ordering    Sort field: name | -name | create_time | -create_time
                (default: name)
    with_count  'true' to include product_count in the response
                (default: true; pass 'false' for a lighter payload)
    """

    def get_permissions(self):
        """
        GET  → IsAuthenticated only (customers can read categories)
        POST → IsAuthenticated + IsAdminOrStallOwnerRole
        """
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsAdminOrStallOwnerRole()]

    # ── GET ─────────────────────────────────────────────────────────────
    def get(self, request):
        qs = Category.objects.all()

        # ── Search ──────────────────────────────────────────────────────
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search) | Q(description__icontains=search)
            )

        # ── Ordering ─────────────────────────────────────────────────────
        allowed_ordering = {'name', '-name', 'create_time', '-create_time'}
        ordering = request.query_params.get('ordering', 'name')
        if ordering not in allowed_ordering:
            ordering = 'name'
        qs = qs.order_by(ordering)

        # ── Serialise ────────────────────────────────────────────────────
        # with_count=false returns the lightweight summary (id + name only)
        # which is used to populate the product-form category dropdown.
        with_count = request.query_params.get('with_count', 'true').lower()
        if with_count == 'false':
            serializer = CategorySummarySerializer(qs, many=True)
        else:
            serializer = CategoryReadSerializer(qs, many=True)

        return ok(
            data={
                'total':   qs.count(),
                'results': serializer.data,
            },
            message=f'{qs.count()} categor{"y" if qs.count() == 1 else "ies"} found.',
        )

    # ── POST ─────────────────────────────────────────────────────────────
    def post(self, request):
        serializer = CategoryWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        category = serializer.save()
        logger.info(
            'CategoryListCreateView: user "%s" created category "%s" (id=%d).',
            request.user.username, category.name, category.id,
        )
        return ok(
            data=CategoryReadSerializer(category).data,
            message=f'Category "{category.name}" created successfully.',
            code=201,
        )


# ---------------------------------------------------------------------------
# 2. CategoryRetrieveUpdateView — GET /api/categories/<id>/
#                                  PATCH /api/categories/<id>/
# ---------------------------------------------------------------------------
class CategoryRetrieveUpdateView(APIView):
    """
    GET   /api/categories/<id>/   → retrieve a single category with product_count
    PATCH /api/categories/<id>/   → partial update (name and/or description)

    Any authenticated user may GET; only admin + stall_owner may PATCH.
    """

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsAdminOrStallOwnerRole()]

    # ── GET ─────────────────────────────────────────────────────────────
    def get(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        return ok(
            data=CategoryReadSerializer(category).data,
            message='Category retrieved successfully.',
        )

    # ── PATCH ───────────────────────────────────────────────────────────
    def patch(self, request, pk):
        category = get_object_or_404(Category, pk=pk)

        serializer = CategoryWriteSerializer(
            category, data=request.data, partial=True
        )
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        updated = serializer.save()
        logger.info(
            'CategoryRetrieveUpdateView: user "%s" updated category "%s" (id=%d).',
            request.user.username, updated.name, updated.id,
        )
        return ok(
            data=CategoryReadSerializer(updated).data,
            message=f'Category "{updated.name}" updated successfully.',
        )


# ---------------------------------------------------------------------------
# 3. CategoryDeleteView — DELETE /api/categories/<id>/
# ---------------------------------------------------------------------------
class CategoryDeleteView(APIView):
    """
    DELETE /api/categories/<id>/

    Hard-deletes the category.

    Guard — mirrors the DB-level ON DELETE RESTRICT on products.category_id:
    If any products are still assigned to this category the deletion is
    refused at the application layer with a clear error message, before the
    request even reaches the database constraint.

    The response includes the count of blocking products so the admin knows
    how many products need to be reassigned first.

    Permission: admin + stall_owner only.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStallOwnerRole]

    def delete(self, request, pk):
        category = get_object_or_404(Category, pk=pk)

        # ── Product guard ────────────────────────────────────────────────
        product_count = category.product_set.count()
        if product_count > 0:
            return fail(
                f'Cannot delete category "{category.name}": '
                f'{product_count} product(s) are still assigned to it. '
                'Reassign or delete those products first.',
                code=400,
                data={'blocking_product_count': product_count},
            )

        name = category.name
        category.delete()

        logger.info(
            'CategoryDeleteView: user "%s" deleted category "%s" (id=%d).',
            request.user.username, name, pk,
        )
        return ok(message=f'Category "{name}" deleted successfully.')


# ---------------------------------------------------------------------------
# 4. CategoryLookupView — GET /api/categories/lookup/
# ---------------------------------------------------------------------------
class CategoryLookupView(APIView):
    """
    GET /api/categories/lookup/

    Returns a lightweight list of { id, name } pairs for every category.
    Intended for use by the product add/edit form's category dropdown and
    the inventory filter pill row in the Vue frontend.

    Returns all categories with no pagination (the list is small and stable).
    Permission: any authenticated user (customers also need this to filter
    the product list).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        categories = Category.objects.order_by('name')
        serializer = CategorySummarySerializer(categories, many=True)
        return ok(
            data=serializer.data,
            message=f'{len(serializer.data)} categor{"y" if len(serializer.data) == 1 else "ies"} available.',
        )
