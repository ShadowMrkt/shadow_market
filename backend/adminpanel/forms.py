# -*- coding: utf-8 -*-
"""
Django forms for the admin panel application.

This module defines forms used for various administrative actions,
such as managing global settings, user bans, dispute resolution,
vendor actions, and marking bond payments.
"""

# Standard Library Imports
import logging
from decimal import Decimal

# Third-Party Imports (Django)
from django import forms
from django.conf import settings # Import settings if specific configurations are needed directly
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MinValueValidator # Added MinValueValidator
from django.utils import timezone

# Local Application Imports
try:
    # Ensure the path 'store.models' is correct relative to your project structure
    # and that 'store' is listed in your INSTALLED_APPS.
    from store.models import GlobalSettings, Order, User, CURRENCY_CHOICES
    # Note: PGP service/validation logic should reside in the view or a dedicated service module,
    # not directly within the form's cleaning methods for better separation of concerns.
    # from store.services import pgp_service # Uncomment if needed for other logic, unlikely here.
except ImportError as e:
    # Log critical error if models cannot be imported, as forms depend on them.
    # This usually indicates a configuration or path issue.
    logging.exception("CRITICAL: Cannot import models from 'store' app in adminpanel/forms.py. Check INSTALLED_APPS and paths.")
    # Re-raising helps make the startup failure obvious during development/deployment.
    raise e


# --- Global Settings Forms ---

class GlobalSettingsForm(forms.ModelForm):
    """
    Form for updating global marketplace settings via the admin panel.

    Includes fields for general site configuration, fees, vendor bonds,
    confirmation requirements, order timings, and the Warrant Canary
    content and associated PGP signing key details.
    """
    # Non-model field to capture the PGP signature during canary updates.
    # Validation (checking if required and verifying the signature)
    # MUST be handled in the corresponding view logic.
    canary_signature_input = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 10,
            'placeholder': 'Paste PGP signature block here ONLY when updating canary content...'
        }),
        required=False, # View logic determines if it's required based on canary_content change.
        label="PGP Signature for Canary Update",
        help_text=(
            "Required IF canary content is changed. "
            "Sign the exact NEW canary content + current date string (YYYY-MM-DD) "
            "using the PGP key specified by the fingerprint below."
        )
    )

    # Model fields explicitly defined for validation or widget customization.
    canary_signing_key_fingerprint = forms.CharField(
        max_length=40,
        required=True, # A fingerprint is essential for verifying the canary's authenticity.
        label="Canary Signing Key Fingerprint",
        validators=[
            RegexValidator(
                regex=r'^[0-9A-Fa-f]{40}$',
                message='Enter a valid 40-character PGP key fingerprint (hexadecimal).'
            )
        ],
        help_text="REQUIRED. The 40-char fingerprint of the PGP key used for signing the canary."
    )
    canary_signing_key_url = forms.URLField(
        max_length=512, # Allow ample length for URLs.
        required=False, # Providing a URL is helpful but not strictly mandatory.
        label="Canary Signing Key URL (Optional)",
        help_text="Optional URL where the public key (matching the fingerprint) can be verified/downloaded."
    )

    class Meta:
        model = GlobalSettings
        fields = [
            # General Settings
            'site_name',
            'maintenance_mode',
            'allow_new_registrations',
            'allow_new_vendors',
            # Fees (per currency)
            'market_fee_percentage_xmr',
            'market_fee_percentage_btc',
            'market_fee_percentage_eth',
            # Vendor Bonds (per currency)
            'vendor_bond_xmr',
            'vendor_bond_btc',
            'vendor_bond_eth',
            # Confirmation Settings (per currency)
            'confirmations_needed_xmr',
            'confirmations_needed_btc',
            'confirmations_needed_eth',
            # Order Timings
            'payment_wait_hours',
            'order_auto_finalize_days',
            'dispute_window_days',
            # Warrant Canary (Content & Key Info)
            'canary_content',
            'canary_signing_key_fingerprint', # Managed by explicit field above
            'canary_signing_key_url',        # Managed by explicit field above
            # Note: 'canary_last_updated' and 'canary_pgp_signature' fields
            # are managed automatically by the view logic upon successful signed update.
            # Note: 'freeze_funds' might be better managed via a separate, dedicated emergency action interface.
            # Note: Tiered DMS thresholds could be managed via settings.py or another mechanism if complex.
        ]
        widgets = {
            # General
            'site_name': forms.TextInput(attrs={'size': '50'}),
            # Fees (Use NumberInput for better UX, step allows decimals)
            'market_fee_percentage_xmr': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'market_fee_percentage_btc': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'market_fee_percentage_eth': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            # Vendor Bonds (Allow fine granularity for crypto)
            'vendor_bond_xmr': forms.NumberInput(attrs={'step': '0.000001', 'min': '0'}),
            'vendor_bond_btc': forms.NumberInput(attrs={'step': '0.00000001', 'min': '0'}),
            'vendor_bond_eth': forms.NumberInput(attrs={'step': '0.000001', 'min': '0'}),
            # Confirmations (Integers, minimum 1)
            'confirmations_needed_xmr': forms.NumberInput(attrs={'step': '1', 'min': '1'}),
            'confirmations_needed_btc': forms.NumberInput(attrs={'step': '1', 'min': '1'}),
            'confirmations_needed_eth': forms.NumberInput(attrs={'step': '1', 'min': '1'}),
            # Order Timings (Integers, minimum 1, consider sensible max if needed)
            'payment_wait_hours': forms.NumberInput(attrs={'step': '1', 'min': '1'}),
            'order_auto_finalize_days': forms.NumberInput(attrs={'step': '1', 'min': '1'}),
            'dispute_window_days': forms.NumberInput(attrs={'step': '1', 'min': '1'}),
            # Canary
            'canary_content': forms.Textarea(attrs={'rows': 15}),
            'canary_signing_key_fingerprint': forms.TextInput(attrs={'size': '45'}), # Defined above
            'canary_signing_key_url': forms.URLInput(attrs={'size': '60'}),          # Defined above
        }
        labels = {
            # Add more descriptive labels if needed, e.g.:
            'market_fee_percentage_xmr': 'Market Fee % (XMR)',
            'vendor_bond_xmr': 'Vendor Bond Amount (XMR)',
            'confirmations_needed_xmr': 'Confirmations Needed (XMR)',
            # ... and similarly for BTC, ETH ...
        }
        help_texts = {
            # Add more specific help texts if needed, e.g.:
            'market_fee_percentage_xmr': 'Percentage fee charged on XMR sales (e.g., 3.5 for 3.5%).',
            'confirmations_needed_xmr': 'Minimum network confirmations for XMR deposits to be credited.',
            'payment_wait_hours': 'Hours buyers have to make payment after placing an order.',
            'order_auto_finalize_days': 'Days after shipping until an order is auto-finalized if buyer takes no action.',
            'dispute_window_days': 'Days after finalization that a buyer can open a dispute.',
        }

    def clean(self):
        """
        Basic form-level validation.

        Note: Complex cross-field validation, especially involving the
        canary_signature_input, should be handled in the view after
        basic field validation passes.
        """
        cleaned_data = super().clean()

        # Example: Ensure fee percentages are within a reasonable range (e.g., 0-100)
        for field_name in ['market_fee_percentage_xmr', 'market_fee_percentage_btc', 'market_fee_percentage_eth']:
            fee = cleaned_data.get(field_name)
            if fee is not None and not (0 <= fee <= 100):
                self.add_error(field_name, ValidationError("Fee percentage must be between 0 and 100."))

        # Example: Ensure bond amounts are non-negative
        for field_name in ['vendor_bond_xmr', 'vendor_bond_btc', 'vendor_bond_eth']:
            bond = cleaned_data.get(field_name)
            if bond is not None and bond < 0:
                self.add_error(field_name, ValidationError("Bond amount cannot be negative."))

        # Add any other simple cross-field validation here if needed.

        return cleaned_data

# --- User Management Forms ---

class BanUserForm(forms.Form):
    """Form for confirming user ban/unban action with an optional reason."""
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4, 'cols': 40}),
        required=False, # Recommended but not strictly required.
        label="Reason for Action (Optional, will be logged)",
        help_text="Provide context for banning or unbanning this user. Visible in admin logs."
    )

# --- Dispute Management Forms ---

class ResolveDisputeForm(forms.Form):
    """Form for moderators to resolve an order dispute and allocate funds."""
    resolution_notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 6, 'cols': 50}),
        required=True,
        label="Moderator Resolution Notes",
        help_text="Explain the reasoning behind the resolution decision. This may be visible to buyer/vendor."
    )
    release_to_buyer_percent = forms.IntegerField(
        min_value=0,
        max_value=100,
        required=True,
        initial=50, # Sensible default, encourages fair consideration.
        label="Percentage of Escrow to Release to Buyer (0-100)",
        help_text=(
            "Enter the percentage (whole number, 0-100) of the escrowed funds "
            "to be released to the BUYER. The remaining percentage automatically goes to the vendor."
        ),
        widget=forms.NumberInput(attrs={'step': '1'}) # Ensure integer steps
    )

    def clean_release_to_buyer_percent(self):
        """Validate the percentage value."""
        percent = self.cleaned_data.get('release_to_buyer_percent')
        if percent is None:
            # Should be caught by required=True, but defensive check.
            raise ValidationError("Percentage is required.")
        if not (0 <= percent <= 100):
            # Should be caught by min/max_value, but defensive check.
            raise ValidationError("Percentage must be between 0 and 100.")
        return percent

# --- Vendor Management Forms ---

class VendorActionReasonForm(forms.Form):
      """
      Generic form for capturing a required reason for vendor-related admin actions
      (e.g., approving application, rejecting application, revoking status).
      """
      reason = forms.CharField(
          widget=forms.Textarea(attrs={'rows': 4, 'cols': 50}),
          required=True, # Ensure administrators provide justification.
          label="Reason / Notes for Action",
          help_text="Provide a clear reason for this vendor action (e.g., approval, rejection, bond update)."
      )


class MarkBondPaidForm(forms.Form):
    """Form for admin to manually record an externally received vendor bond payment."""
    bond_currency = forms.ChoiceField(
        choices=CURRENCY_CHOICES, # Assumes CURRENCY_CHOICES is imported correctly
        required=True,
        label="Bond Currency"
    )
    # Using DecimalField for financial precision.
    # Ensure max_digits aligns with your model definition.
    bond_amount = forms.DecimalField(
        required=True,
        min_value=Decimal('0.00000001'), # Minimum practical value for crypto
        max_digits=20,    # Adjust based on your model's max_digits
        decimal_places=12, # Adjust based on required precision for all currencies
        label="Bond Amount Paid",
        widget=forms.NumberInput(attrs={'step': '0.00000001'}) # Adjust step if needed
    )
    # Optional field for tracking the external transaction.
    external_txid = forms.CharField(
        max_length=100, # Adjust length as needed for TX IDs
        required=False,
        label="External Transaction ID (Optional)",
        help_text="Enter the blockchain transaction ID, if available."
    )
    # Optional notes field.
    notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3, 'cols': 40}),
        required=False,
        label="Admin Notes (Optional)",
        help_text="Any internal notes related to this manual bond payment."
    )

    def clean_bond_amount(self):
        """Ensure bond amount is positive."""
        amount = self.cleaned_data.get('bond_amount')
        if amount is not None and amount <= 0:
            raise ValidationError("Bond amount must be a positive value.")
        return amount

# --- End of File ---