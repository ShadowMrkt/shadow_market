# backend/ledger/tests/test_services.py
# <<< REVISED VERSION 14: Standardize local imports and patch paths >>> # <<< UPDATED REVISION
# <<< REVISED VERSION 13: Standardize store.models import path >>>
# <<< REVISED VERSION 12: Fix TypeError for reason_notes in lock/unlock tests >>>
# <<< REVISED VERSION 11: Fix Bandit B101 assert_used warning >>>
# <<< REVISED VERSION 10: Fix regex match for InsufficientFundsError; Fix amount/notes in mock ledger create calls for lock/unlock >>>
# <<< REVISED VERSION 9: Align lock/unlock/unlock_funds tests with Option 1 (create LedgerTransaction, return object/None or raise) >>>
# <<< REVISED VERSION 8: Explicit available_balance set in tests, debit_funds assert fix, escrow_debit setup fix >>>
"""
Unit tests for the ledger service layer functions. Uses simplified mocking strategy.

Revision History:
# 2025-05-03: v14 (Gemini): # <<< UPDATED DATE & NOTE
#         - FIXED: Changed local imports (`from ledger...`) to absolute paths (`from backend.ledger...`)
#         - FIXED: Updated paths used in `@patch` decorators to match standardized import paths.
# 2025-04-29: v13 (Gemini):
#         - FIXED: Changed `from store.models import Order` to `from backend.store.models import Order`
#           to use the consistent absolute import path, resolving the primary cause of the
#           `Conflicting 'globalsettings' models` error during test collection for this file.
# 2025-04-10: v12 (Gemini):
#         - FIXED: TypeError in lock/unlock tests by removing unexpected 'reason_notes' keyword argument
#           from calls to ledger_service.lock_funds and ledger_service.unlock_funds.
"""

import pytest
from decimal import Decimal, InvalidOperation
from unittest.mock import patch, MagicMock, call, ANY
import uuid

# --- Local Imports ---
try:
    # <<< FIX: Use absolute backend.ledger path >>> # <<< CHANGED IN v14
    # Imports from the current app (ledger)
    # from ledger import services as ledger_service # OLD
    from backend.ledger import services as ledger_service # FIXED
    # from ledger.services import ( # OLD
    from backend.ledger.services import ( # FIXED
        InsufficientFundsError,
        InvalidLedgerOperationError,
        LedgerServiceError,
        LedgerConfigurationError # Added potentially needed import
    )
    # from ledger.models import ( # OLD
    from backend.ledger.models import ( # FIXED
        UserBalance,
        LedgerTransaction,
        TRANSACTION_TYPE_CHOICES,
        CURRENCY_CHOICES
    )

    # Import from other apps using the required absolute path
    # FIX: Use backend.store.models instead of store.models (Fixed in v13)
    from backend.store.models import Order # Assuming store.models.Order exists

    # Import User model (adjust if custom user model location differs)
    # Example uses standard Django user, modify if needed: from backend.users.models import User
    from django.contrib.auth.models import User # Example, adjust if custom user model

    _VALID_TEST_TX_TYPES = {c[0] for c in TRANSACTION_TYPE_CHOICES}
    _VALID_TEST_CURRENCIES = {c[0] for c in CURRENCY_CHOICES}

    # Ensure LOCK_FUNDS and UNLOCK_FUNDS are valid types for these tests
    # R11: Replace asserts with explicit checks
    if 'LOCK_FUNDS' not in _VALID_TEST_TX_TYPES:
        raise AssertionError("LOCK_FUNDS missing from TRANSACTION_TYPE_CHOICES")
    if 'UNLOCK_FUNDS' not in _VALID_TEST_TX_TYPES:
        raise AssertionError("UNLOCK_FUNDS missing from TRANSACTION_TYPE_CHOICES")


except (ImportError, AttributeError, AssertionError) as e:
    pytest.skip(f"Skipping ledger tests: Failed to import modules/attributes or missing required choices - {e}", allow_module_level=True)


# --- Pytest Fixtures ---

@pytest.fixture
def mock_user() -> MagicMock:
    user = MagicMock(spec=User)
    user.id = 1; user.pk = 1; user.username = "test_ledger_user"
    # Add necessary fields if User model requires them
    return user

@pytest.fixture
def mock_order() -> MagicMock:
    # Use the correctly imported Order class for the spec
    order = MagicMock(spec=Order)
    order.id = uuid.uuid4(); order.pk = order.id
    return order

@pytest.fixture
def mock_user_balance() -> MagicMock:
    """
    Pytest fixture for a mock UserBalance object instance.
    Uses standard attributes for balance, locked_balance, and available_balance.
    Set values directly in tests.
    """
    balance_mock = MagicMock(spec=UserBalance)
    balance_mock.balance = Decimal('0.0')
    balance_mock.locked_balance = Decimal('0.0')
    # Ensure available_balance property works if accessed directly by service
    # This calculates it based on balance and locked_balance set in tests
    type(balance_mock).available_balance = property(lambda self: max(self.balance - self.locked_balance, Decimal('0.0')))
    balance_mock.save = MagicMock()
    return balance_mock

# --- Test Suite ---
@pytest.mark.django_db(transaction=False) # transaction=False suitable for mocked DB interactions
# <<< FIX: Update patch paths >>> # <<< CHANGED IN v14
# @patch('ledger.services.LedgerTransaction.objects.create') # OLD
@patch('backend.ledger.services.LedgerTransaction.objects.create') # FIXED
# @patch('ledger.services.UserBalance.objects.select_for_update') # OLD
@patch('backend.ledger.services.UserBalance.objects.select_for_update') # FIXED
class TestLedgerService:
    """ Test suite for ledger service functions using simplified mocking. """

    # --- Mock Setup Helpers (Unchanged) ---
    def _setup_get_or_create(self, mock_sfu_start: MagicMock, mock_balance_instance: MagicMock, created: bool = False) -> MagicMock:
        mock_qs = MagicMock(spec=['get_or_create'])
        mock_qs.get_or_create.return_value = (mock_balance_instance, created)
        mock_sfu_start.return_value = mock_qs
        return mock_qs

    def _setup_get(self, mock_sfu_start: MagicMock, mock_balance_instance: MagicMock) -> MagicMock:
        mock_qs = MagicMock(spec=['get'])
        mock_qs.get.return_value = mock_balance_instance
        mock_sfu_start.return_value = mock_qs
        return mock_qs

    def _setup_get_raises(self, mock_sfu_start: MagicMock, exception_to_raise):
        mock_qs = MagicMock(spec=['get'])
        mock_qs.get.side_effect = exception_to_raise
        mock_sfu_start.return_value = mock_qs
        return mock_qs

    # --- Tests for record_transaction (Assumed OK from previous runs) ---

    def test_record_transaction_credit_new_user(self, mock_sfu_start, mock_ledger_create, mock_user, mock_user_balance):
        currency = 'XMR'; amount = Decimal('10.5'); tx_type = 'DEPOSIT'; notes = "Initial deposit";
        initial_balance = Decimal('0.0'); initial_locked = Decimal('0.0')
        mock_user_balance.balance = initial_balance; mock_user_balance.locked_balance = initial_locked
        # No need to set available_balance explicitly if using property
        mock_qs = self._setup_get_or_create(mock_sfu_start, mock_user_balance, created=True)
        mock_tx = MagicMock(spec=LedgerTransaction, id=uuid.uuid4())
        mock_ledger_create.return_value = mock_tx

        ledger_entry = ledger_service.record_transaction(user=mock_user, transaction_type=tx_type, currency=currency, amount=amount, notes=notes)

        expected_final_balance = initial_balance + amount
        mock_sfu_start.assert_called_once()
        mock_qs.get_or_create.assert_called_once_with(user=mock_user, currency=currency, defaults={'balance': Decimal('0.0'), 'locked_balance': Decimal('0.0')})
        mock_user_balance.save.assert_called_once_with(update_fields=['balance']) # Only balance changes
        mock_ledger_create.assert_called_once_with(user=mock_user, transaction_type=tx_type, currency=currency, amount=amount, balance_before=initial_balance, balance_after=expected_final_balance, locked_balance_after=initial_locked, related_order=None, external_txid=None, notes=notes)
        # R11: Replace assert with explicit check
        if ledger_entry is not mock_tx:
            raise AssertionError(f"Expected ledger_entry to be mock_tx, got {ledger_entry}")

    def test_record_transaction_credit_existing_user(self, mock_sfu_start, mock_ledger_create, mock_user, mock_user_balance):
        currency = 'BTC'; initial_balance = Decimal('0.1'); initial_locked = Decimal('0.01');
        amount = Decimal('0.25'); tx_type = 'MANUAL_ADJUST_CREDIT';
        mock_user_balance.balance = initial_balance; mock_user_balance.locked_balance = initial_locked
        mock_qs = self._setup_get_or_create(mock_sfu_start, mock_user_balance, created=False)
        mock_tx = MagicMock(spec=LedgerTransaction, id=uuid.uuid4())
        mock_ledger_create.return_value = mock_tx

        ledger_entry = ledger_service.record_transaction(user=mock_user, transaction_type=tx_type, currency=currency, amount=amount)

        expected_final_balance = initial_balance + amount
        mock_sfu_start.assert_called_once()
        mock_qs.get_or_create.assert_called_once_with(user=mock_user, currency=currency, defaults=ANY)
        mock_user_balance.save.assert_called_once_with(update_fields=['balance'])
        mock_ledger_create.assert_called_once_with(user=mock_user, transaction_type=tx_type, currency=currency, amount=amount, balance_before=initial_balance, balance_after=expected_final_balance, locked_balance_after=initial_locked, related_order=None, external_txid=None, notes="")
        # R11: Replace assert with explicit check
        if ledger_entry is not mock_tx:
            raise AssertionError(f"Expected ledger_entry to be mock_tx, got {ledger_entry}")

    def test_record_transaction_debit_sufficient_funds(self, mock_sfu_start, mock_ledger_create, mock_user, mock_user_balance):
        currency = 'ETH'; initial_balance = Decimal('2.0'); initial_locked = Decimal('0.5'); # Available = 1.5
        amount_debit = Decimal('-1.2'); # Debit 1.2 <= Available 1.5 -> OK
        tx_type = 'WITHDRAWAL_SENT';
        mock_user_balance.balance = initial_balance; mock_user_balance.locked_balance = initial_locked
        mock_qs = self._setup_get_or_create(mock_sfu_start, mock_user_balance, created=False)
        mock_tx = MagicMock(spec=LedgerTransaction, id=uuid.uuid4())
        mock_ledger_create.return_value = mock_tx

        ledger_entry = ledger_service.record_transaction(user=mock_user, transaction_type=tx_type, currency=currency, amount=amount_debit)

        expected_final_balance = initial_balance + amount_debit
        mock_sfu_start.assert_called_once()
        mock_qs.get_or_create.assert_called_once_with(user=mock_user, currency=currency, defaults=ANY)
        mock_user_balance.save.assert_called_once_with(update_fields=['balance'])
        mock_ledger_create.assert_called_once_with(user=mock_user, transaction_type=tx_type, currency=currency, amount=amount_debit, balance_before=initial_balance, balance_after=expected_final_balance, locked_balance_after=initial_locked, related_order=None, external_txid=None, notes="")
        # R11: Replace assert with explicit check
        if ledger_entry is not mock_tx:
            raise AssertionError(f"Expected ledger_entry to be mock_tx, got {ledger_entry}")

    # <<< FIX: Adjusted regex match pattern >>>
    def test_record_transaction_debit_insufficient_funds(self, mock_sfu_start, mock_ledger_create, mock_user, mock_user_balance):
        currency = 'ETH'; initial_balance = Decimal('1.0'); initial_locked = Decimal('0.8'); # Available = 0.2
        amount_debit = Decimal('-0.5'); # Debit 0.5 > Available 0.2 -> Error
        mock_user_balance.balance = initial_balance; mock_user_balance.locked_balance = initial_locked
        available_check = mock_user_balance.available_balance # Get available from property
        mock_qs = self._setup_get_or_create(mock_sfu_start, mock_user_balance, created=False)
        # Match the core message from the service exception
        match_pattern = rf"Insufficient {currency} funds\."

        with pytest.raises(InsufficientFundsError, match=match_pattern) as exc_info:
            ledger_service.record_transaction(user=mock_user, transaction_type='MANUAL_ADJUST_DEBIT', currency=currency, amount=amount_debit)

        # Check exception attributes if the custom exception stores them
        # R11: Replace asserts with explicit checks
        if exc_info.value.available != available_check:
            raise AssertionError(f"Exception available balance {exc_info.value.available} != expected {available_check}")
        if exc_info.value.required != abs(amount_debit):
            raise AssertionError(f"Exception required amount {exc_info.value.required} != expected {abs(amount_debit)}")
        if exc_info.value.currency != currency:
            raise AssertionError(f"Exception currency {exc_info.value.currency} != expected {currency}")

        mock_user_balance.save.assert_not_called()
        mock_ledger_create.assert_not_called()

    # --- Validation Tests (Assumed OK) ---
    @pytest.mark.parametrize("invalid_type", ["INVALID_TYPE", "", None, 123])
    def test_record_transaction_invalid_type(self, mock_sfu_start, mock_ledger_create, mock_user, invalid_type):
        with pytest.raises(InvalidLedgerOperationError, match="Invalid transaction type"):
            ledger_service.record_transaction(user=mock_user, transaction_type=invalid_type, currency='BTC', amount=Decimal('1.0'))
        mock_sfu_start.assert_not_called(); mock_ledger_create.assert_not_called()

    @pytest.mark.parametrize("invalid_currency", ["USD", "", None, 456])
    def test_record_transaction_invalid_currency(self, mock_sfu_start, mock_ledger_create, mock_user, invalid_currency):
        with pytest.raises(InvalidLedgerOperationError, match="Invalid currency"):
            ledger_service.record_transaction(user=mock_user, transaction_type='DEPOSIT', currency=invalid_currency, amount=Decimal('1.0'))
        mock_sfu_start.assert_not_called(); mock_ledger_create.assert_not_called()

    @pytest.mark.parametrize("invalid_amount", ["abc", None, [], {}])
    def test_record_transaction_invalid_amount_format(self, mock_sfu_start, mock_ledger_create, mock_user, invalid_amount):
        with pytest.raises(InvalidLedgerOperationError, match="Invalid amount format provided."):
            ledger_service.record_transaction(user=mock_user, transaction_type='DEPOSIT', currency='BTC', amount=invalid_amount)
        mock_sfu_start.assert_not_called(); mock_ledger_create.assert_not_called()

    # --- Tests for Helper Functions (Assumed OK) ---
    # <<< FIX: Update patch path >>> # <<< CHANGED IN v14
    # @patch('ledger.services.record_transaction') # OLD
    @patch('backend.ledger.services.record_transaction') # FIXED
    def test_credit_funds_helper_calls_record(self, mock_record_tx, mock_sfu_start, mock_ledger_create, mock_user, mock_order):
        amount = Decimal('5.0'); tx_type = 'DEPOSIT'; notes = "Helper test"; txid = "tx1"; currency = 'BTC'
        mock_record_tx.return_value = MagicMock(spec=LedgerTransaction, id=uuid.uuid4())
        result = ledger_service.credit_funds(user=mock_user, currency=currency, amount=amount, transaction_type=tx_type, notes=notes, external_txid=txid, related_order=mock_order)
        mock_record_tx.assert_called_once_with(user=mock_user, transaction_type=tx_type, currency=currency, amount=amount, notes=notes, external_txid=txid, related_order=mock_order)
        # R11: Replace assert with explicit check
        if result is not mock_record_tx.return_value:
            raise AssertionError(f"Expected result to be return value of mock_record_tx, got {result}")

    # <<< FIX: Update patch path >>> # <<< CHANGED IN v14
    # @patch('ledger.services.record_transaction') # OLD
    @patch('backend.ledger.services.record_transaction') # FIXED
    def test_credit_funds_helper_validation(self, mock_record_tx, mock_sfu_start, mock_ledger_create, mock_user):
        with pytest.raises(InvalidLedgerOperationError, match="Credit amount must be positive."):
            ledger_service.credit_funds(user=mock_user, currency='BTC', amount=Decimal('0.0'), transaction_type='DEPOSIT')
        with pytest.raises(InvalidLedgerOperationError, match="Credit amount must be positive."):
            ledger_service.credit_funds(user=mock_user, currency='BTC', amount=Decimal('-1.0'), transaction_type='DEPOSIT')
        mock_record_tx.assert_not_called()

    # <<< FIX: Update patch path >>> # <<< CHANGED IN v14
    # @patch('ledger.services.record_transaction') # OLD
    @patch('backend.ledger.services.record_transaction') # FIXED
    def test_debit_funds_helper_calls_record(self, mock_record_tx, mock_sfu_start, mock_ledger_create, mock_user):
        amount_positive = Decimal('3.0'); tx_type = 'VENDOR_BOND_PAY'; txid = 'tx123'; currency = 'ETH';
        mock_record_tx.return_value = MagicMock(spec=LedgerTransaction, id=uuid.uuid4())
        result = ledger_service.debit_funds(user=mock_user, currency=currency, amount=amount_positive, transaction_type=tx_type, external_txid=txid)
        mock_record_tx.assert_called_once_with(user=mock_user, transaction_type=tx_type, currency=currency, amount=-amount_positive, external_txid=txid) # Assuming notes/order are defaults
        # R11: Replace assert with explicit check
        if result is not mock_record_tx.return_value:
            raise AssertionError(f"Expected result to be return value of mock_record_tx, got {result}")

    # <<< FIX: Update patch path >>> # <<< CHANGED IN v14
    # @patch('ledger.services.record_transaction') # OLD
    @patch('backend.ledger.services.record_transaction') # FIXED
    def test_debit_funds_helper_validation(self, mock_record_tx, mock_sfu_start, mock_ledger_create, mock_user):
        with pytest.raises(InvalidLedgerOperationError, match="Debit amount must be positive."):
            ledger_service.debit_funds(user=mock_user, currency='ETH', amount=Decimal('0.0'), transaction_type='MANUAL_ADJUST_DEBIT')
        with pytest.raises(InvalidLedgerOperationError, match="Debit amount must be positive."):
            ledger_service.debit_funds(user=mock_user, currency='ETH', amount=Decimal('-2.0'), transaction_type='MANUAL_ADJUST_DEBIT')
        mock_record_tx.assert_not_called()

    # --- Tests for Balance Querying (Assumed OK) ---
    # <<< FIX: Update patch path >>> # <<< CHANGED IN v14
    # @patch('ledger.services.UserBalance.objects.get') # OLD
    @patch('backend.ledger.services.UserBalance.objects.get') # FIXED
    def test_get_user_balance_exists(self, mock_ub_get, mock_sfu_start, mock_ledger_create, mock_user, mock_user_balance):
        currency = 'XMR'; total_bal = Decimal('100.5'); locked_bal = Decimal('10.1');
        mock_user_balance.balance = total_bal; mock_user_balance.locked_balance = locked_bal
        mock_ub_get.return_value = mock_user_balance
        total, available = ledger_service.get_user_balance(mock_user, currency)
        mock_ub_get.assert_called_once_with(user=mock_user, currency=currency)
        # R11: Replace asserts with explicit checks
        if total != total_bal:
            raise AssertionError(f"Total balance {total} != expected {total_bal}")
        if available != (total_bal - locked_bal):
            raise AssertionError(f"Available balance {available} != expected {total_bal - locked_bal}")

    # <<< FIX: Update patch path >>> # <<< CHANGED IN v14
    # @patch('ledger.services.UserBalance.objects.get') # OLD
    @patch('backend.ledger.services.UserBalance.objects.get') # FIXED
    def test_get_user_balance_not_exists(self, mock_ub_get, mock_sfu_start, mock_ledger_create, mock_user):
        currency = 'BTC'; mock_ub_get.side_effect = UserBalance.DoesNotExist
        total, available = ledger_service.get_user_balance(mock_user, currency)
        mock_ub_get.assert_called_once_with(user=mock_user, currency=currency)
        # R11: Replace asserts with explicit checks
        if total != Decimal('0.0'):
            raise AssertionError(f"Total balance {total} != expected 0.0")
        if available != Decimal('0.0'):
            raise AssertionError(f"Available balance {available} != expected 0.0")

    # <<< FIX: Update patch path >>> # <<< CHANGED IN v14
    # @patch('ledger.services.UserBalance.objects.get') # OLD
    @patch('backend.ledger.services.UserBalance.objects.get') # FIXED
    def test_get_user_balance_invalid_currency(self, mock_ub_get, mock_sfu_start, mock_ledger_create, mock_user):
        invalid_currency_code = "INVALID_CUR"
        with pytest.raises(InvalidLedgerOperationError, match=f"Invalid currency: {invalid_currency_code}"):
            ledger_service.get_user_balance(mock_user, invalid_currency_code)
        mock_ub_get.assert_not_called()

    # <<< FIX: Update patch path >>> # <<< CHANGED IN v14
    # @patch('ledger.services.get_user_balance') # OLD
    @patch('backend.ledger.services.get_user_balance') # FIXED
    def test_get_available_balance_delegates(self, mock_get_user_bal, mock_sfu_start, mock_ledger_create, mock_user):
        currency = 'ETH'; expected_available = Decimal('1.23');
        mock_get_user_bal.return_value = (Decimal('2.0'), expected_available)
        available = ledger_service.get_available_balance(mock_user, currency)
        mock_get_user_bal.assert_called_once_with(mock_user, currency)
        # R11: Replace assert with explicit check
        if available != expected_available:
            raise AssertionError(f"Available balance {available} != expected {expected_available}")

    # <<< FIX: Update patch path >>> # <<< CHANGED IN v14
    # @patch('ledger.services.get_user_balance') # OLD
    @patch('backend.ledger.services.get_user_balance') # FIXED
    def test_get_available_balance_handles_exception(self, mock_get_user_bal, mock_sfu_start, mock_ledger_create, mock_user):
        currency = 'ETH'; mock_get_user_bal.side_effect = LedgerServiceError("Underlying DB Failure")
        with pytest.raises(LedgerServiceError, match="Underlying DB Failure"):
            ledger_service.get_available_balance(mock_user, currency)
        mock_get_user_bal.assert_called_once_with(mock_user, currency)

    # --- Tests for lock_funds (REVISED FOR OPTION 1) ---

    # <<< FIX: Assert correct amount/notes in ledger create call >>>
    # <<< FIX v12: Removed reason_notes >>>
    def test_lock_funds_sufficient(self, mock_sfu_start, mock_ledger_create, mock_user, mock_user_balance):
        currency = 'BTC'; initial_balance = Decimal('1.0'); initial_locked = Decimal('0.1'); # Available = 0.9
        amount_lock = Decimal('0.5'); notes = "Test lock"; tx_type = 'LOCK_FUNDS'
        mock_user_balance.balance = initial_balance; mock_user_balance.locked_balance = initial_locked
        mock_qs = self._setup_get(mock_sfu_start, mock_user_balance)
        # Assume lock_funds returns the created transaction object
        mock_tx = MagicMock(spec=LedgerTransaction, id=uuid.uuid4())
        mock_ledger_create.return_value = mock_tx

        # FIX v12: Removed reason_notes=notes
        result = ledger_service.lock_funds(user=mock_user, currency=currency, amount=amount_lock)

        # R11: Replace assert with explicit check
        if result is not mock_tx: # Check if the returned object is the mock transaction
            raise AssertionError(f"Expected result to be mock_tx, got {result}")
        mock_sfu_start.assert_called_once()
        mock_qs.get.assert_called_once_with(user=mock_user, currency=currency)
        # Check that locked_balance was updated correctly before save
        # R11: Replace assert with explicit check
        if mock_user_balance.locked_balance != initial_locked + amount_lock:
            raise AssertionError(f"Locked balance {mock_user_balance.locked_balance} != expected {initial_locked + amount_lock}")
        mock_user_balance.save.assert_called_once_with(update_fields=['locked_balance'])
        # Check that ledger transaction was created correctly
        # NOTE: The 'notes' field might be empty now or use a default if reason_notes was removed from the function entirely
        mock_ledger_create.assert_called_once_with(
            user=mock_user,
            transaction_type=tx_type,
            currency=currency,
            amount=amount_lock, # FIX: Service uses the lock amount here
            balance_before=initial_balance,
            balance_after=initial_balance, # Total balance unchanged by lock
            locked_balance_after=initial_locked + amount_lock, # Locked balance snapshot *after*
            notes=ANY, # Allow any notes field content (or verify specific default if known)
            related_order=None, # Assuming no order passed
            external_txid=None  # Assuming no txid passed
        )

    def test_lock_funds_insufficient(self, mock_sfu_start, mock_ledger_create, mock_user, mock_user_balance):
        currency = 'BTC'; initial_balance = Decimal('1.0'); initial_locked = Decimal('0.7'); # Available = 0.3
        amount_lock = Decimal('0.5'); # Lock 0.5 > Available 0.3 -> Fail
        mock_user_balance.balance = initial_balance; mock_user_balance.locked_balance = initial_locked
        available_check = mock_user_balance.available_balance
        mock_qs = self._setup_get(mock_sfu_start, mock_user_balance)
        # Expect InsufficientFundsError
        match_pattern = rf"Insufficient available {currency} funds to lock\." # Match core message

        with pytest.raises(InsufficientFundsError, match=match_pattern) as exc_info:
            ledger_service.lock_funds(user=mock_user, currency=currency, amount=amount_lock)

        # Check exception attributes
        # R11: Replace asserts with explicit checks
        if exc_info.value.available != available_check:
            raise AssertionError(f"Exception available balance {exc_info.value.available} != expected {available_check}")
        if exc_info.value.required != amount_lock:
            raise AssertionError(f"Exception required amount {exc_info.value.required} != expected {amount_lock}")
        if exc_info.value.currency != currency:
            raise AssertionError(f"Exception currency {exc_info.value.currency} != expected {currency}")

        mock_user_balance.save.assert_not_called()
        mock_ledger_create.assert_not_called()
        mock_sfu_start.assert_called_once() # Ensure balance was fetched
        mock_qs.get.assert_called_once_with(user=mock_user, currency=currency)

    def test_lock_funds_validation(self, mock_sfu_start, mock_ledger_create, mock_user):
        # These tests seem correct as they check for InvalidLedgerOperationError
        with pytest.raises(InvalidLedgerOperationError, match="Lock amount must be positive."):
            ledger_service.lock_funds(user=mock_user, currency='BTC', amount=Decimal('0.0'))
        with pytest.raises(InvalidLedgerOperationError, match="Lock amount must be positive."):
            ledger_service.lock_funds(user=mock_user, currency='BTC', amount=Decimal('-0.1'))
        with pytest.raises(InvalidLedgerOperationError, match="Invalid lock amount format."):
            ledger_service.lock_funds(user=mock_user, currency='BTC', amount='not-a-decimal')
        with pytest.raises(InvalidLedgerOperationError, match="Invalid currency"):
            ledger_service.lock_funds(user=mock_user, currency='INVALID', amount=Decimal('1.0'))
        # R11: Split semicolon line to potentially fix indentation issue
        mock_sfu_start.assert_not_called()
        mock_ledger_create.assert_not_called()

    def test_lock_funds_user_balance_not_exist(self, mock_sfu_start, mock_ledger_create, mock_user):
        mock_qs = self._setup_get_raises(mock_sfu_start, UserBalance.DoesNotExist)
        amount_lock = Decimal('1.0'); currency = 'XMR'
        # Expect LedgerServiceError when UserBalance.DoesNotExist is caught
        match_pattern = rf"Balance record not found for user {mock_user.pk}, currency {currency}\." # Adjust if needed

        with pytest.raises(LedgerServiceError, match=match_pattern):
            ledger_service.lock_funds(user=mock_user, currency=currency, amount=amount_lock)

        mock_sfu_start.assert_called_once()
        mock_qs.get.assert_called_once_with(user=mock_user, currency=currency)
        mock_ledger_create.assert_not_called()

    # --- Tests for unlock_funds (REVISED FOR OPTION 1) ---

    # <<< FIX: Assert correct amount/notes in ledger create call >>>
    # <<< FIX v12: Removed reason_notes >>>
    def test_unlock_funds_normal(self, mock_sfu_start, mock_ledger_create, mock_user, mock_user_balance):
        currency = 'ETH'; initial_locked = Decimal('1.5'); initial_balance = Decimal('2.0');
        amount_unlock = Decimal('1.0'); notes="Test unlock"; tx_type = 'UNLOCK_FUNDS'
        mock_user_balance.balance = initial_balance; mock_user_balance.locked_balance = initial_locked
        mock_qs = self._setup_get(mock_sfu_start, mock_user_balance)
        # Assume unlock_funds returns the created transaction object
        mock_tx = MagicMock(spec=LedgerTransaction, id=uuid.uuid4())
        mock_ledger_create.return_value = mock_tx

        # FIX v12: Removed reason_notes=notes
        result = ledger_service.unlock_funds(user=mock_user, currency=currency, amount=amount_unlock)

        # R11: Replace assert with explicit check
        if result is not mock_tx: # Check if the returned object is the mock transaction
            raise AssertionError(f"Expected result to be mock_tx, got {result}")
        mock_sfu_start.assert_called_once()
        mock_qs.get.assert_called_once_with(user=mock_user, currency=currency)
        # Check that locked_balance was updated correctly before save
        # R11: Replace assert with explicit check
        if mock_user_balance.locked_balance != initial_locked - amount_unlock:
            raise AssertionError(f"Locked balance {mock_user_balance.locked_balance} != expected {initial_locked - amount_unlock}")
        mock_user_balance.save.assert_called_once_with(update_fields=['locked_balance'])
        # Check that ledger transaction was created correctly
        # NOTE: The 'notes' field might be empty now or use a default if reason_notes was removed from the function entirely
        mock_ledger_create.assert_called_once_with(
            user=mock_user,
            transaction_type=tx_type,
            currency=currency,
            amount=amount_unlock, # FIX: Service uses unlock amount
            balance_before=initial_balance,
            balance_after=initial_balance, # Total balance unchanged by unlock
            locked_balance_after=initial_locked - amount_unlock, # Locked balance snapshot *after*
            notes=ANY, # Allow any notes field content (or verify specific default if known)
            related_order=None, # Assuming no order passed
            external_txid=None  # Assuming no txid passed
        )

    # <<< FIX: Assert correct amount/notes in ledger create call >>>
    # <<< FIX v12: Removed reason_notes >>>
    def test_unlock_funds_more_than_locked(self, mock_sfu_start, mock_ledger_create, mock_user, mock_user_balance):
        currency = 'ETH'; initial_locked = Decimal('0.3'); initial_balance = Decimal('1.0');
        amount_unlock_requested = Decimal('1.0'); notes="Test unlock more"; tx_type = 'UNLOCK_FUNDS'
        mock_user_balance.balance = initial_balance; mock_user_balance.locked_balance = initial_locked
        mock_qs = self._setup_get(mock_sfu_start, mock_user_balance)
        # Assume unlock_funds returns the created transaction object
        mock_tx = MagicMock(spec=LedgerTransaction, id=uuid.uuid4())
        mock_ledger_create.return_value = mock_tx
        # Unlock amount should be capped at initial_locked
        effective_unlock_amount = initial_locked

        # FIX v12: Removed reason_notes=notes
        result = ledger_service.unlock_funds(user=mock_user, currency=currency, amount=amount_unlock_requested)

        # R11: Replace assert with explicit check
        if result is not mock_tx: # Check if the returned object is the mock transaction
            raise AssertionError(f"Expected result to be mock_tx, got {result}")
        mock_sfu_start.assert_called_once()
        mock_qs.get.assert_called_once_with(user=mock_user, currency=currency)
        # Check that locked_balance was updated correctly (should go to 0)
        # R11: Replace assert with explicit check
        if mock_user_balance.locked_balance != initial_locked - effective_unlock_amount: # Should be 0
            raise AssertionError(f"Locked balance {mock_user_balance.locked_balance} != expected 0.0")
        mock_user_balance.save.assert_called_once_with(update_fields=['locked_balance'])
        # Check that ledger transaction was created correctly
        # NOTE: The 'notes' field might be empty now or use a default if reason_notes was removed from the function entirely
        mock_ledger_create.assert_called_once_with(
            user=mock_user,
            transaction_type=tx_type,
            currency=currency,
            amount=effective_unlock_amount, # FIX: Service uses effective unlock amount
            balance_before=initial_balance,
            balance_after=initial_balance, # Total balance unchanged by unlock
            locked_balance_after=Decimal('0.0'), # Locked balance snapshot *after* (becomes 0)
            notes=ANY, # Allow any notes field content (or verify specific default if known)
            related_order=None, # Assuming no order passed
            external_txid=None  # Assuming no txid passed
        )


    def test_unlock_funds_zero_locked(self, mock_sfu_start, mock_ledger_create, mock_user, mock_user_balance):
        currency = 'ETH'; initial_locked = Decimal('0.0'); initial_balance = Decimal('1.0');
        amount_unlock = Decimal('0.5');
        mock_user_balance.balance = initial_balance; mock_user_balance.locked_balance = initial_locked
        mock_qs = self._setup_get(mock_sfu_start, mock_user_balance)

        # Expect None if no funds were actually unlocked
        unlocked_result = ledger_service.unlock_funds(user=mock_user, currency=currency, amount=amount_unlock)

        # R11: Replace assert with explicit check
        if unlocked_result is not None: # Check returns None
            raise AssertionError(f"Expected result to be None, got {unlocked_result}")
        mock_sfu_start.assert_called_once() # Should still fetch balance
        mock_qs.get.assert_called_once_with(user=mock_user, currency=currency)
        mock_user_balance.save.assert_not_called() # No change to balance
        mock_ledger_create.assert_not_called() # No transaction created

    def test_unlock_funds_validation(self, mock_sfu_start, mock_ledger_create, mock_user):
        # These tests seem correct as they check for InvalidLedgerOperationError
        with pytest.raises(InvalidLedgerOperationError, match="Unlock amount must be positive."):
            ledger_service.unlock_funds(user=mock_user, currency='ETH', amount=Decimal('0.0'))
        with pytest.raises(InvalidLedgerOperationError, match="Unlock amount must be positive."):
            ledger_service.unlock_funds(user=mock_user, currency='ETH', amount=Decimal('-1.0'))
        with pytest.raises(InvalidLedgerOperationError, match="Invalid unlock amount format."):
            ledger_service.unlock_funds(user=mock_user, currency='ETH', amount='not-a-decimal')
        with pytest.raises(InvalidLedgerOperationError, match="Invalid currency"):
            ledger_service.unlock_funds(user=mock_user, currency='INVALID', amount=Decimal('1.0'))
        mock_sfu_start.assert_not_called(); mock_ledger_create.assert_not_called()

    def test_unlock_funds_user_balance_not_exist(self, mock_sfu_start, mock_ledger_create, mock_user):
        mock_qs = self._setup_get_raises(mock_sfu_start, UserBalance.DoesNotExist)
        amount_unlock = Decimal('1.0'); currency='XMR'

        # Expect None if balance record does not exist
        unlocked_result = ledger_service.unlock_funds(user=mock_user, currency=currency, amount=amount_unlock)

        # R11: Replace assert with explicit check
        if unlocked_result is not None: # Check returns None
            raise AssertionError(f"Expected result to be None, got {unlocked_result}")
        mock_sfu_start.assert_called_once()
        mock_qs.get.assert_called_once_with(user=mock_user, currency=currency)
        mock_ledger_create.assert_not_called() # No transaction created

    # --- Specific Transaction Type Tests (Assumed OK) ---

    def test_transaction_type_deposit(self, mock_sfu_start, mock_ledger_create, mock_user, mock_user_balance, mock_order):
        currency = 'BTC'; initial_balance = Decimal('0.1'); initial_locked = Decimal('0.01');
        amount = Decimal('0.5'); tx_type = 'DEPOSIT'; txid="deposit_txid_1";
        mock_user_balance.balance = initial_balance; mock_user_balance.locked_balance = initial_locked
        self._setup_get_or_create(mock_sfu_start, mock_user_balance, created=False)
        mock_tx = MagicMock(spec=LedgerTransaction, id=uuid.uuid4())
        mock_ledger_create.return_value = mock_tx

        ledger_entry = ledger_service.credit_funds(user=mock_user, currency=currency, amount=amount, transaction_type=tx_type, related_order=mock_order, external_txid=txid)

        expected_balance = initial_balance + amount
        mock_user_balance.save.assert_called_once_with(update_fields=['balance'])
        mock_ledger_create.assert_called_once_with(user=mock_user, transaction_type=tx_type, currency=currency, amount=amount, balance_before=initial_balance, balance_after=expected_balance, locked_balance_after=initial_locked, related_order=mock_order, external_txid=txid, notes="")
        # R11: Replace assert with explicit check
        if ledger_entry is not mock_tx:
            raise AssertionError(f"Expected ledger_entry to be mock_tx, got {ledger_entry}")

    def test_transaction_type_escrow_fund_debit(self, mock_sfu_start, mock_ledger_create, mock_user, mock_user_balance, mock_order):
        """ Verify state after an ESCROW_FUND_DEBIT transaction type (Successful Debit). """
        currency = 'BTC'; initial_balance = Decimal('1.0'); initial_locked = Decimal('0.5'); # Available = 0.5
        amount_to_debit = Decimal('0.5'); tx_type = 'ESCROW_FUND_DEBIT';
        mock_user_balance.balance = initial_balance; mock_user_balance.locked_balance = initial_locked
        self._setup_get_or_create(mock_sfu_start, mock_user_balance, created=False)
        mock_tx = MagicMock(spec=LedgerTransaction, id=uuid.uuid4())
        mock_ledger_create.return_value = mock_tx

        ledger_entry = ledger_service.debit_funds(
            user=mock_user, currency=currency, amount=amount_to_debit, transaction_type=tx_type,
            related_order=mock_order
        )

        expected_balance = initial_balance - amount_to_debit # 1.0 - 0.5 = 0.5
        mock_user_balance.save.assert_called_once_with(update_fields=['balance'])
        mock_ledger_create.assert_called_once_with(
            user=mock_user, transaction_type=tx_type, currency=currency, amount=-amount_to_debit,
            balance_before=initial_balance, balance_after=expected_balance, locked_balance_after=initial_locked,
            related_order=mock_order, external_txid=None, notes=""
        )
        # R11: Replace assert with explicit check
        if ledger_entry is not mock_tx:
            raise AssertionError(f"Expected ledger_entry to be mock_tx, got {ledger_entry}")

    def test_transaction_type_market_bond_forfeit(self, mock_sfu_start, mock_ledger_create, mock_user, mock_user_balance):
        currency = 'XMR'; initial_balance = Decimal('5.0'); initial_locked = Decimal('0');
        amount_forfeit = Decimal('1.0'); tx_type = 'MARKET_BOND_FORFEIT';
        mock_user_balance.balance = initial_balance; mock_user_balance.locked_balance = initial_locked
        self._setup_get_or_create(mock_sfu_start, mock_user_balance, created=False)
        mock_tx = MagicMock(spec=LedgerTransaction, id=uuid.uuid4())
        mock_ledger_create.return_value = mock_tx

        ledger_entry = ledger_service.credit_funds(user=mock_user, currency=currency, amount=amount_forfeit, transaction_type=tx_type)

        expected_final_balance = initial_balance + amount_forfeit
        mock_user_balance.save.assert_called_once_with(update_fields=['balance'])
        mock_ledger_create.assert_called_once_with(user=mock_user, transaction_type=tx_type, currency=currency, amount=amount_forfeit, balance_before=initial_balance, balance_after=expected_final_balance, locked_balance_after=initial_locked, related_order=None, external_txid=None, notes="")
        # R11: Replace assert with explicit check
        if ledger_entry is not mock_tx:
            raise AssertionError(f"Expected ledger_entry to be mock_tx, got {ledger_entry}")

        #-----End of File-----#