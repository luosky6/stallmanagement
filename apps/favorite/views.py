"""
apps/favorite/views.py
======================
Favourites management views.

Design principles
-----------------
1. TOGGLE semantics (not separate add/remove endpoints)
   The Vue frontend shows a single star/heart button that is either
   filled (favourited) or empty (not favourited).  A single POST to
   /toggle/<product_id>/ adds if absent, removes if present — exactly
   mirroring the frontend's toggleFav(item) method.

2. User-scoped queries
   Every queryset is filtered by request.user.  Users can only see and
   manage their own favourites.  Admins and stall_owners do not get a
   "view all favourites" endpoint — this is private user data.

3. Atomic toggle via get_or_create / filter().delete()
   Using get_or_create avoids a check-then-act race condition on add.
   Using filter().delete() avoids a DoesNotExist exception on remove
   if a concurrent request already removed the record.

Permission model
----------------
All endpoints require IsAuthenticated.
All three roles (admin, stall_owner, customer) may use favourites.
RoleCheckMiddleware allows /api/favorites/ for all authenticated users.

Views
-----
FavoriteListView        GET  /api/favorites/                  List own favourites
FavoriteToggleView      POST /api/favorites/toggle/<pid>/     Add or remove
FavoriteCheckView       GET  /api/favorites/check/<pid>/      Is this product favourited?
FavoriteClearView       DELETE /api/favorites/clear/          Remove all own favourites
"""

import logging

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Favorite
from .serializers import FavoriteReadSerializer, FavoriteToggleResponseSerializer
from apps.product.models import Product

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
def _user_favorites_qs(user):
    """
    Return the base queryset for a user's favourites with select_related
    and prefetch to avoid N+1 queries when serialising the product snapshot.
    """
    return (
        Favorite.objects
        .filter(user=user)
        .select_related('product', 'product__category')
        .order_by('-create_time')
    )


# ---------------------------------------------------------------------------
# 1. FavoriteListView — GET /api/favorites/
# ---------------------------------------------------------------------------
class FavoriteListView(APIView):
    """
    GET /api/favorites/

    Returns all products favourited by the requesting user, ordered by
    most recently favourited first.

    Query parameters
    ----------------
    search          Case-insensitive search on product name, sn, description
    category_id     Filter by product category
    stock_status    'ok' | 'low' | 'out'
    page / page_size

    The response includes the product's current stock status so the
    favourites panel can render the same stock badges as the inventory view.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = _user_favorites_qs(request.user)

        # ── Filters on the nested product ────────────────────────────────
        search = request.query_params.get('search', '').strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(product__name__icontains=search)        |
                Q(product__sn__icontains=search)          |
                Q(product__description__icontains=search)
            )

        category_id = request.query_params.get('category_id', '').strip()
        if category_id:
            try:
                qs = qs.filter(product__category_id=int(category_id))
            except ValueError:
                return fail('category_id must be an integer.', code=400)

        from apps.product.models import LOW_STOCK_THRESHOLD
        stock_status = request.query_params.get('stock_status', '').strip().lower()
        if stock_status == 'out':
            qs = qs.filter(product__stock=0)
        elif stock_status == 'low':
            qs = qs.filter(product__stock__gt=0, product__stock__lt=LOW_STOCK_THRESHOLD)
        elif stock_status == 'ok':
            qs = qs.filter(product__stock__gte=LOW_STOCK_THRESHOLD)
        elif stock_status:
            return fail("stock_status must be 'ok', 'low', or 'out'.", code=400)

        # ── Pagination ───────────────────────────────────────────────────
        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 20))))
        except (ValueError, TypeError):
            return fail('page and page_size must be integers.', code=400)

        total     = qs.count()
        offset    = (page - 1) * page_size
        favorites = qs[offset: offset + page_size]

        serializer = FavoriteReadSerializer(favorites, many=True)
        return ok(
            data={
                'total':     total,
                'page':      page,
                'page_size': page_size,
                'results':   serializer.data,
            },
            message=f'{total} favourite(s) found.',
        )


# ---------------------------------------------------------------------------
# 2. FavoriteToggleView — POST /api/favorites/toggle/<product_id>/
# ---------------------------------------------------------------------------
class FavoriteToggleView(APIView):
    """
    POST /api/favorites/toggle/<product_id>/

    Idempotent toggle:
      - If the product is NOT in the user's favourites → add it (201 Created)
      - If the product IS in the user's favourites     → remove it (200 OK)

    No request body is needed — the product is identified by the URL path.
    This mirrors the frontend's single toggleFav(item) method.

    Response body:
    {
        "success": true,
        "data": {
            "action":       "added" | "removed",
            "is_favourite": true | false,
            "product_id":   <int>,
            "favorite_id":  <int> | null
        }
    }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, product_id):
        # Validate the product exists
        product = get_object_or_404(Product, pk=product_id)

        # ── Toggle: get_or_create is atomic at the DB level ──────────────
        favorite, created = Favorite.objects.get_or_create(
            user    = request.user,
            product = product,
        )

        if created:
            # Product was NOT favourited → now added
            logger.debug(
                'FavoriteToggleView: user "%s" ADDED product [%s] "%s" (id=%d) to favourites.',
                request.user.username, product.sn, product.name, product.id,
            )
            response_data = {
                'action':       'added',
                'is_favourite': True,
                'product_id':   product.id,
                'favorite_id':  favorite.id,
            }
            return ok(
                data=response_data,
                message=f'"{product.name}" added to your favourites.',
                code=201,
            )
        else:
            # Product WAS already favourited → now removed
            favorite.delete()
            logger.debug(
                'FavoriteToggleView: user "%s" REMOVED product [%s] "%s" (id=%d) from favourites.',
                request.user.username, product.sn, product.name, product.id,
            )
            response_data = {
                'action':       'removed',
                'is_favourite': False,
                'product_id':   product.id,
                'favorite_id':  None,
            }
            return ok(
                data=response_data,
                message=f'"{product.name}" removed from your favourites.',
            )


# ---------------------------------------------------------------------------
# 3. FavoriteCheckView — GET /api/favorites/check/<product_id>/
# ---------------------------------------------------------------------------
class FavoriteCheckView(APIView):
    """
    GET /api/favorites/check/<product_id>/

    Returns whether the requesting user has favourited a specific product.
    Used by the Vue frontend when loading a product detail view to set the
    initial state of the star/heart toggle button without fetching the full
    favourites list.

    Response:
    {
        "success": true,
        "data": {
            "product_id":   <int>,
            "is_favourite": true | false,
            "favorite_id":  <int> | null
        }
    }
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, product_id):
        # Validate product exists
        product = get_object_or_404(Product, pk=product_id)

        try:
            favorite = Favorite.objects.get(user=request.user, product=product)
            return ok(
                data={
                    'product_id':   product.id,
                    'is_favourite': True,
                    'favorite_id':  favorite.id,
                },
                message=f'"{product.name}" is in your favourites.',
            )
        except Favorite.DoesNotExist:
            return ok(
                data={
                    'product_id':   product.id,
                    'is_favourite': False,
                    'favorite_id':  None,
                },
                message=f'"{product.name}" is not in your favourites.',
            )


# ---------------------------------------------------------------------------
# 4. FavoriteClearView — DELETE /api/favorites/clear/
# ---------------------------------------------------------------------------
class FavoriteClearView(APIView):
    """
    DELETE /api/favorites/clear/

    Removes ALL favourites for the requesting user in a single operation.
    Useful when the user wants to start fresh or when testing.

    Returns the count of removed favourites so the frontend can
    update the UI (e.g. reset all star buttons to unfilled state).

    Permission: any authenticated user (operates only on their own data).
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request):
        count, _ = Favorite.objects.filter(user=request.user).delete()

        logger.info(
            'FavoriteClearView: user "%s" cleared all %d favourite(s).',
            request.user.username, count,
        )
        return ok(
            data={'removed_count': count},
            message=(
                f'All {count} favourite(s) removed.'
                if count else
                'You had no favourites to remove.'
            ),
        )
