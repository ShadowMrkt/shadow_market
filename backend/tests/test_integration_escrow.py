# backend/tests/test_integration_escrow.py
# <<< Revision 1.11.0: Addressed Bandit assert_used warning >>>
# Revision History:
# - v1.11.0 (2025-04-08):
#   - FIXED: Replaced all `assert` statements with explicit `if not condition: raise AssertionError(...)`
#     checks to bypass Bandit B101 warnings in this non-TestCase class. Split compound assertion lines. (#17)
# - v1.10.0 (2025-04-07):
#   - FIXED: Added `market_user_int` fixture dependency to `test_integration_resolve_dispute_crypto_fail`. (#16)
# - v1.9.7:
#   - FIXED: Added `market_user_int` fixture dependency to `test_integration_broadcast_btc_crypto_fail`.
#   - CLARIFIED: Note on `test_integration_resolve_dispute_split_success` failure cause.
# - v1.9.6:
#   - ADDED: `setup_method` to reset cache, fixing several stale cache issues.
# Previous revisions omitted for brevity.

import pytest
import unittest.mock
from decimal import Decimal, ROUND_DOWN
from unittest.mock import patch, MagicMock, ANY, call
from datetime import timedelta
import uuid

# --- Django Imports ---
from django.utils import timezone
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError, FieldError, ObjectDoesNotExist # Added ObjectDoesNotExist
from django.db import transaction, IntegrityError # Import IntegrityError

# --- Local Imports ---
from store.services import escrow_service
from store.services import bitcoin_service, monero_service # ethereum_service # Removed unused ETH import
# Use the inner class directly for status choices
from store.models import Order, GlobalSettings, CryptoPayment, Product, Category, OrderStatus as OrderStatusChoices # noqa
from ledger.models import LedgerTransaction, UserBalance
from ledger import services as ledger_service
from ledger.services import InsufficientFundsError, InvalidLedgerOperationError # Assuming this exists
from store.exceptions import CryptoProcessingError # Added import
# Import utility if needed (e.g., for atomic units conversion if not in service)
from store.utils.conversion import from_atomic, to_atomic # Assuming utils exist

User = get_user_model()

# --- Constants ---
MOCK_TX_HASH_BTC_INT = "aaa_int_" + "a"*56; MOCK_TX_HASH_XMR_INT = "bbb_int_" + "b"*56
MOCK_PSBT_DATA_INT = "mock_psbt_integration_test..."; MOCK_TXSET_DATA_INT = "mock_txset_integration_test..."
MOCK_DISPUTE_TX_HASH = "ccc_dispute_" + "c"*54
# Define fixed PKs for test objects consistent with escrow unit tests
BUYER_PK = 1001; VENDOR_PK = 1002; MODERATOR_PK = 1003; MARKET_USER_PK = 1004; PRODUCT_PK = 2001; CATEGORY_PK = 3001

# --- Fixtures ---
@pytest.fixture(autouse=True)
def mock_settings_integration(settings):
    settings.MARKET_USER_USERNAME = "market_int_user_v2" # Unique username
    settings.MARKET_FEE_PERCENTAGE_BTC = Decimal('2.0'); settings.MARKET_FEE_PERCENTAGE_XMR = Decimal('2.5')
    # Explicitly set network for consistency (required for address validation)
    settings.BITCOIN_NETWORK = 'testnet'
    settings.BITCOIN_RPC_URL = None; settings.MONERO_RPC_URL = None; settings.MONERO_WALLET_RPC_URL = None
    settings.PAYMENT_WAIT_HOURS = 1; settings.ORDER_AUTO_FINALIZE_DAYS = 14; settings.DISPUTE_WINDOW_DAYS = 7
    settings.BITCOIN_CONFIRMATIONS_NEEDED = 2; settings.MONERO_CONFIRMATIONS_NEEDED = 10
    return settings

@pytest.fixture
def global_settings_int(db, mock_settings_integration):
    # Ensure GlobalSettings uses the mocked settings
    gs, _ = GlobalSettings.objects.get_or_create(pk=1, defaults={
        'payment_wait_hours': settings.PAYMENT_WAIT_HOURS,
        'order_auto_finalize_days': settings.ORDER_AUTO_FINALIZE_DAYS,
        'dispute_window_days': settings.DISPUTE_WINDOW_DAYS,
        'market_fee_percentage_btc': settings.MARKET_FEE_PERCENTAGE_BTC,
        'market_fee_percentage_xmr': settings.MARKET_FEE_PERCENTAGE_XMR,
        'confirmations_needed_btc': settings.BITCOIN_CONFIRMATIONS_NEEDED,
        'confirmations_needed_xmr': settings.MONERO_CONFIRMATIONS_NEEDED
        # Add other fields if needed
    })
    # Update existing if necessary
    gs.market_fee_percentage_btc = settings.MARKET_FEE_PERCENTAGE_BTC
    gs.market_fee_percentage_xmr = settings.MARKET_FEE_PERCENTAGE_XMR
    # ... update other fields potentially ...
    gs.save()
    return gs


@pytest.fixture
def market_user_int(db, mock_settings_integration):
    user, _ = User.objects.get_or_create(pk=MARKET_USER_PK, defaults={'username': settings.MARKET_USER_USERNAME, 'is_staff': True, 'pgp_public_key': 'market_pgp_int'})
    UserBalance.objects.get_or_create(user=user, currency='BTC'); UserBalance.objects.get_or_create(user=user, currency='XMR')
    return user

@pytest.fixture
def test_buyer_int(db):
    user, _ = User.objects.get_or_create(pk=BUYER_PK, defaults={'username': 'test_buyer_int', 'pgp_public_key': 'buyer_pgp_int'})
    user.btc_withdrawal_address = "tb1qintegrationtestbuyeraddr1234567890xyz" # Example valid testnet addr
    user.xmr_withdrawal_address = "4integrationtestbuyeraddr1234567890xyz1234567890xyz1234567890xyz1234567890xyz1234567890xyz123456" # Example valid XMR addr
    user.save()
    UserBalance.objects.get_or_create(user=user, currency='BTC'); UserBalance.objects.get_or_create(user=user, currency='XMR')
    return user

@pytest.fixture
def integration_test_vendor(db):
    user, created = User.objects.get_or_create(pk=VENDOR_PK, defaults={'username': 'integration_test_vendor', 'is_vendor': True, 'pgp_public_key': 'vendor_pgp_int'})
    user.btc_withdrawal_address = "tb1qintegrationtestvendoraddr1234567890abc" # Example valid testnet addr
    user.xmr_withdrawal_address = "4integrationtestvendoraddr1234567890abc1234567890abc1234567890abc1234567890abc1234567890abc12345" # Example valid XMR addr
    user.save()
    UserBalance.objects.get_or_create(user=user, currency='BTC'); UserBalance.objects.get_or_create(user=user, currency='XMR')
    return user

@pytest.fixture
def integration_test_category(db):
    category, _ = Category.objects.get_or_create(pk=CATEGORY_PK, defaults={'name': 'Integration Test Category', 'slug': 'integration-test-category'})
    return category

@pytest.fixture
def test_product_int(db, integration_test_vendor, integration_test_category):
    product, created = Product.objects.get_or_create(pk=PRODUCT_PK, defaults={'vendor': integration_test_vendor, 'category': integration_test_category, 'name': 'Integration Test Product', 'slug': 'integration-test-product', 'price_btc': Decimal('0.02'), 'price_xmr': Decimal('1.5'), 'quantity': 10, 'accepted_currencies': 'BTC,XMR', 'description': 'Test product', 'is_active': True, 'ships_from': 'Integration Land', 'ships_to': 'Everywhere'})
    if not created: # Ensure vendor/category are correct if product already existed
        needs_save = False
        if getattr(product, 'vendor_id', None) != integration_test_vendor.pk: product.vendor = integration_test_vendor; needs_save = True
        if getattr(product, 'category_id', None) != integration_test_category.pk: product.category = integration_test_category; needs_save = True
        if needs_save: product.save()
    return product

# --- Fixtures creating Orders in various states ---

@pytest.fixture
def order_ready_for_broadcast_btc_int(db, test_buyer_int, integration_test_vendor, test_product_int, global_settings_int):
    total_price = test_product_int.price_btc; fee_perc = settings.MARKET_FEE_PERCENTAGE_BTC; quantizer = Decimal('1e-8'); fee = (total_price * fee_perc / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN); payout = (total_price - fee).quantize(quantizer, rounding=ROUND_DOWN)
    fee = max(Decimal('0.0'), fee); payout = max(Decimal('0.0'), payout)
    total_price_sats = bitcoin_service.btc_to_satoshis(total_price)
    vendor_addr = integration_test_vendor.btc_withdrawal_address or "tb1qdefaultvendoraddrfortest1234567890pqr"
    # Use a plausible testnet address format
    escrow_addr = "tb1qintegrationtestescrowaddr" + str(uuid.uuid4())[:10]

    order = Order.objects.create(id=uuid.uuid4(), buyer=test_buyer_int, vendor=integration_test_vendor, product=test_product_int, selected_currency='BTC', price_native_selected=total_price_sats, shipping_price_native_selected=0, total_price_native_selected=total_price_sats, quantity=1, status=OrderStatusChoices.SHIPPED, release_initiated=True,
                                 release_metadata={ "fee": str(fee), "payout": str(payout), "vendor_address": vendor_addr, "type": "btc_psbt", "data": MOCK_PSBT_DATA_INT, "signatures": {str(test_buyer_int.id): True, str(integration_test_vendor.id): True}, "ready_for_broadcast": True },
                                 btc_escrow_address=escrow_addr, btc_redeem_script="btc_redeem_script_int")
    CryptoPayment.objects.get_or_create( order=order, currency='BTC', defaults={'payment_address':'tb1qintegrationpayaddr'+ str(uuid.uuid4())[:10], 'expected_amount_native':order.total_price_native_selected, 'is_confirmed':True} )
    return order

@pytest.fixture
def order_ready_for_broadcast_xmr_int(db, test_buyer_int, integration_test_vendor, test_product_int, global_settings_int):
    total_price = test_product_int.price_xmr; fee_perc = settings.MARKET_FEE_PERCENTAGE_XMR; quantizer = Decimal('1e-12'); fee = (total_price * fee_perc / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN); payout = (total_price - fee).quantize(quantizer, rounding=ROUND_DOWN)
    fee = max(Decimal('0.0'), fee); payout = max(Decimal('0.0'), payout)
    total_price_pico = monero_service.xmr_to_piconero(total_price)
    vendor_addr = integration_test_vendor.xmr_withdrawal_address or "4defaultvendorxmraddrfortest1234567890abc1234567890abc1234567890abc1234567890abc1234567890abc1234"

    order = Order.objects.create(id=uuid.uuid4(), buyer=test_buyer_int, vendor=integration_test_vendor, product=test_product_int, selected_currency='XMR', price_native_selected=total_price_pico, shipping_price_native_selected=0, total_price_native_selected=total_price_pico, quantity=1, status=OrderStatusChoices.SHIPPED, release_initiated=True,
                                 xmr_multisig_wallet_name="int_test_xmr_wallet_" + str(uuid.uuid4())[:8],
                                 release_metadata={ "fee": str(fee), "payout": str(payout), "vendor_address": vendor_addr, "type": "xmr_unsigned_txset", "data": MOCK_TXSET_DATA_INT, "signatures": {str(test_buyer_int.id): True, str(integration_test_vendor.id): True}, "ready_for_broadcast": True })
    CryptoPayment.objects.get_or_create( order=order, currency='XMR', defaults={'payment_address':'xmr_int_pay_addr_'+ str(uuid.uuid4())[:10], 'expected_amount_native':order.total_price_native_selected, 'is_confirmed':True} )
    return order

@pytest.fixture
def order_disputed_btc_int(db, test_buyer_int, integration_test_vendor, test_product_int, global_settings_int):
    total_price = test_product_int.price_btc
    total_price_sats = bitcoin_service.btc_to_satoshis(total_price)
    # Use plausible testnet address format
    escrow_addr = "tb1qdisputeescrowaddr" + str(uuid.uuid4())[:10]
    payment_addr = 'tb1qdisputepayaddr'+ str(uuid.uuid4())[:10]

    order = Order.objects.create(
        id=uuid.uuid4(), buyer=test_buyer_int, vendor=integration_test_vendor, product=test_product_int,
        selected_currency='BTC', price_native_selected=total_price_sats, shipping_price_native_selected=0, total_price_native_selected=total_price_sats, quantity=1,
        status=OrderStatusChoices.PAYMENT_CONFIRMED, btc_escrow_address=escrow_addr,
    )
    # Set timestamps and status sequentially
    order.paid_at = timezone.now() - timedelta(days=2); order.status = OrderStatusChoices.SHIPPED; order.shipped_at = timezone.now() - timedelta(days=1); order.disputed_at = timezone.now(); order.status = OrderStatusChoices.DISPUTED; order.save()
    CryptoPayment.objects.get_or_create(
        order=order, currency='BTC', defaults={ 'payment_address': payment_addr, 'expected_amount_native': order.total_price_native_selected, 'is_confirmed': True, 'transaction_hash': 'dispute_btc_tx_hash_' + uuid.uuid4().hex[:10] }
    )
    # Reset balances
    UserBalance.objects.update_or_create(user=order.buyer, currency='BTC', defaults={'balance': Decimal('0.0'), 'locked_balance': Decimal('0.0')})
    UserBalance.objects.update_or_create(user=order.vendor, currency='BTC', defaults={'balance': Decimal('0.0'), 'locked_balance': Decimal('0.0')})
    return order

@pytest.fixture
def test_moderator_int(db):
    user, _ = User.objects.get_or_create(pk=MODERATOR_PK, defaults={'username': 'test_mod_int', 'is_staff': True, 'pgp_public_key': 'mod_pgp_int'})
    return user


# --- Test Class for Escrow Integration ---

@pytest.mark.django_db(transaction=True) # Ensure tests run in transaction for rollback
class TestEscrowIntegration:

    def setup_method(self, method):
        """ Reset escrow_service cache before each test in this class. """
        escrow_service._market_user_cache = None

    @patch('store.services.escrow_service.bitcoin_service.finalize_and_broadcast_btc_release')
    def test_integration_broadcast_btc_success(self, mock_btc_broadcast, order_ready_for_broadcast_btc_int, market_user_int):
        order = order_ready_for_broadcast_btc_int; vendor = order.vendor; order_id = order.id
        initial_vendor_balance = UserBalance.objects.get(user=vendor, currency='BTC').balance
        initial_market_balance = UserBalance.objects.get(user=market_user_int, currency='BTC').balance
        metadata = order.release_metadata; expected_payout_std = Decimal(metadata['payout']); expected_fee_std = Decimal(metadata['fee'])
        mock_btc_broadcast.return_value = MOCK_TX_HASH_BTC_INT

        # Pre-checks
        # R1.11.0: Replace assert with explicit check
        if not User.objects.filter(pk=order.vendor.id).exists():
            raise AssertionError(f"Pre-check failed: Vendor user {order.vendor.id} does not exist.")
        # R1.11.0: Replace assert with explicit check
        if not User.objects.filter(pk=market_user_int.id).exists():
            raise AssertionError(f"Pre-check failed: Market user {market_user_int.id} does not exist.")

        success = escrow_service.broadcast_release_transaction(order_id)

        # R1.11.0: Replace assert with explicit check
        if success is not True:
             raise AssertionError(f"Expected success to be True, but got {success}")
        mock_btc_broadcast.assert_called_once_with(order=order, current_psbt_base64=MOCK_PSBT_DATA_INT)
        order.refresh_from_db()
        # R1.11.0: Split and replace assertions
        if order.status != OrderStatusChoices.FINALIZED:
            raise AssertionError(f"Order status should be FINALIZED, but got {order.status}")
        if order.release_tx_broadcast_hash != MOCK_TX_HASH_BTC_INT:
            raise AssertionError(f"Order release_tx_broadcast_hash '{order.release_tx_broadcast_hash}' != '{MOCK_TX_HASH_BTC_INT}'")

        # Ledger checks...
        vendor_credits = LedgerTransaction.objects.filter(related_order=order, user=vendor, transaction_type='ESCROW_RELEASE_VENDOR')
        # R1.11.0: Split and replace assertions
        if vendor_credits.count() != 1:
            raise AssertionError(f"Expected 1 vendor credit, found {vendor_credits.count()}")
        if vendor_credits.first().amount != expected_payout_std:
            raise AssertionError(f"Vendor credit amount {vendor_credits.first().amount} != {expected_payout_std}")

        market_credits = LedgerTransaction.objects.filter(related_order=order, user=market_user_int, transaction_type='MARKET_FEE')
        if expected_fee_std > 0:
            # R1.11.0: Split and replace assertions
            if market_credits.count() != 1:
                raise AssertionError(f"Expected 1 market credit, found {market_credits.count()}")
            if market_credits.first().amount != expected_fee_std:
                 raise AssertionError(f"Market credit amount {market_credits.first().amount} != {expected_fee_std}")
        else:
            # R1.11.0: Replace assert with explicit check
            if market_credits.count() != 0:
                raise AssertionError(f"Expected 0 market credits, found {market_credits.count()}")

        # Balance checks...
        vendor_balance_after = UserBalance.objects.get(user=vendor, currency='BTC')
        # R1.11.0: Replace assert with explicit check
        if vendor_balance_after.balance != initial_vendor_balance + expected_payout_std:
            raise AssertionError(f"Vendor balance {vendor_balance_after.balance} != expected {initial_vendor_balance + expected_payout_std}")

        market_balance_after = UserBalance.objects.get(user=market_user_int, currency='BTC')
        # R1.11.0: Replace assert with explicit check
        if market_balance_after.balance != initial_market_balance + expected_fee_std:
            raise AssertionError(f"Market balance {market_balance_after.balance} != expected {initial_market_balance + expected_fee_std}")


    @patch('store.services.escrow_service.monero_service.finalize_and_broadcast_xmr_release')
    def test_integration_broadcast_xmr_success(self, mock_xmr_broadcast, order_ready_for_broadcast_xmr_int, market_user_int):
        order = order_ready_for_broadcast_xmr_int; vendor = order.vendor; order_id = order.id
        initial_vendor_balance = UserBalance.objects.get(user=vendor, currency='XMR').balance
        initial_market_balance = UserBalance.objects.get(user=market_user_int, currency='XMR').balance
        metadata = order.release_metadata; expected_payout_std = Decimal(metadata['payout']); expected_fee_std = Decimal(metadata['fee'])
        mock_xmr_broadcast.return_value = MOCK_TX_HASH_XMR_INT

        # Pre-checks
        # R1.11.0: Replace assert with explicit check
        if not User.objects.filter(pk=order.vendor.id).exists():
            raise AssertionError(f"Pre-check failed: Vendor user {order.vendor.id} does not exist.")
        # R1.11.0: Replace assert with explicit check
        if not User.objects.filter(pk=market_user_int.id).exists():
            raise AssertionError(f"Pre-check failed: Market user {market_user_int.id} does not exist.")

        success = escrow_service.broadcast_release_transaction(order_id)

        # R1.11.0: Replace assert with explicit check
        if success is not True:
             raise AssertionError(f"Expected success to be True, but got {success}")
        mock_xmr_broadcast.assert_called_once_with(order=order, current_txset_hex=MOCK_TXSET_DATA_INT)
        order.refresh_from_db()
        # R1.11.0: Split and replace assertions
        if order.status != OrderStatusChoices.FINALIZED:
            raise AssertionError(f"Order status should be FINALIZED, but got {order.status}")
        if order.release_tx_broadcast_hash != MOCK_TX_HASH_XMR_INT:
             raise AssertionError(f"Order release_tx_broadcast_hash '{order.release_tx_broadcast_hash}' != '{MOCK_TX_HASH_XMR_INT}'")

        # Ledger checks...
        vendor_credits = LedgerTransaction.objects.filter(related_order=order, user=vendor, transaction_type='ESCROW_RELEASE_VENDOR', currency='XMR')
        # R1.11.0: Split and replace assertions
        if vendor_credits.count() != 1:
             raise AssertionError(f"Expected 1 vendor credit, found {vendor_credits.count()}")
        if vendor_credits.first().amount != expected_payout_std:
             raise AssertionError(f"Vendor credit amount {vendor_credits.first().amount} != {expected_payout_std}")

        market_credits = LedgerTransaction.objects.filter(related_order=order, user=market_user_int, transaction_type='MARKET_FEE', currency='XMR')
        if expected_fee_std > 0:
            # R1.11.0: Split and replace assertions
            if market_credits.count() != 1:
                 raise AssertionError(f"Expected 1 market credit, found {market_credits.count()}")
            if market_credits.first().amount != expected_fee_std:
                 raise AssertionError(f"Market credit amount {market_credits.first().amount} != {expected_fee_std}")
        else:
             # R1.11.0: Replace assert with explicit check
             if market_credits.count() != 0:
                 raise AssertionError(f"Expected 0 market credits, found {market_credits.count()}")

        # Balance checks...
        vendor_balance_after = UserBalance.objects.get(user=vendor, currency='XMR')
        # R1.11.0: Replace assert with explicit check
        if vendor_balance_after.balance != initial_vendor_balance + expected_payout_std:
             raise AssertionError(f"Vendor balance {vendor_balance_after.balance} != expected {initial_vendor_balance + expected_payout_std}")

        market_balance_after = UserBalance.objects.get(user=market_user_int, currency='XMR')
        # R1.11.0: Replace assert with explicit check
        if market_balance_after.balance != initial_market_balance + expected_fee_std:
             raise AssertionError(f"Market balance {market_balance_after.balance} != expected {initial_market_balance + expected_fee_std}")

    @patch('store.services.escrow_service.bitcoin_service.finalize_and_broadcast_btc_release', return_value=None)
    def test_integration_broadcast_btc_crypto_fail(self, mock_btc_broadcast, order_ready_for_broadcast_btc_int, market_user_int):
        order = order_ready_for_broadcast_btc_int; vendor = order.vendor; order_id = order.id
        initial_status = order.status; initial_vendor_balance = UserBalance.objects.get(user=vendor, currency='BTC').balance
        mock_btc_broadcast.return_value = None # Ensure mock returns None

        # Pre-check market user
        # R1.11.0: Replace assert with explicit check
        if not User.objects.filter(pk=market_user_int.id).exists():
             raise AssertionError(f"Pre-check failed: Market user {market_user_int.id} does not exist.")

        with pytest.raises(CryptoProcessingError, match=f"Crypto broadcast failed for Order {order_id}.*"):
            escrow_service.broadcast_release_transaction(order_id)

        order.refresh_from_db()
        # R1.11.0: Split and replace assertions
        if order.status != initial_status:
            raise AssertionError(f"Order status should be {initial_status}, but got {order.status}")
        if order.release_tx_broadcast_hash is not None:
            raise AssertionError(f"Order release_tx_broadcast_hash should be None, but got {order.release_tx_broadcast_hash}")

        # R1.11.0: Replace assert with explicit check
        ledger_count = LedgerTransaction.objects.filter(related_order=order, transaction_type__in=['ESCROW_RELEASE_VENDOR', 'MARKET_FEE']).count()
        if ledger_count != 0:
            raise AssertionError(f"Expected 0 ledger transactions, found {ledger_count}")

        vendor_balance_after = UserBalance.objects.get(user=vendor, currency='BTC')
        # R1.11.0: Replace assert with explicit check
        if vendor_balance_after.balance != initial_vendor_balance:
             raise AssertionError(f"Vendor balance {vendor_balance_after.balance} != initial {initial_vendor_balance}")
        mock_btc_broadcast.assert_called_once()


    @patch('store.services.bitcoin_service.create_and_broadcast_dispute_tx')
    def test_integration_resolve_dispute_split_success(self, mock_dispute_broadcast,
                                                         order_disputed_btc_int, test_moderator_int, market_user_int):
        order = order_disputed_btc_int; buyer = order.buyer; vendor = order.vendor; order_id = order.id
        initial_buyer_balance = UserBalance.objects.get(user=buyer, currency='BTC').balance
        initial_vendor_balance = UserBalance.objects.get(user=vendor, currency='BTC').balance
        total_escrowed_atomic = order.total_price_native_selected
        if total_escrowed_atomic is None: pytest.fail(f"Fixture FAIL: Order {order.id} total_price_native_selected is None in dispute test setup.")

        mock_dispute_broadcast.return_value = MOCK_DISPUTE_TX_HASH
        buyer_percent = 30

        # Pre-checks
        # R1.11.0: Replace assert with explicit check
        if not User.objects.filter(pk=order.buyer.id).exists():
            raise AssertionError(f"Pre-check failed: Buyer user {order.buyer.id} does not exist.")
        # R1.11.0: Replace assert with explicit check
        if not User.objects.filter(pk=order.vendor.id).exists():
             raise AssertionError(f"Pre-check failed: Vendor user {order.vendor.id} does not exist.")
        # R1.11.0: Replace assert with explicit check
        if not User.objects.filter(pk=market_user_int.id).exists():
             raise AssertionError(f"Pre-check failed: Market user {market_user_int.id} does not exist.")

        success = escrow_service.resolve_dispute(
            order=order, moderator=test_moderator_int, resolution_notes="Split decision: 30% to buyer", release_to_buyer_percent=buyer_percent
        )

        # $$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$
        # NOTE (v1.10.0): THIS TEST STILL FAILS - `success` is False. Needs debugging inside escrow_service.py
        # $$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$
        # R1.11.0: Replace assert with explicit check
        if success is not True:
              raise AssertionError(f"Expected success to be True, but got {success} # Check overall success")

        mock_dispute_broadcast.assert_called_once()
        call_args, call_kwargs = mock_dispute_broadcast.call_args
        # R1.11.0: Replace assert with explicit check
        if call_kwargs.get('order') != order:
            raise AssertionError(f"Mock call kwarg 'order' {call_kwargs.get('order')} != {order}")

        # Calculate expected shares in standard BTC units
        total_escrowed_std = bitcoin_service.satoshis_to_btc(int(total_escrowed_atomic))
        quantizer = Decimal('1e-8')
        expected_buyer_share_std = (total_escrowed_std * Decimal(buyer_percent) / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
        expected_vendor_share_std = (total_escrowed_std - expected_buyer_share_std).quantize(quantizer, rounding=ROUND_DOWN)

        # Assert broadcast function was called with correct amounts
        # R1.11.0: Replace assert with explicit check
        if call_kwargs.get('buyer_payout_amount_btc') != expected_buyer_share_std:
             raise AssertionError(f"Mock call kwarg 'buyer_payout_amount_btc' {call_kwargs.get('buyer_payout_amount_btc')} != {expected_buyer_share_std}")
        # R1.11.0: Replace assert with explicit check
        if call_kwargs.get('vendor_payout_amount_btc') != expected_vendor_share_std:
            raise AssertionError(f"Mock call kwarg 'vendor_payout_amount_btc' {call_kwargs.get('vendor_payout_amount_btc')} != {expected_vendor_share_std}")

        order.refresh_from_db()
        # R1.11.0: Split and replace assertions
        if order.status != OrderStatusChoices.DISPUTE_RESOLVED:
             raise AssertionError(f"Order status should be DISPUTE_RESOLVED, but got {order.status}")
        if order.release_tx_broadcast_hash != MOCK_DISPUTE_TX_HASH:
             raise AssertionError(f"Order release_tx_broadcast_hash '{order.release_tx_broadcast_hash}' != '{MOCK_DISPUTE_TX_HASH}'")

        # Check Ledger entries
        buyer_credits = LedgerTransaction.objects.filter(related_order=order, user=buyer, transaction_type='DISPUTE_RESOLUTION_BUYER')
        vendor_credits = LedgerTransaction.objects.filter(related_order=order, user=vendor, transaction_type='DISPUTE_RESOLUTION_VENDOR')
        if expected_buyer_share_std > 0:
            # R1.11.0: Split and replace assertions
            if buyer_credits.count() != 1:
                raise AssertionError(f"Expected 1 buyer credit, found {buyer_credits.count()}")
            if buyer_credits.first().amount != expected_buyer_share_std:
                raise AssertionError(f"Buyer credit amount {buyer_credits.first().amount} != {expected_buyer_share_std}")
            if buyer_credits.first().external_txid != MOCK_DISPUTE_TX_HASH:
                 raise AssertionError(f"Buyer credit txid {buyer_credits.first().external_txid} != {MOCK_DISPUTE_TX_HASH}")
        else:
            # R1.11.0: Replace assert with explicit check
            if buyer_credits.count() != 0:
                raise AssertionError(f"Expected 0 buyer credits, found {buyer_credits.count()}")

        if expected_vendor_share_std > 0:
             # R1.11.0: Split and replace assertions
            if vendor_credits.count() != 1:
                 raise AssertionError(f"Expected 1 vendor credit, found {vendor_credits.count()}")
            if vendor_credits.first().amount != expected_vendor_share_std:
                 raise AssertionError(f"Vendor credit amount {vendor_credits.first().amount} != {expected_vendor_share_std}")
            if vendor_credits.first().external_txid != MOCK_DISPUTE_TX_HASH:
                 raise AssertionError(f"Vendor credit txid {vendor_credits.first().external_txid} != {MOCK_DISPUTE_TX_HASH}")
        else:
            # R1.11.0: Replace assert with explicit check
            if vendor_credits.count() != 0:
                 raise AssertionError(f"Expected 0 vendor credits, found {vendor_credits.count()}")

        # Check Final Balances
        buyer_balance_after = UserBalance.objects.get(user=buyer, currency='BTC')
        # R1.11.0: Replace assert with explicit check
        if buyer_balance_after.balance != initial_buyer_balance + expected_buyer_share_std:
             raise AssertionError(f"Buyer balance {buyer_balance_after.balance} != expected {initial_buyer_balance + expected_buyer_share_std}")

        vendor_balance_after = UserBalance.objects.get(user=vendor, currency='BTC')
        # R1.11.0: Replace assert with explicit check
        if vendor_balance_after.balance != initial_vendor_balance + expected_vendor_share_std:
             raise AssertionError(f"Vendor balance {vendor_balance_after.balance} != expected {initial_vendor_balance + expected_vendor_share_std}")

    @patch('store.services.bitcoin_service.create_and_broadcast_dispute_tx', return_value=None)
    # <<< FIX v1.10.0: Added market_user_int >>>
    def test_integration_resolve_dispute_crypto_fail(self, mock_dispute_broadcast, order_disputed_btc_int, test_moderator_int, market_user_int):
        order = order_disputed_btc_int; buyer = order.buyer; vendor = order.vendor; order_id = order.id
        initial_status = order.status; initial_buyer_balance = UserBalance.objects.get(user=buyer, currency='BTC').balance; initial_vendor_balance = UserBalance.objects.get(user=vendor, currency='BTC').balance

        # Pre-check market user
        # R1.11.0: Replace assert with explicit check
        if not User.objects.filter(pk=market_user_int.id).exists(): # Ensure market user exists
              raise AssertionError(f"Pre-check failed: Market user {market_user_int.id} does not exist.")

        with pytest.raises(CryptoProcessingError, match="Crypto dispute broadcast failed.*"):
            escrow_service.resolve_dispute(
                order=order, moderator=test_moderator_int, resolution_notes="Attempted resolution", release_to_buyer_percent=50
            )

        order.refresh_from_db()
        # R1.11.0: Replace assert with explicit check
        if order.status != initial_status: # Should remain DISPUTED
            raise AssertionError(f"Order status should be {initial_status}, but got {order.status}")
        # R1.11.0: Replace assert with explicit check
        if order.release_tx_broadcast_hash is not None:
            raise AssertionError(f"Order release_tx_broadcast_hash should be None, but got {order.release_tx_broadcast_hash}")
        # If Order model has dispute_resolved_by, uncomment below:
        # if order.dispute_resolved_by is not None: raise AssertionError(...)

        # R1.11.0: Replace assert with explicit check
        ledger_count = LedgerTransaction.objects.filter(related_order=order, transaction_type__in=['DISPUTE_RESOLUTION_VENDOR', 'DISPUTE_RESOLUTION_BUYER']).count()
        if ledger_count != 0:
             raise AssertionError(f"Expected 0 dispute ledger transactions, found {ledger_count}")

        buyer_balance_after = UserBalance.objects.get(user=buyer, currency='BTC')
        # R1.11.0: Replace assert with explicit check
        if buyer_balance_after.balance != initial_buyer_balance:
             raise AssertionError(f"Buyer balance {buyer_balance_after.balance} != initial {initial_buyer_balance}")

        vendor_balance_after = UserBalance.objects.get(user=vendor, currency='BTC')
        # R1.11.0: Replace assert with explicit check
        if vendor_balance_after.balance != initial_vendor_balance:
             raise AssertionError(f"Vendor balance {vendor_balance_after.balance} != initial {initial_vendor_balance}")
        mock_dispute_broadcast.assert_called_once()

# <<< END OF INTEGRATION TEST SUITE >>>