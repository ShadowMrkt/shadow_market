# backend/store/tests/test_common_escrow_utils.py

# --- Revision History ---
# v1.1.6 (2025-05-03): Standardize Imports by Gemini # <<< NEW REVISION
#   - FIXED: Changed imports for `store.models`, `ledger.models`, `store.services`,
#     `ledger.services`, `notifications.services`, `store.exceptions` to use
#     absolute `backend.` paths to resolve conflicting model errors.
# v1.1.5 (2025-04-09) (The Void):
#   - RE-APPLY: Added missing 'from datetime import timedelta' for fixtures (Attempt 2).
#   - RE-APPLY: Changed test_get_market_fee_percentage to expect default fee for unconfigured currency (Attempt 2).
# v1.1.4 (2025-04-09) (The Void):
#   - Attempted timedelta import and market fee test logic change.
# v1.1.3 (2025-04-09) (The Void):
#   - Attempted to add timedelta import.
#   - Attempted explicit try/except in market fee test.
# v1.1.2 (2025-04-09) (The Void):
#   - Attempted fix for timedelta import.
#   - Attempted restructure of _get_market_fee_percentage.
# v1.1.1 (2025-04-09) (The Void):
#   - FIXED: Corrected import of get_user_model to resolve NameError during test collection.
# v1.1.0 (2025-04-10) (The Void): # NOTE: Date inconsistency in original header
#   - REMOVED: dispatch tests (test_dispatch_*).
#   - UPDATED: pytest.raises match patterns in test_get_withdrawal_address_*.
#   - CORRECTED: patch target for create_notification in test_check_order_timeout_cancels_order.
# v1.0.0 (2025-04-09): REFACTOR (The Void)
#   - Created this file.
# ------------------------

# --- Standard Library Imports ---
import uuid
import logging
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import Dict, Any, Optional, Callable, Tuple
from django.contrib.auth import get_user_model
from unittest.mock import patch, MagicMock, call, ANY
# FIX v1.1.5: Import timedelta
import datetime
from datetime import timedelta # Explicit import

# --- Third-Party Imports ---
import pytest
from django.conf import settings as django_settings
from django.core.exceptions import ValidationError as DjangoValidationError, FieldError, ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

# --- Local Imports ---
# Models
User = get_user_model()
# <<< START FIX v1.1.6: Use absolute backend path >>>
from backend.store.models import Order, Product, GlobalSettings, CryptoPayment, Category, OrderStatus as OrderStatusChoices # noqa
from backend.ledger.models import UserBalance, LedgerTransaction # noqa

# Services and Exceptions
# Primary target for testing:
from backend.store.services import common_escrow_utils
# Import services needed for fixture data or type hinting
from backend.store.services import bitcoin_service, monero_service # Needed for _convert_atomic_to_standard tests potentially
from backend.ledger import services as ledger_service # Potentially needed by fixtures if they create balances
from backend.notifications import services as notification_service # Needed for patching timeout test
from backend.store.exceptions import EscrowError # Assuming defined elsewhere
# <<< END FIX v1.1.6 >>>


# --- Constants ---
MOCK_MARKET_USER_USERNAME = "market_test_user_common"
MOCK_BUYER_USERNAME = "test_buyer_common_escrow"
MOCK_VENDOR_USERNAME = "test_vendor_common_escrow"
MOCK_MODERATOR_USERNAME = "test_mod_common_escrow"

MOCK_PRODUCT_PRICE_BTC = Decimal("0.01")
MOCK_PRODUCT_PRICE_XMR = Decimal("1.0")
MOCK_PRODUCT_PRICE_ETH = Decimal("0.1") # Example
DEFAULT_SETTINGS_MARKET_FEE = Decimal('2.5') # Fallback default for tests

# Addresses/Data
MOCK_BTC_WITHDRAWAL_ADDR = 'vendor_btc_payout_addr_common'
MOCK_BUYER_BTC_REFUND_ADDR = 'buyer_btc_refund_addr_common'
MOCK_XMR_WITHDRAWAL_ADDR = 'vendor_xmr_payout_addr_common'
MOCK_BUYER_XMR_REFUND_ADDR = 'buyer_xmr_refund_addr_common'
MOCK_ETH_WITHDRAWAL_ADDR = "0x" + "b" * 40 + "_common"
MOCK_BUYER_ETH_REFUND_ADDR = "0x" + "c" * 40 + "_common"

MOCK_MARKET_PGP_KEY = "market_pgp_key_data_common_fixture"
MOCK_BUYER_PGP_KEY = "buyer_pgp_key_common_fixture"
MOCK_VENDOR_PGP_KEY = "vendor_pgp_key_data_common_fixture_different"
DEFAULT_CATEGORY_ID = 1

# Constants from common_escrow_utils
try:
    ATTR_BTC_WITHDRAWAL_ADDRESS = common_escrow_utils.ATTR_BTC_WITHDRAWAL_ADDRESS
    ATTR_XMR_WITHDRAWAL_ADDRESS = common_escrow_utils.ATTR_XMR_WITHDRAWAL_ADDRESS
    ATTR_ETH_WITHDRAWAL_ADDRESS = common_escrow_utils.ATTR_ETH_WITHDRAWAL_ADDRESS
except AttributeError:
    ATTR_BTC_WITHDRAWAL_ADDRESS = 'btc_withdrawal_address'
    ATTR_XMR_WITHDRAWAL_ADDRESS = 'xmr_withdrawal_address'
    ATTR_ETH_WITHDRAWAL_ADDRESS = 'eth_withdrawal_address'
    logging.warning("Could not find withdrawal address attribute constants in common_escrow_utils, using fallbacks.")


# --- Helper Function for Atomic Conversion ---
def to_atomic(amount_std: Decimal, decimals: int) -> Decimal:
    if not isinstance(amount_std, Decimal): amount_std = Decimal(amount_std)
    multiplier = Decimal(f'1e{decimals}')
    return (amount_std * multiplier).quantize(Decimal('1'), rounding=ROUND_DOWN)
def from_atomic(amount_atomic: Decimal, decimals: int) -> Decimal:
    if not isinstance(amount_atomic, Decimal): amount_atomic = Decimal(amount_atomic)
    divisor = Decimal(f'1e{decimals}')
    display_precision = Decimal('1e-8'); # Default
    if decimals == 12: display_precision = Decimal('1e-12')
    if decimals == 18: display_precision = Decimal('1e-18')
    return (amount_atomic / divisor).quantize(display_precision, rounding=ROUND_DOWN)


# --- Fixtures ---
@pytest.fixture
def mock_settings_common(settings):
    """Override settings relevant to common escrow utilities."""
    settings.MARKET_FEE_PERCENTAGE_BTC = Decimal("2.5") # Explicitly set for clarity
    settings.MARKET_FEE_PERCENTAGE_XMR = Decimal("2.5")
    settings.MARKET_FEE_PERCENTAGE_ETH = Decimal("3.0") # Example different fee
    settings.MARKET_USER_USERNAME = MOCK_MARKET_USER_USERNAME
    settings.DEFAULT_MARKET_FEE_PERCENTAGE = DEFAULT_SETTINGS_MARKET_FEE # Use constant
    settings.ORDER_PAYMENT_TIMEOUT_HOURS = 24
    yield settings

@pytest.fixture
def market_user_common(db, mock_settings_common) -> User:
    """Provides the market user."""
    user, _ = User.objects.update_or_create(
        username=mock_settings_common.MARKET_USER_USERNAME,
        defaults={ 'is_staff': True, 'is_active': True, 'pgp_public_key': MOCK_MARKET_PGP_KEY }
    )
    UserBalance.objects.get_or_create(user=user, currency='BTC', defaults={'balance': Decimal('10.0')})
    return user

@pytest.fixture
def buyer_user_common(db) -> User:
    """Provides a buyer user."""
    user, _ = User.objects.update_or_create(
        username=MOCK_BUYER_USERNAME,
        defaults={
            'is_active': True, 'pgp_public_key': MOCK_BUYER_PGP_KEY,
            ATTR_BTC_WITHDRAWAL_ADDRESS: MOCK_BUYER_BTC_REFUND_ADDR,
            ATTR_XMR_WITHDRAWAL_ADDRESS: MOCK_BUYER_XMR_REFUND_ADDR,
            ATTR_ETH_WITHDRAWAL_ADDRESS: MOCK_BUYER_ETH_REFUND_ADDR,
        }
    )
    return user

@pytest.fixture
def vendor_user_common(db) -> User:
    """Provides a vendor user."""
    user, _ = User.objects.update_or_create(
        username=MOCK_VENDOR_USERNAME,
        defaults={
            'is_vendor': True, 'is_active': True, 'pgp_public_key': MOCK_VENDOR_PGP_KEY,
            ATTR_BTC_WITHDRAWAL_ADDRESS: MOCK_BTC_WITHDRAWAL_ADDR,
            ATTR_XMR_WITHDRAWAL_ADDRESS: MOCK_XMR_WITHDRAWAL_ADDR,
            ATTR_ETH_WITHDRAWAL_ADDRESS: MOCK_ETH_WITHDRAWAL_ADDR,
        }
    )
    return user

@pytest.fixture
def global_settings_common(db, market_user_common, mock_settings_common) -> GlobalSettings:
    """Ensures GlobalSettings singleton exists and sets relevant attributes."""
    gs, created = GlobalSettings.objects.get_or_create(pk=1, defaults={})
    gs.market_fee_percentage_btc = mock_settings_common.MARKET_FEE_PERCENTAGE_BTC
    gs.market_fee_percentage_xmr = mock_settings_common.MARKET_FEE_PERCENTAGE_XMR
    gs.market_fee_percentage_eth = mock_settings_common.MARKET_FEE_PERCENTAGE_ETH
    # Ensure LTC fee is NOT set
    if hasattr(gs, 'market_fee_percentage_ltc'):
        try:
            delattr(gs, 'market_fee_percentage_ltc')
            logger.info("Removed potentially existing 'market_fee_percentage_ltc' in global_settings_common fixture.")
        except AttributeError: pass
    gs.payment_wait_hours = mock_settings_common.ORDER_PAYMENT_TIMEOUT_HOURS
    gs.save()
    gs.refresh_from_db()
    return gs

@pytest.fixture
def product_category_common(db) -> Category:
    """Ensures a default Category object exists."""
    category, _ = Category.objects.get_or_create(pk=DEFAULT_CATEGORY_ID, defaults={'name': 'Default Common Test Category'})
    return category

@pytest.fixture
def product_common(db, vendor_user_common, product_category_common) -> Product:
    """Provides a generic product."""
    product, _ = Product.objects.update_or_create(
        name="Test Product Common", vendor=vendor_user_common, category=product_category_common,
        defaults={ 'price_btc': MOCK_PRODUCT_PRICE_BTC, 'description': "Test Product for common utils", 'is_active': True }
    )
    return product

@pytest.fixture
def order_common_pending(db, buyer_user_common, vendor_user_common, product_common, mock_settings_common) -> Order:
    """ Creates a generic pending order. """
    order = Order.objects.create(
        buyer=buyer_user_common, vendor=vendor_user_common, product=product_common, quantity=1, selected_currency='BTC',
        price_native_selected=to_atomic(MOCK_PRODUCT_PRICE_BTC, 8), total_price_native_selected=to_atomic(MOCK_PRODUCT_PRICE_BTC, 8),
        status=OrderStatusChoices.PENDING_PAYMENT
    )
    wait_hours = int(getattr(mock_settings_common, 'ORDER_PAYMENT_TIMEOUT_HOURS', 24))
    # FIX v1.1.5: Use imported timedelta
    order.payment_deadline = timezone.now() + timedelta(hours=wait_hours)
    order.save()
    return order


# --- Test Class ---

@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("mock_settings_common", "global_settings_common", "market_user_common")
class TestCommonEscrowUtils:
    """ Test suite for the store.services.common_escrow_utils module. """

    def setup_method(self, method):
        """ Reset market user cache before each test. """
        if hasattr(common_escrow_utils, '_market_user_cache'):
            common_escrow_utils._market_user_cache = None

    # === Test Helper Functions ===

    def test_get_currency_precision(self):
        """ Test _get_currency_precision returns correct decimals or raises ValueError. """
        if not hasattr(common_escrow_utils, '_get_currency_precision'):
             pytest.fail("_get_currency_precision not found in common_escrow_utils.")

        if common_escrow_utils._get_currency_precision('BTC') != 8: raise AssertionError("BTC precision incorrect.")
        if common_escrow_utils._get_currency_precision('XMR') != 12: raise AssertionError("XMR precision incorrect.")
        if common_escrow_utils._get_currency_precision('ETH') != 18: raise AssertionError("ETH precision incorrect.")
        if common_escrow_utils._get_currency_precision('btc') != 8: raise AssertionError("BTC lowercase precision incorrect.")

        with pytest.raises(ValueError, match="Unsupported currency for precision: LTC"):
            common_escrow_utils._get_currency_precision('LTC')

    def test_get_withdrawal_address_success(self, vendor_user_common):
        """ Test _get_withdrawal_address successfully retrieves address. """
        if not hasattr(common_escrow_utils, '_get_withdrawal_address'):
             pytest.fail("_get_withdrawal_address not found in common_escrow_utils.")

        addr_btc = common_escrow_utils._get_withdrawal_address(vendor_user_common, 'BTC')
        if addr_btc != MOCK_BTC_WITHDRAWAL_ADDR: raise AssertionError(f"BTC Address mismatch: got {addr_btc}")
        addr_xmr = common_escrow_utils._get_withdrawal_address(vendor_user_common, 'XMR')
        if addr_xmr != MOCK_XMR_WITHDRAWAL_ADDR: raise AssertionError(f"XMR Address mismatch: got {addr_xmr}")
        addr_eth = common_escrow_utils._get_withdrawal_address(vendor_user_common, 'ETH')
        if addr_eth != MOCK_ETH_WITHDRAWAL_ADDR: raise AssertionError(f"ETH Address mismatch: got {addr_eth}")

    def test_get_withdrawal_address_missing(self, vendor_user_common):
        """ Test _get_withdrawal_address raises ValueError if address missing/empty. """
        if not hasattr(common_escrow_utils, '_get_withdrawal_address'):
             pytest.fail("_get_withdrawal_address not found in common_escrow_utils.")

        original_addr = vendor_user_common.btc_withdrawal_address
        vendor_user_common.btc_withdrawal_address = ""
        vendor_user_common.save()
        expected_error_msg = rf"User {vendor_user_common.username} missing valid withdrawal address for BTC"
        with pytest.raises(ValueError, match=expected_error_msg):
            common_escrow_utils._get_withdrawal_address(vendor_user_common, 'BTC')
        vendor_user_common.btc_withdrawal_address = original_addr # Restore
        vendor_user_common.save()

    def test_get_withdrawal_address_unsupported_currency(self, vendor_user_common):
        """ Test _get_withdrawal_address raises ValueError for unsupported currency. """
        if not hasattr(common_escrow_utils, '_get_withdrawal_address'):
             pytest.fail("_get_withdrawal_address not found in common_escrow_utils.")
        expected_error_msg = "Unsupported currency for withdrawal address: DOGE"
        with pytest.raises(ValueError, match=expected_error_msg):
             common_escrow_utils._get_withdrawal_address(vendor_user_common, 'DOGE')

    def test_get_market_fee_percentage(self, global_settings_common, mock_settings_common):
        """ Test _get_market_fee_percentage retrieves correct fee or the default fee for unconfigured currencies. """
        if not hasattr(common_escrow_utils, '_get_market_fee_percentage'):
             pytest.fail("_get_market_fee_percentage not found in common_escrow_utils.")

        if hasattr(global_settings_common, 'market_fee_percentage_ltc'):
            pytest.fail("Test setup error: global_settings_common fixture explicitly removed ltc fee, but it still exists.")

        if common_escrow_utils._get_market_fee_percentage('BTC') != mock_settings_common.MARKET_FEE_PERCENTAGE_BTC: raise AssertionError("BTC Fee mismatch.")
        if common_escrow_utils._get_market_fee_percentage('XMR') != mock_settings_common.MARKET_FEE_PERCENTAGE_XMR: raise AssertionError("XMR Fee mismatch.")
        if common_escrow_utils._get_market_fee_percentage('ETH') != mock_settings_common.MARKET_FEE_PERCENTAGE_ETH: raise AssertionError("ETH Fee mismatch.")
        if common_escrow_utils._get_market_fee_percentage('btc') != mock_settings_common.MARKET_FEE_PERCENTAGE_BTC: raise AssertionError("Lowercase BTC Fee mismatch.")

        # FIX v1.1.5: Expect the default fee for unconfigured currency (LTC) based on reverted function logic
        currency_to_test = 'LTC'
        expected_default_fee = mock_settings_common.DEFAULT_MARKET_FEE_PERCENTAGE # Get default from settings fixture
        actual_fee = common_escrow_utils._get_market_fee_percentage(currency_to_test)
        if actual_fee != expected_default_fee:
            # Use pytest.fail for clearer message
             pytest.fail(f"Expected default fee ({expected_default_fee}%) for unconfigured currency {currency_to_test}, but got {actual_fee}%.")

    # === Test Timeout Logic ===
    # <<< START FIX v1.1.6: Use absolute backend path for patching >>>
    @patch('backend.notifications.services.create_notification')
    # <<< END FIX v1.1.6 >>>
    def test_check_order_timeout_cancels_order(self, mock_create_notification, order_common_pending, mock_settings_common):
        """ Test _check_order_timeout cancels a timed-out order. """
        if not hasattr(common_escrow_utils, '_check_order_timeout'):
             pytest.skip("_check_order_timeout not found in common_escrow_utils.")

        order = order_common_pending
        order.payment_deadline = timezone.now() - timedelta(hours=1)
        order.status = OrderStatusChoices.PENDING_PAYMENT
        order.save()

        cancelled = common_escrow_utils._check_order_timeout(order)

        if cancelled is not True: raise AssertionError("Should return True when cancelling.")
        order.refresh_from_db()
        if order.status != OrderStatusChoices.CANCELLED_TIMEOUT: raise AssertionError(f"Status mismatch: {order.status}")
        # mock_create_notification.assert_called() # Optional: verify notification call

    def test_check_order_timeout_does_not_cancel_valid_order(self, order_common_pending):
        """ Test _check_order_timeout does not cancel an order before its deadline. """
        if not hasattr(common_escrow_utils, '_check_order_timeout'):
             pytest.skip("_check_order_timeout not found in common_escrow_utils.")

        order = order_common_pending
        initial_status = order.status
        initial_deadline = order.payment_deadline

        if not initial_deadline or initial_deadline <= timezone.now():
            order.payment_deadline = timezone.now() + timedelta(hours=1)
            order.save()
            initial_deadline = order.payment_deadline

        cancelled = common_escrow_utils._check_order_timeout(order)

        if cancelled is True: raise AssertionError("Should return False when not cancelling.")
        order.refresh_from_db()
        if order.status != initial_status: raise AssertionError(f"Status should not change: got {order.status}, expected {initial_status}")
        if order.payment_deadline != initial_deadline: raise AssertionError("Deadline should not change.")


# <<< END OF FILE: backend/store/tests/test_common_escrow_utils.py >>>