"""
apps/stall/models.py
====================
Stall model — maps to the `stalls` table in db_market.sql.

Role in the system
------------------
A stall is the core operational unit of the system. It is owned by a
user with role='stall_owner' and acts as the organisational container
for all inventory, orders, and chat that the stall owner manages.

The Vue frontend header shows the stall name and the current operator's
name. The admin can activate, deactivate, or suspend stalls, controlling
whether they appear as operational in the system.

Status lifecycle
----------------
    active      ←─────────────────┐
      │                           │
      ▼                           │ restore
   inactive  ──── suspend ──► suspended
      │                           │
      └─────────── suspend ───────┘

    active    : Stall is fully operational.
    inactive  : Stall owner has temporarily closed the stall.
    suspended : Admin has suspended the stall (e.g. policy violation).
                Only an admin can move a stall out of suspended status.

Database table: `stalls`  (matches db_market.sql exactly)

SQL reference:
    CREATE TABLE `stalls` (
      `id`          INT AUTO_INCREMENT PRIMARY KEY,
      `name`        VARCHAR(100) NOT NULL,
      `owner_id`    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      `description` VARCHAR(255),
      `status`      ENUM('active','inactive','suspended') DEFAULT 'active',
      `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
      `modify_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )
"""

from django.conf import settings
from django.db import models

from apps.common.mixins import TimeStampMixin


class Stall(TimeStampMixin):
    """
    A market stall owned by a stall_owner-role user.

    Inherits from TimeStampMixin:
        create_time  →  auto-set on first save
        modify_time  →  auto-updated on every save

    No soft-delete: the `stalls` table has no is_deleted column.
    The status field (active / inactive / suspended) serves as the
    operational flag instead of a boolean deleted marker.
    """

    # ------------------------------------------------------------------
    # Status choices — mirror the ENUM in db_market.sql
    # ------------------------------------------------------------------
    class Status(models.TextChoices):
        ACTIVE    = 'active',    'Active'
        INACTIVE  = 'inactive',  'Inactive'
        SUSPENDED = 'suspended', 'Suspended'

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    name = models.CharField(
        max_length=100,
        verbose_name='Stall Name',
        help_text='Display name of the stall shown in the UI header.',
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,           # 'user.User' via AUTH_USER_MODEL
        on_delete=models.CASCADE,           # mirrors ON DELETE CASCADE in SQL
        related_name='stalls',
        verbose_name='Stall Owner',
        help_text='The user (role=stall_owner) who operates this stall.',
        db_column='owner_id',               # keeps column name as owner_id
        limit_choices_to={'role': 'stall_owner'},
    )

    description = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Description',
        help_text='Short description of the stall and what it sells.',
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name='Status',
        help_text=(
            'active    — fully operational.\n'
            'inactive  — temporarily closed by the stall owner.\n'
            'suspended — suspended by an admin (only admin can unsuspend).'
        ),
    )

    # create_time, modify_time → inherited from TimeStampMixin

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------
    class Meta:
        app_label = 'stall'
        db_table            = 'stalls'   # exact table name from db_market.sql
        verbose_name        = 'Stall'
        verbose_name_plural = 'Stalls'
        ordering            = ['name']

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------
    def __str__(self):
        return f'{self.name} [{self.get_status_display()}]'

    # ------------------------------------------------------------------
    # Status helper properties
    # ------------------------------------------------------------------
    @property
    def is_active(self):
        """True when the stall is fully operational."""
        return self.status == self.Status.ACTIVE

    @property
    def is_inactive(self):
        """True when the stall is temporarily closed."""
        return self.status == self.Status.INACTIVE

    @property
    def is_suspended(self):
        """True when the stall has been suspended by an admin."""
        return self.status == self.Status.SUSPENDED

    @property
    def is_operational(self):
        """
        True when the stall can process orders (active only).
        Used as a pre-check before creating inbound/outbound orders.
        """
        return self.status == self.Status.ACTIVE

    # ------------------------------------------------------------------
    # Status transition helpers
    # Called by the activate / deactivate / suspend view actions.
    # ------------------------------------------------------------------
    def activate(self):
        """Set stall to active. Saves the record."""
        self.status = self.Status.ACTIVE
        self.save(update_fields=['status', 'modify_time'])

    def deactivate(self):
        """Set stall to inactive. Saves the record."""
        self.status = self.Status.INACTIVE
        self.save(update_fields=['status', 'modify_time'])

    def suspend(self):
        """Set stall to suspended. Saves the record. Admin only."""
        self.status = self.Status.SUSPENDED
        self.save(update_fields=['status', 'modify_time'])
