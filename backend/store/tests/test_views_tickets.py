# backend/store/tests/test_views_tickets.py
# Revision: 1.5
# Date: 2025-05-23
# Author: Gemini
# Description: Contains tests for the API views in views/tickets.py (SupportTicketViewSet, TicketMessageViewSet).
# Changes:
# - Rev 1.5:
#   - Standardized all class-level patches to let unittest.mock create the default MagicMock.
#   - Ensured mock argument names in test methods are consistent with the patched objects and their order.
# - Rev 1.4:
#   - Corrected patch target for `create_notification` (was `notification_service`).
#   - Ensured mock argument order in test methods matches decorator order.
# - Rev 1.3:
#   - Imported APITestCase, APIClient, and status from rest_framework.test and rest_framework respectively
#     to resolve NameError for APITestCase and ensure status/APIClient are available.
# - Rev 1.2:
#   - Corrected SupportTicket status assignment in setUpTestData to use the globally defined
#     `SupportTicketStatus` enum instead of a non-existent inner `StatusChoices` class.
# - Rev 1.1:
#   - Set pgp_public_key to None for test user creations in setUpTestData.
#   - Ensured Category is created for Product.
#   - Added required price fields for Order creation.
#   - Used .value for Enum fields.
#   - Ensured UUID PKs are passed as strings in data.
# - Rev 1.0 (Initial Creation):
#   - Date: 2025-04-29
#   - Author: Gemini

# Standard Library Imports
from unittest.mock import patch, MagicMock, ANY
from decimal import Decimal
import json
import uuid

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone

# Third-Party Imports
from rest_framework.test import APITestCase, APIClient
from rest_framework import status

# Local Application Imports
from backend.store.models import (
    SupportTicket, TicketMessage, User as StoreUser, Product, Order, Currency, Category,
    SupportTicketStatus
)
from backend.store.permissions import PGP_AUTH_SESSION_KEY

# Mock PGP Service constants
MOCK_SUPPORT_FINGERPRINT = "SUPPORT_FINGERPRINT_HERE"
MOCK_SUPPORT_PUBLIC_KEY = "-----BEGIN PGP PUBLIC KEY BLOCK-----\nSUPPORT KEY\n-----END PGP PUBLIC KEY BLOCK-----"

# --- Constants ---
User = get_user_model()

# --- Test Cases ---

@patch('backend.store.views.tickets.create_notification')  # Outermost -> mock_create_notification (3rd arg)
@patch('backend.store.views.tickets.pgp_service')          # Middle    -> mock_pgp_service (2nd arg)
@patch('backend.store.views.tickets.log_audit_event')     # Innermost -> mock_log_audit_event (1st arg)
class TicketViewTests(APITestCase):
    """Tests for SupportTicketViewSet and TicketMessageViewSet."""

    @classmethod
    def setUpTestData(cls):
        cls.password = 'strongpassword123'
        cls.user_requester = User.objects.create_user(username='ticket_requester', password=cls.password, pgp_public_key=None)
        cls.user_staff = User.objects.create_user(username='ticket_staff', password=cls.password, is_staff=True, pgp_public_key=None)
        cls.user_other_staff = User.objects.create_user(username='other_staff', password=cls.password, is_staff=True, pgp_public_key=None)
        cls.user_unrelated = User.objects.create_user(username='unrelated_user', password=cls.password, pgp_public_key=None)
        cls.user_no_pgp = User.objects.create_user(username='user_no_pgp', password=cls.password, pgp_public_key='')
        cls.vendor = User.objects.create_user(username='vendor_ticket', password=cls.password, is_vendor=True, pgp_public_key=None)

        cls.category_for_product = Category.objects.create(name="Ticket Product Category", slug="ticket-product-cat")
        cls.product = Product.objects.create(
            vendor=cls.vendor, name="Test Product Ticket", slug="test-product-ticket",
            category=cls.category_for_product,
            price_btc=Decimal('0.01'), accepted_currencies=Currency.BTC.value
        )
        cls.order = Order.objects.create(
            buyer=cls.user_requester, vendor=cls.vendor, product=cls.product, quantity=1,
            selected_currency=Currency.BTC.value, status=Order.StatusChoices.FINALIZED.value,
            price_native_selected=Decimal('1000000'),
            total_price_native_selected=Decimal('1000000')
        )
        cls.ticket1 = SupportTicket.objects.create(
            requester=cls.user_requester, assigned_to=cls.user_staff,
            subject="Test Ticket Subject 1", status=SupportTicketStatus.OPEN.value,
            related_order=cls.order
        )
        cls.message1 = TicketMessage.objects.create(
            ticket=cls.ticket1, sender=cls.user_requester,
            encrypted_body="PGP-ENCRYPTED-FOR-SUPPORT-KEY: Initial message content."
        )

    def setUp(self):
        self.client = APIClient()
        self.client.login(username=self.user_requester.username, password=self.password)
        self.settings_patcher_fp = patch('backend.store.views.tickets.MARKET_SUPPORT_PGP_FINGERPRINT', MOCK_SUPPORT_FINGERPRINT)
        self.settings_patcher_pk = patch('backend.store.views.tickets.MARKET_SUPPORT_PGP_PUBLIC_KEY', MOCK_SUPPORT_PUBLIC_KEY)
        self.mock_support_fp = self.settings_patcher_fp.start()
        self.mock_support_pk = self.settings_patcher_pk.start()
        self.addCleanup(self.settings_patcher_fp.stop)
        self.addCleanup(self.settings_patcher_pk.stop)

    # Corrected mock argument order and names
    def test_list_tickets_requester(self, mock_log_audit_event, mock_pgp_service, mock_create_notification):
        url = reverse('store:ticket-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], str(self.ticket1.id))
        self.assertEqual(results[0]['requester']['username'], self.user_requester.username)

    def test_list_tickets_staff(self, mock_log_audit_event, mock_pgp_service, mock_create_notification):
        self.client.login(username=self.user_staff.username, password=self.password)
        url = reverse('store:ticket-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertGreaterEqual(len(results), 1)
        self.assertTrue(any(t['id'] == str(self.ticket1.id) for t in results))

    def test_list_tickets_unauthenticated(self, mock_log_audit_event, mock_pgp_service, mock_create_notification):
        self.client.logout()
        url = reverse('store:ticket-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve_ticket_requester(self, mock_log_audit_event, mock_pgp_service, mock_create_notification):
        url = reverse('store:ticket-detail', kwargs={'pk': self.ticket1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.ticket1.id))
        self.assertEqual(response.data['subject'], self.ticket1.subject)
        self.assertIn('messages', response.data)

    def test_retrieve_ticket_assignee(self, mock_log_audit_event, mock_pgp_service, mock_create_notification):
        self.client.login(username=self.user_staff.username, password=self.password)
        url = reverse('store:ticket-detail', kwargs={'pk': self.ticket1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.ticket1.id))

    def test_retrieve_ticket_other_staff(self, mock_log_audit_event, mock_pgp_service, mock_create_notification):
        self.client.login(username=self.user_other_staff.username, password=self.password)
        url = reverse('store:ticket-detail', kwargs={'pk': self.ticket1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.ticket1.id))

    def test_retrieve_ticket_unrelated_user(self, mock_log_audit_event, mock_pgp_service, mock_create_notification):
        self.client.login(username=self.user_unrelated.username, password=self.password)
        url = reverse('store:ticket-detail', kwargs={'pk': self.ticket1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_ticket_success(self, mock_log_audit_event, mock_pgp_service, mock_create_notification):
        mock_pgp_service.is_pgp_service_available.return_value = True
        mock_pgp_service.encrypt_message_for_recipient.return_value = "ENCRYPTED-INITIAL-MESSAGE"
        url = reverse('store:ticket-list')
        data = {
            'subject': 'New Ticket Test',
            'initial_message_body': 'This is the first message content.',
            'related_order_id_write': str(self.order.pk)
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['subject'], data['subject'])
        self.assertEqual(response.data['requester']['username'], self.user_requester.username)
        self.assertEqual(response.data['status'], SupportTicketStatus.OPEN.value)
        self.assertIsNotNone(response.data['related_order'])
        new_ticket = SupportTicket.objects.get(pk=response.data['id'])
        self.assertEqual(new_ticket.subject, data['subject'])
        initial_message = TicketMessage.objects.filter(ticket=new_ticket).first()
        self.assertIsNotNone(initial_message)
        self.assertEqual(initial_message.encrypted_body, "ENCRYPTED-INITIAL-MESSAGE")
        mock_pgp_service.encrypt_message_for_recipient.assert_called_once_with(
            recipient_public_key=self.mock_support_pk,
            recipient_fingerprint=self.mock_support_fp,
            message=data['initial_message_body']
        )
        mock_create_notification.assert_called()

    def test_list_messages_requester(self, mock_log_audit_event, mock_pgp_service, mock_create_notification):
        mock_pgp_service.is_pgp_service_available.return_value = True
        mock_pgp_service.decrypt_message.return_value = "DECRYPTED: Initial message content."
        url = reverse('store:ticket-message-list', kwargs={'ticket_pk': self.ticket1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], str(self.message1.id))
        self.assertEqual(results[0]['sender']['username'], self.user_requester.username)
        self.assertEqual(results[0]['decrypted_body'], "DECRYPTED: Initial message content.")
        mock_pgp_service.decrypt_message.assert_called_once_with(self.message1.encrypted_body)

    def test_list_messages_staff(self, mock_log_audit_event, mock_pgp_service, mock_create_notification):
        self.client.login(username=self.user_staff.username, password=self.password)
        mock_pgp_service.is_pgp_service_available.return_value = True
        mock_pgp_service.decrypt_message.return_value = "DECRYPTED: Staff view."
        url = reverse('store:ticket-message-list', kwargs={'ticket_pk': self.ticket1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['decrypted_body'], "DECRYPTED: Staff view.")
        mock_pgp_service.decrypt_message.assert_called_once_with(self.message1.encrypted_body)

    def test_list_messages_unauthorized_user(self, mock_log_audit_event, mock_pgp_service, mock_create_notification):
        self.client.login(username=self.user_unrelated.username, password=self.password)
        url = reverse('store:ticket-message-list', kwargs={'ticket_pk': self.ticket1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_message_requester_success(self, mock_log_audit_event, mock_pgp_service, mock_create_notification):
        mock_pgp_service.is_pgp_service_available.return_value = True
        mock_pgp_service.encrypt_message_for_recipient.return_value = "ENCRYPTED-FOR-STAFF"
        mock_pgp_service.get_key_details.return_value = {'fingerprint': 'STAFF_FINGERPRINT_PLACEHOLDER'}
        url = reverse('store:ticket-message-list', kwargs={'ticket_pk': self.ticket1.pk})
        data = {'message_body': 'This is a reply from the requester.'}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['sender']['username'], self.user_requester.username)
        self.assertNotIn('decrypted_body', response.data)
        self.assertEqual(TicketMessage.objects.filter(ticket=self.ticket1).count(), 2)
        new_message = TicketMessage.objects.filter(ticket=self.ticket1).latest('sent_at')
        self.assertEqual(new_message.encrypted_body, "ENCRYPTED-FOR-STAFF")
        mock_pgp_service.get_key_details.assert_called_once_with(self.user_staff.pgp_public_key)
        mock_pgp_service.encrypt_message_for_recipient.assert_called_once_with(
            recipient_public_key=self.user_staff.pgp_public_key,
            recipient_fingerprint='STAFF_FINGERPRINT_PLACEHOLDER',
            message=data['message_body']
        )
        mock_create_notification.assert_called_with(user_id=self.user_staff.id, level='info', message=ANY)

    def test_create_message_staff_success(self, mock_log_audit_event, mock_pgp_service, mock_create_notification):
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
        self.assertEqual(new_message.encrypted_body, "ENCRYPTED-FOR-REQUESTER")
        mock_pgp_service.get_key_details.assert_called_once_with(self.user_requester.pgp_public_key)
        mock_pgp_service.encrypt_message_for_recipient.assert_called_once_with(
            recipient_public_key=self.user_requester.pgp_public_key,
            recipient_fingerprint='REQUESTER_FINGERPRINT_PLACEHOLDER',
            message=data['message_body']
        )
        mock_create_notification.assert_called_with(user_id=self.user_requester.id, level='info', message=ANY)

    def test_create_message_recipient_no_key(self, mock_log_audit_event, mock_pgp_service, mock_create_notification):
        ticket_no_pgp_user = SupportTicket.objects.create(
            requester=self.user_no_pgp, subject="No PGP", status=SupportTicketStatus.OPEN.value
        )
        self.client.login(username=self.user_staff.username, password=self.password)
        mock_pgp_service.is_pgp_service_available.return_value = True
        def get_key_details_side_effect(key_str):
            if not key_str: return None
            return {'fingerprint': 'SOME_FINGERPRINT'}
        mock_pgp_service.get_key_details.side_effect = get_key_details_side_effect
        url = reverse('store:ticket-message-list', kwargs={'ticket_pk': ticket_no_pgp_user.pk})
        data = {'message_body': 'This reply will fail.'}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("recipient does not have a pgp key", response.data['detail'].lower())
        mock_pgp_service.encrypt_message_for_recipient.assert_not_called()

# --- END OF FILE ---