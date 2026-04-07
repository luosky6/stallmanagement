"""
apps/customer/serializers.py
============================
DRF serializers for the Customer model.

Serializers
-----------
CustomerReadSerializer
    Full read-only representation returned in list and retrieve responses.
    Includes computed helper fields (is_supplier, is_buyer, order counts).

CustomerWriteSerializer
    Shared write serializer used for both CREATE (POST) and UPDATE (PATCH).
    Validates phone format and enforces uniqueness of name+phone combination
    to prevent accidental duplicate contacts.
"""

from rest_framework import serializers
from .models import Customer


# ---------------------------------------------------------------------------
# 1. CustomerReadSerializer — safe read output
# ---------------------------------------------------------------------------
class CustomerReadSerializer(serializers.ModelSerializer):
    """
    Read-only serializer returned by list / retrieve endpoints.

    Extra computed fields
    ---------------------
    customer_type_display   Human-readable label for the customer_type value.
    inbound_order_count     Number of inbound orders linked to this supplier.
    outbound_order_count    Number of outbound orders linked to this buyer.
    """

    customer_type_display = serializers.CharField(
        source='get_customer_type_display',
        read_only=True,
        help_text='Human-readable contact type label.',
    )

    inbound_order_count = serializers.SerializerMethodField(
        help_text='Total number of inbound (purchase) orders from this supplier.',
    )
    outbound_order_count = serializers.SerializerMethodField(
        help_text='Total number of outbound (sales) orders to this buyer.',
    )

    class Meta:
        model  = Customer
        fields = [
            'id',
            'name',
            'phone',
            'address',
            'customer_type',
            'customer_type_display',
            'inbound_order_count',
            'outbound_order_count',
            'create_time',
            'modify_time',
        ]
        read_only_fields = fields

    def get_inbound_order_count(self, obj):
        """Count of inbound orders where this contact is the supplier."""
        return obj.inorder_set.count()

    def get_outbound_order_count(self, obj):
        """Count of outbound orders where this contact is the buyer."""
        return obj.outorder_set.count()


# ---------------------------------------------------------------------------
# 2. CustomerWriteSerializer — create and update
# ---------------------------------------------------------------------------
class CustomerWriteSerializer(serializers.ModelSerializer):
    """
    Write serializer for POST /api/customers/ and PATCH /api/customers/<id>/.

    Validation rules
    ----------------
    - name      : required, stripped of leading/trailing whitespace
    - phone     : validated by the model's RegexValidator; also stripped
    - address   : required, stripped
    - customer_type : must be 'supplier' or 'buyer'

    Uniqueness check
    ----------------
    The combination of (name, phone) must be unique among all customers.
    This prevents duplicate contact entries for the same person/company.
    The check is skipped for the current instance during updates (partial=True).
    """

    class Meta:
        model  = Customer
        fields = [
            'name',
            'phone',
            'address',
            'customer_type',
        ]
        extra_kwargs = {
            'name':          {'help_text': 'Full name of the supplier or buyer.'},
            'phone':         {'help_text': 'Contact phone (7–20 digits, optional +/spaces/hyphens).'},
            'address':       {'help_text': 'Business address.'},
            'customer_type': {'help_text': 'supplier | buyer'},
        }

    # ── Field-level validation ──────────────────────────────────────────
    def validate_name(self, value):
        """Strip whitespace; reject blank names."""
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Name cannot be blank.')
        return value

    def validate_phone(self, value):
        """Strip whitespace from the phone number."""
        return value.strip()

    def validate_address(self, value):
        """Strip whitespace; reject blank addresses."""
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Address cannot be blank.')
        return value

    def validate_customer_type(self, value):
        """Ensure the type is one of the two valid choices."""
        valid_types = [ct.value for ct in Customer.CustomerType]
        if value not in valid_types:
            raise serializers.ValidationError(
                f'"{value}" is not valid. Choose from: {valid_types}.'
            )
        return value

    # ── Object-level validation ─────────────────────────────────────────
    def validate(self, attrs):
        """
        Enforce uniqueness of (name, phone) combination.
        During updates, exclude the current instance from the uniqueness check.
        """
        name  = attrs.get('name',  getattr(self.instance, 'name',  None))
        phone = attrs.get('phone', getattr(self.instance, 'phone', None))

        qs = Customer.objects.filter(name=name, phone=phone)

        # Exclude the current record when updating
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError(
                {
                    'non_field_errors': (
                        f'A customer named "{name}" with phone "{phone}" already exists. '
                        'Please verify you are not creating a duplicate entry.'
                    )
                }
            )
        return attrs

    # ── Save ────────────────────────────────────────────────────────────
    def create(self, validated_data):
        return Customer.objects.create(**validated_data)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
