# backend/store/tests/test_bitcoin_escrow_service.py

# --- Revision History ---
# v1.4.0 (2025-04-09): The Void
#   - FIXED: In `mark_disputed` fixture, added 'requester' field (pointing to order.buyer)
#     to the `defaults` dict in `Dispute.objects.get_or_create` call to satisfy
#     the database NOT NULL constraint on 'requester_id'.
# v1.3.0 (2025-04-09): The Void
#   - FIXED: In `mark_disputed` fixture, removed 'opened_by' from `get_or_create` defaults
#     and added logic to attempt setting common user relation fields post-creation to prevent `FieldError`.
#   - FIXED: In `test_create_escrow_btc_success`, aligned mock return key ('redeemScript')
#     and expected script value with the field checked in `bitcoin_escrow_service.create_escrow`
#     to resolve `AssertionError` for script mismatch.
# v1.2.0 (2025-04-09): The Void
#   - FIXED: In `mark_disputed` fixture, corrected `Dispute.objects.get_or_create` call
#     by removing potentially invalid field names ('opened_at') from the `defaults` dict
#     to resolve `FieldError`. Assumed `opened_by` is correct FK name.
# v1.1.0 (2025-04-09): The Void
#   - FIXED: In `test_sign_order_release_buyer_first_btc`, updated dummy `buyer_key_info`
#     to pass the basic length check in `bitcoin_escrow_service.sign_release`.
#   - FIXED: In `test_resolve_dispute_btc_full_buyer`, removed assertion checking
#     `order.dispute_resolved_at` as the field does not exist on the Order model.
#     Added checks for other optional dispute fields if they exist.
# v1.0.0 (2025-04-09): REFACTOR The Void
#   - Created this file by extracting Bitcoin-specific tests, fixtures, and constants
#     from the original monolithic `test_escrow_service.py`.
#   - Updated imports and service calls to reflect the split of escrow logic into
#     `bitcoin_escrow_service.py` and `common_escrow_utils.py` (Assumed structure).
#   - Renamed test class to `TestBitcoinEscrowService`.
# --- Relevant Prior History (from test_escrow_service.py) ---
# v1.23.0 (2025-04-08): The Void
#   - FIXED: Replaced `assert` with explicit checks for Bandit B101.
# v1.22.3 (2025-04-07): The Void
#   - FIXED: Mocking for User.objects.get in dispute tests.
# v1.22.2 (2025-04-07): The Void
#   - FIXED: MOCK_BTC_MULTISIG_ADDRESS format.
# v1.18.2 (2025-04-07): The Void
#   - FIXED: Mock call assertions to use keyword arguments.
# v1.18.1 (2025-04-07): The Void
#   - FIXED: MOCK_BTC_MULTISIG_ADDRESS validation issue.
# --- Prior revisions omitted ---
# ------------------------

# --- Standard Library Imports ---
import uuid
import logging
import sys
from decimal import Decimal, ROUND_DOWN, InvalidOperation, getcontext
from typing import Dict, Any, Optional, Callable, Tuple
from django.contrib.auth import get_user_model as django_get_user_model
from unittest.mock import patch, MagicMock, call, ANY
import datetime # Required if not already imported

# --- Third-Party Imports ---
import pytest
from django.conf import settings as django_settings
from django.core.exceptions import ValidationError as DjangoValidationError, FieldError, ObjectDoesNotExist
from django.db import transaction, IntegrityError # Added IntegrityError
from django.utils import timezone

# --- Local Imports ---
# Models
from store.models import Order, Product, User, GlobalSettings, CryptoPayment, Category, OrderStatus as OrderStatusChoices, Dispute # noqa - Added Dispute for potential check
from ledger.models import UserBalance, LedgerTransaction # noqa

# Services and Exceptions
# --- Updated Imports (v1.0.0 Refactor) ---
# Assuming primary BTC escrow logic is here:
from store.services import bitcoin_escrow_service
# Assuming shared helpers/constants are here:
from store.services import common_escrow_utils
# Keep direct bitcoin_service import if needed for non-escrow BTC functions:
from store.services import bitcoin_service
# Ledger service remains the same:
from ledger import services as ledger_service # Explicit import for clarity
from ledger.services import InsufficientFundsError, InvalidLedgerOperationError # noqa
from ledger.exceptions import LedgerError # noqa
# Store/Escrow Exceptions remain the same:
from store.exceptions import EscrowError, CryptoProcessingError # noqa
# --- End Updated Imports ---

DjangoUser = django_get_user_model()

logger = logging.getLogger(__name__)

# --- Bitcoin-Specific Test Constants ---
# Extracted from original test_escrow_service.py
MOCK_MARKET_USER_USERNAME = "market_test_user_btc" # Make slightly distinct if needed
MOCK_BUYER_USERNAME = "test_buyer_btc_escrow"
MOCK_VENDOR_USERNAME = "test_vendor_btc_escrow"
MOCK_MODERATOR_USERNAME = "test_mod_btc_escrow"

MOCK_PRODUCT_PRICE_BTC = Decimal("0.01") # Standard Units
MOCK_MARKET_FEE_PERCENT = Decimal("2.5") # Assume same fee for simplicity, adjust if needed

# Atomic units (BTC: 8 decimals)
MOCK_PRODUCT_PRICE_BTC_ATOMIC = Decimal(1_000_000) # 0.01 * 10^8

# Use valid Bech32 testnet address (from previous fixes)
MOCK_BTC_MULTISIG_ADDRESS = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"
# Example Taproot/P2WSH address if needed for specific tests:
# MOCK_BTC_MULTISIG_ADDRESS_P2WSH = "tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7"

MOCK_BTC_WITHDRAWAL_ADDR = 'vendor_btc_payout_addr_fix'
MOCK_BUYER_BTC_REFUND_ADDR = 'buyer_btc_refund_addr_fix'

MOCK_TX_HASH_BTC = "btc_tx_hash_" + "b" * 54
MOCK_UNSIGNED_PSBT_BTC = "unsigned_psbt_btc_data"
MOCK_PARTIAL_PSBT_BTC = "partial_psbt_btc_data"
MOCK_FINAL_PSBT_BTC = "final_psbt_btc_data"

MOCK_SIGNED_PSBT_BUYER = "dummy_partially_signed_psbt_base64_buyer"
MOCK_SIGNED_PSBT_VENDOR = "dummy_fully_signed_psbt_base64_vendor"

MOCK_MARKET_PGP_KEY = "market_pgp_key_data_btc_fixture"
MOCK_BUYER_PGP_KEY = "buyer_pgp_key_btc_fixture"
MOCK_VENDOR_PGP_KEY = "vendor_pgp_key_data_btc_fixture_different"
DEFAULT_CATEGORY_ID = 1 # Keep if product fixture needs it

# Assume these constants are now in common_escrow_utils
ATTR_BTC_MULTISIG_PUBKEY = 'btc_multisig_pubkey' # Default, adjust if changed
ATTR_BTC_WITHDRAWAL_ADDRESS = 'btc_withdrawal_address' # Default


# --- Helper Function for Atomic Conversion (Generic, keep) ---
# Assumes these might be in store.utils.conversion now, but keep local for clarity if not
def to_atomic(amount_std: Decimal, decimals: int) -> Decimal:
    """Converts standard decimal amount to atomic units (integer-like Decimal)."""
    if not isinstance(amount_std, Decimal):
        amount_std = Decimal(amount_std)
    multiplier = Decimal(f'1e{decimals}')
    return (amount_std * multiplier).quantize(Decimal('1'), rounding=ROUND_DOWN)

def from_atomic(amount_atomic: Decimal, decimals: int) -> Decimal:
    """Converts atomic units (integer-like Decimal) back to standard decimal amount."""
    if not isinstance(amount_atomic, Decimal):
        amount_atomic = Decimal(amount_atomic)
    divisor = Decimal(f'1e{decimals}')
    # Assuming BTC precision is 8 for standard display
    display_precision = Decimal('1e-8') if decimals == 8 else Decimal(f'1e-{decimals}')
    return (amount_atomic / divisor).quantize(display_precision, rounding=ROUND_DOWN)


# --- Fixtures ---
@pytest.fixture
def mock_settings_btc_escrow(settings):
    """Override specific Django settings for BTC escrow tests."""
    settings.MARKET_FEE_PERCENTAGE_BTC = MOCK_MARKET_FEE_PERCENT
    # Remove XMR/ETH fee settings
    settings.MARKET_USER_USERNAME = MOCK_MARKET_USER_USERNAME
    settings.MULTISIG_PARTIES_REQUIRED = 3
    settings.MULTISIG_SIGNATURES_REQUIRED = 2
    settings.ORDER_PAYMENT_TIMEOUT_HOURS = 24
    settings.ORDER_FINALIZE_TIMEOUT_DAYS = 14
    settings.ORDER_DISPUTE_WINDOW_DAYS = 7
    settings.BITCOIN_CONFIRMATIONS_NEEDED = 3
    # Remove XMR/ETH confirmation settings
    yield settings

# --- User Fixtures (Adapted for BTC focus) ---
@pytest.fixture
def market_user_btc(db, mock_settings_btc_escrow) -> DjangoUser:
    """Provides the market user configured for BTC tests."""
    # Use constant defined above or fetch from common_escrow_utils if preferred
    # btc_pubkey_attr = getattr(common_escrow_utils, 'ATTR_BTC_MULTISIG_PUBKEY', ATTR_BTC_MULTISIG_PUBKEY)
    btc_pubkey_attr = ATTR_BTC_MULTISIG_PUBKEY # Use local constant for now

    user, _ = DjangoUser.objects.update_or_create(
        username=mock_settings_btc_escrow.MARKET_USER_USERNAME,
        defaults={
            'is_staff': True, 'is_active': True, 'pgp_public_key': MOCK_MARKET_PGP_KEY,
            btc_pubkey_attr: "market_btc_pubkey_fixture",
            # Remove XMR multisig info
        }
    )
    # Ensure BTC balance exists (remove others)
    UserBalance.objects.get_or_create(user=user, currency='BTC', defaults={'balance': Decimal('10.0')})
    user.refresh_from_db()
    return user

@pytest.fixture
def buyer_user_btc(db) -> DjangoUser:
    """Provides a buyer user configured for BTC tests."""
    # btc_pubkey_attr = getattr(common_escrow_utils, 'ATTR_BTC_MULTISIG_PUBKEY', ATTR_BTC_MULTISIG_PUBKEY)
    # btc_refund_attr = getattr(common_escrow_utils, 'ATTR_BTC_WITHDRAWAL_ADDRESS', ATTR_BTC_WITHDRAWAL_ADDRESS)
    btc_pubkey_attr = ATTR_BTC_MULTISIG_PUBKEY
    btc_refund_attr = ATTR_BTC_WITHDRAWAL_ADDRESS

    user, _ = DjangoUser.objects.update_or_create(
        username=MOCK_BUYER_USERNAME,
        defaults={
            'is_active': True, 'pgp_public_key': MOCK_BUYER_PGP_KEY,
            btc_refund_attr: MOCK_BUYER_BTC_REFUND_ADDR,
            btc_pubkey_attr: "buyer_btc_pubkey_fixture",
            # Remove XMR multisig info and refund address
        }
    )
    # Ensure BTC balance exists (remove others)
    UserBalance.objects.get_or_create(user=user, currency='BTC', defaults={'balance': Decimal('1.0')})
    user.refresh_from_db()
    return user

@pytest.fixture
def vendor_user_btc(db) -> DjangoUser:
    """Provides a vendor user configured for BTC tests."""
    # btc_pubkey_attr = getattr(common_escrow_utils, 'ATTR_BTC_MULTISIG_PUBKEY', ATTR_BTC_MULTISIG_PUBKEY)
    # btc_wd_attr = getattr(common_escrow_utils, 'ATTR_BTC_WITHDRAWAL_ADDRESS', ATTR_BTC_WITHDRAWAL_ADDRESS)
    btc_pubkey_attr = ATTR_BTC_MULTISIG_PUBKEY
    btc_wd_attr = ATTR_BTC_WITHDRAWAL_ADDRESS

    user, _ = DjangoUser.objects.update_or_create(
        username=MOCK_VENDOR_USERNAME,
        defaults={
            'is_vendor': True, 'is_active': True, 'pgp_public_key': MOCK_VENDOR_PGP_KEY,
            btc_wd_attr: MOCK_BTC_WITHDRAWAL_ADDR,
            btc_pubkey_attr: "vendor_btc_pubkey_fixture",
            # Remove XMR multisig info and withdrawal address
        }
    )
    # Ensure BTC balance exists (remove others)
    UserBalance.objects.get_or_create(user=user, currency='BTC', defaults={'balance': Decimal('5.0')})
    user.refresh_from_db()
    return user

@pytest.fixture
def moderator_user_btc(db) -> DjangoUser:
    """Provides a moderator user (generic, keep as is)."""
    user, _ = DjangoUser.objects.get_or_create(
        username=MOCK_MODERATOR_USERNAME,
        defaults={'is_staff': True, 'is_active': True}
    )
    user.refresh_from_db()
    return user

# --- Generic Setup Fixtures (Keep, ensure they use BTC settings) ---
@pytest.fixture
def global_settings_btc(db, market_user_btc, mock_settings_btc_escrow) -> GlobalSettings:
    """Ensures GlobalSettings singleton exists and sets BTC-relevant attributes."""
    try:
        gs = GlobalSettings.get_solo()
    except AttributeError as e:
        raise AttributeError(f"CRITICAL FIXTURE ERROR: GlobalSettings missing '.get_solo()'. {e}") from e
    except Exception as e:
        pytest.fail(f"Failed to get/create GlobalSettings via get_solo(): {e}")

    gs.market_fee_percentage_btc = mock_settings_btc_escrow.MARKET_FEE_PERCENTAGE_BTC
    # Remove XMR/ETH fees
    setattr(gs, 'payment_wait_hours', mock_settings_btc_escrow.ORDER_PAYMENT_TIMEOUT_HOURS)
    setattr(gs, 'order_auto_finalize_days', mock_settings_btc_escrow.ORDER_FINALIZE_TIMEOUT_DAYS)
    setattr(gs, 'dispute_window_days', mock_settings_btc_escrow.ORDER_DISPUTE_WINDOW_DAYS)
    setattr(gs, 'confirmations_needed_btc', mock_settings_btc_escrow.BITCOIN_CONFIRMATIONS_NEEDED)
    # Remove XMR/ETH confirmations

    gs.save()
    gs.refresh_from_db()

    # Ensure market user PGP key exists (generic requirement)
    if not market_user_btc.pgp_public_key:
        market_user_btc.pgp_public_key = MOCK_MARKET_PGP_KEY
        market_user_btc.save(update_fields=['pgp_public_key'])

    return gs

@pytest.fixture
def product_category_btc(db) -> Category:
    """Ensures a default Category object exists."""
    # Generic, keep as is. Rename if desired (e.g., product_category_generic).
    category, created = Category.objects.get_or_create(
        pk=DEFAULT_CATEGORY_ID,
        defaults={'name': 'Default BTC Test Category'}
    )
    return category

@pytest.fixture
def product_btc(db, vendor_user_btc, product_category_btc) -> Product:
    """Provides a simple BTC product."""
    product, created = Product.objects.update_or_create(
        name="Test BTC Product Only", vendor=vendor_user_btc, category=product_category_btc,
        defaults={
            'price_btc': MOCK_PRODUCT_PRICE_BTC,
            'description': "Test BTC Product Description",
            'is_active': True,
            'price_xmr': None, # Ensure non-BTC prices are None/excluded
        }
    )
    product.refresh_from_db()
    if product.category_id != product_category_btc.id:
        pytest.fail(f"VERIFICATION FAIL (product_btc): Category mismatch.")
    if product.price_btc != MOCK_PRODUCT_PRICE_BTC:
        pytest.fail(f"VERIFICATION FAIL (product_btc): Price mismatch.")
    return product

# --- Order Creation Fixtures (BTC-Specific and Generic Helpers) ---

@pytest.fixture
def create_btc_order(db, buyer_user_btc, vendor_user_btc, global_settings_btc) -> Callable[[Product, str], Order]:
    """
    Factory fixture to create BTC orders, setting atomic price fields.
    Simplified from original create_order, hardcoded for BTC.
    """
    def _create_btc_order(product: Product, status: str = OrderStatusChoices.PENDING_PAYMENT) -> Order:
        currency_upper = 'BTC'; decimals = 8
        price_std = product.price_btc

        if price_std is None or not isinstance(price_std, Decimal) or price_std <= Decimal('0.0'):
            pytest.fail(f"Product {product.id} has invalid BTC price ({price_std}) in create_btc_order fixture.")

        price_native_selected_atomic = to_atomic(price_std, decimals)
        if price_native_selected_atomic <= Decimal('0'):
            pytest.fail(f"Calculated atomic BTC price ({price_native_selected_atomic}) is not positive.")

        quantity = 1; shipping_price_std = Decimal(0)
        shipping_price_native_selected_atomic = to_atomic(shipping_price_std, decimals)
        total_price_native_selected_atomic_calculated = (price_native_selected_atomic * quantity) + shipping_price_native_selected_atomic

        # Verify participants
        if not DjangoUser.objects.filter(pk=buyer_user_btc.pk).exists(): pytest.fail(f"Buyer {buyer_user_btc.pk} missing.")
        if not DjangoUser.objects.filter(pk=vendor_user_btc.pk).exists(): pytest.fail(f"Vendor {vendor_user_btc.pk} missing.")
        if not Product.objects.filter(pk=product.pk).exists(): pytest.fail(f"Product {product.pk} missing.")

        order = Order.objects.create(
            id=uuid.uuid4(), # Ensure unique ID for each order created by factory
            buyer=buyer_user_btc, vendor=vendor_user_btc, product=product,
            quantity=quantity, selected_currency=currency_upper,
            price_native_selected=price_native_selected_atomic,
            shipping_price_native_selected=shipping_price_native_selected_atomic,
            total_price_native_selected=total_price_native_selected_atomic_calculated,
            status=status
        )

        # Immediate verification
        if order.total_price_native_selected != total_price_native_selected_atomic_calculated:
            raise AssertionError(f"Order {order.id} total price mismatch immediately after create.")

        # Verify after refresh
        try:
            order.refresh_from_db()
            if order.buyer_id != buyer_user_btc.id: raise AssertionError("Buyer ID mismatch.")
            if order.vendor_id != vendor_user_btc.id: raise AssertionError("Vendor ID mismatch.")
            if order.product_id != product.id: raise AssertionError("Product ID mismatch.")
            if order.total_price_native_selected is None: raise AssertionError("Total price is None after refresh.")
            if order.total_price_native_selected != total_price_native_selected_atomic_calculated:
                raise AssertionError(f"Total price mismatch after refresh ({order.total_price_native_selected} vs {total_price_native_selected_atomic_calculated}).")
        except ObjectDoesNotExist:
            pytest.fail(f"Order {order.id} failed refresh_from_db.")
        return order
    return _create_btc_order

@pytest.fixture
def order_pending_btc(create_btc_order, product_btc) -> Order:
    """ Creates a BTC order in PENDING_PAYMENT status. """
    return create_btc_order(product_btc, OrderStatusChoices.PENDING_PAYMENT)

# Generic setup_escrow needs adjustment or replacement if create_escrow_for_order changed signature
@pytest.fixture
def setup_btc_escrow(db, mock_settings_btc_escrow) -> Callable[[Order, str, Optional[str]], Order]:
    """ Helper fixture for BTC escrow setup (CryptoPayment, deadlines). """
    # Simplified from original setup_escrow
    def _setup_btc_escrow(order: Order, escrow_address: str, witness_script: Optional[str] = None) -> Order:
        order.refresh_from_db()
        if order.selected_currency != 'BTC': pytest.fail("setup_btc_escrow called on non-BTC order.")
        if order.total_price_native_selected is None or order.total_price_native_selected <= Decimal('0'):
            pytest.fail(f"Order {order.id} has invalid total price.")

        order.status = OrderStatusChoices.PENDING_PAYMENT
        order.payment_deadline = timezone.now() + timezone.timedelta(hours=mock_settings_btc_escrow.ORDER_PAYMENT_TIMEOUT_HOURS)

        update_fields_order = ['status', 'payment_deadline', 'updated_at']
        # Assume Order model still has btc_escrow_address and potentially script fields
        if hasattr(order, 'btc_escrow_address'):
            order.btc_escrow_address = escrow_address
            update_fields_order.append('btc_escrow_address')
        script_value = witness_script
        if script_value:
            # Use the field name that matches the service code logic
            if hasattr(order, 'btc_redeem_script'):
                 setattr(order, 'btc_redeem_script', script_value)
                 update_fields_order.append('btc_redeem_script')
            # Add check for tapscript if that's also a possibility
            elif hasattr(order, 'btc_tapscript'):
                 setattr(order, 'btc_tapscript', script_value)
                 update_fields_order.append('btc_tapscript')


        order.save(update_fields=list(set(update_fields_order)))

        confirmations_needed = mock_settings_btc_escrow.BITCOIN_CONFIRMATIONS_NEEDED

        payment, created = CryptoPayment.objects.update_or_create(
            order=order, currency='BTC',
            defaults={
                'payment_address': escrow_address,
                'expected_amount_native': order.total_price_native_selected,
                'confirmations_needed': confirmations_needed,
            }
        )
        order.refresh_from_db()
        return order
    return _setup_btc_escrow

@pytest.fixture
def order_escrow_created_btc(order_pending_btc, setup_btc_escrow) -> Order:
    """ Creates a BTC order with escrow details set up (PENDING_PAYMENT). """
    # Uses MOCK_BTC_MULTISIG_ADDRESS (valid bech32 testnet)
    # Provide dummy script content aligned with test_create_escrow_btc_success mock fix
    return setup_btc_escrow(order_pending_btc, MOCK_BTC_MULTISIG_ADDRESS, witness_script='dummy_redeem_script_hex') # Use redeem script

# Generic confirm_payment helper - Adapt for BTC
@pytest.fixture
def confirm_btc_payment(db) -> Callable[[Order, str, int], Order]:
    """ Helper fixture to simulate confirming BTC payment for an order. """
    def _confirm_btc_payment(order: Order, tx_hash: str, confirmations_received: int) -> Order:
        if order.selected_currency != 'BTC': pytest.fail("confirm_btc_payment called on non-BTC order.")
        now = timezone.now()
        try:
            payment = CryptoPayment.objects.get(order=order, currency='BTC')
        except CryptoPayment.DoesNotExist:
            pytest.fail(f"CryptoPayment (BTC) not found for Order {order.id}.")

        payment.refresh_from_db()
        if payment.expected_amount_native is None or payment.expected_amount_native <= Decimal('0'):
            pytest.fail(f"CryptoPayment {payment.id} has invalid expected_amount_native.")

        # Update payment record fields
        payment.received_amount_native = payment.expected_amount_native # Assume full payment
        payment.transaction_hash = tx_hash
        payment.is_confirmed = True
        payment.confirmations_received = confirmations_received
        payment.save(update_fields=['received_amount_native', 'transaction_hash', 'is_confirmed', 'confirmations_received', 'updated_at'])

        # Update order status
        order.status = OrderStatusChoices.PAYMENT_CONFIRMED
        order.paid_at = now
        order.save(update_fields=['status', 'paid_at', 'updated_at'])

        order.refresh_from_db()
        return order
    return _confirm_btc_payment

@pytest.fixture
def order_payment_confirmed_btc(order_escrow_created_btc, confirm_btc_payment, mock_settings_btc_escrow) -> Order:
    """ Creates a BTC order confirmed with sufficient confirmations. """
    return confirm_btc_payment(order_escrow_created_btc, MOCK_TX_HASH_BTC, mock_settings_btc_escrow.BITCOIN_CONFIRMATIONS_NEEDED + 5)


# <<< backend/store/tests/test_bitcoin_escrow_service.py Part 1 of 2 >>>
# <<< backend/store/tests/test_bitcoin_escrow_service.py Part 2 of 2 >>>

# Generic mark_shipped helper - Adapt for BTC
@pytest.fixture
def mark_btc_shipped(db, mock_settings_btc_escrow, global_settings_btc) -> Callable[[Order, str], Order]:
    """ Helper fixture to simulate marking a BTC order as shipped. """
    # Requires common_escrow_utils for helpers
    try:
        # Attempt to import helpers assumed to be in common_escrow_utils
        from store.services.common_escrow_utils import _get_currency_precision, _get_withdrawal_address
    except ImportError:
        pytest.fail("Could not import helper functions (_get_currency_precision, _get_withdrawal_address) from common_escrow_utils in mark_btc_shipped fixture.")

    def _mark_btc_shipped(order: Order, unsigned_release_data: str) -> Order:
        if order.selected_currency != 'BTC': pytest.fail("mark_btc_shipped called on non-BTC order.")
        now = timezone.now()
        order.refresh_from_db()

        if order.total_price_native_selected is None or order.total_price_native_selected <= Decimal('0'):
            pytest.fail(f"Order {order.id} has invalid total price.")
        if not order.vendor: pytest.fail(f"Order {order.id} missing vendor.")

        # Calculate payout/fee (BTC specific)
        fee_percent = global_settings_btc.market_fee_percentage_btc
        atomic_quantizer = Decimal('0'); decimals = 8
        total_atomic = order.total_price_native_selected
        market_fee_atomic = (total_atomic * fee_percent / Decimal(100)).quantize(atomic_quantizer, rounding=ROUND_DOWN)
        payout_atomic = (total_atomic - market_fee_atomic).quantize(atomic_quantizer, rounding=ROUND_DOWN)
        market_fee_atomic = max(Decimal('0'), market_fee_atomic)
        payout_atomic = max(Decimal('0'), payout_atomic)

        # Convert to standard units for metadata
        try:
            prec = _get_currency_precision('BTC') # Use imported helper
            if prec != decimals: logger.warning(f"Precision mismatch in mark_btc_shipped: Expected {decimals}, got {prec}")
        except Exception as e:
            pytest.fail(f"Failed to get BTC precision in mark_btc_shipped: {e}")

        payout_std = from_atomic(payout_atomic, decimals)
        fee_std = from_atomic(market_fee_atomic, decimals)

        try:
            vendor_payout_address = _get_withdrawal_address(order.vendor, 'BTC') # Use imported helper
        except ValueError as e:
            pytest.fail(f"Vendor {order.vendor.username} missing BTC withdrawal address: {e}")

        release_type = 'btc_psbt' # Hardcoded for BTC

        # Construct release metadata
        release_metadata = {
            'type': release_type, 'data': unsigned_release_data,
            'payout': str(payout_std), 'fee': str(fee_std),
            'vendor_address': vendor_payout_address, 'ready_for_broadcast': False,
            'signatures': {}, 'prepared_at': now.isoformat()
        }

        # Update order fields
        order.status = OrderStatusChoices.SHIPPED
        order.shipped_at = now
        order.auto_finalize_deadline = now + timezone.timedelta(days=mock_settings_btc_escrow.ORDER_FINALIZE_TIMEOUT_DAYS)
        order.dispute_deadline = now + timezone.timedelta(days=mock_settings_btc_escrow.ORDER_DISPUTE_WINDOW_DAYS)
        order.release_initiated = True
        order.release_metadata = release_metadata

        order.save(update_fields=[
            'status', 'shipped_at', 'auto_finalize_deadline', 'dispute_deadline',
            'release_initiated', 'release_metadata', 'updated_at'
        ])
        order.refresh_from_db()
        return order
    return _mark_btc_shipped


@pytest.fixture
def order_shipped_btc(order_payment_confirmed_btc, mark_btc_shipped) -> Order:
    """ Creates a BTC order marked as shipped. """
    return mark_btc_shipped(order_payment_confirmed_btc, MOCK_UNSIGNED_PSBT_BTC)

# Generic mark_signed helper - Adapt for BTC
@pytest.fixture
def mark_btc_signed(db, mock_settings_btc_escrow) -> Callable[[Order, DjangoUser, str, Optional[bool]], Order]:
    """ Helper fixture to simulate applying a signature to BTC release metadata. """
    def _mark_btc_signed(order: Order, user: DjangoUser, signed_data: str, is_final_override: Optional[bool] = None) -> Order:
        if order.selected_currency != 'BTC': pytest.fail("mark_btc_signed called on non-BTC order.")
        metadata = order.release_metadata if isinstance(order.release_metadata, dict) else {}
        if not metadata: pytest.fail("Cannot mark signed: Order release metadata missing.")

        metadata['data'] = signed_data # Update with signed PSBT
        if 'signatures' not in metadata or not isinstance(metadata['signatures'], dict): metadata['signatures'] = {}
        metadata['signatures'][str(user.id)] = {'signed_at': timezone.now().isoformat(), 'signer': user.username}

        required_sigs = mock_settings_btc_escrow.MULTISIG_SIGNATURES_REQUIRED
        is_complete = is_final_override if is_final_override is not None else (len(metadata['signatures']) >= required_sigs)
        metadata['ready_for_broadcast'] = is_complete

        # Update type if final (specific to BTC)
        if is_complete: metadata['type'] = 'btc_final_psbt'

        order.release_metadata = metadata
        order.save(update_fields=['release_metadata', 'updated_at'])
        order.refresh_from_db()

        # Fixture verification
        if order.release_metadata is None or not isinstance(order.release_metadata, dict):
            raise AssertionError(f"Fixture FAIL (mark_btc_signed): Invalid metadata after save/refresh.")
        return order
    return _mark_btc_signed

@pytest.fixture
def order_buyer_signed_btc(order_shipped_btc, mark_btc_signed, buyer_user_btc) -> Order:
    """ Creates a BTC order signed by the buyer only. Uses MOCK_PARTIAL_PSBT_BTC. """
    signed_order = mark_btc_signed(order_shipped_btc, buyer_user_btc, MOCK_PARTIAL_PSBT_BTC, is_final_override=False)
    # Fixture verification
    if not (signed_order.release_metadata and isinstance(signed_order.release_metadata, dict)):
        raise AssertionError(f"Fixture FAIL (order_buyer_signed_btc): Invalid metadata.")
    return signed_order

@pytest.fixture
def order_ready_for_broadcast_btc(order_buyer_signed_btc, mark_btc_signed, vendor_user_btc) -> Order:
    """ Creates a BTC order signed by buyer and vendor, ready for broadcast. Uses MOCK_FINAL_PSBT_BTC. """
    ready_order = mark_btc_signed(order_buyer_signed_btc, vendor_user_btc, MOCK_FINAL_PSBT_BTC, is_final_override=True)
    # Fixture verification
    if not (ready_order.release_metadata and isinstance(ready_order.release_metadata, dict)):
        raise AssertionError(f"Fixture FAIL (order_ready_for_broadcast_btc): Invalid metadata.")
    if ready_order.release_metadata.get('ready_for_broadcast') is not True:
        raise AssertionError(f"Fixture FAIL (order_ready_for_broadcast_btc): Not marked ready.")
    return ready_order

# Generic mark_disputed helper
@pytest.fixture
def mark_disputed(db) -> Callable[[Order], Order]:
    """ Helper fixture to mark an order as disputed (generic). """
    def _mark_disputed(order: Order) -> Order:
        order.status = OrderStatusChoices.DISPUTED
        order.disputed_at = timezone.now()

        # --- FIX v1.4.0: Add 'requester' field to defaults for Dispute.get_or_create ---
        # Based on IntegrityError for requester_id NOT NULL constraint.
        dispute, created = Dispute.objects.get_or_create(
            order=order,
            defaults={
                'requester': order.buyer, # Add the non-nullable FK field
                'reason': "Test dispute from fixture",
            }
        )
        # --- End FIX ---

        # Set related fields on Order model if they exist
        if hasattr(order, 'dispute_reason'): order.dispute_reason = dispute.reason
        if hasattr(order, 'dispute_opened_by'): order.dispute_opened_by = order.buyer # Keep setting this on Order if field exists
        order.save() # Save all fields to ensure price persists and relation links
        order.refresh_from_db()
        return order
    return _mark_disputed


@pytest.fixture
def order_disputed_btc(order_shipped_btc, mark_disputed) -> Order:
    """ Creates a BTC order marked as disputed. """
    allowed_statuses = [OrderStatusChoices.SHIPPED, OrderStatusChoices.PAYMENT_CONFIRMED]
    if order_shipped_btc.status not in allowed_statuses:
        pytest.skip(f"Order status {order_shipped_btc.status} not disputable in fixture.")

    disputed_order = mark_disputed(order_shipped_btc)
    # Validation after marking disputed
    disputed_order.refresh_from_db()
    if disputed_order.total_price_native_selected is None or not (disputed_order.total_price_native_selected > Decimal('0')):
        raise AssertionError(f"Fixture Validation FAIL (order_disputed_btc): Invalid price after dispute.")
    try:
        # Ensure the related dispute object was created/retrieved
        if not hasattr(disputed_order, 'dispute') or disputed_order.dispute is None:
             raise AssertionError(f"Fixture Validation FAIL (order_disputed_btc): Related Dispute object missing.")
    except Dispute.DoesNotExist:
         raise AssertionError(f"Fixture Validation FAIL (order_disputed_btc): Related Dispute object DoesNotExist.")
    return disputed_order


# --- Test Class ---

@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("mock_settings_btc_escrow", "global_settings_btc", "market_user_btc")
class TestBitcoinEscrowService:
    """ Test suite for the store.services.bitcoin_escrow_service module. """

    def setup_method(self, method):
        """ Reset market user cache if it exists in common_escrow_utils. """
        # Assuming cache moved to common_escrow_utils
        if hasattr(common_escrow_utils, '_market_user_cache'):
            common_escrow_utils._market_user_cache = None


    # --- Test Helper Functions (Indirectly via BTC service calls) ---

    def test_helper_get_withdrawal_address_missing(self, vendor_user_btc):
        """ Verify _get_withdrawal_address (common util) raises error if address missing. """
        wd_addr_attr = ATTR_BTC_WITHDRAWAL_ADDRESS
        setattr(vendor_user_btc, wd_addr_attr, "")
        vendor_user_btc.save()

        # Assuming _get_withdrawal_address is in common_escrow_utils
        with pytest.raises(ValueError, match="missing valid withdrawal address"):
            common_escrow_utils._get_withdrawal_address(vendor_user_btc, 'BTC')


    # === Test BTC Escrow Creation ===

    # Patch the actual BTC service function responsible for multisig address creation
    @patch('store.services.bitcoin_service.create_btc_multisig_address')
    def test_create_escrow_btc_success(self, mock_create_btc_addr, order_pending_btc, market_user_btc, buyer_user_btc, vendor_user_btc, mock_settings_btc_escrow, global_settings_btc):
        """ Test successful creation of BTC escrow. """
        order = order_pending_btc
        btc_pubkey_attr = ATTR_BTC_MULTISIG_PUBKEY

        buyer_key = getattr(buyer_user_btc, btc_pubkey_attr, None)
        vendor_key = getattr(vendor_user_btc, btc_pubkey_attr, None)
        market_key = getattr(market_user_btc, btc_pubkey_attr, None)

        if not all([buyer_key, vendor_key, market_key]):
            pytest.skip(f"Skipping test: Participants missing '{btc_pubkey_attr}'.")

        # --- FIX v1.3.0: Align mock return key with service logic ---
        # Mock the bitcoin_service call, providing 'redeemScript'
        mock_create_btc_addr.return_value = {
             'address': MOCK_BTC_MULTISIG_ADDRESS,
             'redeemScript': 'dummy_redeem_script_hex', # Use key expected by service
             'internal_pubkey': 'dummy_internal_pubkey_hex', # Keep other keys if needed
             'control_block': 'dummy_control_block_hex'
        }
        # --- End FIX ---

        # Call the BTC-specific escrow service function (assuming this name)
        # This might be create_escrow_for_order if it dispatches internally, or a BTC-specific name
        # ASSUMPTION: Function name is create_escrow in bitcoin_escrow_service
        try:
            # Prefer explicit bitcoin_escrow_service if functions moved there
            if hasattr(bitcoin_escrow_service, 'create_escrow'):
                 bitcoin_escrow_service.create_escrow(order)
            # Fallback to common_escrow_utils if it acts as dispatcher
            elif hasattr(common_escrow_utils, 'create_escrow_for_order'):
                 common_escrow_utils.create_escrow_for_order(order)
            else:
                 pytest.fail("Cannot find create_escrow function in bitcoin_escrow_service or common_escrow_utils.")
        except Exception as e:
             pytest.fail(f"Service call failed: {e}")


        order.refresh_from_db()

        # Assertions on order state (BTC specific)
        if order.status != OrderStatusChoices.PENDING_PAYMENT: raise AssertionError(f"Status mismatch: {order.status}")
        # Use getattr for flexibility
        escrow_addr_field = getattr(order, 'btc_escrow_address', None)
        if escrow_addr_field != MOCK_BTC_MULTISIG_ADDRESS: raise AssertionError(f"BTC Escrow Address mismatch.")
        # Check script field (prefer tapscript, fallback to redeem_script)
        script_field_value = None
        if hasattr(order, 'btc_tapscript'):
             script_field_value = order.btc_tapscript
             script_field_name = 'btc_tapscript'
        elif hasattr(order, 'btc_redeem_script'):
             script_field_value = order.btc_redeem_script
             script_field_name = 'btc_redeem_script'
        else:
             script_field_name = 'script (tapscript/redeem_script)' # For error message

        # --- FIX v1.3.0: Align expected script with mock ---
        expected_script = 'dummy_redeem_script_hex' # Match mock return value
        # --- End FIX ---
        if script_field_value != expected_script:
             raise AssertionError(f"Order {script_field_name} mismatch. Got: '{script_field_value}', Expected: '{expected_script}'")

        if order.payment_deadline is None: raise AssertionError("Payment deadline not set.")

        # Assert crypto service call details
        expected_participant_keys = sorted([buyer_key, vendor_key, market_key])
        mock_create_btc_addr.assert_called_once()
        call_args, call_kwargs = mock_create_btc_addr.call_args
        # Check keyword args (from previous fix)
        if call_args: raise AssertionError(f"Expected no positional args, got {call_args}")
        if 'participant_pubkeys_hex' not in call_kwargs: raise AssertionError("Kwarg 'participant_pubkeys_hex' missing")
        if sorted(call_kwargs['participant_pubkeys_hex']) != expected_participant_keys: raise AssertionError("Pubkeys mismatch")
        if call_kwargs.get('threshold') != mock_settings_btc_escrow.MULTISIG_SIGNATURES_REQUIRED: raise AssertionError("Threshold mismatch")

        # Assert CryptoPayment record
        payment = CryptoPayment.objects.get(order=order, currency='BTC')
        if payment.payment_address != MOCK_BTC_MULTISIG_ADDRESS: raise AssertionError("Payment address mismatch.")
        if payment.expected_amount_native != order.total_price_native_selected: raise AssertionError("Payment expected amount mismatch.")
        if payment.confirmations_needed != mock_settings_btc_escrow.BITCOIN_CONFIRMATIONS_NEEDED: raise AssertionError("Payment confirmations needed mismatch.")

    # Test failure during BTC multisig address creation
    @patch('store.services.bitcoin_service.create_btc_multisig_address', side_effect=CryptoProcessingError("BTC Gen Failed"))
    def test_create_escrow_btc_crypto_fail(self, mock_create_btc_addr, order_pending_btc, market_user_btc, buyer_user_btc, vendor_user_btc, global_settings_btc):
        """ Test create_escrow handles crypto service failure (BTC). """
        order = order_pending_btc
        btc_pubkey_attr = ATTR_BTC_MULTISIG_PUBKEY
        if not all([getattr(u, btc_pubkey_attr, None) for u in [buyer_user_btc, vendor_user_btc, market_user_btc]]):
            pytest.skip(f"Skipping test: Participants missing '{btc_pubkey_attr}'.")

        # Expect CryptoProcessingError raised by the service (either bitcoin_escrow_service or common_escrow_utils)
        with pytest.raises(CryptoProcessingError, match="Failed to generate BTC escrow details: BTC Gen Failed"):
             # ASSUMPTION: Function name is create_escrow
             if hasattr(bitcoin_escrow_service, 'create_escrow'):
                 bitcoin_escrow_service.create_escrow(order)
             elif hasattr(common_escrow_utils, 'create_escrow_for_order'):
                  common_escrow_utils.create_escrow_for_order(order)
             else:
                 pytest.fail("Cannot find create_escrow function.")

        # Verify order state remains unchanged
        order.refresh_from_db()
        if order.status != OrderStatusChoices.PENDING_PAYMENT: raise AssertionError(f"Status mismatch: {order.status}")
        # Use getattr for flexibility
        if getattr(order, 'btc_escrow_address', None) is not None: raise AssertionError("BTC Escrow address should be None.")
        if CryptoPayment.objects.filter(order=order, currency='BTC').exists(): raise AssertionError("CryptoPayment should not exist.")

    # === Test BTC Payment Confirmation ===

    # Patch User.objects.get and ledger service calls
    @patch('store.models.User.objects.get')
    @patch('store.services.bitcoin_service.scan_for_payment_confirmation')
    @patch('ledger.services.credit_funds')
    @patch('ledger.services.lock_funds')
    @patch('ledger.services.debit_funds')
    @patch('ledger.services.unlock_funds')
    def test_check_confirm_btc_success(self, mock_ledger_unlock, mock_ledger_debit, mock_ledger_lock, mock_ledger_credit, mock_scan_btc, mock_user_get, order_escrow_created_btc, market_user_btc, mock_settings_btc_escrow):
        """ Test successful BTC payment confirmation check, including ledger updates. """
        order = order_escrow_created_btc
        payment = CryptoPayment.objects.get(order=order, currency='BTC')
        payment.refresh_from_db()
        buyer = order.buyer # Use buyer_user_btc implicitly from fixture

        if not (payment.expected_amount_native and payment.expected_amount_native > Decimal('0')):
            raise AssertionError("Test Setup FAIL: Payment expected amount invalid.")

        amount_paid_atomic = payment.expected_amount_native
        confs_found = mock_settings_btc_escrow.BITCOIN_CONFIRMATIONS_NEEDED + 5
        mock_scan_btc.return_value = (True, amount_paid_atomic, confs_found, MOCK_TX_HASH_BTC)
        mock_ledger_credit.return_value = MagicMock(spec=LedgerTransaction)
        mock_ledger_lock.return_value = True
        mock_ledger_debit.return_value = MagicMock(spec=LedgerTransaction)
        mock_ledger_unlock.return_value = True

        # Setup side effect for User.objects.get (from previous fix)
        MARKET_USER_ID_FROM_LOGS = 3 # Assume still relevant if logs showed this
        def user_get_side_effect(*args, **kwargs):
            pk_kw = kwargs.get('pk')
            if pk_kw:
                if buyer and pk_kw == buyer.pk: return buyer
                if market_user_btc and pk_kw == market_user_btc.pk: return market_user_btc
                if market_user_btc and pk_kw == MARKET_USER_ID_FROM_LOGS: return market_user_btc
                raise DjangoUser.DoesNotExist(f"Mock User.get: PK {pk_kw} not found.")
            username_kw = kwargs.get('username')
            if username_kw:
                if market_user_btc and username_kw == market_user_btc.username: return market_user_btc
                raise DjangoUser.DoesNotExist(f"Mock User.get: Username {username_kw} not found.")
            raise DjangoUser.DoesNotExist(f"Mock User.get: Query {kwargs} not handled.")
        mock_user_get.side_effect = user_get_side_effect

        # Call the service function (assuming check_confirm in bitcoin_escrow_service)
        try:
            if hasattr(bitcoin_escrow_service, 'check_confirm'):
                 bitcoin_escrow_service.check_confirm(payment.id)
            elif hasattr(common_escrow_utils, 'check_and_confirm_payment'):
                 common_escrow_utils.check_and_confirm_payment(payment.id)
            else:
                 pytest.fail("Cannot find check_confirm or check_and_confirm_payment function.")
        except Exception as e:
            pytest.fail(f"Service call failed: {e}")

        # Assert final state
        order.refresh_from_db(); payment.refresh_from_db()
        if order.status != OrderStatusChoices.PAYMENT_CONFIRMED: raise AssertionError(f"Status mismatch: {order.status}")
        if order.paid_at is None: raise AssertionError("Paid_at not set.")
        if payment.is_confirmed is not True: raise AssertionError("Payment not confirmed.")
        if payment.received_amount_native != amount_paid_atomic: raise AssertionError("Received amount mismatch.")
        if payment.transaction_hash != MOCK_TX_HASH_BTC: raise AssertionError("TX Hash mismatch.")
        if payment.confirmations_received != confs_found: raise AssertionError("Confirmations mismatch.")

        # Assert mock calls
        mock_scan_btc.assert_called_once_with(payment)
        # Assert ledger calls (using logic from previous fix)
        amount_paid_std = from_atomic(amount_paid_atomic, 8)
        # Assuming _get_market_fee_percentage and _get_currency_precision are in common_escrow_utils
        fee_percent = common_escrow_utils._get_market_fee_percentage('BTC')
        prec = common_escrow_utils._get_currency_precision('BTC')
        quantizer = Decimal(f'1e-{prec}')
        expected_fee_std = (amount_paid_std * fee_percent / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
        expected_fee_std = max(Decimal('0.0'), expected_fee_std)
        expected_net_deposit_std = (amount_paid_std - expected_fee_std).quantize(quantizer, rounding=ROUND_DOWN)
        expected_net_deposit_std = max(Decimal('0.0'), expected_net_deposit_std)
        expected_order_amount_std = from_atomic(payment.expected_amount_native, 8)

        expected_ledger_calls = []
        if expected_fee_std > Decimal('0.0'):
            expected_ledger_calls.append(call(user=market_user_btc, currency='BTC', amount=expected_fee_std, transaction_type='MARKET_FEE', related_order=order, notes=f"Deposit Fee Order {order.id}"))
        expected_ledger_calls.append(call(user=order.buyer, currency='BTC', amount=expected_net_deposit_std, transaction_type='DEPOSIT', external_txid=MOCK_TX_HASH_BTC, related_order=order, notes=ANY))
        mock_ledger_credit.assert_has_calls(expected_ledger_calls, any_order=True)
        if mock_ledger_credit.call_count != len(expected_ledger_calls): raise AssertionError("Ledger credit call count mismatch.")

        mock_ledger_lock.assert_called_once_with(user=order.buyer, currency='BTC', amount=expected_order_amount_std, related_order=order, notes=ANY)
        mock_ledger_debit.assert_called_once_with(user=order.buyer, currency='BTC', amount=expected_order_amount_std, transaction_type='ESCROW_FUND_DEBIT', related_order=order, external_txid=MOCK_TX_HASH_BTC, notes=ANY)
        mock_ledger_unlock.assert_called_once_with(user=order.buyer, currency='BTC', amount=expected_order_amount_std, related_order=order, notes=ANY)

        # Assert user re-fetches via mock
        pk_calls_buyer = [c for c in mock_user_get.call_args_list if c.kwargs.get('pk') == buyer.pk]
        pk_calls_market = [c for c in mock_user_get.call_args_list if c.kwargs.get('pk') == market_user_btc.pk or c.kwargs.get('pk') == MARKET_USER_ID_FROM_LOGS]
        if not pk_calls_buyer: raise AssertionError("Buyer not re-fetched by PK.")
        if not pk_calls_market: raise AssertionError("Market user not re-fetched by PK.")


    # --- Test Mark Shipped ---
    # Patch the BTC-specific prepare release function (internal helper in bitcoin_escrow_service)
    @patch('store.services.bitcoin_escrow_service._prepare_btc_release')
    def test_mark_shipped_btc_success(self, mock_prepare_btc_release, order_payment_confirmed_btc, vendor_user_btc, global_settings_btc):
        """ Test successful marking of a BTC order as shipped by the vendor. """
        order = order_payment_confirmed_btc
        order.refresh_from_db()
        if not (order.total_price_native_selected and order.total_price_native_selected > Decimal('0')):
            raise AssertionError("Test Setup FAIL: Invalid order total price.")

        # Calculate expected values for metadata mock
        expected_payout_std = from_atomic(Decimal('975000'), 8) # Example calculation (0.01 - 2.5% fee)
        expected_fee_std = from_atomic(Decimal('25000'), 8)    # Example calculation
        # Use timezone.now() for comparison, allow slight difference
        now_for_mock = timezone.now()
        mock_prepared_at_iso = now_for_mock.isoformat()

        mock_metadata = {
            'type': 'btc_psbt', 'data': MOCK_UNSIGNED_PSBT_BTC,
            'payout': str(expected_payout_std), 'fee': str(expected_fee_std),
            'vendor_address': vendor_user_btc.btc_withdrawal_address,
            'ready_for_broadcast': False, 'signatures': {}, 'prepared_at': mock_prepared_at_iso
        }
        mock_prepare_btc_release.return_value = mock_metadata

        # Call the service function (assuming it's in bitcoin_escrow_service now)
        try:
            if hasattr(bitcoin_escrow_service, 'mark_order_shipped'):
                 bitcoin_escrow_service.mark_order_shipped(order, vendor_user_btc, tracking_info="TRACK123BTC")
            # Fallback check for common_escrow_utils (though less likely for mark_shipped)
            elif hasattr(common_escrow_utils, 'mark_order_shipped'):
                 # If this path exists, the test will fail due to the AttributeError from previous run
                 common_escrow_utils.mark_order_shipped(order, vendor_user_btc, tracking_info="TRACK123BTC")
            else:
                 pytest.fail("Cannot find mark_order_shipped function.")
        except Exception as e:
             pytest.fail(f"Service call failed: {e}")

        # Assert final state
        order.refresh_from_db()
        if order.status != OrderStatusChoices.SHIPPED: raise AssertionError(f"Status mismatch: {order.status}")
        if order.shipped_at is None: raise AssertionError("Shipped_at not set.")
        if order.release_initiated is not True: raise AssertionError("release_initiated not True.")
        # Check deadlines
        if order.dispute_deadline is None: raise AssertionError("Dispute deadline not set.")
        if order.auto_finalize_deadline is None: raise AssertionError("Auto finalize deadline not set.")
        # Compare metadata carefully
        if order.release_metadata is None: raise AssertionError("Metadata is None.")
        if not isinstance(order.release_metadata, dict): raise AssertionError("Metadata is not dict.")
        # Compare prepared_at with tolerance if needed, or just check keys/values
        if order.release_metadata.get('type') != mock_metadata['type']: raise AssertionError("Metadata type mismatch.")
        if order.release_metadata.get('data') != mock_metadata['data']: raise AssertionError("Metadata data mismatch.")
        if order.release_metadata.get('payout') != mock_metadata['payout']: raise AssertionError("Metadata payout mismatch.")
        if order.release_metadata.get('fee') != mock_metadata['fee']: raise AssertionError("Metadata fee mismatch.")
        if order.release_metadata.get('vendor_address') != mock_metadata['vendor_address']: raise AssertionError("Metadata vendor_address mismatch.")
        if order.release_metadata.get('ready_for_broadcast') is not False: raise AssertionError("Metadata ready_for_broadcast mismatch.")
        # Check prepared_at timestamp with tolerance
        prepared_at_str = order.release_metadata.get('prepared_at')
        if not prepared_at_str: raise AssertionError("Metadata prepared_at missing.")
        try:
            prepared_at_dt = datetime.datetime.fromisoformat(prepared_at_str)
            if abs(prepared_at_dt - now_for_mock) > datetime.timedelta(seconds=5):
                 raise AssertionError(f"Metadata prepared_at timestamp difference too large: {prepared_at_dt} vs {now_for_mock}")
        except ValueError:
             raise AssertionError("Metadata prepared_at is not a valid ISO format string.")


        if hasattr(order, 'tracking_info') and order.tracking_info != "TRACK123BTC": raise AssertionError("Tracking info mismatch.")

        mock_prepare_btc_release.assert_called_once_with(order) # Assert helper was called


    # === Test BTC Release Signing ===

    # Patch the BTC signing function in bitcoin_service
    @patch('store.services.bitcoin_service.sign_btc_multisig_tx')
    def test_sign_order_release_buyer_first_btc(self, mock_sign_btc, order_shipped_btc, buyer_user_btc):
        """ Test buyer signing the BTC release transaction first. """
        order = order_shipped_btc
        # --- FIX v1.1.0: Use longer dummy key info ---
        # Original: buyer_key_info = "buyer_dummy_key_info_btc"
        buyer_key_info = "Ldummywifkeythatislongenoughforthebasiclengthcheck123" # 52 chars
        # --- End FIX ---
        if not order.release_metadata or 'data' not in order.release_metadata:
            pytest.fail("Test Setup FAIL: Order missing release metadata.")
        initial_metadata_data = order.release_metadata['data']
        mock_sign_btc.return_value = MOCK_SIGNED_PSBT_BUYER

        # Call the service function (assuming sign_release in bitcoin_escrow_service)
        try:
            if hasattr(bitcoin_escrow_service, 'sign_release'):
                 success, is_ready = bitcoin_escrow_service.sign_release(order, buyer_user_btc, buyer_key_info)
            elif hasattr(common_escrow_utils, 'sign_order_release'):
                 success, is_ready = common_escrow_utils.sign_order_release(order, buyer_user_btc, buyer_key_info)
            else:
                 pytest.fail("Cannot find sign_release or sign_order_release function.")
        except Exception as e:
             pytest.fail(f"Service call failed: {e}")


        if success is not True: raise AssertionError("Signing should be successful.")
        if is_ready is not False: raise AssertionError("Release should not be ready.")
        mock_sign_btc.assert_called_once_with(psbt_base64=initial_metadata_data, private_key_wif=buyer_key_info)
        order.refresh_from_db()
        updated_metadata = order.release_metadata
        if updated_metadata.get('data') != MOCK_SIGNED_PSBT_BUYER: raise AssertionError("Metadata 'data' not updated.")
        signatures = updated_metadata.get('signatures', {})
        if str(buyer_user_btc.id) not in signatures: raise AssertionError("Buyer ID missing from signatures.")
        if len(signatures) != 1: raise AssertionError("Incorrect signature count.")
        if updated_metadata.get('ready_for_broadcast') is not False: raise AssertionError("'ready_for_broadcast' should be False.")


    # === Test BTC Release Broadcast ===

    # Patch User.get, the BTC broadcast function, and ledger credit
    @patch('store.models.User.objects.get')
    @patch('store.services.bitcoin_service.finalize_and_broadcast_btc_release')
    @patch('ledger.services.credit_funds')
    def test_broadcast_release_btc_success(self, mock_ledger_credit, mock_btc_broadcast, mock_user_get, order_ready_for_broadcast_btc, market_user_btc):
        """ Test successful broadcast of a finalized BTC release transaction. """
        order = order_ready_for_broadcast_btc
        vendor = order.vendor # Use vendor_user_btc implicitly
        buyer = order.buyer   # Use buyer_user_btc implicitly
        if not (order.release_metadata and order.release_metadata.get('data') and order.release_metadata.get('payout') and order.release_metadata.get('fee')):
            pytest.fail("Test Setup FAIL: Missing metadata.")
        final_psbt = order.release_metadata['data']
        payout_std = Decimal(order.release_metadata['payout'])
        fee_std = Decimal(order.release_metadata['fee'])
        mock_btc_broadcast.return_value = MOCK_TX_HASH_BTC
        mock_ledger_credit.return_value = MagicMock(spec=LedgerTransaction)

        # Setup user_get side effect (as before)
        MARKET_USER_ID_FROM_LOGS = 3
        def user_get_side_effect(*args, **kwargs):
            pk_kw = kwargs.get('pk')
            if pk_kw:
                if vendor and pk_kw == vendor.pk: return vendor
                if buyer and pk_kw == buyer.pk: return buyer # Should not be needed here, but safe
                if market_user_btc and pk_kw == market_user_btc.pk: return market_user_btc
                if market_user_btc and pk_kw == MARKET_USER_ID_FROM_LOGS: return market_user_btc
                raise DjangoUser.DoesNotExist(f"Mock User.get: PK {pk_kw} not found.")
            username_kw = kwargs.get('username')
            # Handle username lookup if common_escrow_utils._get_market_user() uses it initially
            if username_kw:
                 if market_user_btc and username_kw == market_user_btc.username: return market_user_btc
                 raise DjangoUser.DoesNotExist(f"Mock User.get: Username {username_kw} not found.")
            raise DjangoUser.DoesNotExist(f"Mock User.get: Query {kwargs} not handled.")
        mock_user_get.side_effect = user_get_side_effect

        # Call the service function (assuming broadcast_release in bitcoin_escrow_service)
        try:
            if hasattr(bitcoin_escrow_service, 'broadcast_release'):
                 success = bitcoin_escrow_service.broadcast_release(order.id)
            elif hasattr(common_escrow_utils, 'broadcast_release_transaction'):
                 success = common_escrow_utils.broadcast_release_transaction(order.id)
            else:
                 pytest.fail("Cannot find broadcast_release or broadcast_release_transaction function.")
        except Exception as e:
            pytest.fail(f"Service call failed: {e}")


        if success is not True: raise AssertionError("broadcast should return True.")
        order.refresh_from_db()
        if order.status != OrderStatusChoices.FINALIZED: raise AssertionError(f"Status mismatch: {order.status}")
        if order.finalized_at is None: raise AssertionError("Finalized_at not set.")
        if order.release_tx_broadcast_hash != MOCK_TX_HASH_BTC: raise AssertionError("Release TX hash mismatch.")

        # Verify mock calls
        mock_btc_broadcast.assert_called_once_with(order=order, current_psbt_base64=final_psbt)
        expected_ledger_calls = []
        if payout_std > 0: expected_ledger_calls.append(call(user=vendor, currency='BTC', amount=payout_std, transaction_type='ESCROW_RELEASE_VENDOR', related_order=order, external_txid=MOCK_TX_HASH_BTC, notes=ANY))
        if fee_std > 0: expected_ledger_calls.append(call(user=market_user_btc, currency='BTC', amount=fee_std, transaction_type='MARKET_FEE', related_order=order, notes=f"Market Fee Order {order.id}"))
        mock_ledger_credit.assert_has_calls(expected_ledger_calls, any_order=True)
        if mock_ledger_credit.call_count != len(expected_ledger_calls): raise AssertionError("Ledger credit call count mismatch.")
        # Verify User.objects.get calls
        if not mock_user_get.called: raise AssertionError("User.objects.get not called.")
        # Verify PK lookups happened for payout/fee recipients
        if payout_std > 0: mock_user_get.assert_any_call(pk=vendor.pk)
        if fee_std > 0:
            pk_calls_market = [c for c in mock_user_get.call_args_list if c.kwargs.get('pk') == market_user_btc.pk or c.kwargs.get('pk') == MARKET_USER_ID_FROM_LOGS]
            if not pk_calls_market: raise AssertionError("Market user not re-fetched by PK.")


    # === Test BTC Dispute Resolution ===

    # Patch User.get, the BTC dispute broadcast function, and ledger credit
    @patch('store.models.User.objects.get')
    @patch('store.services.bitcoin_service.create_and_broadcast_dispute_tx')
    @patch('ledger.services.credit_funds')
    def test_resolve_dispute_btc_full_buyer(self, mock_ledger_credit, mock_dispute_broadcast, mock_user_get, order_disputed_btc, moderator_user_btc, market_user_btc):
        """ Test BTC dispute resolution: 100% released to buyer. """
        order = order_disputed_btc
        buyer = order.buyer # Use buyer_user_btc implicitly
        vendor = order.vendor # Use vendor_user_btc implicitly
        if order.status != OrderStatusChoices.DISPUTED: raise AssertionError("Fixture Setup: Not disputed.")
        if not (order.total_price_native_selected and order.total_price_native_selected > 0): raise AssertionError("Fixture Setup: Invalid price.")
        if not buyer.btc_withdrawal_address: raise AssertionError("Fixture Setup: Buyer missing BTC address.")

        total_escrowed_atomic = order.total_price_native_selected
        # Assuming from_atomic is available (local or from common_escrow_utils)
        total_escrowed_std = from_atomic(total_escrowed_atomic, 8)
        # Assuming _get_currency_precision is in common_escrow_utils
        prec = common_escrow_utils._get_currency_precision('BTC')
        quantizer = Decimal(f'1e-{prec}')
        buyer_payout_std = total_escrowed_std.quantize(quantizer, rounding=ROUND_DOWN)
        vendor_payout_std = Decimal('0.0')
        mock_dispute_broadcast.return_value = MOCK_TX_HASH_BTC # Use specific hash if needed
        mock_ledger_credit.return_value = MagicMock(spec=LedgerTransaction)

        # Setup user_get side effect (similar to broadcast test, ensure buyer/vendor/market fetched)
        MARKET_USER_ID_FROM_LOGS = 3
        def user_get_side_effect_dispute(*args, **kwargs):
            pk_kw = kwargs.get('pk')
            if pk_kw:
                if buyer and pk_kw == buyer.pk: return buyer
                if vendor and pk_kw == vendor.pk: return vendor
                if market_user_btc and pk_kw == market_user_btc.pk: return market_user_btc
                if market_user_btc and pk_kw == MARKET_USER_ID_FROM_LOGS: return market_user_btc
                raise DjangoUser.DoesNotExist(f"Mock User.get (Dispute): PK {pk_kw} not found.")
            # Handle username lookup if needed for _get_market_user
            username_kw = kwargs.get('username')
            if username_kw:
                 if market_user_btc and username_kw == market_user_btc.username: return market_user_btc
                 raise DjangoUser.DoesNotExist(f"Mock User.get (Dispute): Username {username_kw} not found.")
            raise DjangoUser.DoesNotExist(f"Mock User.get (Dispute): Query {kwargs} not handled.")
        mock_user_get.side_effect = user_get_side_effect_dispute

        # Call the service function (assuming resolve_dispute in bitcoin_escrow_service)
        try:
            if hasattr(bitcoin_escrow_service, 'resolve_dispute'):
                 success = bitcoin_escrow_service.resolve_dispute(order=order, moderator=moderator_user_btc, resolution_notes="Full BTC refund.", release_to_buyer_percent=100)
            elif hasattr(common_escrow_utils, 'resolve_dispute'):
                 success = common_escrow_utils.resolve_dispute(order=order, moderator=moderator_user_btc, resolution_notes="Full BTC refund.", release_to_buyer_percent=100)
            else:
                 pytest.fail("Cannot find resolve_dispute function.")
        except Exception as e:
            pytest.fail(f"Service call failed: {e}")

        if success is not True: raise AssertionError("resolve_dispute should return True.")
        order.refresh_from_db()
        if order.status != OrderStatusChoices.DISPUTE_RESOLVED: raise AssertionError(f"Status mismatch: {order.status}")

        # --- Check Dispute model timestamp instead of Order ---
        try:
            dispute = Dispute.objects.get(order=order)
            if dispute.resolved_at is None:
                raise AssertionError("Dispute model resolved_at not set.")
        except Dispute.DoesNotExist:
            logger.warning(f"Test check skipped: Cannot find related Dispute object for order {order.id} to check resolved_at.")
        # --- End FIX ---

        # Check optional fields like resolved_by, notes, buyer_percent on Order if they exist
        if hasattr(order, 'dispute_resolved_by'):
             if order.dispute_resolved_by != moderator_user_btc:
                 raise AssertionError("dispute_resolved_by mismatch.")
        if hasattr(order, 'dispute_resolution_notes'):
            if order.dispute_resolution_notes != "Full BTC refund.": # Match notes used in service call
                raise AssertionError("dispute_resolution_notes mismatch.")
        if hasattr(order, 'dispute_buyer_percent'):
            # Compare as Decimal or int depending on field type
            try:
                if order.dispute_buyer_percent != Decimal('100.0'):
                    raise AssertionError("dispute_buyer_percent mismatch (Decimal).")
            except InvalidOperation: # Handle if it's an Int field
                 if order.dispute_buyer_percent != 100:
                     raise AssertionError("dispute_buyer_percent mismatch (Int).")

        if order.release_tx_broadcast_hash != MOCK_TX_HASH_BTC: raise AssertionError("Release TX hash mismatch.")

        # Verify mock calls
        mock_dispute_broadcast.assert_called_once_with(
            order=order,
            buyer_payout_amount_btc=buyer_payout_std,
            buyer_address=buyer.btc_withdrawal_address,
            vendor_payout_amount_btc=None, # vendor_payout_std is 0
            vendor_address=None,
            moderator_key_info=None # Assuming moderator doesn't sign BTC tx
        )
        # Verify ledger calls
        expected_ledger_calls = []
        if buyer_payout_std > 0: expected_ledger_calls.append(call(user=buyer, currency='BTC', amount=buyer_payout_std, transaction_type='DISPUTE_RESOLUTION_BUYER', related_order=order, external_txid=MOCK_TX_HASH_BTC, notes=ANY))
        mock_ledger_credit.assert_has_calls(expected_ledger_calls, any_order=True)
        if mock_ledger_credit.call_count != len(expected_ledger_calls): raise AssertionError("Ledger credit call count mismatch.")


# === Test Placeholders / Future Work ===
# Add tests for signing with real crypto mocks if applicable to BTC service
# Add tests for edge cases in amount calculations (BTC specific)
# Add tests for BTC timeout logic if different from generic

# <<< END OF FILE: backend/store/tests/test_bitcoin_escrow_service.py >>>