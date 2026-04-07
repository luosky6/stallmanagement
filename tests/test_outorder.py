"""
tests/test_outorder.py
======================
Tests for the OutOrder model, signals, and REST API.

Coverage
--------
- OutOrder model: status helpers, is_editable, computed totals
- Create order with lines (draft)
- Retrieve and update draft orders
- Complete order: stock check + deduction (signal)
- Complete order with insufficient stock: transaction rollback, no partial deduction
- Cancel draft order: no stock change
- Cancel completed order (admin only): stock RESTORED via signal
- Delete draft order only
- Permission checks: only admin can cancel completed orders
- Concurrent-request guard: completing the same order twice is safe
"""

import pytest
from django.db import transaction

from apps.outorder.models import OutOrder, OutOrderProduct
from apps.product.models import Product
from tests.conftest import assert_ok, assert_fail

pytestmark = pytest.mark.django_db


# ===========================================================================
# OutOrder model unit tests
# ===========================================================================
class TestOutOrderModel:

    def test_status_helpers(self, draft_outorder):
        assert draft_outorder.is_draft      is True
        assert draft_outorder.is_completed  is False
        assert draft_outorder.is_cancelled  is False
        assert draft_outorder.is_editable   is True

    def test_total_amount(self, draft_outorder):
        assert draft_outorder.total_amount == 20

    def test_total_value(self, draft_outorder):
        # 20 × 59.99
        assert draft_outorder.total_value == pytest.approx(1199.80, rel=1e-4)

    def test_str_representation(self, draft_outorder):
        assert 'OUT20241201001' in str(draft_outorder)

    def test_completed_order_not_editable(self, draft_outorder):
        draft_outorder._previous_status = draft_outorder.status
        draft_outorder.status = OutOrder.Status.COMPLETED
        draft_outorder.save()
        assert draft_outorder.is_editable is False


# ===========================================================================
# OutOrder API: Create
# ===========================================================================
class TestOutOrderCreate:

    def test_owner_can_create_draft_order(self, owner_client, buyer, product):
        response = owner_client.post('/api/outorders/', {
            'code':        'OUT20250101001',
            'customer_id': buyer.id,
            'remark':      'Test sale',
            'lines': [
                {'product_id': product.id, 'amount': 10, 'unit_price': '59.99'},
            ],
        }, format='json')
        data = assert_ok(response, code=201)
        assert data['code'] == 'OUT20250101001'
        assert data['status'] == 'draft'
        assert len(data['lines']) == 1

    def test_create_order_with_supplier_fails(self, owner_client, supplier, product):
        """Outbound orders require a BUYER, not a supplier."""
        response = owner_client.post('/api/outorders/', {
            'code':        'OUT20250101002',
            'customer_id': supplier.id,
            'lines': [{'product_id': product.id, 'amount': 5}],
        }, format='json')
        assert_fail(response, code=400)

    def test_create_does_not_change_stock(self, owner_client, buyer, product):
        """Creating a draft order must NOT modify stock."""
        initial_stock = product.stock
        owner_client.post('/api/outorders/', {
            'code':        'OUT20250101003',
            'customer_id': buyer.id,
            'lines': [{'product_id': product.id, 'amount': 10}],
        }, format='json')
        product.refresh_from_db()
        assert product.stock == initial_stock

    def test_duplicate_product_in_lines_fails(self, owner_client, buyer, product):
        response = owner_client.post('/api/outorders/', {
            'code':        'OUT20250101004',
            'customer_id': buyer.id,
            'lines': [
                {'product_id': product.id, 'amount': 5},
                {'product_id': product.id, 'amount': 10},  # duplicate
            ],
        }, format='json')
        assert_fail(response, code=400)

    def test_customer_cannot_create_order(self, customer_client, buyer, product):
        response = customer_client.post('/api/outorders/', {
            'code':        'OUT20250101005',
            'customer_id': buyer.id,
            'lines': [{'product_id': product.id, 'amount': 1}],
        }, format='json')
        assert response.status_code == 403


# ===========================================================================
# OutOrder API: Complete — stock deduction
# ===========================================================================
class TestOutOrderComplete:

    def test_complete_order_deducts_stock(self, owner_client, draft_outorder, product):
        initial_stock = product.stock   # 100
        response = owner_client.post(f'/api/outorders/{draft_outorder.id}/complete/')
        assert_ok(response)

        product.refresh_from_db()
        assert product.stock == initial_stock - 20   # 80

    def test_complete_changes_status(self, owner_client, draft_outorder):
        owner_client.post(f'/api/outorders/{draft_outorder.id}/complete/')
        draft_outorder.refresh_from_db()
        assert draft_outorder.status == OutOrder.Status.COMPLETED

    def test_insufficient_stock_returns_400(self, owner_client, buyer, stall_owner_user,
                                             zero_stock_product):
        """Completing an order when stock=0 must fail with shortfall details."""
        order = OutOrder.objects.create(
            code='OUTZERO001', customer=buyer, operator=stall_owner_user, status='draft'
        )
        OutOrderProduct.objects.create(
            outorder=order, product=zero_stock_product, amount=5, unit_price='10'
        )
        response = owner_client.post(f'/api/outorders/{order.id}/complete/')
        fail_data = assert_fail(response, code=400)

        # Response must include shortfall details
        details = fail_data.get('data')
        assert details is not None
        assert len(details) == 1
        assert details[0]['product_id'] == zero_stock_product.id
        assert details[0]['shortfall'] == 5

    def test_insufficient_stock_does_not_deduct_any_stock(
        self, owner_client, buyer, stall_owner_user, product, zero_stock_product
    ):
        """With multi-line order, if ONE line fails the ENTIRE transaction rolls back."""
        initial_product_stock = product.stock   # 100

        order = OutOrder.objects.create(
            code='OUTPARTIAL001', customer=buyer, operator=stall_owner_user, status='draft'
        )
        # Line 1: product has enough stock (100 available, want 10)
        OutOrderProduct.objects.create(
            outorder=order, product=product, amount=10, unit_price='59.99'
        )
        # Line 2: zero_stock_product has 0 stock (want 5 → will fail)
        OutOrderProduct.objects.create(
            outorder=order, product=zero_stock_product, amount=5, unit_price='10'
        )

        response = owner_client.post(f'/api/outorders/{order.id}/complete/')
        assert_fail(response, code=400)

        # CRITICAL: product stock must be completely unchanged (no partial deduction)
        product.refresh_from_db()
        assert product.stock == initial_product_stock

        # Order must remain in draft (rolled back)
        order.refresh_from_db()
        assert order.status == OutOrder.Status.DRAFT

    def test_cannot_complete_already_completed_order(self, owner_client, draft_outorder):
        owner_client.post(f'/api/outorders/{draft_outorder.id}/complete/')
        response = owner_client.post(f'/api/outorders/{draft_outorder.id}/complete/')
        assert_fail(response, code=400)

    def test_complete_order_without_lines_fails(self, owner_client, buyer, stall_owner_user):
        empty = OutOrder.objects.create(
            code='OUTEMPTY001', customer=buyer, operator=stall_owner_user, status='draft'
        )
        response = owner_client.post(f'/api/outorders/{empty.id}/complete/')
        assert_fail(response, code=400)


# ===========================================================================
# OutOrder API: Cancel
# ===========================================================================
class TestOutOrderCancel:

    def test_cancel_draft_order_no_stock_change(self, owner_client, draft_outorder, product):
        initial_stock = product.stock
        response = owner_client.post(f'/api/outorders/{draft_outorder.id}/cancel/')
        assert_ok(response)
        product.refresh_from_db()
        assert product.stock == initial_stock

    def test_cancel_changes_draft_status(self, owner_client, draft_outorder):
        owner_client.post(f'/api/outorders/{draft_outorder.id}/cancel/')
        draft_outorder.refresh_from_db()
        assert draft_outorder.status == OutOrder.Status.CANCELLED

    def test_admin_can_cancel_completed_order_and_stock_is_restored(
        self, admin_client, owner_client, draft_outorder, product
    ):
        initial_stock = product.stock   # 100

        # Complete the order (stock 100 → 80)
        owner_client.post(f'/api/outorders/{draft_outorder.id}/complete/')
        product.refresh_from_db()
        assert product.stock == initial_stock - 20

        # Admin cancels the completed order (stock 80 → 100)
        response = admin_client.post(f'/api/outorders/{draft_outorder.id}/cancel/')
        assert_ok(response)

        product.refresh_from_db()
        assert product.stock == initial_stock   # fully restored

    def test_stall_owner_cannot_cancel_completed_order(
        self, owner_client, draft_outorder, product
    ):
        owner_client.post(f'/api/outorders/{draft_outorder.id}/complete/')
        response = owner_client.post(f'/api/outorders/{draft_outorder.id}/cancel/')
        assert_fail(response, code=403)

    def test_cancel_already_cancelled_order_returns_400(self, owner_client, draft_outorder):
        owner_client.post(f'/api/outorders/{draft_outorder.id}/cancel/')
        response = owner_client.post(f'/api/outorders/{draft_outorder.id}/cancel/')
        assert_fail(response, code=400)


# ===========================================================================
# OutOrder API: Update
# ===========================================================================
class TestOutOrderUpdate:

    def test_update_draft_remark(self, owner_client, draft_outorder):
        response = owner_client.patch(f'/api/outorders/{draft_outorder.id}/', {
            'remark': 'Updated remark',
        }, format='json')
        data = assert_ok(response)
        assert data['remark'] == 'Updated remark'

    def test_cannot_edit_completed_order(self, owner_client, draft_outorder):
        owner_client.post(f'/api/outorders/{draft_outorder.id}/complete/')
        response = owner_client.patch(f'/api/outorders/{draft_outorder.id}/', {
            'remark': 'Should fail',
        }, format='json')
        assert_fail(response, code=400)

    def test_status_change_via_patch_rejected(self, owner_client, draft_outorder):
        response = owner_client.patch(f'/api/outorders/{draft_outorder.id}/', {
            'status': 'completed',
        }, format='json')
        assert_fail(response, code=400)


# ===========================================================================
# OutOrder API: Delete
# ===========================================================================
class TestOutOrderDelete:

    def test_delete_draft_order(self, owner_client, draft_outorder):
        order_id = draft_outorder.id
        response = owner_client.delete(f'/api/outorders/{order_id}/delete/')
        assert_ok(response)
        assert not OutOrder.objects.filter(pk=order_id).exists()
        assert not OutOrderProduct.objects.filter(outorder_id=order_id).exists()

    def test_cannot_delete_completed_order(self, owner_client, draft_outorder):
        owner_client.post(f'/api/outorders/{draft_outorder.id}/complete/')
        response = owner_client.delete(f'/api/outorders/{draft_outorder.id}/delete/')
        assert_fail(response, code=400)

    def test_delete_message_suggests_cancel(self, owner_client, draft_outorder):
        owner_client.post(f'/api/outorders/{draft_outorder.id}/complete/')
        response = owner_client.delete(f'/api/outorders/{draft_outorder.id}/delete/')
        assert 'cancel' in response.data.get('message', '').lower()
