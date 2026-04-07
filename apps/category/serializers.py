"""
apps/category/serializers.py
============================
DRF serializers for the Category model.

Serializers
-----------
CategoryReadSerializer
    Full read-only representation returned in list and retrieve responses.
    Includes the computed product_count field so the frontend can display
    how many products belong to each category without a second request.

CategoryWriteSerializer
    Shared write serializer used for both CREATE (POST) and UPDATE (PATCH).
    Normalises the name to title-case, validates uniqueness, and rejects
    blank descriptions (treats blank as empty string instead).

CategorySummarySerializer
    Lightweight serializer (id + name only) used as a nested field inside
    ProductReadSerializer so the full category object is embedded in every
    product response without including timestamps or product_count.
"""

from rest_framework import serializers
from .models import Category


# ---------------------------------------------------------------------------
# 1. CategoryReadSerializer — full read output
# ---------------------------------------------------------------------------
class CategoryReadSerializer(serializers.ModelSerializer):
    """
    Read-only serializer returned by list / retrieve endpoints.
    Adds the computed product_count so the frontend pill row can show
    how many items are in each category (e.g. "Clothing (4)").
    """

    product_count = serializers.SerializerMethodField(
        help_text='Total number of products currently assigned to this category.',
    )

    class Meta:
        model  = Category
        fields = [
            'id',
            'name',
            'description',
            'product_count',
            'create_time',
            'modify_time',
        ]
        read_only_fields = fields

    def get_product_count(self, obj):
        """Hit the reverse FK relation product_set to count assigned products."""
        return obj.product_set.count()


# ---------------------------------------------------------------------------
# 2. CategoryWriteSerializer — create and update
# ---------------------------------------------------------------------------
class CategoryWriteSerializer(serializers.ModelSerializer):
    """
    Write serializer for POST /api/categories/ and PATCH /api/categories/<id>/.

    Validation rules
    ----------------
    name
        - Required on create; optional on partial update.
        - Stripped of leading/trailing whitespace.
        - Converted to title-case  (e.g. "home essentials" → "Home Essentials")
          for consistent display across the frontend filter pills.
        - Must be unique (enforced at DB level; also checked here to return a
          friendly message instead of a raw IntegrityError).

    description
        - Optional.
        - Stripped of whitespace; stored as empty string if omitted.
    """

    class Meta:
        model  = Category
        fields = ['name', 'description']
        extra_kwargs = {
            'name':        {'help_text': 'Unique category name (title-cased automatically).'},
            'description': {
                'required':   False,
                'allow_blank': True,
                'help_text':  'Short description of the category (optional).',
            },
        }

    # ── Field-level validation ──────────────────────────────────────────
    def validate_name(self, value):
        """
        Normalise to title-case and verify uniqueness.
        Excludes the current instance from the uniqueness check during updates.
        """
        value = value.strip().title()

        if not value:
            raise serializers.ValidationError('Category name cannot be blank.')

        qs = Category.objects.filter(name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError(
                f'A category named "{value}" already exists.'
            )
        return value

    def validate_description(self, value):
        """Strip whitespace; return empty string for blank/None values."""
        return value.strip() if value else ''

    # ── Save ────────────────────────────────────────────────────────────
    def create(self, validated_data):
        return Category.objects.create(**validated_data)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


# ---------------------------------------------------------------------------
# 3. CategorySummarySerializer — lightweight nested use
# ---------------------------------------------------------------------------
class CategorySummarySerializer(serializers.ModelSerializer):
    """
    Minimal (id + name) serializer embedded inside ProductReadSerializer.

    Keeps product API responses lightweight — no timestamps or counts —
    while still giving the frontend all it needs to render the category pill
    and populate the category dropdown on the product form.
    """

    class Meta:
        model  = Category
        fields = ['id', 'name']
        read_only_fields = fields
