"""
apps/user/serializers.py
========================
DRF serializers for the User model.

Serializers
-----------
UserReadSerializer
    Safe read-only representation — never exposes the password field.
    Used in list and retrieve responses.

UserCreateSerializer
    Write serializer for creating a new user (admin only).
    Accepts plain-text password, validates it, and hashes it via
    set_password() before saving.

UserUpdateSerializer
    Write serializer for updating an existing user (admin only).
    Password field is optional; if omitted the existing hash is kept.
    Role and is_active can be changed; username cannot be changed after
    creation (business rule: usernames are permanent identifiers).

UserChangePasswordSerializer
    Allows an authenticated user to change their own password by
    supplying the current password for verification, plus the new one.
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import serializers

from .models import User


# ---------------------------------------------------------------------------
# 1. UserReadSerializer — safe, read-only, no password
# ---------------------------------------------------------------------------
class UserReadSerializer(serializers.ModelSerializer):
    """
    Read-only serializer.  Never includes the password field.
    Returned by list, retrieve, and as the nested representation inside
    other serializers (e.g. stall owner inside StallSerializer).
    """

    role_display = serializers.CharField(
        source='get_role_display',
        read_only=True,
        help_text='Human-readable role label.',
    )

    class Meta:
        model  = User
        fields = [
            'id',
            'username',
            'name',
            'role',
            'role_display',
            'is_active',
            'is_deleted',
            'create_time',
            'modify_time',
        ]
        read_only_fields = fields   # every field is read-only in this serializer


# ---------------------------------------------------------------------------
# 2. UserCreateSerializer — admin creates a new user
# ---------------------------------------------------------------------------
class UserCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer for POST /api/users/.
    Accepts a plain-text password, validates its strength, hashes it,
    and saves the new user.

    Required fields: username, password, password_confirm, name, role
    Optional fields: is_active (defaults to True)
    """

    password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={'input_type': 'password'},
        help_text='Plain-text password — will be hashed before storage.',
    )
    password_confirm = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
        help_text='Must match the password field.',
    )

    class Meta:
        model  = User
        fields = [
            'username',
            'password',
            'password_confirm',
            'name',
            'role',
            'is_active',
        ]
        extra_kwargs = {
            'username':  {'help_text': '50 characters or fewer. Lowercase recommended.'},
            'name':      {'help_text': 'Real or display name.'},
            'role':      {'help_text': 'admin | stall_owner | customer'},
            'is_active': {'default': True},
        }

    # ── Field-level validation ──────────────────────────────────────────
    def validate_username(self, value):
        """Normalise to lowercase and check uniqueness."""
        value = value.strip().lower()
        if User.all_objects.filter(username=value).exists():
            raise serializers.ValidationError(
                f'The username "{value}" is already taken.'
            )
        return value

    def validate_role(self, value):
        """Ensure the role is one of the three valid choices."""
        valid_roles = [r.value for r in User.Role]
        if value not in valid_roles:
            raise serializers.ValidationError(
                f'"{value}" is not a valid role. Choose from: {valid_roles}.'
            )
        return value

    # ── Object-level validation ─────────────────────────────────────────
    def validate(self, attrs):
        password         = attrs.get('password')
        password_confirm = attrs.pop('password_confirm', None)   # remove before save

        if password != password_confirm:
            raise serializers.ValidationError(
                {'password_confirm': 'Passwords do not match.'}
            )

        # Run Django's built-in password strength validators
        try:
            validate_password(password)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)})

        return attrs

    # ── Save ────────────────────────────────────────────────────────────
    def create(self, validated_data):
        """Hash the password and create the user via the manager."""
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


# ---------------------------------------------------------------------------
# 3. UserUpdateSerializer — admin edits an existing user
# ---------------------------------------------------------------------------
class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Write serializer for PATCH /api/users/<id>/.
    Username is read-only after creation (permanent identifier).
    Password is optional; supply it only when changing.
    """

    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        min_length=8,
        style={'input_type': 'password'},
        help_text='Leave blank to keep the current password.',
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        style={'input_type': 'password'},
        help_text='Required only when changing the password.',
    )

    class Meta:
        model  = User
        fields = [
            'name',
            'role',
            'is_active',
            'password',
            'password_confirm',
        ]

    def validate(self, attrs):
        password         = attrs.get('password', '')
        password_confirm = attrs.pop('password_confirm', '')

        # Only validate password if it was actually provided
        if password:
            if password != password_confirm:
                raise serializers.ValidationError(
                    {'password_confirm': 'Passwords do not match.'}
                )
            try:
                validate_password(password)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({'password': list(exc.messages)})
        else:
            # Discard the blank value so it is not processed in update()
            attrs.pop('password', None)

        return attrs

    def update(self, instance, validated_data):
        """Apply changes; hash the new password only if one was supplied."""
        password = validated_data.pop('password', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()
        return instance


# ---------------------------------------------------------------------------
# 4. UserChangePasswordSerializer — user changes their own password
# ---------------------------------------------------------------------------
class UserChangePasswordSerializer(serializers.Serializer):
    """
    Allows an authenticated user to change their own password.

    POST /api/users/change_password/
    Body: { "current_password": "...", "new_password": "...", "new_password_confirm": "..." }

    Steps:
    1. Verify current_password against the stored hash.
    2. Ensure new_password != current_password (no-op check).
    3. Run Django password validators on new_password.
    4. Confirm new_password == new_password_confirm.
    """

    current_password     = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
    )
    new_password         = serializers.CharField(
        write_only=True,
        min_length=8,
        style={'input_type': 'password'},
    )
    new_password_confirm = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
    )

    def validate_current_password(self, value):
        """Verify the supplied current password against the stored hash."""
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value

    def validate(self, attrs):
        new_password         = attrs.get('new_password')
        new_password_confirm = attrs.get('new_password_confirm')
        current_password     = attrs.get('current_password')

        if new_password == current_password:
            raise serializers.ValidationError(
                {'new_password': 'New password must be different from the current password.'}
            )

        if new_password != new_password_confirm:
            raise serializers.ValidationError(
                {'new_password_confirm': 'New passwords do not match.'}
            )

        try:
            validate_password(new_password, user=self.context['request'].user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'new_password': list(exc.messages)})

        return attrs

    def save(self, **kwargs):
        """Apply the new password to the requesting user."""
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password'])
        return user
