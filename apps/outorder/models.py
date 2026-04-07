"""
apps/outorder/models.py
=======================
Outbound (sales) order models — map to `outorder` and `outorder_products`
tables in db_market.sql.

Role in the system
------------------
An outbound order represents a sale to a buyer:
  - The stall owner selects a buyer (Customer with type='buyer').
  - They add one or more product lines (OutOrderProduct), each specifying
    a product, quantity, and unit price.
  - BEFORE the order is allowed to complete, the view performs a stock
    availability check for every line within transaction.atomic() using
    select_for_update() to lock the product rows against concurrent writes.
  - When the order status transitions to 'completed', the signal in
    signals.py fires and DECREASES each product's stock by the sold
    quantity via utils.helpers.adjust_stock.
  - If stock is insufficient for any line, the entire transaction rolls back
    — neither the order status change nor any stock deduction is persisted.

Key difference from inbound orders
-----------------------------------
  Inbound  → stock INCREASES on completion  (purchase from supplier)
  Outbound → stock DECREASES on completion  (sale to buyer)
             + stock sufficiency check required before completion

Stock restoration on cancellation
----------------------------------
  If a COMPLETED outbound order is cancelled (admin action), stock IS
  restored for the lines.  This mirrors the frontend's deleteOutorder()
  behaviour which calls adjustStock(+amount) on delete.
  Only completed→cancelled triggers a restoration; draft→cancelled does not
  (stock was never deducted from a draft order).

Status lifecycle
----------------
    draft ──► completed  (stock deducted)
      │
      └──► cancelled     (no stock change)

    completed ──► cancelled  (stock RESTORED — admin action only)

Database tables
---------------
`outorder`          — the order header
`outorder_products` — the order line items

SQL reference:
    CREATE TABLE `outorder` (
      `id`          INT AUTO_INCREMENT PRIMARY KEY,
      `code`        VARCHAR(50) NOT NULL UNIQUE,
      `customer_id` INT NOT NULL REFERENCES customer(id) ON DELETE CASCADE,
      `user_id`     INT NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
      `status`      ENUM('draft','completed','cancelled') DEFAULT 'draft',
      `remark`      VARCHAR(255),
      `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
      `modify_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )

    CREATE TABLE `outorder_products` (
      `id`          INT AUTO_INCREMENT PRIMARY KEY,
      `outorder_id` INT NOT NULL REFERENCES outorder(id)  ON DELETE CASCADE,
      `product_id`  INT NOT NULL REFERENCES products(id)  ON DELETE CASCADE,
      `amount`      INT NOT NULL DEFAULT 0,
      `unit_price`  DECIMAL(10,2)
    )
"""

from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator

from apps.common.mixins import TimeStampMixin


class OutOrder(TimeStampMixin):
    """
    Outbound sales order header.

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
            'Unique outbound order number. '
            'Format from seed data: OUT{YYYYMMDD}{sequence}, e.g. OUT2024112701.'
        ),
        error_messages={
            'unique': 'An outbound order with this code already exists.',
        },
    )

    customer = models.ForeignKey(
        'customer.Customer',
        on_delete=models.CASCADE,           # mirrors ON DELETE CASCADE in SQL
        related_name='outorder_set',
        verbose_name='Buyer',
        help_text='The buyer (Customer with type=buyer) for this order.',
        db_column='customer_id',
        limit_choices_to={'customer_type': 'buyer'},
    )

    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,           # mirrors ON DELETE CASCADE in SQL
        related_name='outorders_operated',
        verbose_name='Operator',
        help_text='The user who created/manages this order.',
        db_column='user_id',
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name='Status',
        help_text=(
            'draft → completed (stock check + deduction)\n'
            'draft → cancelled (no stock change)\n'
            'completed → cancelled (stock RESTORED — admin only)'
        ),
    )

    remark = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Remark',
        help_text='Optional notes about this sale.',
    )

    # create_time, modify_time → inherited from TimeStampMixin

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------
    class Meta:
        app_label = 'outorder'
        db_table            = 'outorder'
        verbose_name        = 'Outbound Order'
        verbose_name_plural = 'Outbound Orders'
        ordering            = ['-create_time']
        indexes = [
            models.Index(fields=['status'],      name='idx_outorder_status'),
            models.Index(fields=['customer'],    name='idx_outorder_customer'),
            models.Index(fields=['operator'],    name='idx_outorder_operator'),
            models.Index(fields=['create_time'], name='idx_outorder_created'),
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
        """Only draft orders can be modified."""
        return self.status == self.Status.DRAFT

    # ------------------------------------------------------------------
    # Computed totals (covered by prefetch_related in views/_base_qs)
    # ------------------------------------------------------------------
    @property
    def total_amount(self):
        """Total quantity across all line items."""
        return sum(line.amount for line in self.lines.all())

    @property
    def total_value(self):
        """Total sales value (sum of amount × unit_price per line)."""
        return sum(
            (line.amount * line.unit_price)
            for line in self.lines.all()
            if line.unit_price is not None
        )


# ---------------------------------------------------------------------------
# OutOrderProduct — one line item per product in an outbound order
# ---------------------------------------------------------------------------
class OutOrderProduct(models.Model):
    """
    A single line item within an outbound order.

    No TimeStampMixin: the `outorder_products` table in db_market.sql has
    no create_time / modify_time columns.
    """

    outorder = models.ForeignKey(
        OutOrder,
        on_delete=models.CASCADE,
        related_name='lines',
        verbose_name='Outbound Order',
        db_column='outorder_id',
    )

    product = models.ForeignKey(
        'product.Product',
        on_delete=models.CASCADE,
        related_name='outorderproduct_set',
        verbose_name='Product',
        db_column='product_id',
    )

    amount = models.IntegerField(
        default=0,
        verbose_name='Quantity',
        help_text='Number of units sold in this line.',
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
        help_text='Selling price per unit charged to the buyer.',
        validators=[
            MinValueValidator(0, message='Unit price cannot be negative.')
        ],
    )

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------
    class Meta:
        db_table            = 'outorder_products'
        verbose_name        = 'Outbound Order Line'
        verbose_name_plural = 'Outbound Order Lines'

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------
    def __str__(self):
        return (
            f'{self.outorder.code} → '
            f'{self.product.name} × {self.amount}'
        )

    # ------------------------------------------------------------------
    # Computed line total
    # ------------------------------------------------------------------
    @property
    def line_total(self):
        """Total sales value of this line (amount × unit_price)."""
        if self.unit_price is None:
            return None
        return self.amount * self.unit_price
