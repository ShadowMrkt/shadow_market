# backend/store/tests/test_monero_escrow_service.py

# --- Revision History ---
# v1.0.0 (2025-04-09): REFACTOR (Gemini)
#   - Created this file by extracting Monero-specific tests, fixtures, and constants
#     from the original monolithic `test_escrow_service.py`.
#   - Updated imports and service calls to reflect the split of escrow logic into
#     `monero_escrow_service.py` and `common_escrow_utils.py` (Assumed structure).
#   - Renamed test class to `TestMoneroEscrowService`.
# --- Relevant Prior History (from test_escrow_service.py) ---
# v1.23.0 (2025-04-08):
#   - FIXED: Replaced `assert` with explicit checks for Bandit B101.
# v1.22.3 (2025-04-07):
#   - FIXED: Mocking for User.objects.get in dispute tests (apply if dispute tests kept/adapted).
# v1.18.2 (2025-04-07):
#   - FIXED: Mock call assertions to use keyword arguments.
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
import datetime

# --- Third-Party Imports ---
import pytest
from django.conf import settings as django_settings
from django.core.exceptions import ValidationError as DjangoValidationError, FieldError, ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

# --- Local Imports ---
# Models
from store.models import Order, Product, User, GlobalSettings, CryptoPayment, Category, OrderStatus as OrderStatusChoices # noqa
from ledger.models import UserBalance, LedgerTransaction # noqa

# Services and Exceptions
# --- Updated Imports (v1.0.0 Refactor) ---
# Assuming primary XMR escrow logic is here:
from store.services import monero_escrow_service
# Assuming shared helpers/constants are here:
from store.services import common_escrow_utils
# Keep direct monero_service import if needed for non-escrow XMR functions:
from store.services import monero_service
# Ledger service remains the same:
from ledger import services as ledger_service # Explicit import for clarity
from ledger.services import InsufficientFundsError, InvalidLedgerOperationError # noqa
from ledger.exceptions import LedgerError # noqa
# Store/Escrow Exceptions remain the same:
from store.exceptions import EscrowError, CryptoProcessingError # noqa
# --- End Updated Imports ---

DjangoUser = django_get_user_model()

logger = logging.getLogger(__name__)

# --- Monero-Specific Test Constants ---
# Extracted from original test_escrow_service.py
MOCK_MARKET_USER_USERNAME = "market_test_user_xmr" # Make slightly distinct if needed
MOCK_BUYER_USERNAME = "test_buyer_xmr_escrow"
MOCK_VENDOR_USERNAME = "test_vendor_xmr_escrow"
MOCK_MODERATOR_USERNAME = "test_mod_xmr_escrow" # Keep generic if mods are global

MOCK_PRODUCT_PRICE_XMR = Decimal("1.0") # Standard Units
MOCK_MARKET_FEE_PERCENT = Decimal("2.5") # Assume same fee for simplicity

# Atomic units (XMR: 12 decimals)
MOCK_PRODUCT_PRICE_XMR_ATOMIC = Decimal(1_000_000_000_000) # 1.0 * 10^12

MOCK_XMR_MULTISIG_ADDRESS = "xmr_multisig_address_test_456" # Example address
MOCK_XMR_WITHDRAWAL_ADDR = 'vendor_xmr_payout_addr_test_8ABCD...'
MOCK_BUYER_XMR_REFUND_ADDR = 'buyer_xmr_refund_addr_test_fix'

MOCK_XMR_WALLET_NAME = "msig_order_xmr_test_wallet"
MOCK_XMR_MULTISIG_INFO = {"viewkey": "mock_viewkey", "spendkey": "mock_spendkey"} # Example structure
MOCK_XMR_PAYMENT_ID_PREFIX = "xmr_pid_test_"

MOCK_TX_HASH_XMR = "xmr_tx_hash_test_" + "c" * 50 # Adjusted length slightly
MOCK_UNSIGNED_TXSET_XMR = "unsigned_txset_xmr_data_test"
MOCK_PARTIAL_TXSET_XMR = "partial_txset_xmr_data_test"
MOCK_FINAL_TXSET_XMR = "final_txset_xmr_data_test"

# Generic constants potentially needed by fixtures
MOCK_MARKET_PGP_KEY = "market_pgp_key_data_xmr_fixture"
MOCK_BUYER_PGP_KEY = "buyer_pgp_key_xmr_fixture"
MOCK_VENDOR_PGP_KEY = "vendor_pgp_key_data_xmr_fixture_different"
DEFAULT_CATEGORY_ID = 1

# Assume these constants are now in common_escrow_utils
ATTR_XMR_MULTISIG_INFO = 'xmr_multisig_info' # Default, adjust if changed
ATTR_XMR_WITHDRAWAL_ADDRESS = 'xmr_withdrawal_address' # Default
ATTR_XMR_MULTISIG_WALLET_NAME = 'xmr_multisig_wallet_name' # Default
ATTR_XMR_MULTISIG_INFO_ORDER = 'xmr_multisig_info' # If stored on order


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
    # Assuming XMR precision is 12 for standard display
    display_precision = Decimal('1e-12') if decimals == 12 else Decimal(f'1e-{decimals}')
    return (amount_atomic / divisor).quantize(display_precision, rounding=ROUND_DOWN)


# --- Fixtures ---
@pytest.fixture
def mock_settings_xmr_escrow(settings):
    """Override specific Django settings for XMR escrow tests."""
    settings.MARKET_FEE_PERCENTAGE_XMR = MOCK_MARKET_FEE_PERCENT
    # Remove BTC/ETH fee settings
    settings.MARKET_USER_USERNAME = MOCK_MARKET_USER_USERNAME
    settings.MULTISIG_PARTIES_REQUIRED = 3
    settings.MULTISIG_SIGNATURES_REQUIRED = 2
    settings.ORDER_PAYMENT_TIMEOUT_HOURS = 24
    settings.ORDER_FINALIZE_TIMEOUT_DAYS = 14
    settings.ORDER_DISPUTE_WINDOW_DAYS = 7
    settings.MONERO_CONFIRMATIONS_NEEDED = 10
    # Remove BTC/ETH confirmation settings
    yield settings

# --- User Fixtures (Adapted for XMR focus) ---
@pytest.fixture
def market_user_xmr(db, mock_settings_xmr_escrow) -> DjangoUser:
    """Provides the market user configured for XMR tests."""
    # Use constant defined above or fetch from common_escrow_utils
    # xmr_info_attr = getattr(common_escrow_utils, 'ATTR_XMR_MULTISIG_INFO', ATTR_XMR_MULTISIG_INFO)
    xmr_info_attr = ATTR_XMR_MULTISIG_INFO # Use local constant

    user, _ = DjangoUser.objects.update_or_create(
        username=mock_settings_xmr_escrow.MARKET_USER_USERNAME,
        defaults={
            'is_staff': True, 'is_active': True, 'pgp_public_key': MOCK_MARKET_PGP_KEY,
            xmr_info_attr: {"viewkey": "market_xmr_viewkey_fixture", "spendkey": "market_xmr_spendkey_fixture"}, # Example structure
            # Remove BTC pubkey
        }
    )
    # Ensure XMR balance exists (remove others)
    UserBalance.objects.get_or_create(user=user, currency='XMR', defaults={'balance': Decimal('100.0')})
    user.refresh_from_db()
    return user

@pytest.fixture
def buyer_user_xmr(db) -> DjangoUser:
    """Provides a buyer user configured for XMR tests."""
    # xmr_info_attr = getattr(common_escrow_utils, 'ATTR_XMR_MULTISIG_INFO', ATTR_XMR_MULTISIG_INFO)
    # xmr_refund_attr = getattr(common_escrow_utils, 'ATTR_XMR_WITHDRAWAL_ADDRESS', ATTR_XMR_WITHDRAWAL_ADDRESS)
    xmr_info_attr = ATTR_XMR_MULTISIG_INFO
    xmr_refund_attr = ATTR_XMR_WITHDRAWAL_ADDRESS

    user, _ = DjangoUser.objects.update_or_create(
        username=MOCK_BUYER_USERNAME,
        defaults={
            'is_active': True, 'pgp_public_key': MOCK_BUYER_PGP_KEY,
            xmr_refund_attr: MOCK_BUYER_XMR_REFUND_ADDR,
            xmr_info_attr: {"viewkey": "buyer_xmr_viewkey_fixture", "spendkey": "buyer_xmr_spendkey_fixture"},
            # Remove BTC refund/pubkey attributes
        }
    )
    # Ensure XMR balance exists (remove others)
    UserBalance.objects.get_or_create(user=user, currency='XMR', defaults={'balance': Decimal('10.0')})
    user.refresh_from_db()
    return user

@pytest.fixture
def vendor_user_xmr(db) -> DjangoUser:
    """Provides a vendor user configured for XMR tests."""
    # xmr_info_attr = getattr(common_escrow_utils, 'ATTR_XMR_MULTISIG_INFO', ATTR_XMR_MULTISIG_INFO)
    # xmr_wd_attr = getattr(common_escrow_utils, 'ATTR_XMR_WITHDRAWAL_ADDRESS', ATTR_XMR_WITHDRAWAL_ADDRESS)
    xmr_info_attr = ATTR_XMR_MULTISIG_INFO
    xmr_wd_attr = ATTR_XMR_WITHDRAWAL_ADDRESS

    user, _ = DjangoUser.objects.update_or_create(
        username=MOCK_VENDOR_USERNAME,
        defaults={
            'is_vendor': True, 'is_active': True, 'pgp_public_key': MOCK_VENDOR_PGP_KEY,
            xmr_wd_attr: MOCK_XMR_WITHDRAWAL_ADDR,
            xmr_info_attr: {"viewkey": "vendor_xmr_viewkey_fixture", "spendkey": "vendor_xmr_spendkey_fixture"},
            # Remove BTC withdrawal/pubkey attributes
        }
    )
    # Ensure XMR balance exists (remove others)
    UserBalance.objects.get_or_create(user=user, currency='XMR', defaults={'balance': Decimal('50.0')})
    user.refresh_from_db()
    return user

@pytest.fixture
def moderator_user_xmr(db) -> DjangoUser:
    """Provides a moderator user (generic, keep as is)."""
    user, _ = DjangoUser.objects.get_or_create(
        username=MOCK_MODERATOR_USERNAME,
        defaults={'is_staff': True, 'is_active': True}
    )
    user.refresh_from_db()
    return user

# --- Generic Setup Fixtures (Keep, ensure they use XMR settings) ---
@pytest.fixture
def global_settings_xmr(db, market_user_xmr, mock_settings_xmr_escrow) -> GlobalSettings:
    """Ensures GlobalSettings singleton exists and sets XMR-relevant attributes."""
    try:
        gs = GlobalSettings.get_solo()
    except AttributeError as e:
        raise AttributeError(f"CRITICAL FIXTURE ERROR: GlobalSettings missing '.get_solo()'. {e}") from e
    except Exception as e:
        pytest.fail(f"Failed to get/create GlobalSettings via get_solo(): {e}")

    gs.market_fee_percentage_xmr = mock_settings_xmr_escrow.MARKET_FEE_PERCENTAGE_XMR
    # Remove BTC/ETH fees
    setattr(gs, 'payment_wait_hours', mock_settings_xmr_escrow.ORDER_PAYMENT_TIMEOUT_HOURS)
    setattr(gs, 'order_auto_finalize_days', mock_settings_xmr_escrow.ORDER_FINALIZE_TIMEOUT_DAYS)
    setattr(gs, 'dispute_window_days', mock_settings_xmr_escrow.ORDER_DISPUTE_WINDOW_DAYS)
    setattr(gs, 'confirmations_needed_xmr', mock_settings_xmr_escrow.MONERO_CONFIRMATIONS_NEEDED)
    # Remove BTC/ETH confirmations

    gs.save()
    gs.refresh_from_db()

    # Ensure market user PGP key exists
    if not market_user_xmr.pgp_public_key:
        market_user_xmr.pgp_public_key = MOCK_MARKET_PGP_KEY
        market_user_xmr.save(update_fields=['pgp_public_key'])

    return gs

@pytest.fixture
def product_category_xmr(db) -> Category:
    """Ensures a default Category object exists."""
    category, created = Category.objects.get_or_create(
        pk=DEFAULT_CATEGORY_ID,
        defaults={'name': 'Default XMR Test Category'}
    )
    return category

@pytest.fixture
def product_xmr(db, vendor_user_xmr, product_category_xmr) -> Product:
    """Provides a simple XMR product."""
    product, created = Product.objects.update_or_create(
        name="Test XMR Product Only", vendor=vendor_user_xmr, category=product_category_xmr,
        defaults={
            'price_xmr': MOCK_PRODUCT_PRICE_XMR,
            'description': "Test XMR Product Description",
            'is_active': True,
            'price_btc': None, # Ensure non-XMR prices are None/excluded
        }
    )
    product.refresh_from_db()
    if product.category_id != product_category_xmr.id:
        pytest.fail(f"VERIFICATION FAIL (product_xmr): Category mismatch.")
    if product.price_xmr != MOCK_PRODUCT_PRICE_XMR:
        pytest.fail(f"VERIFICATION FAIL (product_xmr): Price mismatch.")
    return product

# --- Order Creation Fixtures (XMR-Specific and Generic Helpers) ---

@pytest.fixture
def create_xmr_order(db, buyer_user_xmr, vendor_user_xmr, global_settings_xmr) -> Callable[[Product, str], Order]:
    """ Factory fixture to create XMR orders, setting atomic price fields. """
    def _create_xmr_order(product: Product, status: str = OrderStatusChoices.PENDING_PAYMENT) -> Order:
        currency_upper = 'XMR'; decimals = 12
        price_std = product.price_xmr

        if price_std is None or not isinstance(price_std, Decimal) or price_std <= Decimal('0.0'):
            pytest.fail(f"Product {product.id} has invalid XMR price ({price_std}).")

        price_native_selected_atomic = to_atomic(price_std, decimals)
        if price_native_selected_atomic <= Decimal('0'):
            pytest.fail(f"Calculated atomic XMR price ({price_native_selected_atomic}) is not positive.")

        quantity = 1; shipping_price_std = Decimal(0)
        shipping_price_native_selected_atomic = to_atomic(shipping_price_std, decimals)
        total_price_native_selected_atomic_calculated = (price_native_selected_atomic * quantity) + shipping_price_native_selected_atomic

        # Verify participants
        if not DjangoUser.objects.filter(pk=buyer_user_xmr.pk).exists(): pytest.fail(f"Buyer {buyer_user_xmr.pk} missing.")
        if not DjangoUser.objects.filter(pk=vendor_user_xmr.pk).exists(): pytest.fail(f"Vendor {vendor_user_xmr.pk} missing.")
        if not Product.objects.filter(pk=product.pk).exists(): pytest.fail(f"Product {product.pk} missing.")

        order = Order.objects.create(
            buyer=buyer_user_xmr, vendor=vendor_user_xmr, product=product,
            quantity=quantity, selected_currency=currency_upper,
            price_native_selected=price_native_selected_atomic,
            shipping_price_native_selected=shipping_price_native_selected_atomic,
            total_price_native_selected=total_price_native_selected_atomic_calculated,
            status=status
        )
        # Immediate verification
        if order.total_price_native_selected != total_price_native_selected_atomic_calculated:
            raise AssertionError("Order total price mismatch immediately after create.")
        # Verify after refresh
        try:
            order.refresh_from_db()
            if order.buyer_id != buyer_user_xmr.id: raise AssertionError("Buyer ID mismatch.")
            if order.vendor_id != vendor_user_xmr.id: raise AssertionError("Vendor ID mismatch.")
            if order.product_id != product.id: raise AssertionError("Product ID mismatch.")
            if order.total_price_native_selected is None: raise AssertionError("Total price is None after refresh.")
            if order.total_price_native_selected != total_price_native_selected_atomic_calculated:
                raise AssertionError("Total price mismatch after refresh.")
        except ObjectDoesNotExist:
            pytest.fail(f"Order {order.id} failed refresh_from_db.")
        return order
    return _create_xmr_order

@pytest.fixture
def order_pending_xmr(create_xmr_order, product_xmr) -> Order:
    """ Creates an XMR order in PENDING_PAYMENT status. """
    return create_xmr_order(product_xmr, OrderStatusChoices.PENDING_PAYMENT)

# Adapt setup_escrow for XMR
@pytest.fixture
def setup_xmr_escrow(db, mock_settings_xmr_escrow) -> Callable[[Order, str, Optional[str], Optional[str]], Order]:
    """ Helper fixture for XMR escrow setup (CryptoPayment, deadlines). """
    def _setup_xmr_escrow(order: Order, escrow_address: str, wallet_name: Optional[str] = None, payment_id: Optional[str] = None) -> Order:
        order.refresh_from_db()
        if order.selected_currency != 'XMR': pytest.fail("setup_xmr_escrow called on non-XMR order.")
        if order.total_price_native_selected is None or order.total_price_native_selected <= Decimal('0'):
            pytest.fail(f"Order {order.id} has invalid total price.")

        order.status = OrderStatusChoices.PENDING_PAYMENT
        order.payment_deadline = timezone.now() + timezone.timedelta(hours=mock_settings_xmr_escrow.ORDER_PAYMENT_TIMEOUT_HOURS)

        update_fields_order = ['status', 'payment_deadline', 'updated_at']
        # XMR specific fields on Order model (if they exist)
        # Assume ATTR_XMR_MULTISIG_WALLET_NAME is correct
        wallet_name_attr = ATTR_XMR_MULTISIG_WALLET_NAME
        if hasattr(order, wallet_name_attr) and wallet_name:
            setattr(order, wallet_name_attr, wallet_name)
            update_fields_order.append(wallet_name_attr)
        # Add other XMR order fields like multisig_info if needed

        order.save(update_fields=list(set(update_fields_order)))

        confirmations_needed = mock_settings_xmr_escrow.MONERO_CONFIRMATIONS_NEEDED

        # Create CryptoPayment record for XMR
        payment, created = CryptoPayment.objects.update_or_create(
            order=order, currency='XMR',
            defaults={
                'payment_address': escrow_address, # This is the multisig address
                'expected_amount_native': order.total_price_native_selected,
                'confirmations_needed': confirmations_needed,
                'payment_id_monero': payment_id # Optional XMR payment ID
            }
        )
        order.refresh_from_db()
        return order
    return _setup_xmr_escrow

@pytest.fixture
def order_escrow_created_xmr(order_pending_xmr, setup_xmr_escrow) -> Order:
    """ Creates an XMR order with escrow details set up (PENDING_PAYMENT). """
    xmr_payment_id = MOCK_XMR_PAYMENT_ID_PREFIX + uuid.uuid4().hex[:10]
    return setup_xmr_escrow(order_pending_xmr, MOCK_XMR_MULTISIG_ADDRESS, MOCK_XMR_WALLET_NAME, xmr_payment_id)

# Adapt confirm_payment for XMR
@pytest.fixture
def confirm_xmr_payment(db) -> Callable[[Order, str, int], Order]:
    """ Helper fixture to simulate confirming XMR payment. """
    def _confirm_xmr_payment(order: Order, tx_hash: str, confirmations_received: int) -> Order:
        if order.selected_currency != 'XMR': pytest.fail("confirm_xmr_payment called on non-XMR order.")
        now = timezone.now()
        try:
            payment = CryptoPayment.objects.get(order=order, currency='XMR')
        except CryptoPayment.DoesNotExist:
            pytest.fail(f"CryptoPayment (XMR) not found for Order {order.id}.")

        payment.refresh_from_db()
        if payment.expected_amount_native is None or payment.expected_amount_native <= Decimal('0'):
            pytest.fail(f"CryptoPayment {payment.id} has invalid expected_amount_native.")

        payment.received_amount_native = payment.expected_amount_native # Assume full payment
        payment.transaction_hash = tx_hash
        payment.is_confirmed = True
        payment.confirmations_received = confirmations_received
        payment.save(update_fields=['received_amount_native', 'transaction_hash', 'is_confirmed', 'confirmations_received', 'updated_at'])

        order.status = OrderStatusChoices.PAYMENT_CONFIRMED
        order.paid_at = now
        order.save(update_fields=['status', 'paid_at', 'updated_at'])
        order.refresh_from_db()
        return order
    return _confirm_xmr_payment

@pytest.fixture
def order_payment_confirmed_xmr(order_escrow_created_xmr, confirm_xmr_payment, mock_settings_xmr_escrow) -> Order:
    """ Creates an XMR order confirmed with sufficient confirmations. """
    return confirm_xmr_payment(order_escrow_created_xmr, MOCK_TX_HASH_XMR, mock_settings_xmr_escrow.MONERO_CONFIRMATIONS_NEEDED + 5)

# Adapt mark_shipped for XMR
@pytest.fixture
def mark_xmr_shipped(db, mock_settings_xmr_escrow, global_settings_xmr) -> Callable[[Order, str], Order]:
    """ Helper fixture to simulate marking an XMR order as shipped. """
    # Requires common_escrow_utils helpers
    try:
        from store.services.common_escrow_utils import _get_currency_precision, _get_withdrawal_address
    except ImportError:
        pytest.fail("Could not import helpers from common_escrow_utils in mark_xmr_shipped.")

    def _mark_xmr_shipped(order: Order, unsigned_release_data: str) -> Order:
        if order.selected_currency != 'XMR': pytest.fail("mark_xmr_shipped called on non-XMR order.")
        now = timezone.now()
        order.refresh_from_db()

        if order.total_price_native_selected is None or order.total_price_native_selected <= Decimal('0'):
            pytest.fail(f"Order {order.id} has invalid total price.")
        if not order.vendor: pytest.fail(f"Order {order.id} missing vendor.")

        # Calculate payout/fee (XMR specific)
        fee_percent = global_settings_xmr.market_fee_percentage_xmr
        atomic_quantizer = Decimal('0'); decimals = 12
        total_atomic = order.total_price_native_selected
        market_fee_atomic = (total_atomic * fee_percent / Decimal(100)).quantize(atomic_quantizer, rounding=ROUND_DOWN)
        payout_atomic = (total_atomic - market_fee_atomic).quantize(atomic_quantizer, rounding=ROUND_DOWN)
        market_fee_atomic = max(Decimal('0'), market_fee_atomic)
        payout_atomic = max(Decimal('0'), payout_atomic)

        # Convert to standard units for metadata
        try:
            prec = _get_currency_precision('XMR')
            if prec != decimals: logger.warning(f"Precision mismatch in mark_xmr_shipped: Expected {decimals}, got {prec}")
        except Exception as e:
            pytest.fail(f"Failed to get XMR precision in mark_xmr_shipped: {e}")
        payout_std = from_atomic(payout_atomic, decimals)
        fee_std = from_atomic(market_fee_atomic, decimals)

        try:
            vendor_payout_address = _get_withdrawal_address(order.vendor, 'XMR')
        except ValueError as e:
            pytest.fail(f"Vendor {order.vendor.username} missing XMR withdrawal address: {e}")

        release_type = 'xmr_unsigned_txset' # Hardcoded for XMR

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
        order.auto_finalize_deadline = now + timezone.timedelta(days=mock_settings_xmr_escrow.ORDER_FINALIZE_TIMEOUT_DAYS)
        order.dispute_deadline = now + timezone.timedelta(days=mock_settings_xmr_escrow.ORDER_DISPUTE_WINDOW_DAYS)
        order.release_initiated = True
        order.release_metadata = release_metadata

        order.save(update_fields=[
            'status', 'shipped_at', 'auto_finalize_deadline', 'dispute_deadline',
            'release_initiated', 'release_metadata', 'updated_at'
        ])
        order.refresh_from_db()
        return order
    return _mark_xmr_shipped
# <<< Continued from previous response: backend/store/tests/test_monero_escrow_service.py >>>

@pytest.fixture
def order_shipped_xmr(order_payment_confirmed_xmr, mark_xmr_shipped) -> Order:
    """ Creates an XMR order marked as shipped. """
    return mark_xmr_shipped(order_payment_confirmed_xmr, MOCK_UNSIGNED_TXSET_XMR)

# Adapt mark_signed for XMR
@pytest.fixture
def mark_xmr_signed(db, mock_settings_xmr_escrow) -> Callable[[Order, DjangoUser, str, Optional[bool]], Order]:
    """ Helper fixture to simulate applying a signature to XMR release metadata. """
    def _mark_xmr_signed(order: Order, user: DjangoUser, signed_data: str, is_final_override: Optional[bool] = None) -> Order:
        if order.selected_currency != 'XMR': pytest.fail("mark_xmr_signed called on non-XMR order.")
        metadata = order.release_metadata if isinstance(order.release_metadata, dict) else {}
        if not metadata: pytest.fail("Cannot mark signed: Order release metadata missing.")

        metadata['data'] = signed_data # Update with signed txset
        if 'signatures' not in metadata or not isinstance(metadata['signatures'], dict): metadata['signatures'] = {}
        metadata['signatures'][str(user.id)] = {'signed_at': timezone.now().isoformat(), 'signer': user.username}

        required_sigs = mock_settings_xmr_escrow.MULTISIG_SIGNATURES_REQUIRED
        is_complete = is_final_override if is_final_override is not None else (len(metadata['signatures']) >= required_sigs)
        metadata['ready_for_broadcast'] = is_complete

        # Update type if final (specific to XMR)
        if is_complete: metadata['type'] = 'xmr_signed_txset'

        order.release_metadata = metadata
        order.save(update_fields=['release_metadata', 'updated_at'])
        order.refresh_from_db()

        # Fixture verification
        if order.release_metadata is None or not isinstance(order.release_metadata, dict):
            raise AssertionError(f"Fixture FAIL (mark_xmr_signed): Invalid metadata after save/refresh.")
        return order
    return _mark_xmr_signed

# XMR signing flow fixtures might differ from BTC; adapt as needed
# These assume a similar buyer->vendor signing flow for simplicity
@pytest.fixture
def order_buyer_signed_xmr(order_shipped_xmr, mark_xmr_signed, buyer_user_xmr) -> Order:
    """ Creates an XMR order signed by the buyer only (example). Uses MOCK_PARTIAL_TXSET_XMR. """
    # Note: Real XMR multisig signing flow might be different. Adjust if needed.
    signed_order = mark_xmr_signed(order_shipped_xmr, buyer_user_xmr, MOCK_PARTIAL_TXSET_XMR, is_final_override=False)
    if not (signed_order.release_metadata and isinstance(signed_order.release_metadata, dict)):
        raise AssertionError(f"Fixture FAIL (order_buyer_signed_xmr): Invalid metadata.")
    return signed_order

@pytest.fixture
def order_ready_for_broadcast_xmr(order_buyer_signed_xmr, mark_xmr_signed, vendor_user_xmr) -> Order:
    """ Creates an XMR order signed by buyer and vendor, ready for broadcast. Uses MOCK_FINAL_TXSET_XMR. """
    ready_order = mark_xmr_signed(order_buyer_signed_xmr, vendor_user_xmr, MOCK_FINAL_TXSET_XMR, is_final_override=True)
    if not (ready_order.release_metadata and isinstance(ready_order.release_metadata, dict)):
        raise AssertionError(f"Fixture FAIL (order_ready_for_broadcast_xmr): Invalid metadata.")
    if ready_order.release_metadata.get('ready_for_broadcast') is not True:
        raise AssertionError(f"Fixture FAIL (order_ready_for_broadcast_xmr): Not marked ready.")
    return ready_order

# Use generic mark_disputed fixture defined previously
@pytest.fixture
def order_disputed_xmr(order_shipped_xmr, mark_disputed) -> Order:
    """ Creates an XMR order marked as disputed. """
    allowed_statuses = [OrderStatusChoices.SHIPPED, OrderStatusChoices.PAYMENT_CONFIRMED]
    if order_shipped_xmr.status not in allowed_statuses:
        pytest.skip(f"Order status {order_shipped_xmr.status} not disputable in fixture.")

    disputed_order = mark_disputed(order_shipped_xmr)
    # Validation after marking disputed
    disputed_order.refresh_from_db()
    if disputed_order.total_price_native_selected is None or not (disputed_order.total_price_native_selected > Decimal('0')):
        raise AssertionError(f"Fixture Validation FAIL (order_disputed_xmr): Invalid price after dispute.")
    return disputed_order


# --- Test Class ---

@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("mock_settings_xmr_escrow", "global_settings_xmr", "market_user_xmr")
class TestMoneroEscrowService:
    """ Test suite for the store.services.monero_escrow_service module. """

    def setup_method(self, method):
        """ Reset market user cache if it exists in common_escrow_utils. """
        if hasattr(common_escrow_utils, '_market_user_cache'):
            common_escrow_utils._market_user_cache = None

    # === Test XMR Escrow Creation ===

    # Patch the actual XMR service function responsible for wallet creation
    @patch('store.services.monero_service.create_monero_multisig_wallet')
    def test_create_escrow_xmr_success(self, mock_create_xmr_wallet, order_pending_xmr, market_user_xmr, buyer_user_xmr, vendor_user_xmr, mock_settings_xmr_escrow, global_settings_xmr):
        """ Test successful creation of XMR escrow. """
        order = order_pending_xmr
        xmr_info_attr = ATTR_XMR_MULTISIG_INFO

        buyer_info = getattr(buyer_user_xmr, xmr_info_attr, None)
        vendor_info = getattr(vendor_user_xmr, xmr_info_attr, None)
        market_info = getattr(market_user_xmr, xmr_info_attr, None)

        if not all([buyer_info, vendor_info, market_info]):
            pytest.skip(f"Skipping test: Participants missing '{xmr_info_attr}'.")

        # Mock the monero_service call
        mock_xmr_payment_id = MOCK_XMR_PAYMENT_ID_PREFIX + "success"
        mock_create_xmr_wallet.return_value = {
            'address': MOCK_XMR_MULTISIG_ADDRESS,
            'wallet_name': MOCK_XMR_WALLET_NAME,
            'multisig_info': MOCK_XMR_MULTISIG_INFO, # Assuming this is the hex string/data
            'payment_id': mock_xmr_payment_id,
        }

        # Call the XMR-specific escrow service function (assuming this name)
        # ASSUMPTION: Function name is create_escrow_for_order_xmr
        try:
             if hasattr(monero_escrow_service, 'create_escrow_for_order_xmr'):
                 monero_escrow_service.create_escrow_for_order_xmr(order)
             # Fallback to common_escrow_utils if it acts as dispatcher
             elif hasattr(common_escrow_utils, 'create_escrow_for_order'):
                  common_escrow_utils.create_escrow_for_order(order)
             else:
                  pytest.fail("Cannot find create_escrow_for_order function in monero_escrow_service or common_escrow_utils.")
        except Exception as e:
             pytest.fail(f"Service call failed: {e}")

        order.refresh_from_db()

        # Assertions on order state (XMR specific)
        if order.status != OrderStatusChoices.PENDING_PAYMENT: raise AssertionError(f"Status mismatch: {order.status}")
        wallet_name_attr = ATTR_XMR_MULTISIG_WALLET_NAME
        info_order_attr = ATTR_XMR_MULTISIG_INFO_ORDER # Assuming info is stored on order too
        if hasattr(order, wallet_name_attr):
            if getattr(order, wallet_name_attr) != MOCK_XMR_WALLET_NAME: raise AssertionError("Wallet name mismatch.")
        if hasattr(order, info_order_attr):
            # Compare structure or specific keys if MOCK_XMR_MULTISIG_INFO is dict
            if getattr(order, info_order_attr) != MOCK_XMR_MULTISIG_INFO: raise AssertionError("Multisig info mismatch.")
        if order.payment_deadline is None: raise AssertionError("Payment deadline not set.")

        # Assert crypto service call details
        expected_participant_infos = sorted([buyer_info, vendor_info, market_info]) # Sort dicts if needed
        mock_create_xmr_wallet.assert_called_once()
        call_args, call_kwargs = mock_create_xmr_wallet.call_args
        # Check keyword args (from previous fix)
        if call_args: raise AssertionError(f"Expected no positional args, got {call_args}")
        if 'participant_infos' not in call_kwargs: raise AssertionError("Kwarg 'participant_infos' missing")
        # Sorting dicts requires a key or converting to comparable items
        # For simplicity, just check count and presence of specific dicts if sorting is complex
        if len(call_kwargs['participant_infos']) != 3: raise AssertionError("Incorrect number of participant infos passed.")
        # TODO: Add more robust check for participant_infos content if needed
        if call_kwargs.get('order_guid') != str(order.id): raise AssertionError("order_guid mismatch.")
        if call_kwargs.get('threshold') != mock_settings_xmr_escrow.MULTISIG_SIGNATURES_REQUIRED: raise AssertionError("Threshold mismatch.")

        # Assert CryptoPayment record
        payment = CryptoPayment.objects.get(order=order, currency='XMR')
        if payment.payment_address != MOCK_XMR_MULTISIG_ADDRESS: raise AssertionError("Payment address mismatch.")
        if payment.expected_amount_native != order.total_price_native_selected: raise AssertionError("Payment expected amount mismatch.")
        if payment.payment_id_monero != mock_xmr_payment_id: raise AssertionError("Payment ID mismatch.")
        if payment.confirmations_needed != mock_settings_xmr_escrow.MONERO_CONFIRMATIONS_NEEDED: raise AssertionError("Confirmations needed mismatch.")

    # Test failure during XMR wallet creation
    @patch('store.services.monero_service.create_monero_multisig_wallet', side_effect=CryptoProcessingError("XMR Wallet Gen Failed"))
    def test_create_escrow_xmr_crypto_fail(self, mock_create_xmr_wallet, order_pending_xmr, market_user_xmr, buyer_user_xmr, vendor_user_xmr, global_settings_xmr):
        """ Test create_escrow_for_order handles crypto service failure (XMR). """
        order = order_pending_xmr
        xmr_info_attr = ATTR_XMR_MULTISIG_INFO
        if not all([getattr(u, xmr_info_attr, None) for u in [buyer_user_xmr, vendor_user_xmr, market_user_xmr]]):
            pytest.skip(f"Skipping test: Participants missing '{xmr_info_attr}'.")

        # Expect CryptoProcessingError
        with pytest.raises(CryptoProcessingError, match="Failed to generate XMR escrow details: XMR Wallet Gen Failed"):
             # ASSUMPTION: Function name is create_escrow_for_order_xmr
             if hasattr(monero_escrow_service, 'create_escrow_for_order_xmr'):
                 monero_escrow_service.create_escrow_for_order_xmr(order)
             elif hasattr(common_escrow_utils, 'create_escrow_for_order'):
                  common_escrow_utils.create_escrow_for_order(order)
             else:
                  pytest.fail("Cannot find create_escrow_for_order function.")

        # Verify state remains unchanged
        order.refresh_from_db()
        if order.status != OrderStatusChoices.PENDING_PAYMENT: raise AssertionError(f"Status mismatch: {order.status}")
        if CryptoPayment.objects.filter(order=order, currency='XMR').exists(): raise AssertionError("CryptoPayment should not exist.")
        wallet_name_attr = ATTR_XMR_MULTISIG_WALLET_NAME
        if hasattr(order, wallet_name_attr) and getattr(order, wallet_name_attr) is not None:
            raise AssertionError("XMR Wallet name should be None.")

    # === Test XMR Payment Confirmation ===
    # Add XMR-specific confirmation tests if the logic differs significantly from BTC
    # (e.g., different parameters for scan_for_payment_confirmation)
    # If logic is identical beyond currency, could potentially reuse generic tests
    # with parametrize, but keeping separate for clarity based on file split.

    # === Test XMR Mark Shipped ===
    # Add XMR-specific mark shipped tests. Patch the XMR release preparation.
    # ASSUMPTION: _prepare_release is common, or there's _prepare_xmr_release
    # ASSUMPTION: mark_order_shipped is common dispatch, or monero_escrow_service.mark_order_shipped_xmr
    # @patch('store.services.common_escrow_utils._prepare_release') # Or patch XMR specific prep
    # def test_mark_shipped_xmr_success(self, mock_prepare_release, order_payment_confirmed_xmr, vendor_user_xmr, global_settings_xmr):
        # ... similar structure to test_mark_shipped_btc_success ...
        # mock_prepare_release.return_value = { 'type': 'xmr_unsigned_txset', 'data': MOCK_UNSIGNED_TXSET_XMR, ... }
        # common_escrow_utils.mark_order_shipped(order, vendor_user_xmr, ...)
        # Assertions ...

    # === Test XMR Signing ===
    # Add XMR-specific signing tests. Patch XMR signing function.
    # Note: XMR signing flow might be different (e.g., requires more context than just txset).
    # @patch('store.services.monero_service.sign_monero_multisig_tx') # Example patch target
    # def test_sign_order_release_xmr_buyer_first(self, mock_sign_xmr, order_shipped_xmr, buyer_user_xmr):
        # ... similar structure to test_sign_order_release_buyer_first_btc ...
        # mock_sign_xmr.return_value = MOCK_PARTIAL_TXSET_XMR
        # common_escrow_utils.sign_order_release(order, buyer_user_xmr, buyer_key_info="xmr_signing_context") # Key info might be different
        # Assertions ...

    # === Test XMR Broadcast ===
    # Add XMR-specific broadcast tests. Patch XMR broadcast function.
    # @patch('store.models.User.objects.get')
    # @patch('store.services.monero_service.finalize_and_broadcast_xmr_release')
    # @patch('ledger.services.credit_funds')
    # def test_broadcast_release_xmr_success(self, mock_ledger_credit, mock_xmr_broadcast, mock_user_get, order_ready_for_broadcast_xmr, market_user_xmr):
        # ... similar structure to test_broadcast_release_btc_success ...
        # mock_xmr_broadcast.return_value = MOCK_TX_HASH_XMR
        # Setup user_get side effect
        # common_escrow_utils.broadcast_release_transaction(order.id) # Or monero_escrow_service specific call
        # Assertions for XMR (status, hash, ledger credits) ...

    # === Test XMR Dispute Resolution ===
    # Add XMR-specific dispute tests. Patch XMR dispute broadcast.
    # @patch('store.models.User.objects.get')
    # @patch('store.services.monero_service.create_and_broadcast_dispute_tx') # Example patch target
    # @patch('ledger.services.credit_funds')
    # def test_resolve_dispute_xmr_split(self, mock_ledger_credit, mock_dispute_broadcast, mock_user_get, order_disputed_xmr, moderator_user_xmr, market_user_xmr):
        # ... similar structure to test_resolve_dispute_btc_full_buyer / _split ...
        # Calculate XMR payouts (12 decimals)
        # Setup user_get side effect
        # mock_dispute_broadcast.return_value = MOCK_TX_HASH_XMR # Use specific hash
        # common_escrow_utils.resolve_dispute(...) # Or monero_escrow_service specific call
        # Assertions for XMR (status, hash, ledger credits) ...

    # === Test XMR Get Unsigned Tx ===
    # Test getting unsigned tx data for XMR (likely same logic as BTC, points to metadata)
    # def test_get_unsigned_release_tx_xmr_success(self, order_shipped_xmr, buyer_user_xmr):
    #    ... similar to test_get_unsigned_release_tx_success ...
    #    result = common_escrow_utils.get_unsigned_release_tx(order, buyer_user_xmr) # Or monero_escrow_service call
    #    Assertions ...


# === Test Placeholders / Future Work ===
# Add tests for XMR-specific signing flows if different from simple signing
# Add tests for XMR edge cases (e.g., payment ID handling)

# <<< END OF FILE: backend/store/tests/test_monero_escrow_service.py >>>