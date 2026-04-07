"""
apps/inorder/signals.py
=======================
Django signals for the inbound order module.

Signal: post_save on InOrder
-----------------------------
When an InOrder's status transitions to 'completed', this signal fires
and increases the stock of every product in the order's lines by the
ordered quantity.

Why signals for stock adjustment?
----------------------------------
Stock adjustment is a side effect of a business event (order completion),
not a direct user action.  Using a signal decouples the stock logic from
the view, keeping views thin and making the stock update testable in
isolation.

Transaction safety
------------------
The signal fires INSIDE the transaction.atomic() block that wraps the
order-save in views.py.  This means:
  - If adjust_stock() raises an exception (e.g. DB error), the entire
    transaction rolls back — neither the order update nor the stock
    changes are persisted.
  - The signal does NOT use transaction.on_commit() because we want the
    stock update to be part of the same atomic unit as the status change.

Stock adjustment direction
--------------------------
Inbound  → INCREASE stock  (+amount)
Outbound → DECREASE stock  (-amount)  [handled in outorder/signals.py]

Connection
----------
Signals are connected in the AppConfig.ready() method of InOrderConfig
(defined below in apps.py / via default_app_config) to guarantee they
are registered exactly once after Django finishes loading all apps.
The connection is made in InOrderConfig.ready() using:
    from apps.inorder import signals  # noqa: F401
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import InOrder

logger = logging.getLogger('apps')


@receiver(post_save, sender=InOrder)
def on_inorder_saved(sender, instance, created, **kwargs):
    """
    Fires after every InOrder save.

    Logic
    -----
    We only act when:
      1. The order was NOT just created (created=False → this is an update).
      2. The new status is 'completed'.
      3. The PREVIOUS status was 'draft' (idempotency guard — prevents
         double-incrementing stock if the signal fires more than once on
         an already-completed order, e.g. from an admin save action).

    The previous status is attached to the instance by the view layer
    before saving:
        instance._previous_status = <old status>

    If _previous_status is not set (e.g. signal fired from a direct
    queryset.update() call that bypassed the view), we skip the stock
    adjustment and log a warning instead of silently double-adjusting.
    """
    # ── Guard: only act on updates, not initial creation ────────────────
    if created:
        return

    # ── Guard: only act when transitioning TO completed ─────────────────
    if instance.status != InOrder.Status.COMPLETED:
        return

    # ── Guard: idempotency — must have transitioned FROM draft ───────────
    previous_status = getattr(instance, '_previous_status', None)

    if previous_status is None:
        logger.warning(
            'on_inorder_saved: InOrder id=%d reached completed status but '
            '_previous_status was not set. Stock adjustment SKIPPED to prevent '
            'double-increment. Use the view layer to update orders.',
            instance.id,
        )
        return

    if previous_status == InOrder.Status.COMPLETED:
        # Already completed — no-op, stock was already adjusted
        logger.debug(
            'on_inorder_saved: InOrder id=%d re-saved as completed; '
            'stock already adjusted, skipping.',
            instance.id,
        )
        return

    # ── Perform stock increase for every line ────────────────────────────
    from utils.helpers import adjust_stock

    lines = instance.lines.select_related('product').all()

    if not lines.exists():
        logger.warning(
            'on_inorder_saved: InOrder id=%d completed with NO line items. '
            'No stock was adjusted.',
            instance.id,
        )
        return

    logger.info(
        'on_inorder_saved: InOrder "%s" (id=%d) completed. '
        'Increasing stock for %d product line(s).',
        instance.code, instance.id, lines.count(),
    )

    for line in lines:
        adjust_stock(
            product=line.product,
            delta=+line.amount,          # positive delta → stock increase
            reason=f'Inbound order {instance.code} completed',
        )
        logger.info(
            'on_inorder_saved: +%d units to product [%s] "%s" (id=%d). '
            'New stock: %d.',
            line.amount,
            line.product.sn,
            line.product.name,
            line.product.id,
            line.product.stock,
        )
