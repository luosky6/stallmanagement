"""
apps/outorder/signals.py
========================
Django signals for the outbound order module.

Signal: post_save on OutOrder
------------------------------
This signal handles TWO transitions:

1. draft → completed
   Decreases product stock for every line by the sold quantity.
   The stock sufficiency check was already performed in the view
   (using select_for_update) BEFORE the save, so by the time this
   signal fires the stock is guaranteed sufficient.

2. completed → cancelled  (admin action only)
   RESTORES product stock for every line.
   This mirrors the frontend's deleteOutorder() which calls
   adjustStock(+amount) when an outbound order is deleted.

Transaction safety
------------------
Both signal actions fire INSIDE the transaction.atomic() block that
wraps the order-save in views.py and admin.py.  This means:
  - If adjust_stock() raises, the entire transaction rolls back.
  - The order status change AND the stock change are one atomic unit.

Idempotency guard
-----------------
The view attaches instance._previous_status before every save().
The signal uses this to determine:
  - draft      → completed : deduct stock
  - completed  → cancelled : restore stock
  - anything else          : no-op

If _previous_status is absent (e.g. direct queryset.update() bypass),
the signal logs a warning and skips all stock adjustments.

Connection
----------
Registered in OutOrderConfig.ready() via apps/outorder/apps.py.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import OutOrder

logger = logging.getLogger('apps')


@receiver(post_save, sender=OutOrder)
def on_outorder_saved(sender, instance, created, **kwargs):
    """
    Fires after every OutOrder save.

    Handles:
      draft → completed  →  deduct stock  (negative delta)
      completed → cancelled  →  restore stock  (positive delta)
    """

    # ── Guard: only act on updates ───────────────────────────────────────
    if created:
        return

    current_status  = instance.status
    previous_status = getattr(instance, '_previous_status', None)

    if previous_status is None:
        logger.warning(
            'on_outorder_saved: OutOrder id=%d status changed to "%s" but '
            '_previous_status was not set. Stock adjustment SKIPPED to prevent '
            'incorrect stock mutation. Always use the view layer to update orders.',
            instance.id, current_status,
        )
        return

    # ── No-op: status did not change ────────────────────────────────────
    if previous_status == current_status:
        return

    from utils.helpers import adjust_stock

    # ── Case 1: draft → completed → DEDUCT stock ────────────────────────
    if (previous_status == OutOrder.Status.DRAFT
            and current_status == OutOrder.Status.COMPLETED):

        lines = instance.lines.select_related('product').all()

        if not lines.exists():
            logger.warning(
                'on_outorder_saved: OutOrder "%s" (id=%d) completed with NO '
                'line items. No stock was deducted.',
                instance.code, instance.id,
            )
            return

        logger.info(
            'on_outorder_saved: OutOrder "%s" (id=%d) completed. '
            'Deducting stock for %d product line(s).',
            instance.code, instance.id, lines.count(),
        )

        for line in lines:
            adjust_stock(
                product=line.product,
                delta=-line.amount,          # negative delta → stock decrease
                reason=f'Outbound order {instance.code} completed',
            )
            logger.info(
                'on_outorder_saved: -%d units from product [%s] "%s" (id=%d). '
                'New stock: %d.',
                line.amount,
                line.product.sn,
                line.product.name,
                line.product.id,
                line.product.stock,
            )

    # ── Case 2: completed → cancelled → RESTORE stock ───────────────────
    elif (previous_status == OutOrder.Status.COMPLETED
            and current_status == OutOrder.Status.CANCELLED):

        lines = instance.lines.select_related('product').all()

        logger.warning(
            'on_outorder_saved: OutOrder "%s" (id=%d) CANCELLED from completed. '
            'Restoring stock for %d product line(s).',
            instance.code, instance.id, lines.count(),
        )

        for line in lines:
            adjust_stock(
                product=line.product,
                delta=+line.amount,          # positive delta → stock restoration
                reason=f'Outbound order {instance.code} cancelled — stock restored',
            )
            logger.info(
                'on_outorder_saved: +%d units restored to product [%s] "%s" (id=%d). '
                'New stock: %d.',
                line.amount,
                line.product.sn,
                line.product.name,
                line.product.id,
                line.product.stock,
            )

    # ── Case 3: draft → cancelled → no stock change ──────────────────────
    elif (previous_status == OutOrder.Status.DRAFT
            and current_status == OutOrder.Status.CANCELLED):
        logger.info(
            'on_outorder_saved: OutOrder "%s" (id=%d) cancelled from draft. '
            'No stock adjustment required.',
            instance.code, instance.id,
        )

    else:
        logger.warning(
            'on_outorder_saved: OutOrder "%s" (id=%d) unexpected transition '
            '"%s" → "%s". No stock adjustment performed.',
            instance.code, instance.id, previous_status, current_status,
        )
