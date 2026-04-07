"""
apps/inorder/models.py
======================
Inbound (purchase) order models — map to `inorder` and `inorder_products`
tables in db_market.sql.

Role in the system
------------------
An inbound order represents a purchase from a supplier:
  - The stall owner selects a supplier (Customer with type='supplier').
  - They add one or more product lines (InOrderProduct), each specifying
    a product, quantity, and unit price.
  - When the order status transitions to 'completed', the signal in
    signals.py fires and increases each product's stock by the ordered
    quantity via utils.helpers.adjust_stock (wrapped in transaction.atomic).
  - If the order is later cancelled, stock is NOT automatically reversed
    — cancellation of a completed order requires manual stock correction
    through a new outbound adjustment order (business rule).

Status lifecycle
----------------
    draft ──► completed
      │
      └──► cancelled

    Only draft orders can be edited (lines added/removed, fields updated).
    Completed and cancelled orders are immutable.

Database tables
---------------
`inorder`           — the order header
`inorder_products`  — the order line items (one row per product per order)

SQL reference:
    CREATE TABLE `inorder` (
      `id`          INT AUTO_INCREMENT PRIMARY KEY,
      `code`        VARCHAR(50) NOT NULL UNIQUE,
      `customer_id` INT NOT NULL REFERENCES customer(id) ON DELETE CASCADE,
      `user_id`     INT NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
      `status`      ENUM('draft','completed','cancelled') DEFAULT 'draft',
      `remark`      VARCHAR(255),
      `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
      `modify_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )

    CREATE TABLE `inorder_products` (
      `id`         INT AUTO_INCREMENT PRIMARY KEY,
      `inorder_id` INT NOT NULL REFERENCES inorder(id)  ON DELETE CASCADE,
      `product_id` INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
      `amount`     INT NOT NULL DEFAULT 0,
      `unit_price` DECIMAL(10,2)
    )
"""

from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator

from apps.common.mixins import TimeStampMixin


class InOrder(TimeStampMixin):
    """
    Inbound purchase order header.

    Inherits from TimeStampMixin:
        create_time  →  auto-set on first save
        modify_time  →  auto-updated on every save
    """

    # ------------------------------------------------------------------
    # Status choices — mirror the ENUM in db_market.sql
    # ------------------------------------------------------------------
    class Status(models.TextChoices):
        DRAFT     = 'draft',     'Draft'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='Order Code',
        help_text=(
            'Unique inbound order number. '
            'Format from seed data: IN{YYYYMMDD}{sequence}, e.g. IN2024112701.'
        ),
        error_messages={
            'unique': 'An inbound order with this code already exists.',
        },
    )

    customer = models.ForeignKey(
        'customer.Customer',
        on_delete=models.CASCADE,           # mirrors ON DELETE CASCADE in SQL
        related_name='inorder_set',
        verbose_name='Supplier',
        help_text='The supplier (Customer with type=supplier) for this order.',
        db_column='customer_id',
        limit_choices_to={'customer_type': 'supplier'},
    )

    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,           # mirrors ON DELETE CASCADE in SQL
        related_name='inorders_operated',
        verbose_name='Operator',
        help_text='The user who created/manages this order.',
        db_column='user_id',
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name='Status',
        help_text='draft → completed (stock increased) | draft → cancelled.',
    )

    remark = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Remark',
        help_text='Optional notes about this order.',
    )

    # create_time, modify_time → inherited from TimeStampMixin

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------
    class Meta:
        app_label = 'inorder'
        db_table            = 'inorder'
        verbose_name        = 'Inbound Order'
        verbose_name_plural = 'Inbound Orders'
        ordering            = ['-create_time']
        indexes = [
            models.Index(fields=['status'],      name='idx_inorder_status'),
            models.Index(fields=['customer'],    name='idx_inorder_customer'),
            models.Index(fields=['operator'],    name='idx_inorder_operator'),
            models.Index(fields=['create_time'], name='idx_inorder_created'),
        ]

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------
    def __str__(self):
        return f'{self.code} [{self.get_status_display()}]'

    # ------------------------------------------------------------------
    # Status helper properties
    # ------------------------------------------------------------------
    @property
    def is_draft(self):
        return self.status == self.Status.DRAFT

    @property
    def is_completed(self):
        return self.status == self.Status.COMPLETED

    @property
    def is_cancelled(self):
        return self.status == self.Status.CANCELLED

    @property
    def is_editable(self):
        """
        Only draft orders can be modified (lines added/removed, header updated).
        Completed and cancelled orders are immutable.
        """
        return self.status == self.Status.DRAFT

    # ------------------------------------------------------------------
    # Computed totals
    # ------------------------------------------------------------------
    @property
    def total_amount(self):
        """Total quantity across all line items."""
        return sum(line.amount for line in self.lines.all())

    @property
    def total_value(self):
        """
        Total purchase value (sum of amount × unit_price per line).
        Returns 0 if any line has no unit_price set.
        """
        return sum(
            (line.amount * line.unit_price)
            for line in self.lines.all()
            if line.unit_price is not None
        )


# ---------------------------------------------------------------------------
# InOrderProduct — one line item per product in an inbound order
# ---------------------------------------------------------------------------
class InOrderProduct(models.Model):
    """
    A single line item within an inbound order.

    No TimeStampMixin: the `inorder_products` table in db_market.sql has
    no create_time / modify_time columns — lines are created and deleted
    as a unit with the parent order.

    The combination of (inorder, product) is implicitly unique in business
    logic — the view layer merges duplicate product entries on create/update.
    """

    inorder = models.ForeignKey(
        InOrder,
        on_delete=models.CASCADE,           # mirrors ON DELETE CASCADE in SQL
        related_name='lines',
        verbose_name='Inbound Order',
        db_column='inorder_id',
    )

    product = models.ForeignKey(
        'product.Product',
        on_delete=models.CASCADE,           # mirrors ON DELETE CASCADE in SQL
        related_name='inorderproduct_set',
        verbose_name='Product',
        db_column='product_id',
    )

    amount = models.IntegerField(
        default=0,
        verbose_name='Quantity',
        help_text='Number of units purchased in this line.',
        validators=[
            MinValueValidator(1, message='Quantity must be at least 1.')
        ],
    )

    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Unit Price',
        help_text='Purchase price per unit paid to the supplier.',
        validators=[
            MinValueValidator(0, message='Unit price cannot be negative.')
        ],
    )

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------
    class Meta:
        db_table            = 'inorder_products'
        verbose_name        = 'Inbound Order Line'
        verbose_name_plural = 'Inbound Order Lines'

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------
    def __str__(self):
        return (
            f'{self.inorder.code} → '
            f'{self.product.name} × {self.amount}'
        )

    # ------------------------------------------------------------------
    # Computed line total
    # ------------------------------------------------------------------
    @property
    def line_total(self):
        """Total value of this line (amount × unit_price)."""
        if self.unit_price is None:
            return None
        return self.amount * self.unit_price
