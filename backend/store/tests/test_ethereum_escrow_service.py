# backend/store/tests/test_ethereum_escrow_service.py
# Author: The Void

# --- Revision History ---
# 2025-04-11 (Gemini Rev 4):
#   - Removed direct import of 'get_market_user' (ModuleNotFoundError).
# 2025-04-11 (Gemini Rev 3):
#   - Removed direct import of 'create_notification' (ModuleNotFoundError).
#   - Updated @patch target for 'create_notification' to the service module namespace.
# 2025-04-11 (Gemini Rev 2):
#   - Corrected ImportError by importing IntegrityError from django.db instead of django.core.exceptions.
# 2025-04-11 (Gemini Rev 1):
#   - Updated expected error message in test_create_escrow_eth_crypto_fail
#     to match actual error raised by service ('Failed to generate...').
# ... (Previous revisions omitted) ...
# ------------------------

# --- Standard Library Imports ---
import uuid
import logging
import sys
from decimal import Decimal, ROUND_DOWN, InvalidOperation, getcontext
from typing import Dict, Any, Optional, Callable, Tuple, List # Added List
from django.contrib.auth import get_user_model as django_get_user_model
from unittest.mock import patch, MagicMock, call, ANY
import datetime # Keep even if unused for potential future use

# --- Third-Party Imports ---
import pytest
from django.conf import settings as django_settings
# FIX (Rev 2): Import IntegrityError from django.db
from django.core.exceptions import ValidationError as DjangoValidationError, FieldError, ObjectDoesNotExist
from django.db import transaction, IntegrityError # Keep transaction, add IntegrityError
from django.utils import timezone

# --- Local Imports ---
# Models
from store.models import Order, Product, User, GlobalSettings, CryptoPayment, Category, OrderStatus as OrderStatusChoices, EscrowType as EscrowTypeChoices # Ensure EscrowTypeChoices is imported
from ledger.models import UserBalance, LedgerTransaction # noqa - Mark as used by fixtures/setup

# Services and Exceptions
# Import specific service being tested if direct calls are made, otherwise rely on common_escrow_utils dispatch
from store.services import ethereum_escrow_service as service_under_test # Import service under test
from store.services import common_escrow_utils
# Assume ethereum_service is imported within ethereum_escrow_service or patched
# from store.services import ethereum_service
from ledger import services as ledger_service
from ledger.services import InsufficientFundsError, InvalidLedgerOperationError # noqa
from ledger.exceptions import LedgerError # noqa
from store.exceptions import EscrowError, CryptoProcessingError # noqa
# FIX (Rev 3): Removed direct import of create_notification
# FIX (Rev 4): Removed direct import of get_market_user
# from store.utils.users import get_market_user # Removed import

DjangoUser = django_get_user_model()

logger = logging.getLogger(__name__)

# --- Ethereum-Specific Test Constants (PLACEHOLDERS) ---
# !!! IMPLEMENTATION NEEDED: Replace with actual mock data !!!
MOCK_MARKET_USER_USERNAME = "market_test_user_eth"
MOCK_BUYER_USERNAME = "test_buyer_eth_escrow"
MOCK_VENDOR_USERNAME = "test_vendor_eth_escrow"
MOCK_MODERATOR_USERNAME = "test_mod_eth_escrow"

MOCK_PRODUCT_PRICE_ETH = Decimal("0.1") # Standard Units (Example)
MOCK_MARKET_FEE_PERCENT = Decimal("3.0") # Example ETH Fee

# Atomic units (ETH: 18 decimals - Wei)
MOCK_PRODUCT_PRICE_ETH_ATOMIC = Decimal("100000000000000000") # 0.1 * 10^18 (Example)

MOCK_ETH_CONTRACT_ADDRESS = "0x" + "a" * 40 # Placeholder contract address
MOCK_ETH_WITHDRAWAL_ADDR = "0x" + "b" * 40 # Placeholder vendor withdrawal
MOCK_BUYER_ETH_REFUND_ADDR = "0x" + "c" * 40 # Placeholder buyer refund

# Fixture Addresses (v1.1.0) - Placeholders for multisig owner roles
MOCK_MARKET_ETH_OWNER_ADDR = "0xMARKET" + "1" * 34
MOCK_BUYER_ETH_OWNER_ADDR = "0xBUYER_" + "2" * 34
MOCK_VENDOR_ETH_OWNER_ADDR = "0xVENDOR" + "3" * 34


MOCK_TX_HASH_ETH = "0x" + "d" * 64 # Placeholder transaction hash
MOCK_UNSIGNED_TX_ETH = {"data": "0x...", "to": MOCK_ETH_CONTRACT_ADDRESS, "value": MOCK_PRODUCT_PRICE_ETH_ATOMIC} # Example structure
MOCK_SIGNED_TX_ETH_BUYER = "0xSIGNED_BUYER..." # Placeholder signed tx
MOCK_SIGNED_TX_ETH_VENDOR = "0xSIGNED_VENDOR..." # Placeholder signed tx (might not apply if contract handles release)
MOCK_FINAL_TX_ETH = "0xFINAL_TX_DATA..." # Placeholder for final broadcastable tx

# Generic constants potentially needed by fixtures
MOCK_MARKET_PGP_KEY = "market_pgp_key_data_eth_fixture"
MOCK_BUYER_PGP_KEY = "buyer_pgp_key_eth_fixture"
MOCK_VENDOR_PGP_KEY = "vendor_pgp_key_data_eth_fixture_different"
DEFAULT_CATEGORY_ID = 1

# Get constant names dynamically from common_escrow_utils
ATTR_ETH_OWNER_ADDRESS_NAME = getattr(common_escrow_utils, 'ATTR_ETH_MULTISIG_OWNER_ADDRESS', 'eth_multisig_owner_address') # Default added
ATTR_ETH_WITHDRAWAL_ADDRESS_NAME = getattr(common_escrow_utils, 'ATTR_ETH_WITHDRAWAL_ADDRESS', 'eth_withdrawal_address') # Default added
# Dynamically get constant if defined, otherwise use default (used in setup_eth_escrow)
ATTR_ETH_ESCROW_ADDRESS_NAME = getattr(common_escrow_utils, 'ATTR_ETH_ESCROW_ADDRESS', 'eth_escrow_address')


# --- Helper Function for Atomic Conversion (Generic, keep) ---
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
    # Assuming ETH precision is 18 for standard display
    display_precision = Decimal('1e-18') if decimals == 18 else Decimal(f'1e-{decimals}')
    return (amount_atomic / divisor).quantize(display_precision, rounding=ROUND_DOWN)


# --- Fixtures ---
@pytest.fixture
def mock_settings_eth_escrow(settings):
    """Override specific Django settings for ETH escrow tests."""
    settings.MARKET_FEE_PERCENTAGE_ETH = MOCK_MARKET_FEE_PERCENT
    # Remove BTC/XMR fee settings if they exist
    if hasattr(settings, 'MARKET_FEE_PERCENTAGE_BTC'): delattr(settings, 'MARKET_FEE_PERCENTAGE_BTC')
    if hasattr(settings, 'MARKET_FEE_PERCENTAGE_XMR'): delattr(settings, 'MARKET_FEE_PERCENTAGE_XMR')

    settings.MARKET_USER_USERNAME = MOCK_MARKET_USER_USERNAME
    settings.ORDER_PAYMENT_TIMEOUT_HOURS = 24
    settings.ORDER_FINALIZE_TIMEOUT_DAYS = 14
    settings.ORDER_DISPUTE_WINDOW_DAYS = 7
    settings.ETHEREUM_CONFIRMATIONS_NEEDED = 12 # Example
    # Remove BTC/XMR confirmation settings if they exist
    if hasattr(settings, 'BITCOIN_CONFIRMATIONS_NEEDED'): delattr(settings, 'BITCOIN_CONFIRMATIONS_NEEDED')
    if hasattr(settings, 'MONERO_CONFIRMATIONS_NEEDED'): delattr(settings, 'MONERO_CONFIRMATIONS_NEEDED')

    settings.MULTISIG_SIGNATURES_REQUIRED = 2 # Keep generic setting
    yield settings

# --- User Fixtures (Adapted for ETH focus) ---
@pytest.fixture
def market_user_eth(db, mock_settings_eth_escrow) -> DjangoUser:
    """Provides the market user configured for ETH tests."""
    eth_owner_attr = ATTR_ETH_OWNER_ADDRESS_NAME # Use dynamically fetched name

    defaults_dict = {
        'is_staff': True, 'is_active': True, 'pgp_public_key': MOCK_MARKET_PGP_KEY,
        # FIX v1.1.0: Add the multisig owner address required by the service skeleton
        eth_owner_attr: MOCK_MARKET_ETH_OWNER_ADDR,
    }

    user, _ = DjangoUser.objects.update_or_create(
        username=mock_settings_eth_escrow.MARKET_USER_USERNAME,
        defaults=defaults_dict
    )
    # Ensure ETH balance exists (remove others)
    UserBalance.objects.update_or_create(user=user, currency='ETH', defaults={'balance': Decimal('50.0')})
    UserBalance.objects.filter(user=user).exclude(currency='ETH').delete() # Clean up other currencies
    user.refresh_from_db()
    # Verify attribute was set
    if getattr(user, eth_owner_attr, None) != MOCK_MARKET_ETH_OWNER_ADDR:
        pytest.fail(f"Failed to set '{eth_owner_attr}' on market_user_eth fixture.")
    return user

@pytest.fixture
def buyer_user_eth(db) -> DjangoUser:
    """Provides a buyer user configured for ETH tests."""
    eth_owner_attr = ATTR_ETH_OWNER_ADDRESS_NAME
    eth_refund_attr = ATTR_ETH_WITHDRAWAL_ADDRESS_NAME

    defaults_dict = {
        'is_active': True, 'pgp_public_key': MOCK_BUYER_PGP_KEY,
        eth_refund_attr: MOCK_BUYER_ETH_REFUND_ADDR, # Keep withdrawal/refund address
        # FIX v1.1.0: Add the multisig owner address required by the service skeleton
        eth_owner_attr: MOCK_BUYER_ETH_OWNER_ADDR,
    }

    user, _ = DjangoUser.objects.update_or_create(
        username=MOCK_BUYER_USERNAME,
        defaults=defaults_dict
    )
    UserBalance.objects.update_or_create(user=user, currency='ETH', defaults={'balance': Decimal('5.0')})
    UserBalance.objects.filter(user=user).exclude(currency='ETH').delete()
    user.refresh_from_db()
    # Verify attributes were set
    if getattr(user, eth_owner_attr, None) != MOCK_BUYER_ETH_OWNER_ADDR:
        pytest.fail(f"Failed to set '{eth_owner_attr}' on buyer_user_eth fixture.")
    if getattr(user, eth_refund_attr, None) != MOCK_BUYER_ETH_REFUND_ADDR:
        pytest.fail(f"Failed to set '{eth_refund_attr}' on buyer_user_eth fixture.")
    return user

@pytest.fixture
def vendor_user_eth(db) -> DjangoUser:
    """Provides a vendor user configured for ETH tests."""
    eth_owner_attr = ATTR_ETH_OWNER_ADDRESS_NAME
    eth_wd_attr = ATTR_ETH_WITHDRAWAL_ADDRESS_NAME

    defaults_dict = {
        'is_vendor': True, 'is_active': True, 'pgp_public_key': MOCK_VENDOR_PGP_KEY,
        eth_wd_attr: MOCK_ETH_WITHDRAWAL_ADDR, # Keep withdrawal address
        # FIX v1.1.0: Add the multisig owner address required by the service skeleton
        eth_owner_attr: MOCK_VENDOR_ETH_OWNER_ADDR,
    }
    user, _ = DjangoUser.objects.update_or_create(
        username=MOCK_VENDOR_USERNAME,
        defaults=defaults_dict
    )
    UserBalance.objects.update_or_create(user=user, currency='ETH', defaults={'balance': Decimal('25.0')})
    UserBalance.objects.filter(user=user).exclude(currency='ETH').delete()
    user.refresh_from_db()
    # Verify attributes were set
    if getattr(user, eth_owner_attr, None) != MOCK_VENDOR_ETH_OWNER_ADDR:
        pytest.fail(f"Failed to set '{eth_owner_attr}' on vendor_user_eth fixture.")
    if getattr(user, eth_wd_attr, None) != MOCK_ETH_WITHDRAWAL_ADDR:
        pytest.fail(f"Failed to set '{eth_wd_attr}' on vendor_user_eth fixture.")
    return user

@pytest.fixture
def moderator_user_eth(db) -> DjangoUser:
    """Provides a moderator user (generic)."""
    user, _ = DjangoUser.objects.get_or_create(
        username=MOCK_MODERATOR_USERNAME,
        defaults={'is_staff': True, 'is_active': True}
    )
    user.refresh_from_db()
    return user

# --- Generic Setup Fixtures ---
@pytest.fixture
def global_settings_eth(db, market_user_eth, mock_settings_eth_escrow) -> GlobalSettings:
    """Ensures GlobalSettings singleton exists and sets ETH-relevant attributes."""
    try:
        # Use update_or_create for the singleton for robustness
        gs, created = GlobalSettings.objects.update_or_create(
            pk=1, # Assuming singleton has pk=1
            defaults={
                'market_fee_percentage_eth': mock_settings_eth_escrow.MARKET_FEE_PERCENTAGE_ETH,
                'payment_wait_hours': mock_settings_eth_escrow.ORDER_PAYMENT_TIMEOUT_HOURS,
                'order_auto_finalize_days': mock_settings_eth_escrow.ORDER_FINALIZE_TIMEOUT_DAYS,
                'dispute_window_days': mock_settings_eth_escrow.ORDER_DISPUTE_WINDOW_DAYS,
                'confirmations_needed_eth': mock_settings_eth_escrow.ETHEREUM_CONFIRMATIONS_NEEDED,
            }
        )
        # FIX v1.2.0: Set other currency fields to valid defaults (0) instead of None
        gs.market_fee_percentage_btc = Decimal('0.0')
        gs.market_fee_percentage_xmr = Decimal('0.0') # Set default instead of None
        gs.confirmations_needed_btc = 0
        gs.confirmations_needed_xmr = 0 # Set default instead of None

        # Ensure other potentially non-nullable fields have defaults if not set by update_or_create
        if not gs.site_name: gs.site_name = "Default Site"
        # Add defaults for any other potentially problematic fields if needed

        gs.save()

    except AttributeError as e: raise AttributeError(f"GlobalSettings model might be outdated or missing fields. {e}") from e
    except IntegrityError as e: pytest.fail(f"IntegrityError saving GlobalSettings (check NOT NULL fields): {e}")
    except Exception as e: pytest.fail(f"Failed to get/create/update GlobalSettings: {e}")

    gs.refresh_from_db()
    # Ensure market user PGP key
    if not market_user_eth.pgp_public_key:
        market_user_eth.pgp_public_key = MOCK_MARKET_PGP_KEY
        market_user_eth.save(update_fields=['pgp_public_key'])
    return gs

@pytest.fixture
def product_category_eth(db) -> Category:
    """Ensures a default Category object exists."""
    category, created = Category.objects.get_or_create(pk=DEFAULT_CATEGORY_ID, defaults={'name': 'Default ETH Test Category'})
    return category

@pytest.fixture
def product_eth(db, vendor_user_eth, product_category_eth) -> Product:
    """Provides a simple ETH product."""
    product, created = Product.objects.update_or_create(
        name="Test ETH Product Only", vendor=vendor_user_eth, category=product_category_eth,
        defaults={
            'price_eth': MOCK_PRODUCT_PRICE_ETH, # Use ETH price field
            'description': "Test ETH Product Description",
            'is_active': True,
            'price_btc': None, 'price_xmr': None, # Exclude other prices
        }
    )
    product.refresh_from_db()
    if product.category_id != product_category_eth.id: pytest.fail("Category mismatch.")
    if product.price_eth != MOCK_PRODUCT_PRICE_ETH: pytest.fail("Price mismatch.")
    return product

# --- Order Creation Fixtures (ETH-Specific and Generic Helpers) ---

@pytest.fixture
def create_eth_order(db, buyer_user_eth, vendor_user_eth, global_settings_eth) -> Callable[[Product, str], Order]:
    """ Factory fixture to create ETH orders, setting atomic price fields (Wei). """
    def _create_eth_order(product: Product, status: str = OrderStatusChoices.PENDING_PAYMENT) -> Order:
        currency_upper = 'ETH'; decimals = 18
        price_std = product.price_eth

        if price_std is None or not isinstance(price_std, Decimal) or price_std <= Decimal('0.0'):
            pytest.fail(f"Product {product.id} has invalid ETH price ({price_std}).")

        price_native_selected_atomic = to_atomic(price_std, decimals) # Price in Wei
        if price_native_selected_atomic <= Decimal('0'):
            pytest.fail(f"Calculated atomic ETH price ({price_native_selected_atomic}) is not positive.")

        quantity = 1; shipping_price_std = Decimal(0)
        shipping_price_native_selected_atomic = to_atomic(shipping_price_std, decimals)
        total_price_native_selected_atomic_calculated = (price_native_selected_atomic * quantity) + shipping_price_native_selected_atomic

        # Verify participants
        if not DjangoUser.objects.filter(pk=buyer_user_eth.pk).exists(): pytest.fail("Buyer missing.")
        if not DjangoUser.objects.filter(pk=vendor_user_eth.pk).exists(): pytest.fail("Vendor missing.")
        if not Product.objects.filter(pk=product.pk).exists(): pytest.fail("Product missing.")

        order = Order.objects.create(
            buyer=buyer_user_eth, vendor=vendor_user_eth, product=product,
            quantity=quantity, selected_currency=currency_upper,
            price_native_selected=price_native_selected_atomic,
            shipping_price_native_selected=shipping_price_native_selected_atomic,
            total_price_native_selected=total_price_native_selected_atomic_calculated,
            status=status,
            escrow_type=EscrowTypeChoices.MULTISIG # Set default escrow type
            # Add ETH specific fields if needed (e.g., eth_contract_address initially None)
            # eth_contract_address=None,
        )
        # Immediate verification
        if order.total_price_native_selected != total_price_native_selected_atomic_calculated:
            raise AssertionError("Order total price mismatch immediately after create.")
        # Verify after refresh
        try:
            order.refresh_from_db()
            # ... standard checks for buyer, vendor, product, total_price ...
            if order.total_price_native_selected != total_price_native_selected_atomic_calculated:
                raise AssertionError("Total price mismatch after refresh.")
        except ObjectDoesNotExist:
            pytest.fail(f"Order {order.id} failed refresh_from_db.")
        return order
    return _create_eth_order

@pytest.fixture
def order_pending_eth(create_eth_order, product_eth) -> Order:
    """ Creates an ETH order in PENDING_PAYMENT status. """
    return create_eth_order(product_eth, OrderStatusChoices.PENDING_PAYMENT)

# Adapt setup_escrow for ETH (likely involves deploying/setting contract address)
@pytest.fixture
def setup_eth_escrow(db, mock_settings_eth_escrow) -> Callable[[Order, str], Order]:
    """ Helper fixture for ETH escrow setup (CryptoPayment, deadlines, contract address). """
    # !!! IMPLEMENTATION NEEDED: Adapt based on how ETH escrow is initiated !!!
    def _setup_eth_escrow(order: Order, contract_address: str) -> Order:
        order.refresh_from_db()
        if order.selected_currency != 'ETH': pytest.fail("setup_eth_escrow called on non-ETH order.")
        if order.total_price_native_selected is None or order.total_price_native_selected <= Decimal('0'):
            pytest.fail(f"Order {order.id} has invalid total price (Wei).")

        order.status = OrderStatusChoices.PENDING_PAYMENT
        order.payment_deadline = timezone.now() + timezone.timedelta(hours=mock_settings_eth_escrow.ORDER_PAYMENT_TIMEOUT_HOURS)

        update_fields_order = ['status', 'payment_deadline', 'updated_at']
        # Set ETH specific field (e.g., the contract address for this order)
        eth_addr_attr = ATTR_ETH_ESCROW_ADDRESS_NAME # Use dynamically fetched name
        if hasattr(order, eth_addr_attr):
            setattr(order, eth_addr_attr, contract_address)
            update_fields_order.append(eth_addr_attr)
        # Add other fields if needed (e.g., ABI, deployment tx hash)

        order.save(update_fields=list(set(update_fields_order)))

        confirmations_needed = mock_settings_eth_escrow.ETHEREUM_CONFIRMATIONS_NEEDED

        # Create CryptoPayment record for ETH
        payment, created = CryptoPayment.objects.update_or_create(
            order=order, currency='ETH',
            defaults={
                'payment_address': contract_address, # Payment goes TO the contract
                'expected_amount_native': order.total_price_native_selected, # Amount in Wei
                'confirmations_needed': confirmations_needed,
                # Add other relevant fields if needed (e.g., specific function selector)
            }
        )
        order.refresh_from_db()
        return order
    return _setup_eth_escrow

@pytest.fixture
def order_escrow_created_eth(order_pending_eth, setup_eth_escrow) -> Order:
    """ Creates an ETH order with escrow details set up (PENDING_PAYMENT). """
    # Assumes setup involves setting a contract address
    return setup_eth_escrow(order_pending_eth, MOCK_ETH_CONTRACT_ADDRESS)

# Adapt confirm_payment for ETH
@pytest.fixture
def confirm_eth_payment(db) -> Callable[[Order, str, int], Order]:
    """ Helper fixture to simulate confirming ETH payment. """
    def _confirm_eth_payment(order: Order, tx_hash: str, confirmations_received: int) -> Order:
        if order.selected_currency != 'ETH': pytest.fail("confirm_eth_payment called on non-ETH order.")
        now = timezone.now()
        try:
            payment = CryptoPayment.objects.get(order=order, currency='ETH')
        except CryptoPayment.DoesNotExist:
            pytest.fail(f"CryptoPayment (ETH) not found for Order {order.id}.")

        payment.refresh_from_db()
        if payment.expected_amount_native is None or payment.expected_amount_native <= Decimal('0'):
            pytest.fail(f"CryptoPayment {payment.id} has invalid expected_amount_native (Wei).")

        payment.received_amount_native = payment.expected_amount_native # Assume full payment in Wei
        payment.transaction_hash = tx_hash
        payment.is_confirmed = True
        payment.confirmations_received = confirmations_received
        payment.save(update_fields=['received_amount_native', 'transaction_hash', 'is_confirmed', 'confirmations_received', 'updated_at'])

        order.status = OrderStatusChoices.PAYMENT_CONFIRMED
        order.paid_at = now
        order.save(update_fields=['status', 'paid_at', 'updated_at'])
        order.refresh_from_db()
        return order
    return _confirm_eth_payment

@pytest.fixture
def order_payment_confirmed_eth(order_escrow_created_eth, confirm_eth_payment, mock_settings_eth_escrow) -> Order:
    """ Creates an ETH order confirmed with sufficient confirmations. """
    return confirm_eth_payment(order_escrow_created_eth, MOCK_TX_HASH_ETH, mock_settings_eth_escrow.ETHEREUM_CONFIRMATIONS_NEEDED + 5)

# Adapt mark_shipped for ETH (might involve preparing a specific contract call)
@pytest.fixture
def mark_eth_shipped(db, mock_settings_eth_escrow, global_settings_eth) -> Callable[[Order, Dict], Order]:
    """ Helper fixture to simulate marking an ETH order as shipped. """
    # !!! IMPLEMENTATION NEEDED: Adapt based on ETH release mechanism (e.g., preparing contract call data) !!!
    try:
        # Ensure these helpers exist and are importable
        from store.services.common_escrow_utils import _get_currency_precision, _get_withdrawal_address
    except ImportError: pytest.fail("Could not import helpers in mark_eth_shipped.")

    def _mark_eth_shipped(order: Order, unsigned_release_data: Dict) -> Order: # Data might be a dict for ETH tx
        if order.selected_currency != 'ETH': pytest.fail("mark_eth_shipped called on non-ETH order.")
        now = timezone.now()
        order.refresh_from_db()
        if order.status != OrderStatusChoices.PAYMENT_CONFIRMED:
            pytest.fail(f"mark_eth_shipped called on order with status {order.status}, expected PAYMENT_CONFIRMED.")
        if not order.vendor: pytest.fail("Order missing vendor.")
        if not order.total_price_native_selected or order.total_price_native_selected <= Decimal('0'):
            pytest.fail("Order missing valid total price.")

        # Calculate payout/fee (ETH specific)
        fee_percent = getattr(global_settings_eth, 'market_fee_percentage_eth', Decimal('0.0')) # Use actual attr name
        decimals = 18 # Wei
        total_atomic = order.total_price_native_selected

        # Ensure fee_percent is valid Decimal
        if not isinstance(fee_percent, Decimal):
            try: fee_percent = Decimal(str(fee_percent))
            except: fee_percent = Decimal('0.0')
        fee_percent = max(Decimal('0.0'), min(Decimal('100.0'), fee_percent))

        # Use Decimal for all calculations
        market_fee_atomic = (total_atomic * fee_percent / Decimal(100)).quantize(Decimal('1'), rounding=ROUND_DOWN)
        market_fee_atomic = max(Decimal('0'), min(total_atomic, market_fee_atomic))
        payout_atomic = total_atomic - market_fee_atomic

        # Convert to standard units (ETH) for metadata display if needed
        payout_std = from_atomic(payout_atomic, decimals)
        fee_std = from_atomic(market_fee_atomic, decimals)

        try: vendor_payout_address = _get_withdrawal_address(order.vendor, 'ETH')
        except ValueError as e: pytest.fail(f"Vendor missing ETH withdrawal address: {e}")

        release_type = 'eth_multisig_tx_params' # Match type used in skeleton service

        # Construct release metadata (adapt structure for ETH)
        release_metadata = {
            'type': release_type,
            'data': unsigned_release_data, # Assume this comes from fixture call
            'payout': str(payout_std), # Store STANDARD ETH as string
            'fee': str(fee_std),      # Store STANDARD ETH as string
            'vendor_address': vendor_payout_address,
            'ready_for_broadcast': False, # Needs signing/interaction
            'signatures': {}, # Store signatures keyed by signer's ETH address
            'prepared_at': now.isoformat()
        }

        # Update order fields
        order.status = OrderStatusChoices.SHIPPED
        order.shipped_at = now
        order.dispute_deadline = now + datetime.timedelta(days=mock_settings_eth_escrow.ORDER_DISPUTE_WINDOW_DAYS)
        order.auto_finalize_deadline = now + datetime.timedelta(days=mock_settings_eth_escrow.ORDER_FINALIZE_TIMEOUT_DAYS)
        order.release_initiated = True
        order.release_metadata = release_metadata
        update_fields = ['status', 'shipped_at', 'dispute_deadline', 'auto_finalize_deadline', 'release_initiated', 'release_metadata', 'updated_at']
        order.save(update_fields=update_fields)
        order.refresh_from_db()
        return order
    return _mark_eth_shipped

@pytest.fixture
def order_shipped_eth(order_payment_confirmed_eth, mark_eth_shipped) -> Order:
    """ Creates an ETH order marked as shipped. """
    # Pass example unsigned data (adapt structure as needed)
    unsigned_data = MOCK_UNSIGNED_TX_ETH # Use constant defined earlier
    return mark_eth_shipped(order_payment_confirmed_eth, unsigned_data)

# Adapt mark_signed for ETH (might involve signing tx data or interacting with contract)
@pytest.fixture
def mark_eth_signed(db, mock_settings_eth_escrow) -> Callable[[Order, DjangoUser, Any, Optional[bool]], Order]:
    """ Helper fixture to simulate applying a signature/interaction for ETH release. """
    # !!! IMPLEMENTATION NEEDED: Adapt based on ETH signing/release mechanism !!!
    def _mark_eth_signed(order: Order, user: DjangoUser, signed_data: Any, is_final_override: Optional[bool] = None) -> Order:
        if order.selected_currency != 'ETH': pytest.fail("mark_eth_signed called on non-ETH order.")
        metadata = order.release_metadata if isinstance(order.release_metadata, dict) else {}
        if not metadata: pytest.fail("Cannot mark signed: Order release metadata missing.")

        metadata['data'] = signed_data # Update with signed tx or updated contract state info
        if 'signatures' not in metadata or not isinstance(metadata['signatures'], dict): metadata['signatures'] = {}

        # Use ETH address as key
        user_eth_address_attr = ATTR_ETH_OWNER_ADDRESS_NAME
        user_eth_address = getattr(user, user_eth_address_attr, None)
        if not user_eth_address: pytest.fail(f"Signing user {user.username} missing '{user_eth_address_attr}'.")

        metadata['signatures'][user_eth_address] = {'signed_at': timezone.now().isoformat(), 'signer': user.username, 'sig_data': signed_data} # Store the signature data

        required_sigs_or_steps = mock_settings_eth_escrow.MULTISIG_SIGNATURES_REQUIRED # Use setting
        is_complete = is_final_override if is_final_override is not None else (len(metadata['signatures']) >= required_sigs_or_steps)
        metadata['ready_for_broadcast'] = is_complete
        metadata['last_signed_at'] = timezone.now().isoformat() # Add timestamp

        # Update type if final (specific to ETH)
        # if is_complete: metadata['type'] = 'eth_signed_tx' # Or 'eth_contract_ready' etc.

        order.release_metadata = metadata
        order.save(update_fields=['release_metadata', 'updated_at'])
        order.refresh_from_db()
        if order.release_metadata is None or not isinstance(order.release_metadata, dict):
            raise AssertionError("Fixture FAIL (mark_eth_signed): Invalid metadata after save.")
        return order
    return _mark_eth_signed

# Fixtures for signed states - adapt based on actual ETH flow
@pytest.fixture
def order_buyer_signed_eth(order_shipped_eth, mark_eth_signed, buyer_user_eth) -> Order:
    """ Creates an ETH order signed by the buyer only (example). """
    signed_order = mark_eth_signed(order_shipped_eth, buyer_user_eth, MOCK_SIGNED_TX_ETH_BUYER, is_final_override=False)
    if not (signed_order.release_metadata and isinstance(signed_order.release_metadata, dict)):
        raise AssertionError("Fixture FAIL (order_buyer_signed_eth): Invalid metadata.")
    if len(signed_order.release_metadata.get('signatures', {})) != 1:
        raise AssertionError("Fixture FAIL (order_buyer_signed_eth): Incorrect signature count.")
    return signed_order

@pytest.fixture
def order_ready_for_broadcast_eth(order_buyer_signed_eth, mark_eth_signed, vendor_user_eth) -> Order:
    """ Creates an ETH order ready for broadcast/finalization (example). """
    # This might involve a second signature or just one party triggering a contract function
    ready_order = mark_eth_signed(order_buyer_signed_eth, vendor_user_eth, MOCK_FINAL_TX_ETH, is_final_override=True)
    if not (ready_order.release_metadata and isinstance(ready_order.release_metadata, dict)):
        raise AssertionError("Fixture FAIL (order_ready_for_broadcast_eth): Invalid metadata.")
    if ready_order.release_metadata.get('ready_for_broadcast') is not True:
        raise AssertionError("Fixture FAIL (order_ready_for_broadcast_eth): Not marked ready.")
    if len(ready_order.release_metadata.get('signatures', {})) != 2: # Assuming 2 sigs needed
        raise AssertionError("Fixture FAIL (order_ready_for_broadcast_eth): Incorrect signature count.")
    return ready_order

# Use generic mark_disputed fixture (assuming it exists in conftest or elsewhere)
@pytest.fixture
def mark_disputed(db) -> Callable[[Order], Order]:
    """Generic helper to mark an order as disputed."""
    def _mark_disputed(order: Order) -> Order:
        order.status = OrderStatusChoices.DISPUTED
        order.disputed_at = timezone.now()
        # Ensure Dispute object exists for the order
        Dispute.objects.get_or_create(order=order, defaults={'status': Dispute.StatusChoices.OPEN})
        order.save(update_fields=['status', 'disputed_at', 'updated_at'])
        order.refresh_from_db()
        return order
    return _mark_disputed


@pytest.fixture
def order_disputed_eth(order_shipped_eth, mark_disputed) -> Order:
    """ Creates an ETH order marked as disputed. """
    disputed_order = mark_disputed(order_shipped_eth)
    disputed_order.refresh_from_db()
    if disputed_order.status != OrderStatusChoices.DISPUTED:
        raise AssertionError("Fixture Validation FAIL (order_disputed_eth): Status not DISPUTED.")
    if disputed_order.total_price_native_selected is None or not (disputed_order.total_price_native_selected > Decimal('0')):
        raise AssertionError("Fixture Validation FAIL (order_disputed_eth): Invalid price after dispute.")
    return disputed_order


# --- Test Class ---

@pytest.mark.django_db(transaction=True) # Use transactions for tests involving multiple saves
@pytest.mark.usefixtures("db", "mock_settings_eth_escrow", "global_settings_eth", "market_user_eth")
class TestEthereumEscrowService:
    """ Test suite for the store.services.ethereum_escrow_service module. (SKELETON) """

    def setup_method(self, method):
        """ Reset market user cache if it exists in common_escrow_utils. """
        # Check the actual location of get_market_user cache if used
        if hasattr(common_escrow_utils, 'get_market_user'):
             if hasattr(common_escrow_utils.get_market_user, 'cache_clear'):
                 common_escrow_utils.get_market_user.cache_clear()


    # === Test ETH Escrow Creation ===
    # Patch the assumed function in ethereum_service that creates the contract
    @patch('store.services.ethereum_escrow_service.ethereum_service.create_eth_multisig_contract', create=True)
    # FIX (Rev 3): Patch create_notification where it's looked up (in the service module)
    @patch('store.services.ethereum_escrow_service.create_notification')
    @patch('store.services.ethereum_escrow_service.get_market_user')
    def test_create_escrow_eth_success(self, mock_get_mkt_user, mock_notify, mock_create_contract, order_pending_eth, market_user_eth, buyer_user_eth, vendor_user_eth):
        """ Test successful creation of ETH escrow (contract deployment). """
        order = order_pending_eth
        mock_get_mkt_user.return_value = market_user_eth # Ensure helper returns correct user
        # Mock contract deployment result
        mock_create_contract.return_value = {'contract_address': MOCK_ETH_CONTRACT_ADDRESS, 'tx_hash': '0xDEPLOY_HASH...'}

        # Call via the common dispatcher
        common_escrow_utils.create_escrow_for_order(order)

        # --- Assertions ---
        order.refresh_from_db()
        assert order.status == OrderStatusChoices.PENDING_PAYMENT
        eth_addr_attr = ATTR_ETH_ESCROW_ADDRESS_NAME
        assert getattr(order, eth_addr_attr, None) == MOCK_ETH_CONTRACT_ADDRESS
        assert order.payment_deadline is not None
        assert order.payment_deadline > timezone.now()
        try:
            payment = CryptoPayment.objects.get(order=order, currency='ETH')
            assert payment.payment_address == MOCK_ETH_CONTRACT_ADDRESS
            assert payment.expected_amount_native == order.total_price_native_selected
        except CryptoPayment.DoesNotExist:
            pytest.fail("CryptoPayment record for ETH was not created.")
        mock_create_contract.assert_called_once()
        call_args, call_kwargs = mock_create_contract.call_args
        owner_arg_name = 'owner_addresses'
        assert owner_arg_name in call_kwargs
        owner_addresses_passed = call_kwargs[owner_arg_name]
        assert MOCK_BUYER_ETH_OWNER_ADDR in owner_addresses_passed
        assert MOCK_VENDOR_ETH_OWNER_ADDR in owner_addresses_passed
        assert MOCK_MARKET_ETH_OWNER_ADDR in owner_addresses_passed
        assert len(owner_addresses_passed) == 3
        assert call_kwargs.get('threshold') == 2


    @patch('store.services.ethereum_escrow_service.ethereum_service.create_eth_multisig_contract', side_effect=CryptoProcessingError("ETH Deploy Failed"), create=True)
    @patch('store.services.ethereum_escrow_service.get_market_user')
    def test_create_escrow_eth_crypto_fail(self, mock_get_mkt_user, mock_create_contract, order_pending_eth, buyer_user_eth, vendor_user_eth, market_user_eth):
        """ Test create_escrow handles crypto service failure (ETH). """
        mock_get_mkt_user.return_value = market_user_eth

        order = order_pending_eth
        initial_status = order.status

        # FIX (Gemini Rev 1): Updated match string
        with pytest.raises(CryptoProcessingError, match="Failed to generate ETH escrow details: ETH Deploy Failed"):
             common_escrow_utils.create_escrow_for_order(order)

        # Assert order state unchanged
        order.refresh_from_db()
        assert order.status == initial_status
        eth_addr_attr = ATTR_ETH_ESCROW_ADDRESS_NAME
        assert getattr(order, eth_addr_attr, None) is None
        assert not CryptoPayment.objects.filter(order=order, currency='ETH').exists()
        mock_create_contract.assert_called_once() # Verify the mock service call was attempted


    # === Placeholder Tests (Unchanged) ===
    # !!! IMPLEMENTATION NEEDED !!!
    # @patch('store.services.ethereum_escrow_service.ethereum_service.check_eth_multisig_deposit')
    # @patch('store.services.ethereum_escrow_service.ledger_service.lock_funds')
    # # ... other patches ...
    # def test_check_confirm_eth_success(self, mock_lock_funds, mock_check_deposit, order_escrow_created_eth, ...):
    #    payment = CryptoPayment.objects.get(...)
    #    mock_check_deposit.return_value = (True, payment.expected_amount_native, MOCK_ETH_TX_HASH)
    #    mock_lock_funds.return_value = True
    #    confirmed = common_escrow_utils.check_payment_confirmation(payment.id)
    #    assert confirmed is True
    #    # ... other assertions ...


# Note: Ensure ETHEREUM_SERVICE_APP_LABEL and COMMON_ESCROW_UTILS_APP_LABEL are correctly defined
# in the service_under_test module or replace with the actual import path string. Example:
# ETHEREUM_SERVICE_APP_LABEL = 'ethereum_service' # If it's a sibling service
# COMMON_ESCROW_UTILS_APP_LABEL = 'common_escrow_utils'
# LEDGER_SERVICE_APP_LABEL = 'ledger_service'

# If they are imported directly, use the module path:
# e.g. @patch('store.services.ethereum_service.check_eth_multisig_deposit')

# === Test Placeholders / Future Work ===
# Add tests for ETH-specific contract interactions
# Add tests for gas handling, event listening (if applicable)
# Add tests for ETH edge cases

# <<< END OF FILE: backend/store/tests/test_ethereum_escrow_service.py >>>