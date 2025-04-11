# backend/withdraw/tests/test_withdraw_service.py
# <<< ENTERPRISE GRADE REVISION: v1.2.0 - Refactor Imports & Fixes >>>
# Revision History:
# - v1.2.0 (2025-04-09) (Gemini):
#   - FIXED: Corrected import for `_get_currency_precision` to point to `common_escrow_utils`.
#   - REMOVED: Unnecessary custom try/except ImportError handling around the helper import.
#   - REMOVED: Related CRITICAL stderr print statement.
# - v1.1.0 (2025-04-08):
#   - FIXED: Replaced all `assert` statements with explicit checks for Bandit B101. Split compound lines.
# - v1.0.0 (2025-04-06): Initial creation and tests for ledger interactions.

import pytest
from decimal import Decimal, ROUND_DOWN
from unittest.mock import patch, MagicMock, ANY, call
from django.db import transaction
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.utils import timezone
import logging

# Local Imports
from withdraw import services as withdraw_service
from withdraw.models import WithdrawalRequest, WithdrawalStatusChoices # Assuming WithdrawalStatusChoices exists
from withdraw.exceptions import WithdrawalError
from ledger.models import UserBalance, LedgerTransaction
from ledger import services as ledger_service
from ledger.services import InsufficientFundsError, InvalidLedgerOperationError # Assuming this exists
from ledger.exceptions import LedgerError
from store.exceptions import CryptoProcessingError # Assuming crypto errors live here

# FIX v1.2.0: Import helper from common_escrow_utils
from store.services import common_escrow_utils

# Import specific crypto services only if needed for mocks, not for direct calls from tests
from store.services import bitcoin_service, monero_service
# Import notification service if used
from notifications import services as notification_service # Assumed import path

User = get_user_model()

# --- Constants ---
TEST_USER_PK = 9001; SITE_OWNER_PK = 9002
BTC_ADDR = "tb1qwdrawtestaddrbtc9876543210fedcba"; XMR_ADDR = "4withdrawtestaddrxmr9876543210fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210fed"
MOCK_TX_HASH_WITHDRAW = "withdraw_tx_hash_" + "w" * 50

# --- Fixtures ---
@pytest.fixture
def mock_settings_withdraw(settings):
    settings.SITE_OWNER_USERNAME = "site_owner_withdraw_test"
    settings.WITHDRAWAL_FEE_PERCENTAGE = Decimal('5.0') # Test with 5% fee
    yield settings

@pytest.fixture
def site_owner_user(db, mock_settings_withdraw):
    user, _ = User.objects.get_or_create(pk=SITE_OWNER_PK, defaults={'username': mock_settings_withdraw.SITE_OWNER_USERNAME, 'is_staff': True})
    UserBalance.objects.get_or_create(user=user, currency='BTC', defaults={'balance': Decimal('1000.0')})
    UserBalance.objects.get_or_create(user=user, currency='XMR', defaults={'balance': Decimal('10000.0')})
    return user

@pytest.fixture
def test_user_withdraw(db):
    user, _ = User.objects.get_or_create(pk=TEST_USER_PK, defaults={'username': 'test_user_withdraw'})
    UserBalance.objects.get_or_create(user=user, currency='BTC', defaults={'balance': Decimal('1.0')})
    UserBalance.objects.get_or_create(user=user, currency='XMR', defaults={'balance': Decimal('20.0')})
    user.btc_withdrawal_address = BTC_ADDR # Example
    user.xmr_withdrawal_address = XMR_ADDR # Example
    user.save()
    return user

# --- Test Class ---
@pytest.mark.django_db(transaction=True)
class TestWithdrawService:

    def setup_method(self, method):
        """ Reset site owner cache before each test. """
        # Access cache via the imported service module name
        if hasattr(withdraw_service, '_site_owner_user_cache'):
            withdraw_service._site_owner_user_cache = None

    def test_get_site_owner_user_success(self, site_owner_user):
        """ Test retrieving the site owner user successfully. """
        owner = withdraw_service._get_site_owner_user()
        if owner != site_owner_user:
            raise AssertionError(f"Retrieved owner {owner} != fixture {site_owner_user}")
        # Test caching
        owner_cached = withdraw_service._get_site_owner_user()
        if owner_cached != owner:
            raise AssertionError(f"Cached owner {owner_cached} != first retrieved {owner}")

    # Test helper function indirectly via main service call tests

    @patch('withdraw.services._get_site_owner_user') # Mock helper in withdraw.services
    @patch('ledger.services.debit_funds')
    @patch('ledger.services.credit_funds')
    @patch('withdraw.services._get_crypto_service') # Mock the crypto service getter in withdraw.services
    @patch('notifications.services.create_notification') # Mock notifications
    def test_request_withdrawal_btc_success(self, mock_create_notification, mock_get_crypto_svc, mock_ledger_credit, mock_ledger_debit, mock_get_owner, test_user_withdraw, site_owner_user, mock_settings_withdraw):
        """ Test successful BTC withdrawal request including broadcast. """
        mock_get_owner.return_value = site_owner_user
        amount = Decimal('0.5'); currency = 'BTC'; fee_perc = Decimal('5.0')
        # FIX v1.2.0: Use imported helper
        precision = common_escrow_utils._get_currency_precision(currency)
        quantizer = Decimal(f'1e-{precision}')
        amount = amount.quantize(quantizer, rounding=ROUND_DOWN) # Apply precision early if service expects it
        expected_fee = (amount * fee_perc / 100).quantize(quantizer, rounding=ROUND_DOWN)
        expected_net = (amount - expected_fee).quantize(quantizer, rounding=ROUND_DOWN)

        # Mock the crypto service returned by the getter
        mock_btc_service = MagicMock()
        mock_btc_service.send_to_address.return_value = MOCK_TX_HASH_WITHDRAW
        mock_get_crypto_svc.return_value = mock_btc_service

        # Call the service function
        withdrawal_request = withdraw_service.request_withdrawal(
            user=test_user_withdraw, currency=currency, amount_standard=amount, withdrawal_address=BTC_ADDR
        )

        if withdrawal_request is None: raise AssertionError("withdrawal_request is None")
        if withdrawal_request.user != test_user_withdraw: raise AssertionError("User mismatch")
        if withdrawal_request.currency != currency: raise AssertionError("Currency mismatch")
        # Compare quantized amount if service applies it early
        if withdrawal_request.requested_amount != amount: raise AssertionError("Requested amount mismatch")
        if withdrawal_request.fee_percentage != fee_perc: raise AssertionError("Fee percentage mismatch")
        if withdrawal_request.fee_amount != expected_fee: raise AssertionError("Fee amount mismatch")
        if withdrawal_request.net_amount != expected_net: raise AssertionError("Net amount mismatch")
        if withdrawal_request.withdrawal_address != BTC_ADDR: raise AssertionError("Address mismatch")
        if withdrawal_request.status != WithdrawalStatusChoices.COMPLETED: raise AssertionError(f"Status mismatch: {withdrawal_request.status}")
        if withdrawal_request.broadcast_tx_hash != MOCK_TX_HASH_WITHDRAW: raise AssertionError("TX Hash mismatch")
        if withdrawal_request.processed_at is None: raise AssertionError("Processed_at not set")

        # Assert ledger calls
        mock_ledger_debit.assert_called_once_with(
            user=test_user_withdraw, currency=currency, amount=amount, # Use quantized amount
            transaction_type=withdraw_service.LEDGER_TX_WITHDRAWAL_DEBIT,
            related_withdrawal=withdrawal_request, notes=ANY
        )
        if expected_fee > 0:
            mock_ledger_credit.assert_called_once_with(
                user=site_owner_user, currency=currency, amount=expected_fee,
                transaction_type=withdraw_service.LEDGER_TX_WITHDRAWAL_FEE,
                related_withdrawal=withdrawal_request, notes=ANY
            )
        else:
            mock_ledger_credit.assert_not_called()

        # Assert crypto service call
        mock_get_crypto_svc.assert_called_once_with(currency)
        mock_btc_service.send_to_address.assert_called_once_with(
             currency=currency, amount_standard=expected_net, address=BTC_ADDR
        )
        # Assert notification preparation (actual call depends on on_commit trigger)
        # Check if create_notification was prepared to be called
        # In a real test environment, you might need to mock transaction.on_commit

    # Example: Insufficient Funds
    @patch('withdraw.services._get_site_owner_user')
    @patch('ledger.services.debit_funds')
    def test_request_withdrawal_insufficient_funds(self, mock_ledger_debit, mock_get_owner, test_user_withdraw, site_owner_user):
        """ Test withdrawal fails cleanly if user balance is too low. """
        mock_get_owner.return_value = site_owner_user
        amount = Decimal('10.0'); currency = 'BTC' # User only has 1.0 BTC

        with pytest.raises(InsufficientFundsError, match="Insufficient available balance.*"):
            withdraw_service.request_withdrawal(
                user=test_user_withdraw, currency=currency, amount_standard=amount, withdrawal_address=BTC_ADDR
            )

        if WithdrawalRequest.objects.filter(user=test_user_withdraw, currency=currency, requested_amount=amount).exists():
            raise AssertionError("WithdrawalRequest should not be created on insufficient funds.")
        mock_ledger_debit.assert_not_called()

    # Example: Crypto Broadcast Failure
    @patch('withdraw.services._get_site_owner_user')
    @patch('ledger.services.debit_funds')
    @patch('ledger.services.credit_funds')
    @patch('withdraw.services._get_crypto_service')
    @patch('notifications.services.create_notification')
    def test_request_withdrawal_broadcast_fail(self, mock_create_notification, mock_get_crypto_svc, mock_ledger_credit, mock_ledger_debit, mock_get_owner, test_user_withdraw, site_owner_user, mock_settings_withdraw):
        """ Test withdrawal fails if crypto broadcast returns error. """
        mock_get_owner.return_value = site_owner_user
        amount = Decimal('0.1'); currency = 'BTC'
        # Quantize amount if service expects it early
        precision = common_escrow_utils._get_currency_precision(currency)
        quantizer = Decimal(f'1e-{precision}')
        amount = amount.quantize(quantizer, rounding=ROUND_DOWN)

        mock_btc_service = MagicMock()
        broadcast_error_msg = "RPC Timeout during broadcast"
        mock_btc_service.send_to_address.side_effect = CryptoProcessingError(broadcast_error_msg)
        mock_get_crypto_svc.return_value = mock_btc_service

        with pytest.raises(CryptoProcessingError, match=broadcast_error_msg):
             withdraw_service.request_withdrawal(
                 user=test_user_withdraw, currency=currency, amount_standard=amount, withdrawal_address=BTC_ADDR
             )

        pending_or_complete = WithdrawalRequest.objects.filter(
             user=test_user_withdraw, currency=currency, requested_amount=amount
        ).exclude(status=WithdrawalStatusChoices.FAILED).exists()

        if pending_or_complete:
             raise AssertionError("WithdrawalRequest should not be PENDING or COMPLETED after broadcast failure.")

        mock_ledger_debit.assert_called()
        if (amount * mock_settings_withdraw.WITHDRAWAL_FEE_PERCENTAGE / 100) > 0:
             mock_ledger_credit.assert_called()
        # Check balances reverted (fetch initial balance first for accurate check)
        initial_balance = Decimal('1.0') # From fixture
        final_balance = UserBalance.objects.get(user=test_user_withdraw, currency=currency).balance
        if final_balance != initial_balance:
            raise AssertionError(f"User balance {final_balance} did not revert to initial state {initial_balance}.")

# <<< END OF FILE: backend/withdraw/tests/test_withdraw_service.py >>>