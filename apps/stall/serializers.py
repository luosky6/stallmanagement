"""
apps/stall/serializers.py
=========================
DRF serializers for the Stall model.

Serializers
-----------
StallReadSerializer
    Full read-only representation returned in list and retrieve responses.
    Nests a compact owner profile (id, username, name) so the frontend
    can display the owner's name in the stall card without a second request.
    Adds computed fields: status_display, is_operational.

StallWriteSerializer
    Shared write serializer for CREATE (POST) and UPDATE (PATCH).
    Accepts owner_id as an integer FK.
    Validates that the referenced owner has role='stall_owner'.
    Prevents assigning a suspended or admin user as a stall owner.

StallStatusSerializer
    Minimal serializer used exclusively by the activate / deactivate /
    suspend action endpoints. Accepts only the `status` field.
"""

from rest_framework import serializers

from .models import Stall
from apps.user.models import User


# ---------------------------------------------------------------------------
# Nested owner representation — embedded inside StallReadSerializer
# ---------------------------------------------------------------------------
class StallOwnerSummarySerializer(serializers.ModelSerializer):
    """Compact owner profile embedded in every stall read response."""

    class Meta:
        model  = User
        fields = ['id', 'username', 'name', 'is_active']
        read_only_fields = fields


# ---------------------------------------------------------------------------
# 1. StallReadSerializer — full read output
# ---------------------------------------------------------------------------
class StallReadSerializer(serializers.ModelSerializer):
    """
    Read-only serializer returned by list / retrieve endpoints.

    Computed fields
    ---------------
    status_display   Human-readable label for the status value.
    is_operational   True when status == 'active' (can process orders).
    owner            Nested StallOwnerSummarySerializer (id, username, name).
    """

    owner          = StallOwnerSummarySerializer(read_only=True)
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True,
    )
    is_operational = serializers.BooleanField(read_only=True)

    class Meta:
        model  = Stall
        fields = [
            'id',
            'name',
            'owner',
            'description',
            'status',
            'status_display',
            'is_operational',
            'create_time',
            'modify_time',
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# 2. StallWriteSerializer — create and update
# ---------------------------------------------------------------------------
class StallWriteSerializer(serializers.ModelSerializer):
    """
    Write serializer for POST /api/stalls/ and PATCH /api/stalls/<id>/.

    Accepts owner_id as a plain integer (FK reference).

    Validation rules
    ----------------
    name
        Required on create; optional on partial update.
        Stripped of whitespace.

    owner_id
        Must reference an existing, active user with role='stall_owner'.
        Admin and customer users cannot own a stall.
        A deactivated (is_active=False) user cannot be set as owner.

    description
        Optional. Stripped; stored as empty string if blank.

    status
        Optional on create (defaults to 'active').
        On PATCH, use the dedicated action endpoints (activate/deactivate/
        suspend) rather than this field to enforce role-based transition rules.
        Direct status writes via PATCH are permitted for admin convenience
        but the action endpoints are the canonical way to change status.
    """

    owner_id = serializers.IntegerField(
        help_text='ID of an existing user with role=stall_owner.',
    )

    class Meta:
        model  = Stall
        fields = ['name', 'owner_id', 'description', 'status']
        extra_kwargs = {
            'name':        {'help_text': 'Display name of the stall.'},
            'description': {
                'required': False, 'allow_blank': True,
                'help_text': 'Short description of the stall.',
            },
            'status': {
                'required': False,
                'help_text': 'active | inactive | suspended (default: active).',
            },
        }

    # ── Field-level validation ──────────────────────────────────────────
    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Stall name cannot be blank.')
        return value

    def validate_description(self, value):
        return value.strip() if value else ''

    def validate_owner_id(self, value):
        """
        Ensure the referenced user:
          1. Exists (not soft-deleted).
          2. Has role='stall_owner'.
          3. Is active (is_active=True).
        """
        try:
            user = User.objects.get(pk=value)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                f'User with id={value} does not exist.'
            )

        if user.role != User.Role.STALL_OWNER:
            raise serializers.ValidationError(
                f'User "{user.username}" has role="{user.role}". '
                'Only users with role="stall_owner" can own a stall.'
            )

        if not user.is_active:
            raise serializers.ValidationError(
                f'User "{user.username}" is deactivated and cannot be assigned as stall owner. '
                'Activate the user account first.'
            )
        return value

    # ── Save ────────────────────────────────────────────────────────────
    def create(self, validated_data):
        return Stall.objects.create(**validated_data)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


# ---------------------------------------------------------------------------
# 3. StallStatusSerializer — used by action endpoints only
# ---------------------------------------------------------------------------
class StallStatusSerializer(serializers.ModelSerializer):
    """
    Minimal serializer for status-only updates.
    Used by: POST /api/stalls/<id>/activate/
             POST /api/stalls/<id>/deactivate/
             POST /api/stalls/<id>/suspend/

    Returns the updated stall with the new status after the action,
    serialised through StallReadSerializer (not this one directly).
    """

    class Meta:
        model  = Stall
        fields = ['status']
