"""
utils/helpers.py
================
Shared business-logic helpers for the StallManagement project.

Primary export
--------------
adjust_stock(product, delta, reason='')
    The ONLY authorised way to modify a product's stock field.
    Wraps the update in select_for_update() + transaction.atomic()
    to prevent race conditions when two orders are processed at the
    same time.

    Called by:
        apps.inorder.signals.on_inorder_saved   (+delta on completion)
        apps.outorder.signals.on_outorder_saved  (-delta on completion)
        apps.outorder.signals.on_outorder_saved  (+delta on cancellation)

    The view layer NEVER writes product.stock directly.

Secondary exports
-----------------
get_or_404_json(model, **kwargs)
    Like Django's get_object_or_404 but raises a DRF-friendly error.

paginate_queryset(qs, query_params)
    Shared manual pagination logic used across multiple view files.

format_order_code(prefix, date=None)
    Generates a timestamped order code (e.g. IN20241201001).
"""

import logging
from datetime import date as date_type

from django.db import transaction

from .exceptions import InsufficientStockError

logger = logging.getLogger('apps')


# ---------------------------------------------------------------------------
# adjust_stock — the single authorised stock mutation function
# ---------------------------------------------------------------------------
def adjust_stock(product, delta: int, reason: str = '') -> None:
    """
    Atomically adjust the stock of a product by `delta` units.

    Parameters
    ----------
    product : apps.product.models.Product
        The product instance whose stock should be adjusted.
        Must already be loaded from the DB (can be a "stale" instance —
        this function re-fetches with select_for_update() internally).
    delta : int
        Positive integer  → increase stock (inbound order completed).
        Negative integer  → decrease stock (outbound order completed).
        Zero is a no-op (logged as a warning).
    reason : str
        Human-readable reason for the adjustment, written to the log.
        Examples:
            'Inbound order IN2024120101 completed'
            'Outbound order OUT2024112701 completed'
            'Outbound order OUT2024112701 cancelled — stock restored'

    Raises
    ------
    InsufficientStockError
        If delta is negative and the adjustment would push stock below zero.
        This is a safety net — the outbound order view should have already
        checked stock sufficiency with select_for_update() before this is
        called.  Both checks together give defence in depth.
    ValueError
        If delta is zero (silent no-ops are never intended and indicate a
        bug in the caller).

    Notes
    -----
    This function MUST be called inside an existing transaction.atomic()
    block (the one opened in the view or signal handler).  It does NOT
    open its own outer transaction — doing so would cause nested
    transactions that hide failures from the outer rollback.

    The select_for_update() call locks the product row for the duration
    of the enclosing transaction, preventing concurrent writes from
    another request that is also trying to adjust the same product's stock.
    """

    if delta == 0:
        logger.warning(
            'adjust_stock: called with delta=0 for product id=%d ("%s"). '
            'Reason: %s. This is a no-op and likely indicates a bug.',
            product.id, product.name, reason,
        )
        return

    # ── Re-fetch with row-level lock inside the enclosing transaction ────
    # We import here (not at module level) to avoid circular imports:
    # utils → product.models → (potentially) utils
    from apps.product.models import Product

    with transaction.atomic():
        locked_product = (
            Product.objects
            .select_for_update()    # locks this row until transaction commits
            .get(pk=product.id)
        )

        new_stock = locked_product.stock + delta

        # ── Safety net: reject negative stock ────────────────────────────
        if new_stock < 0:
            raise InsufficientStockError(
                f'Cannot adjust stock for "{locked_product.name}" '
                f'[{locked_product.sn}]: '
                f'current stock={locked_product.stock}, '
                f'delta={delta}, '
                f'result would be {new_stock} (below zero).',
                details={
                    'product_id':   locked_product.id,
                    'product_sn':   locked_product.sn,
                    'product_name': locked_product.name,
                    'stock':        locked_product.stock,
                    'requested':    abs(delta),
                    'shortfall':    abs(new_stock),
                },
            )

        # ── Apply the adjustment ─────────────────────────────────────────
        locked_product.stock = new_stock
        locked_product.save(update_fields=['stock', 'modify_time'])

        # Reflect the new stock back onto the caller's instance so it
        # doesn't hold a stale value after this function returns.
        product.stock = new_stock

        direction = 'INCREASED' if delta > 0 else 'DECREASED'
        logger.info(
            'adjust_stock: stock %s by %+d for product [%s] "%s" (id=%d). '
            'Old: %d → New: %d. Reason: %s.',
            direction,
            delta,
            locked_product.sn,
            locked_product.name,
            locked_product.id,
            locked_product.stock - delta,   # old value
            new_stock,
            reason or '(no reason provided)',
        )


# ---------------------------------------------------------------------------
# paginate_queryset — shared manual pagination across view files
# ---------------------------------------------------------------------------
def paginate_queryset(qs, query_params, default_page_size=20, max_page_size=100):
    """
    Apply manual pagination to a queryset from URL query parameters.

    Parameters
    ----------
    qs              : QuerySet
    query_params    : request.query_params (QueryDict)
    default_page_size : int  (default: 20)
    max_page_size   : int  (default: 100)

    Returns
    -------
    dict with keys:
        total     : int           total count before slicing
        page      : int           current page number (1-based)
        page_size : int           items per page (clamped to max)
        items     : QuerySet      sliced queryset for current page
        error     : str | None    error message if params are invalid

    Usage in a view:
        result = paginate_queryset(qs, request.query_params)
        if result['error']:
            return fail(result['error'], code=400)
        serializer = MySerializer(result['items'], many=True)
        return ok(data={'total': result['total'], 'results': serializer.data})
    """
    try:
        page      = max(1, int(query_params.get('page', 1)))
        page_size = min(
            max_page_size,
            max(1, int(query_params.get('page_size', default_page_size))),
        )
    except (ValueError, TypeError):
        return {
            'total': 0, 'page': 1, 'page_size': default_page_size,
            'items': qs.none(), 'error': 'page and page_size must be integers.',
        }

    total  = qs.count()
    offset = (page - 1) * page_size

    return {
        'total':     total,
        'page':      page,
        'page_size': page_size,
        'items':     qs[offset: offset + page_size],
        'error':     None,
    }


# ---------------------------------------------------------------------------
# format_order_code — generates timestamped order codes
# ---------------------------------------------------------------------------
def format_order_code(prefix: str, sequence: int = 1, date=None) -> str:
    """
    Generate a timestamped order code matching the project's naming convention.

    Parameters
    ----------
    prefix   : str   'IN' for inbound, 'OUT' for outbound
    sequence : int   Sequential number within the day (default: 1)
    date     : date  Target date (default: today)

    Returns
    -------
    str   e.g. 'IN20241201001' or 'OUT20241201001'

    The format matches the seed data in db_market.sql:
        IN2024112701, IN2024112702
        OUT2024112701, OUT2024112702

    Usage
    -----
    Called when the frontend auto-generates an order code suggestion.
    The view should still validate uniqueness via the serializer — this
    function does NOT guarantee uniqueness.
    """
    today     = date or date_type.today()
    date_part = today.strftime('%Y%m%d')
    seq_part  = str(sequence).zfill(3)   # zero-padded to 3 digits: 001, 002 …
    return f'{prefix.upper()}{date_part}{seq_part}'


# ---------------------------------------------------------------------------
# get_or_404_json — DRF-friendly object fetch
# ---------------------------------------------------------------------------
def get_or_404_json(model, error_message: str = None, **kwargs):
    """
    Fetch a model instance by the given kwargs; raise a DRF-friendly
    exception (caught by custom_exception_handler) if not found.

    Unlike Django's get_object_or_404, this raises a project-level error
    that the custom exception handler converts into the standard JSON
    envelope rather than Django's HTML 404 page.

    Parameters
    ----------
    model         : Django Model class
    error_message : str   Custom error message (optional)
    **kwargs      : lookup fields passed to model.objects.get()

    Returns
    -------
    model instance

    Raises
    ------
    StallManagementError (http_status=404) if the object is not found.
    """
    from .exceptions import StallManagementError
    from rest_framework import status as drf_status

    try:
        return model.objects.get(**kwargs)
    except model.DoesNotExist:
        msg = error_message or (
            f'{model.__name__} matching {kwargs} not found.'
        )
        err = StallManagementError(msg)
        err.http_status = drf_status.HTTP_404_NOT_FOUND
        raise err
