# backend/store/tests/test_views_tickets.py
# Revision: 1.1
# Date: 2025-05-22
# Author: Gemini
# Description: Contains tests for the API views in views/tickets.py (SupportTicketViewSet, TicketMessageViewSet).
# Changes:
# - Rev 1.1:
#   - Set pgp_public_key to None for test user creations in setUpTestData to comply with
#     stricter PGP validation in models.py (v1.4.2+).
#   - Ensured Category is created for Product.
#   - Added required price fields for Order creation.
#   - Used .value for Enum fields (Currency, Order.StatusChoices, SupportTicket.StatusChoices).
#   - Ensured UUID PKs are passed as strings in data for POST requests.
#   - Clarified mock calls for PGP service when user PGP keys are None.
# - Rev 1.0 (Initial Creation):
#   - Date: 2025-04-29
#   - Author: Gemini
#   - Description: Contains tests for the API views in views/tickets.py (SupportTicketViewSet, TicketMessageViewSet).

# Standard Library Imports
from unittest.mock import patch, MagicMock, ANY
from decimal import Decimal
import json
import uuid # Added for UUIDs

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.conf import settings

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# Local Application Imports
from backend.store.models import (
    SupportTicket, TicketMessage, User as StoreUser, Product, Order, Currency, Category # Added Category
)
# Import permissions for checking
from backend.store.permissions import PGP_AUTH_SESSION_KEY # Corrected from IsTicketRequesterAssigneeOrStaff if it's for session
# Import serializers if needed for asserting response structure
# from backend.store.serializers import SupportTicketListSerializer, SupportTicketDetailSerializer, TicketMessageSerializer

# Mock PGP Service constants if needed, or patch the settings access
MOCK_SUPPORT_FINGERPRINT = "SUPPORT_FINGERPRINT_HERE"
MOCK_SUPPORT_PUBLIC_KEY = "-----BEGIN PGP PUBLIC KEY BLOCK-----\nSUPPORT KEY\n-----END PGP PUBLIC KEY BLOCK-----" # Remains placeholder as service is mocked

# --- Constants ---
User = get_user_model()

# --- Test Cases ---

# Mock services used by the views globally for this test module
@patch('backend.store.views.tickets.notification_service', MagicMock()) # Mock notifications
@patch('backend.store.views.tickets.pgp_service') # Mock the entire PGP service module
@patch('backend.store.views.tickets.log_audit_event', MagicMock()) # Mock audit logging
class TicketViewTests(APITestCase):
    """Tests for SupportTicketViewSet and TicketMessageViewSet."""

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        cls.password = 'strongpassword123'

        # Create users
        cls.user_requester = User.objects.create_user(
            username='ticket_requester', password=cls.password,
            pgp_public_key=None # Set to None
        )
        cls.user_staff = User.objects.create_user(
            username='ticket_staff', password=cls.password, is_staff=True,
            pgp_public_key=None # Set to None (will need handling in tests if key content is "used" by mock)
        )
        cls.user_other_staff = User.objects.create_user(
            username='other_staff', password=cls.password, is_staff=True,
            pgp_public_key=None # Set to None
        )
        cls.user_unrelated = User.objects.create_user(
            username='unrelated_user', password=cls.password,
            pgp_public_key=None # Set to None
        )
        cls.user_no_pgp = User.objects.create_user( # This user intentionally has no PGP key
            username='user_no_pgp', password=cls.password, pgp_public_key='' # Empty string is fine
        )

        # Create a vendor and product/order for linking tests
        cls.vendor = User.objects.create_user(
            username='vendor_ticket', password=cls.password, is_vendor=True,
            pgp_public_key=None # Set to None
        )
        # Create Category first
        cls.category_for_product = Category.objects.create(name="Ticket Product Category", slug="ticket-product-cat")
        cls.product = Product.objects.create(
            vendor=cls.vendor, name="Test Product Ticket", slug="test-product-ticket",
            category=cls.category_for_product, # Link created category
            price_btc=Decimal('0.01'), accepted_currencies=Currency.BTC.value
        )
        cls.order = Order.objects.create(
            buyer=cls.user_requester, vendor=cls.vendor, product=cls.product, quantity=1,
            selected_currency=Currency.BTC.value, status=Order.StatusChoices.FINALIZED.value,
            price_native_selected=Decimal('1000000'), # Example: 0.01 BTC in satoshis
            total_price_native_selected=Decimal('1000000') # Example
        )

        # Create an initial ticket and message
        cls.ticket1 = SupportTicket.objects.create(
            requester=cls.user_requester,
            assigned_to=cls.user_staff,
            subject="Test Ticket Subject 1",
            status=SupportTicket.StatusChoices.OPEN.value, # Use .value
            related_order=cls.order
        )
        # Simulate encrypted message (assuming encrypted for support)
        cls.message1 = TicketMessage.objects.create(
            ticket=cls.ticket1,
            sender=cls.user_requester,
            encrypted_body="PGP-ENCRYPTED-FOR-SUPPORT-KEY: Initial message content."
        )

    def setUp(self):
        """Set up for each test method."""
        self.client = APIClient()
        self.client.login(username=self.user_requester.username, password=self.password)
        self.settings_patcher_fp = patch('backend.store.views.tickets.MARKET_SUPPORT_PGP_FINGERPRINT', MOCK_SUPPORT_FINGERPRINT)
        self.settings_patcher_pk = patch('backend.store.views.tickets.MARKET_SUPPORT_PGP_PUBLIC_KEY', MOCK_SUPPORT_PUBLIC_KEY)
        self.mock_support_fp = self.settings_patcher_fp.start()
        self.mock_support_pk = self.settings_patcher_pk.start()
        self.addCleanup(self.settings_patcher_fp.stop)
        self.addCleanup(self.settings_patcher_pk.stop)


    # === SupportTicketViewSet Tests ===

    def test_list_tickets_requester(self, mock_pgp_service, mock_audit_log, mock_notify):
        url = reverse('store:ticket-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], str(self.ticket1.id))
        self.assertEqual(response.data[0]['requester']['username'], self.user_requester.username)

    def test_list_tickets_staff(self, mock_pgp_service, mock_audit_log, mock_notify):
        self.client.login(username=self.user_staff.username, password=self.password)
        url = reverse('store:ticket-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)
        self.assertTrue(any(t['id'] == str(self.ticket1.id) for t in response.data))

    def test_list_tickets_unauthenticated(self, mock_pgp_service, mock_audit_log, mock_notify):
        self.client.logout()
        url = reverse('store:ticket-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve_ticket_requester(self, mock_pgp_service, mock_audit_log, mock_notify):
        url = reverse('store:ticket-detail', kwargs={'pk': self.ticket1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.ticket1.id))
        self.assertEqual(response.data['subject'], self.ticket1.subject)
        self.assertIn('messages', response.data)

    def test_retrieve_ticket_assignee(self, mock_pgp_service, mock_audit_log, mock_notify):
        self.client.login(username=self.user_staff.username, password=self.password)
        url = reverse('store:ticket-detail', kwargs={'pk': self.ticket1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.ticket1.id))

    def test_retrieve_ticket_other_staff(self, mock_pgp_service, mock_audit_log, mock_notify):
        self.client.login(username=self.user_other_staff.username, password=self.password)
        url = reverse('store:ticket-detail', kwargs={'pk': self.ticket1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.ticket1.id))

    def test_retrieve_ticket_unrelated_user(self, mock_pgp_service, mock_audit_log, mock_notify):
        self.client.login(username=self.user_unrelated.username, password=self.password)
        url = reverse('store:ticket-detail', kwargs={'pk': self.ticket1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_ticket_success(self, mock_pgp_service, mock_audit_log, mock_notify):
        mock_pgp_service.is_pgp_service_available.return_value = True
        mock_pgp_service.encrypt_message_for_recipient.return_value = "ENCRYPTED-INITIAL-MESSAGE"

        url = reverse('store:ticket-list')
        data = {
            'subject': 'New Ticket Test',
            'initial_message_body': 'This is the first message content.',
            'related_order_id_write': str(self.order.pk) # Ensure UUID is string
        }
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['subject'], data['subject'])
        self.assertEqual(response.data['requester']['username'], self.user_requester.username)
        self.assertEqual(response.data['status'], SupportTicket.StatusChoices.OPEN.value)
        self.assertIsNotNone(response.data['related_order'])

        new_ticket = SupportTicket.objects.get(pk=response.data['id'])
        self.assertEqual(new_ticket.subject, data['subject'])
        self.assertEqual(new_ticket.requester, self.user_requester)
        self.assertEqual(new_ticket.related_order, self.order)

        initial_message = TicketMessage.objects.filter(ticket=new_ticket).first()
        self.assertIsNotNone(initial_message)
        self.assertEqual(initial_message.sender, self.user_requester)
        self.assertEqual(initial_message.encrypted_body, "ENCRYPTED-INITIAL-MESSAGE")

        mock_pgp_service.encrypt_message_for_recipient.assert_called_once_with(
            recipient_public_key=self.mock_support_pk, # Patched setting value
            recipient_fingerprint=self.mock_support_fp, # Patched setting value
            message=data['initial_message_body']
        )
        mock_notify.create_notification.assert_called()


    # === TicketMessageViewSet Tests ===

    def test_list_messages_requester(self, mock_pgp_service, mock_audit_log, mock_notify):
        mock_pgp_service.is_pgp_service_available.return_value = True
        mock_pgp_service.decrypt_message.return_value = "DECRYPTED: Initial message content."

        url = reverse('store:ticket-message-list', kwargs={'ticket_pk': self.ticket1.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], str(self.message1.id))
        self.assertEqual(response.data[0]['sender']['username'], self.user_requester.username)
        self.assertEqual(response.data[0]['decrypted_body'], "DECRYPTED: Initial message content.")
        mock_pgp_service.decrypt_message.assert_called_once_with(self.message1.encrypted_body)

    def test_list_messages_staff(self, mock_pgp_service, mock_audit_log, mock_notify):
        self.client.login(username=self.user_staff.username, password=self.password)
        mock_pgp_service.is_pgp_service_available.return_value = True
        mock_pgp_service.decrypt_message.return_value = "DECRYPTED: Staff view."

        url = reverse('store:ticket-message-list', kwargs={'ticket_pk': self.ticket1.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['decrypted_body'], "DECRYPTED: Staff view.")
        mock_pgp_service.decrypt_message.assert_called_once_with(self.message1.encrypted_body)

    def test_list_messages_unauthorized_user(self, mock_pgp_service, mock_audit_log, mock_notify):
        self.client.login(username=self.user_unrelated.username, password=self.password)
        url = reverse('store:ticket-message-list', kwargs={'ticket_pk': self.ticket1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_message_requester_success(self, mock_pgp_service, mock_audit_log, mock_notify):
        mock_pgp_service.is_pgp_service_available.return_value = True
        mock_pgp_service.encrypt_message_for_recipient.return_value = "ENCRYPTED-FOR-STAFF"
        # If self.user_staff.pgp_public_key is None, get_key_details should handle it or be mocked to handle it.
        # For this test, assume get_key_details can accept None or a string.
        mock_pgp_service.get_key_details.return_value = {'fingerprint': 'STAFF_FINGERPRINT_PLACEHOLDER'}

        url = reverse('store:ticket-message-list', kwargs={'ticket_pk': self.ticket1.pk})
        data = {'message_body': 'This is a reply from the requester.'}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['sender']['username'], self.user_requester.username)
        self.assertNotIn('decrypted_body', response.data)

        self.assertEqual(TicketMessage.objects.filter(ticket=self.ticket1).count(), 2)
        new_message = TicketMessage.objects.filter(ticket=self.ticket1).latest('sent_at')
        self.assertEqual(new_message.sender, self.user_requester)
        self.assertEqual(new_message.encrypted_body, "ENCRYPTED-FOR-STAFF")

        mock_pgp_service.get_key_details.assert_called_once_with(self.user_staff.pgp_public_key) # Will pass None
        mock_pgp_service.encrypt_message_for_recipient.assert_called_once_with(
            recipient_public_key=self.user_staff.pgp_public_key, # Will pass None
            recipient_fingerprint='STAFF_FINGERPRINT_PLACEHOLDER', # From mock
            message=data['message_body']
        )
        mock_notify.create_notification.assert_called_with(
            user_id=self.user_staff.id, level='info', message=ANY
        )

    def test_create_message_staff_success(self, mock_pgp_service, mock_audit_log, mock_notify):
        self.client.login(username=self.user_staff.username, password=self.password)
        mock_pgp_service.is_pgp_service_available.return_value = True
        mock_pgp_service.encrypt_message_for_recipient.return_value = "ENCRYPTED-FOR-REQUESTER"
        mock_pgp_service.get_key_details.return_value = {'fingerprint': 'REQUESTER_FINGERPRINT_PLACEHOLDER'}

        url = reverse('store:ticket-message-list', kwargs={'ticket_pk': self.ticket1.pk})
        data = {'message_body': 'This is a reply from staff.'}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['sender']['username'], self.user_staff.username)

        new_message = TicketMessage.objects.filter(ticket=self.ticket1).latest('sent_at')
        self.assertEqual(new_message.sender, self.user_staff)
        self.assertEqual(new_message.encrypted_body, "ENCRYPTED-FOR-REQUESTER")

        mock_pgp_service.get_key_details.assert_called_once_with(self.user_requester.pgp_public_key) # Will pass None
        mock_pgp_service.encrypt_message_for_recipient.assert_called_once_with(
            recipient_public_key=self.user_requester.pgp_public_key, # Will pass None
            recipient_fingerprint='REQUESTER_FINGERPRINT_PLACEHOLDER', # From mock
            message=data['message_body']
        )
        mock_notify.create_notification.assert_called_with(
            user_id=self.user_requester.id, level='info', message=ANY
        )

    def test_create_message_recipient_no_key(self, mock_pgp_service, mock_audit_log, mock_notify):
        ticket_no_pgp_user = SupportTicket.objects.create(requester=self.user_no_pgp, subject="No PGP")
        self.client.login(username=self.user_staff.username, password=self.password)
        mock_pgp_service.is_pgp_service_available.return_value = True
        # Ensure get_key_details returns None or raises an error if key is effectively None (empty string)
        # to simulate the "no key" scenario for encryption attempt.
        def get_key_details_side_effect(key_str):
            if not key_str: # Handles None or empty string
                return None # Or raise an error that the view would catch
            return {'fingerprint': 'SOME_FINGERPRINT'} # For other valid key strings
        mock_pgp_service.get_key_details.side_effect = get_key_details_side_effect

        url = reverse('store:ticket-message-list', kwargs={'ticket_pk': ticket_no_pgp_user.pk})
        data = {'message_body': 'This reply will fail.'}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("recipient does not have a PGP key", response.data['detail'].lower())
        mock_pgp_service.encrypt_message_for_recipient.assert_not_called()

# --- END OF FILE ---