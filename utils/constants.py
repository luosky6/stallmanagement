"""
utils/constants.py
==================
Project-wide constant definitions for the StallManagement project.

Centralising constants here means:
  1. The frontend and backend use identical string values (documented).
  2. A single change here propagates to every import site.
  3. Code that uses these constants is self-documenting.

Import example:
    from utils.constants import UserRole, OrderStatus, LOW_STOCK_THRESHOLD
"""

# ---------------------------------------------------------------------------
# User roles
# Mirrors: apps.user.models.User.Role (TextChoices)
# Mirrors: db_market.sql ENUM('admin','stall_owner','customer')
# ---------------------------------------------------------------------------
class UserRole:
    ADMIN       = 'admin'
    STALL_OWNER = 'stall_owner'
    CUSTOMER    = 'customer'

    ALL    = (ADMIN, STALL_OWNER, CUSTOMER)
    LABELS = {
        ADMIN:       'Admin',
        STALL_OWNER: 'Stall Owner',
        CUSTOMER:    'Customer',
    }

    @classmethod
    def choices(cls):
        return [(v, cls.LABELS[v]) for v in cls.ALL]


# ---------------------------------------------------------------------------
# Order statuses
# Mirrors: InOrder.Status and OutOrder.Status (TextChoices)
# Mirrors: db_market.sql ENUM('draft','completed','cancelled')
# ---------------------------------------------------------------------------
class OrderStatus:
    DRAFT     = 'draft'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'

    ALL    = (DRAFT, COMPLETED, CANCELLED)
    LABELS = {
        DRAFT:     'Draft',
        COMPLETED: 'Completed',
        CANCELLED: 'Cancelled',
    }

    # Status transitions that are allowed
    # { current_status: [allowed_next_statuses] }
    ALLOWED_TRANSITIONS = {
        DRAFT:     [COMPLETED, CANCELLED],
        COMPLETED: [CANCELLED],   # admin-only reversal (outbound only)
        CANCELLED: [],            # terminal — no transitions out of cancelled
    }

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        """Return True if the given status transition is allowed."""
        return to_status in cls.ALLOWED_TRANSITIONS.get(from_status, [])


# ---------------------------------------------------------------------------
# Customer types
# Mirrors: apps.customer.models.Customer.CustomerType (TextChoices)
# Mirrors: db_market.sql ENUM('supplier','buyer')
# ---------------------------------------------------------------------------
class CustomerType:
    SUPPLIER = 'supplier'
    BUYER    = 'buyer'

    ALL    = (SUPPLIER, BUYER)
    LABELS = {
        SUPPLIER: 'Supplier',
        BUYER:    'Buyer',
    }


# ---------------------------------------------------------------------------
# Stall statuses
# Mirrors: apps.stall.models.Stall.Status (TextChoices)
# Mirrors: db_market.sql ENUM('active','inactive','suspended')
# ---------------------------------------------------------------------------
class StallStatus:
    ACTIVE    = 'active'
    INACTIVE  = 'inactive'
    SUSPENDED = 'suspended'

    ALL    = (ACTIVE, INACTIVE, SUSPENDED)
    LABELS = {
        ACTIVE:    'Active',
        INACTIVE:  'Inactive',
        SUSPENDED: 'Suspended',
    }

    OPERATIONAL = (ACTIVE,)   # statuses that allow order creation


# ---------------------------------------------------------------------------
# Stock thresholds
# Mirrors: apps.product.models.LOW_STOCK_THRESHOLD
# Centralised here so the value is shared with utils and non-product code.
# ---------------------------------------------------------------------------
LOW_STOCK_THRESHOLD = 20    # products with stock < 20 are flagged as low-stock
OUT_OF_STOCK        = 0     # products with stock == 0 are flagged as out-of-stock


# ---------------------------------------------------------------------------
# Order code prefixes
# Used by utils.helpers.format_order_code()
# ---------------------------------------------------------------------------
class OrderCodePrefix:
    INBOUND  = 'IN'
    OUTBOUND = 'OUT'


# ---------------------------------------------------------------------------
# Pagination defaults
# Used by utils.helpers.paginate_queryset() and all views
# ---------------------------------------------------------------------------
class Pagination:
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE     = 100
    CHAT_PAGE_SIZE    = 50    # chat history loads more messages per page


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
class ChatConfig:
    MAX_MESSAGE_LENGTH = 5000   # characters — enforced in consumer and serializer
    ROOM_PREFIX        = 'chat'
    GROUP_PREFIX       = 'group_chat'


# ---------------------------------------------------------------------------
# HTTP response codes (documented for cross-team reference)
# These mirror standard HTTP status codes but are listed here so frontend
# developers know exactly which codes to expect from this API.
# ---------------------------------------------------------------------------
class APICode:
    OK         = 200
    CREATED    = 201
    BAD_REQUEST        = 400
    UNAUTHORIZED       = 401
    FORBIDDEN          = 403
    NOT_FOUND          = 404
    CONFLICT           = 409
    INTERNAL_ERROR     = 500


# ---------------------------------------------------------------------------
# Log message templates (prevents typos in repeated log strings)
# ---------------------------------------------------------------------------
class LogMsg:
    STOCK_INCREASED = 'Stock INCREASED by %+d for [%s] "%s" (id=%d). %d → %d. %s'
    STOCK_DECREASED = 'Stock DECREASED by %+d for [%s] "%s" (id=%d). %d → %d. %s'
    ORDER_COMPLETED = '%s order "%s" (id=%d) completed by user "%s".'
    ORDER_CANCELLED = '%s order "%s" (id=%d) cancelled by user "%s".'
    LOGIN_SUCCESS   = 'User "%s" (role=%s) logged in successfully.'
    LOGIN_FAILED    = 'Failed login attempt for username="%s".'
    PERMISSION_DENIED = 'User "%s" (role=%s) denied access to %s.'
