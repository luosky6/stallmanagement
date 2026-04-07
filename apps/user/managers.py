"""
apps/user/managers.py
=====================
Custom manager for the User model.

Django requires any model that extends AbstractBaseUser to define a
custom manager that implements create_user() and create_superuser().
This manager also integrates the SoftDelete behaviour from
apps.common.mixins so that deleted users are hidden from normal queries.

Classes
-------
CustomUserManager
    Primary manager attached as User.objects.
    - Filters out soft-deleted users by default.
    - Provides create_user() and create_superuser() as required by Django.
    - Provides create_stall_owner() and create_customer() as convenience
      methods matching the three roles defined in the DB schema.
"""

from django.contrib.auth.models import BaseUserManager


class CustomUserManager(BaseUserManager):
    """
    Manager for the custom User model (extends AbstractBaseUser).

    Default queryset excludes soft-deleted users (is_deleted=False).
    Use User.all_objects.all() to retrieve deleted records.
    """

    # ------------------------------------------------------------------
    # Internal queryset filter — hides soft-deleted users everywhere
    # ------------------------------------------------------------------
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

    # ------------------------------------------------------------------
    # Core factory: _create_user
    # Called internally by create_user() and create_superuser().
    # ------------------------------------------------------------------
    def _create_user(self, username, password, name, role, **extra_fields):
        """
        Shared logic for all user-creation paths.

        Parameters
        ----------
        username : str   Login username — must be unique.
        password : str   Plain-text password — will be hashed via set_password().
        name     : str   Display / real name stored in the `name` column.
        role     : str   One of 'admin' | 'stall_owner' | 'customer'.
        **extra_fields   Any additional model fields (e.g. is_active).
        """
        if not username:
            raise ValueError('A username is required.')
        if not password:
            raise ValueError('A password is required.')
        if not name:
            raise ValueError('A display name is required.')

        # Normalise username: strip whitespace, lowercase
        username = username.strip().lower()

        user = self.model(
            username=username,
            name=name,
            role=role,
            **extra_fields,
        )
        user.set_password(password)   # hashes with PBKDF2 (Django default)
        user.save(using=self._db)
        return user

    # ------------------------------------------------------------------
    # Public factory methods
    # ------------------------------------------------------------------
    def create_user(self, username, password, name, role='customer', **extra_fields):
        """
        Create and return a regular user.

        Defaults
        --------
        - role      : 'customer'  (safest default — least privilege)
        - is_active : True
        """
        extra_fields.setdefault('is_active', True)
        return self._create_user(username, password, name, role, **extra_fields)

    def create_superuser(self, username, password, name='Admin', **extra_fields):
        """
        Create and return a superuser (role='admin').

        Called by Django's  manage.py createsuperuser  command.
        Forces is_active=True and role='admin'.
        """
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_active') is not True:
            raise ValueError('Superuser must have is_active=True.')

        return self._create_user(
            username, password, name, role='admin', **extra_fields
        )

    # ------------------------------------------------------------------
    # Convenience methods matching the project's three roles
    # ------------------------------------------------------------------
    def create_stall_owner(self, username, password, name, **extra_fields):
        """Create and return a stall_owner role user."""
        extra_fields.setdefault('is_active', True)
        return self._create_user(username, password, name, 'stall_owner', **extra_fields)

    def create_customer(self, username, password, name, **extra_fields):
        """Create and return a customer role user."""
        extra_fields.setdefault('is_active', True)
        return self._create_user(username, password, name, 'customer', **extra_fields)

    # ------------------------------------------------------------------
    # Queryset helpers
    # ------------------------------------------------------------------
    def active(self):
        """Return only active (non-disabled, non-deleted) users."""
        return self.get_queryset().filter(is_active=True)

    def by_role(self, role):
        """
        Filter users by role.

        Usage: User.objects.by_role('stall_owner')
        """
        return self.get_queryset().filter(role=role)

    def admins(self):
        """Shortcut: all admin users."""
        return self.by_role('admin')

    def stall_owners(self):
        """Shortcut: all stall_owner users."""
        return self.by_role('stall_owner')

    def customers(self):
        """Shortcut: all customer users."""
        return self.by_role('customer')
