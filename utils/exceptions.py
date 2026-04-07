"""
utils/exceptions.py
===================
Custom exception classes for the StallManagement project.

These exceptions are raised in business-logic code (helpers, signals,
views) and caught at the view layer to return structured JSON error
responses via the custom DRF exception handler (also defined here).

Hierarchy
---------
Exception
└── StallManagementError          Base for all project exceptions
    ├── InsufficientStockError    Stock check fails on outbound order
    ├── OrderImmutableError       Attempt to edit a non-draft order
    ├── InvalidStatusTransition   Illegal order status change
    └── StallNotOperationalError  Order attempted on inactive/suspended stall

DRF integration
---------------
custom_exception_handler() is registered in settings.py:
    REST_FRAMEWORK = {
        'EXCEPTION_HANDLER': 'utils.exceptions.custom_exception_handler'
    }
It wraps all unhandled DRF and project exceptions into the standard
response envelope: { success, code, message, data }.
"""

import logging

from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger('apps')


# ---------------------------------------------------------------------------
# Base exception
# ---------------------------------------------------------------------------
class StallManagementError(Exception):
    """
    Base class for all StallManagement domain exceptions.

    Attributes
    ----------
    message : str
        Human-readable error description (safe to show in API responses).
    details : any
        Optional structured data (e.g. list of stock shortfalls).
        Set to None if not applicable.
    http_status : int
        HTTP status code this exception maps to (default 400).
    """

    default_message = 'An unexpected error occurred.'
    http_status     = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str = None, details=None):
        self.message = message or self.default_message
        self.details = details
        super().__init__(self.message)

    def __str__(self):
        return self.message


# ---------------------------------------------------------------------------
# InsufficientStockError
# ---------------------------------------------------------------------------
class InsufficientStockError(StallManagementError):
    """
    Raised when an outbound order line requests more units than are
    currently in stock.

    Raised by
    ---------
    utils.helpers.adjust_stock()         (delta would push stock negative)
    apps.outorder.views._check_stock_for_lines()  (pre-completion check)

    The `details` attribute is a list of dicts, one per under-stocked product:
    [
        {
            "product_id":   1,
            "product_sn":   "CLT-001",
            "product_name": "Men's T-Shirt",
            "stock":        5,
            "requested":    20,
            "shortfall":    15
        },
        ...
    ]
    """

    default_message = 'Insufficient stock for one or more products.'
    http_status     = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str = None, details=None):
        super().__init__(message or self.default_message, details)


# ---------------------------------------------------------------------------
# OrderImmutableError
# ---------------------------------------------------------------------------
class OrderImmutableError(StallManagementError):
    """
    Raised when an attempt is made to edit or delete an order that is
    no longer in 'draft' status (completed or cancelled orders are
    read-only records).

    Raised by
    ---------
    apps.inorder.views and apps.outorder.views PATCH / DELETE handlers.
    """

    default_message = 'This order cannot be modified because it is no longer a draft.'
    http_status     = status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# InvalidStatusTransition
# ---------------------------------------------------------------------------
class InvalidStatusTransition(StallManagementError):
    """
    Raised when a status change is not allowed by the business rules.

    Example: attempting to complete an already-cancelled order.

    Attributes
    ----------
    from_status : str   The current status of the order.
    to_status   : str   The requested (invalid) target status.
    """

    default_message = 'This status transition is not allowed.'
    http_status     = status.HTTP_400_BAD_REQUEST

    def __init__(self, from_status: str, to_status: str, message: str = None):
        self.from_status = from_status
        self.to_status   = to_status
        msg = message or (
            f'Cannot transition from "{from_status}" to "{to_status}".'
        )
        super().__init__(msg, details={
            'from_status': from_status,
            'to_status':   to_status,
        })


# ---------------------------------------------------------------------------
# StallNotOperationalError
# ---------------------------------------------------------------------------
class StallNotOperationalError(StallManagementError):
    """
    Raised when an inbound or outbound order is attempted on a stall
    that is not currently active (e.g. inactive or suspended).

    Raised by
    ---------
    Any order creation view if stall-level checks are added in future.
    """

    default_message = 'The stall is not currently operational.'
    http_status     = status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# DRF custom exception handler
# ---------------------------------------------------------------------------
def custom_exception_handler(exc, context):
    """
    Custom DRF exception handler registered in settings.py.

    Wraps ALL exception responses — both DRF built-in exceptions
    (AuthenticationFailed, NotFound, PermissionDenied, etc.) and
    StallManagement domain exceptions — into the project's standard
    JSON envelope:

        {
            "success": false,
            "code":    <http_status_int>,
            "message": "<human-readable description>",
            "data":    <details_or_null>
        }

    This ensures the Vue frontend always receives a consistent shape
    regardless of whether the error came from DRF or project code.

    Falls back to DRF's default handler for exceptions it does not
    recognise, so unexpected server errors still get logged properly.
    """

    # ── Handle StallManagement domain exceptions ────────────────────────
    if isinstance(exc, StallManagementError):
        logger.warning(
            'custom_exception_handler: %s — %s',
            type(exc).__name__,
            exc.message,
        )
        return Response(
            {
                'success': False,
                'code':    exc.http_status,
                'message': exc.message,
                'data':    exc.details,
            },
            status=exc.http_status,
        )

    # ── Delegate everything else to DRF's built-in handler ───────────────
    response = drf_exception_handler(exc, context)

    if response is not None:
        # Re-wrap DRF's response into the standard envelope
        original_data = response.data

        # Extract a clean message string from DRF's varied response shapes:
        #   { "detail": "Not found." }
        #   { "username": ["This field is required."] }
        #   "Authentication credentials were not provided."
        if isinstance(original_data, dict) and 'detail' in original_data:
            message = str(original_data['detail'])
            data    = None
        elif isinstance(original_data, dict):
            message = 'Validation error. See data for details.'
            data    = original_data
        elif isinstance(original_data, list):
            message = 'Validation error. See data for details.'
            data    = original_data
        else:
            message = str(original_data)
            data    = None

        response.data = {
            'success': False,
            'code':    response.status_code,
            'message': message,
            'data':    data,
        }

    return response
