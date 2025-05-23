# backend/adminpanel/views.py
# Revision History:
# - v1.0.7 (2025-05-03): Corrected import path for ATOMIC_FACTOR to use ledger.constants. (Gemini)
# - v1.0.6 (2025-05-03): Corrected import path for ATOMIC_FACTOR to use services.common_escrow_utils. (Gemini) # NOTE: Previous attempt failed.
# - v1.0.5 (2025-05-03): Corrected import path for ATOMIC_FACTOR to use utils.conversion. (Gemini) # NOTE: Previous attempt failed.
# - v1.0.4 (2025-05-03): Refactor escrow service imports to use modules and function calls,
#                       aligning with the functional structure of provided ETH service files. (Gemini)
# - v1.0.3 (2025-05-03): Fix escrow service imports by importing classes and instantiating them. (Gemini) # NOTE: Previous attempt, structure mismatch.
# - v1.0.2 (2025-05-03): Corrected specific escrow service imports and selection logic. (Gemini) # NOTE: This seems superseded by v1.0.3 logic. Keeping history.
# - v1.0.1 (2025-05-03): Corrected syntax, use absolute model import path. (Gemini)
# - v1.0.0: Initial version.

import logging
import secrets
from datetime import date, timedelta, datetime
from decimal import Decimal

# Django Imports
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError, ObjectDoesNotExist
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.html import escape

# Local Imports (Attempt - using absolute paths from 'backend')
try:
    # Models - Use absolute path from 'backend'
    from backend.store.models import (
        Order, User, GlobalSettings, AuditLog, SupportTicket, Product, VendorApplication, AuditLogAction, # Added AuditLogAction
        ORDER_STATUS_CHOICES, CURRENCY_CHOICES, Currency, EscrowType, # Added Currency, EscrowType
        VENDOR_APP_STATUS_PENDING_REVIEW, VENDOR_APP_STATUS_APPROVED, VENDOR_APP_STATUS_REJECTED, # Added App Statuses
        VENDOR_APP_STATUS_PENDING_BOND, # Added Pending Bond status
        Dispute # Added Dispute model for updating in resolve_dispute
    )
    # Forms - Relative import within the same app is okay
    from .forms import (
        GlobalSettingsForm, BanUserForm, ResolveDisputeForm,
        VendorActionReasonForm, MarkBondPaidForm
        # Add ReviewVendorApplicationForm if needed for specific fields beyond reason
    )
    # --- Services - Use absolute path from 'backend' ---
    # Import non-escrow services directly if needed
    from backend.store.services import pgp_service # Assuming PGP service is needed elsewhere

    # --- Escrow Services - Import MODULES ---
    # Import MODULES instead of classes, assuming functional structure
    from backend.store.services import bitcoin_escrow_service as btc_escrow_module
    from backend.store.services import ethereum_escrow_service as eth_escrow_module
    from backend.store.services import monero_escrow_service as xmr_escrow_module
    from backend.store.services import simple_ethereum_escrow_service as simple_eth_escrow_module
    # --- End Escrow Service Module Imports ---

    # --- Other Services - Use absolute path from 'backend' ---
    from backend.store.exceptions import CryptoProcessingError, EscrowError, PostBroadcastUpdateError # Import necessary exceptions
    from backend.store.permissions import PGP_AUTH_SESSION_KEY
    from backend.ledger import services as ledger_service
    from backend.ledger.services import InsufficientFundsError # Note: InvalidLedgerOperationError not used here yet
    from backend.ledger.exceptions import LedgerError # Import ledger exceptions if needed
    from backend.notifications import services as notification_service # Assuming notification service exists
    from backend.notifications.exceptions import NotificationError # Import notification exceptions

    # --- Constants & Helpers - Use absolute path from 'backend' ---
    # Import ATOMIC_FACTOR from ledger constants (Likely location)
    from backend.ledger.constants import ATOMIC_FACTOR
    # Keep separate import for get_market_user from common utils
    from backend.store.services.common_escrow_utils import get_market_user

except ImportError as e:
    # Use basicConfig only if logging isn't already configured
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO) # Or your preferred default level
    logger_init = logging.getLogger(__name__)
    logger_init.critical(f"CRITICAL IMPORT ERROR in adminpanel/views.py: {e}. Check file paths, dependencies, and class/instance names.", exc_info=True)
    raise e

# Setup Loggers
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('django.security')

# --- Helper Functions & Decorators ---

def is_staff(user):
    """Check if a user is authenticated and has staff status."""
    return user and user.is_authenticated and getattr(user, 'is_staff', False)

def is_owner(user):
    """Check if a user is staff and belongs to the 'Owner' group."""
    # TODO: Use a constant or setting for the 'Owner' group name
    return is_staff(user) and hasattr(user, 'groups') and user.groups.filter(name='Owner').exists()

def check_pgp_auth_session(request):
    """
    Verify if the user has a valid PGP authentication timestamp in their session.
    Refreshes the timestamp on successful check.
    Returns True if valid, False otherwise.
    """
    user = getattr(request, 'user', None)
    session = getattr(request, 'session', None)
    if not user or not user.is_authenticated or not session:
        return False

    pgp_auth_timestamp_str = session.get(PGP_AUTH_SESSION_KEY)
    if not pgp_auth_timestamp_str:
        return False

    try:
        # Determine timeout based on user role (Owner gets longer timeout)
        default_timeout = getattr(settings, 'DEFAULT_PGP_AUTH_SESSION_TIMEOUT_MINUTES', 30) # Default 30 mins
        owner_timeout = getattr(settings, 'OWNER_PGP_AUTH_SESSION_TIMEOUT_MINUTES', 10) # Shorter for owner? Or longer? Example uses shorter. Adjust as needed.
        timeout_minutes = owner_timeout if is_owner(user) else default_timeout

        pgp_auth_time = datetime.fromisoformat(pgp_auth_timestamp_str)

        # Check if the session has expired
        if (timezone.now() - pgp_auth_time) > timedelta(minutes=timeout_minutes):
            session.pop(PGP_AUTH_SESSION_KEY, None)
            logger.warning(f"PGP Session expired for User: {user.username}")
            return False

        # Refresh the timestamp on successful check (sliding window)
        session[PGP_AUTH_SESSION_KEY] = timezone.now().isoformat()
        return True
    except Exception as e:
        logger.error(f"Error during PGP session check for User: {getattr(user, 'username', 'N/A')}: {e}")
        # Invalidate session key on error for safety
        session.pop(PGP_AUTH_SESSION_KEY, None)
        return False

def log_admin_action(request, actor, action, target_user=None, target_order=None, target_application=None, details=""):
    """Helper function to create an AuditLog entry for admin actions."""
    # Check if User and AuditLog models were imported successfully
    # Ensure action is a valid choice if AuditLogAction enum/choices are used
    action_value = action
    if 'AuditLogAction' in globals():
        if isinstance(action, AuditLogAction):
             action_value = action.value
        elif isinstance(action, str):
             # Optionally validate if the string 'action' is a valid key/value in AuditLogAction
             # For now, assume string actions are handled directly by the model field
             pass

    if 'User' in globals() and 'AuditLog' in globals() and isinstance(actor, User):
        try:
            ip_address = request.META.get('REMOTE_ADDR')
            AuditLog.objects.create(
                actor=actor,
                action=action_value, # Use potentially converted value
                target_user=target_user,
                target_order=target_order,
                target_application=target_application, # Added target_application
                details=details[:500], # Limit details length
                ip_address=ip_address
            )
        except Exception as e:
            logger.error(f"Failed to log admin action: {e}")
    elif 'AuditLog' not in globals():
        logger.error("AuditLog model not available for logging admin action.")
    elif not isinstance(actor, User):
        logger.error(f"Invalid actor type for logging admin action: {type(actor)}")


# --- Admin Panel Views ---

@login_required
def admin_dashboard(request):
    """Displays the main admin dashboard with key statistics."""
    if not is_staff(request.user):
        messages.error(request, "Access Denied.")
        return redirect('/')

    if not check_pgp_auth_session(request):
        messages.warning(request, "PGP authentication required for performing actions.")

    # Use constants/enum members for status checks if available and imported
    disputed_status = getattr(Order.StatusChoices, 'DISPUTED', 'disputed')
    open_status = getattr(SupportTicket.StatusChoices, 'OPEN', 'open')

    pending_disputes = Order.objects.filter(status=disputed_status).count()
    open_tickets = SupportTicket.objects.filter(status=open_status).count()
    recent_orders = Order.objects.order_by('-created_at')[:10]
    pending_vendor_apps = VendorApplication.objects.filter(status=VENDOR_APP_STATUS_PENDING_REVIEW).count() # Added

    context = {
        'pending_disputes': pending_disputes,
        'open_tickets': open_tickets,
        'recent_orders': recent_orders,
        'pending_vendor_apps': pending_vendor_apps, # Added
    }
    return render(request, 'adminpanel/admin_dashboard.html', context)

@login_required
def user_list(request):
    """Displays a searchable and filterable list of all users."""
    if not is_staff(request.user):
        messages.error(request, "Access Denied.")
        return redirect('/')

    if not check_pgp_auth_session(request):
        messages.warning(request, "PGP authentication recommended for potential actions.")

    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    users = User.objects.all().order_by('-date_joined')

    if query:
        users = users.filter(username__icontains=query)

    if status_filter == 'vendor':
        users = users.filter(is_vendor=True)
    elif status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)

    context = {
        'users': users,
        'query': query,
        'status_filter': status_filter,
    }
    return render(request, 'adminpanel/user_list.html', context)

@login_required
def user_detail(request, user_id):
    """Displays detailed information and actions for a specific user."""
    if not is_staff(request.user):
        messages.error(request, "Access Denied.")
        return redirect('/')

    if not check_pgp_auth_session(request):
        messages.warning(request, "PGP authentication required for performing actions.")

    user_obj = get_object_or_404(User, id=user_id)

    # Fetch related vendor application if exists
    vendor_application = VendorApplication.objects.filter(user=user_obj).order_by('-created_at').first()

    # Prepare forms needed on the detail page
    context = {
        'target_user': user_obj,
        'vendor_application': vendor_application, # Pass application to context
        'ban_form': BanUserForm(),
        # 'approve_reject_form' removed as legacy actions are removed/handled via application view
        'bond_action_form': VendorActionReasonForm(), # Renamed/repurposed for forfeit action
    }
    return render(request, 'adminpanel/user_detail.html', context)

@login_required
def ban_user(request, user_id):
    """Handles banning or unbanning a user. Requires PGP auth."""
    if not is_staff(request.user):
        messages.error(request, "Access Denied.")
        return redirect('/')

    if not check_pgp_auth_session(request):
        messages.error(request, "PGP authentication required to ban/unban users.")
        return redirect('adminpanel:user_detail', user_id=user_id)

    target_user = get_object_or_404(User, id=user_id)
    action_to_perform = 'unban' if not target_user.is_active else 'ban'

    # Prevent modifying staff/superuser accounts or self
    if target_user.is_staff or target_user.is_superuser:
        messages.error(request, "Cannot modify staff or superuser accounts.")
        return redirect('adminpanel:user_detail', user_id=user_id)
    if target_user == request.user:
        messages.error(request, f"You cannot {action_to_perform} yourself.")
        return redirect('adminpanel:user_detail', user_id=user_id)

    if request.method == 'POST':
        form = BanUserForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data.get('reason', 'No reason provided.')
            if action_to_perform == 'ban':
                target_user.is_active = False
                log_action = 'user_ban' # Or AuditLogAction.USER_BAN
                msg = f"User '{escape(target_user.username)}' has been banned."
                sec_msg = f"Banned User: {target_user.username} by {request.user.username}. Reason: {reason}"
            else: # unban
                target_user.is_active = True
                log_action = 'user_unban' # Or AuditLogAction.USER_UNBAN
                msg = f"User '{escape(target_user.username)}' has been unbanned."
                sec_msg = f"Unbanned User: {target_user.username} by {request.user.username}. Reason: {reason}"

            target_user.save(update_fields=['is_active'])
            log_admin_action(request, request.user, log_action, target_user=target_user, details=f"Reason: {reason}")
            messages.success(request, msg)
            security_logger.warning(sec_msg)
            return redirect('adminpanel:user_list')
        else:
            messages.error(request, "Invalid input provided. Please check the form.")
            # Determine template based on action and re-render with errors
            template_name = (
                'adminpanel/user_ban_confirm.html' if action_to_perform == 'ban'
                else 'adminpanel/user_unban_confirm.html'
            )
            context = {'target_user': target_user, 'form': form, 'action': action_to_perform}
            return render(request, template_name, context)

    # GET request: Show confirmation form
    form = BanUserForm()
    template_name = (
        'adminpanel/user_ban_confirm.html' if action_to_perform == 'ban'
        else 'adminpanel/user_unban_confirm.html'
    )
    context = {'target_user': target_user, 'form': form, 'action': action_to_perform}
    return render(request, template_name, context)


@login_required
def order_list(request):
    """Displays a filterable list of all orders."""
    if not is_staff(request.user):
        messages.error(request, "Access Denied.")
        return redirect('/')

    # PGP auth not strictly required to view, but recommend if actions are possible from list
    if not check_pgp_auth_session(request):
        messages.warning(request, "PGP authentication recommended for potential actions.")

    status_filter = request.GET.get('status', '')
    # Use select_related to optimize DB queries by fetching related objects
    orders = Order.objects.select_related('buyer', 'vendor', 'product').order_by('-created_at')

    if status_filter:
        # Ensure status_filter is a valid choice if necessary
        if status_filter in [choice[0] for choice in ORDER_STATUS_CHOICES]:
            orders = orders.filter(status=status_filter)
        else:
            messages.warning(request, f"Invalid status filter: {escape(status_filter)}")
            status_filter = '' # Clear invalid filter

    context = {
        'orders': orders,
        'status_filter': status_filter,
        'status_choices': ORDER_STATUS_CHOICES,
    }
    return render(request, 'adminpanel/order_list.html', context)

@login_required
def order_detail(request, order_id):
    """
    Displays details for a specific order.
    Handles dispute resolution form submission (requires PGP auth).
    """
    if not is_staff(request.user):
        messages.error(request, "Access Denied.")
        return redirect('/')

    is_pgp_authenticated = check_pgp_auth_session(request)

    # Require PGP auth strictly for POST actions like resolving disputes
    if request.method == 'POST' and 'resolve_dispute_submit' in request.POST and not is_pgp_authenticated:
        messages.error(request, "PGP authentication session required to resolve dispute.")
        return redirect('adminpanel:order_detail', order_id=order_id)
    # Warn on GET if PGP auth is missing but actions might be possible
    elif request.method != 'POST' and not is_pgp_authenticated:
        messages.warning(request, "PGP authentication required for performing actions on this page.")

    # Fetch order with related objects
    order = get_object_or_404(
        Order.objects.select_related('buyer', 'vendor', 'product', 'payment'),
        pk=order_id
    )
    context = {'order': order}
    form_error_message = None
    resolve_form = None # Initialize form variable

    # Handle Dispute Resolution POST request
    # Use constant for status check
    disputed_status = getattr(Order.StatusChoices, 'DISPUTED', 'disputed') # Default if const missing
    if order.status == disputed_status and request.method == 'POST' and 'resolve_dispute_submit' in request.POST:
        resolve_form = ResolveDisputeForm(request.POST)
        if resolve_form.is_valid():
            notes = resolve_form.cleaned_data['resolution_notes']
            percent = resolve_form.cleaned_data['release_to_buyer_percent']

            # --- Select Correct Escrow Service MODULE ---
            selected_module = None
            service_func_name = 'resolve_dispute' # Function name expected in modules

            if order.selected_currency == Currency.BTC:
                selected_module = btc_escrow_module
            elif order.selected_currency == Currency.XMR:
                selected_module = xmr_escrow_module
            elif order.selected_currency == Currency.ETH:
                if order.escrow_type == EscrowType.BASIC:
                    selected_module = simple_eth_escrow_module
                else: # Default to standard multisig ETH service MODULE
                    selected_module = eth_escrow_module
            # ------------------------------------

            if selected_module:
                # Check if the required function exists in the selected module
                if hasattr(selected_module, service_func_name):
                    resolve_func = getattr(selected_module, service_func_name)
                    try:
                        # Call the selected escrow service FUNCTION
                        success = resolve_func(
                            order=order,
                            moderator=request.user,
                            resolution_notes=notes,
                            release_to_buyer_percent=percent # Pass as integer
                        )
                        if success:
                            messages.success(request, f"Dispute resolved for Order {order.id}. Funds release process logged/initiated.")
                            # Use AuditLogAction enum if available
                            log_action = getattr(AuditLogAction, 'DISPUTE_RESOLVE', 'dispute_resolve')
                            log_admin_action(
                                request, request.user, log_action, target_order=order,
                                details=f"Resolution: {percent}% to Buyer. Notes:{notes[:100]}..." # Log truncated notes
                            )
                            order.refresh_from_db() # Update order status in context
                            context['resolve_form'] = None # Clear form on success
                            resolve_form = None # Clear submitted form too
                        else:
                            # The service function returned False (expected failure)
                            messages.error(request, "Failed to process dispute resolution. Service indicated failure. Please check system logs.")
                            form_error_message = "Processing failed. See logs for details."

                    # --- Catch specific expected exceptions from escrow services ---
                    except (EscrowError, CryptoProcessingError, LedgerError, InsufficientFundsError, PostBroadcastUpdateError, ValueError, ObjectDoesNotExist, PermissionDenied) as service_err:
                        logger.error(f"Error resolving dispute for Order ID {order.id} using {selected_module.__name__}: {service_err}", exc_info=True)
                        # Provide a slightly more specific error message based on the exception type
                        if isinstance(service_err, PostBroadcastUpdateError):
                             error_msg = f"CRITICAL: Broadcast OK (TX: {service_err.tx_hash}) but DB/Ledger update FAILED. Requires manual review."
                        elif isinstance(service_err, CryptoProcessingError):
                            error_msg = f"Crypto processing error: {service_err}"
                        elif isinstance(service_err, LedgerError):
                             error_msg = f"Ledger processing error: {service_err}"
                        else:
                            error_msg = f"Escrow processing error: {service_err}"
                        messages.error(request, error_msg)
                        form_error_message = f"Processing failed: {service_err}"
                    # --- Catch unexpected exceptions ---
                    except Exception as e:
                        logger.exception(f"Unexpected error resolving dispute for Order ID {order.id} using {selected_module.__name__}: {e}")
                        messages.error(request, f"An unexpected server error occurred: {e}")
                        form_error_message = "Server error occurred."
                else:
                    # Function doesn't exist in the module
                    logger.error(f"'{service_func_name}' function not found in module {selected_module.__name__} for Order {order.id}")
                    messages.error(request, f"Dispute resolution function not available for {order.selected_currency}/{order.escrow_type}.")
                    form_error_message = "Resolution function unavailable."
            else: # No service module found for the currency/type
                 if not form_error_message: # Avoid overwriting specific error message above
                    messages.error(request, f"Cannot resolve dispute: No escrow service configured or available for currency '{order.selected_currency}' and type '{order.escrow_type}'.")
                    form_error_message = "Unsupported currency/escrow type for dispute resolution."

        else: # Form is invalid
            messages.error(request, f"Invalid resolution data provided: {resolve_form.errors.as_json()}")
            form_error_message = "Invalid data submitted."

        # If there was an error or form was invalid, pass the form back to the template
        if form_error_message:
            context['resolve_form'] = resolve_form # Pass back the submitted form with errors
            context['resolve_form_error'] = form_error_message

    # Prepare form for GET request if the order is currently disputed and no POST error occurred
    elif order.status == disputed_status and not form_error_message:
         context['resolve_form'] = ResolveDisputeForm()


    return render(request, 'adminpanel/order_detail.html', context)

# --- NEW VENDOR APPLICATION VIEWS ---

@login_required
def vendor_application_list(request):
    """Displays a list of vendor applications needing review."""
    if not is_staff(request.user):
        messages.error(request, "Access Denied.")
        return redirect('/')

    # PGP auth not strictly required to view, but recommend if actions are possible from list
    if not check_pgp_auth_session(request):
        messages.warning(request, "PGP authentication recommended for potential actions.")

    # Filter applications needing review
    applications = VendorApplication.objects.filter(
        status=VENDOR_APP_STATUS_PENDING_REVIEW
    ).select_related('user').order_by('created_at')

    context = {
        'applications': applications,
        'page_title': "Pending Vendor Applications",
    }
    return render(request, 'adminpanel/vendor_application_list.html', context)

@login_required
def review_vendor_application(request, application_id):
    """
    Displays details of a specific vendor application and allows staff
    to approve or reject it. Requires Staff + PGP Auth for actions.
    """
    if not is_staff(request.user):
        messages.error(request, "Access Denied.")
        return redirect('/') # Or 'adminpanel:admin_dashboard'

    application = get_object_or_404(
        VendorApplication.objects.select_related('user'),
        pk=application_id
    )

    is_pgp_authenticated = check_pgp_auth_session(request)
    log_prefix = f"[ReviewVendorApp:{application.id}|User:{application.user.username}]"
    form = None # Initialize form

    # Handle POST actions (Approve/Reject)
    if request.method == 'POST':
        if not is_pgp_authenticated:
            messages.error(request, "PGP authentication required to approve or reject applications.")
            # Redirect back to the detail view
            return redirect('adminpanel:review_vendor_application', application_id=application.id)

        # Check if application is still pending review before processing action
        application.refresh_from_db() # Get latest status
        if application.status != VENDOR_APP_STATUS_PENDING_REVIEW:
            messages.warning(request, f"Application is no longer pending review (Current status: {application.get_status_display()}). Action aborted.")
            return redirect('adminpanel:vendor_application_list') # Redirect to list

        action_type = None
        if 'approve_submit' in request.POST:
            action_type = 'approve'
            form = VendorActionReasonForm(request.POST, prefix='approve') # Use prefix to differentiate forms if needed
        elif 'reject_submit' in request.POST:
            action_type = 'reject'
            form = VendorActionReasonForm(request.POST, prefix='reject')

        if not action_type:
            messages.error(request, "Invalid action submitted.")
            return redirect('adminpanel:review_vendor_application', application_id=application.id)

        # Use the same form for both, but reason is mandatory for rejection
        reason_is_required = (action_type == 'reject')

        if form.is_valid():
            reason = form.cleaned_data.get('reason', '')
            if reason_is_required and not reason:
                # Add form error if reason was required but not provided
                form.add_error('reason', 'A reason is required to reject the application.')
                # Fall through to re-render form with error
            else:
                # --- Proceed with Action (within transaction) ---
                try:
                    with transaction.atomic():
                        target_user = application.user # Get the related user

                        if action_type == 'approve':
                            # --- Approve Logic ---
                            application.status = VENDOR_APP_STATUS_APPROVED
                            # These fields might not exist on VendorApplication, check model
                            # application.reviewed_by = request.user
                            # application.reviewed_at = timezone.now()
                            application.rejection_reason = None # Clear any previous reason
                            application.save(update_fields=['status', 'rejection_reason', 'updated_at']) # Add relevant fields

                            # Update user status
                            target_user.is_vendor = True
                            target_user.approved_vendor_since = timezone.now()
                            target_user.save(update_fields=['is_vendor', 'approved_vendor_since'])

                            # Logging and Notifications
                            log_details = f"Approved Vendor Application {application.id}. Notes: {reason or 'N/A'}"
                            # Use AuditLogAction enum if available
                            log_action = getattr(AuditLogAction, 'VENDOR_APP_APPROVE', 'vendor_app_approve')
                            log_admin_action(request, request.user, log_action, target_application=application, target_user=target_user, details=log_details)
                            messages.success(request, f"Vendor application for '{escape(target_user.username)}' approved successfully.")
                            security_logger.info(f"VENDOR APP APPROVED: AppID:{application.id}, User:{target_user.username}, By:{request.user.username}")
                            try:
                                if notification_service:
                                    notification_service.create_notification(
                                        user_id=target_user.id, level='success',
                                        message="Congratulations! Your vendor application has been approved."
                                    )
                            except Exception as notify_e:
                                logger.error(f"{log_prefix} Failed sending approval notification: {notify_e}")

                        elif action_type == 'reject':
                            # --- Reject Logic ---
                            application.status = VENDOR_APP_STATUS_REJECTED
                            # application.reviewed_by = request.user # Add if needed
                            # application.reviewed_at = timezone.now() # Add if needed
                            application.rejection_reason = reason # Store the reason
                            application.save(update_fields=['status', 'rejection_reason', 'updated_at']) # Add relevant fields

                            # Ensure user is NOT a vendor (in case of reversal/mistake)
                            if target_user.is_vendor:
                                target_user.is_vendor = False
                                target_user.approved_vendor_since = None
                                target_user.save(update_fields=['is_vendor', 'approved_vendor_since'])
                                logger.warning(f"{log_prefix} User was marked as vendor during rejection. Status corrected.")

                            # --- Bond Handling on Rejection ---
                            # For now, log that bond is NOT automatically returned/forfeited.
                            # Implement separate admin action for bond return/forfeit if needed later.
                            bond_info = f"{application.bond_amount_crypto} {application.bond_currency}" if application.bond_amount_crypto else "N/A"
                            logger.warning(f"{log_prefix} Application rejected. Bond ({bond_info}) is NOT automatically returned or forfeited via this action.")

                            # Logging and Notifications
                            log_details = f"Rejected Vendor Application {application.id}. Reason: {reason}"
                             # Use AuditLogAction enum if available
                            log_action = getattr(AuditLogAction, 'VENDOR_APP_REJECT', 'vendor_app_reject')
                            log_admin_action(request, request.user, log_action, target_application=application, target_user=target_user, details=log_details)
                            messages.warning(request, f"Vendor application for '{escape(target_user.username)}' has been rejected.")
                            security_logger.warning(f"VENDOR APP REJECTED: AppID:{application.id}, User:{target_user.username}, By:{request.user.username}. Reason: {reason}")
                            try:
                                if notification_service:
                                    notification_service.create_notification(
                                        user_id=target_user.id, level='error',
                                        message=f"Your vendor application has been rejected. Reason: {reason}"
                                    )
                            except Exception as notify_e:
                                logger.error(f"{log_prefix} Failed sending rejection notification: {notify_e}")

                    # Redirect after successful transaction
                    return redirect('adminpanel:vendor_application_list')

                except Exception as e:
                    logger.exception(f"{log_prefix} Error processing application action '{action_type}': {e}")
                    messages.error(request, "An unexpected server error occurred while processing the application.")
                    # Fall through to re-render form

        # If form is invalid (e.g., missing reason for rejection), fall through to re-render GET response with the invalid form
        if form and not form.is_valid():
             messages.error(request, "Invalid input. Please provide a reason if rejecting.")
        # Note: 'form' might be None if action_type wasn't set, handled above.

    # GET Request or failed POST: Render detail page
    # Prepare forms for GET request, ensuring prefixes match potential POST submissions
    approve_form_instance = form if request.method == 'POST' and action_type == 'approve' and not form.is_valid() else VendorActionReasonForm(prefix='approve')
    reject_form_instance = form if request.method == 'POST' and action_type == 'reject' and not form.is_valid() else VendorActionReasonForm(prefix='reject')

    context = {
        'application': application,
        'approve_form': approve_form_instance,
        'reject_form': reject_form_instance,
        'page_title': f"Review Vendor Application #{application.id}",
        'is_pgp_authenticated': is_pgp_authenticated,
    }
    return render(request, 'adminpanel/vendor_application_detail.html', context)


# --- Owner Panel Views (Require 'Owner' Group Membership) ---

@login_required
def owner_dashboard(request):
    """Displays the owner dashboard with global settings and critical stats."""
    if not is_owner(request.user):
        messages.error(request, "Access Denied. Owner privileges required.")
        return redirect('adminpanel:admin_dashboard') # Redirect to staff dash if not owner

    # Owner actions always require active PGP auth
    if not check_pgp_auth_session(request):
        messages.error(request, "PGP authentication required for owner panel access.")
        # Redirect to login might be too disruptive, maybe redirect to PGP auth page?
        # For now, redirecting to admin dash with error. Consider a dedicated PGP auth prompt page.
        return redirect('adminpanel:admin_dashboard')

    settings_obj = GlobalSettings.load()
    # Pre-populate form with current settings
    initial_data = {
        k: v for k, v in settings_obj.__dict__.items() if hasattr(GlobalSettingsForm.Meta, 'fields') and k in GlobalSettingsForm.Meta.fields
    } if settings_obj else {} # Handle case where settings_obj is None
    settings_form = GlobalSettingsForm(initial=initial_data)

    # Gather stats
    total_users = User.objects.count()
    total_vendors = User.objects.filter(is_vendor=True).count()
    total_orders = Order.objects.count()
    pending_vendor_apps = VendorApplication.objects.filter(status=VENDOR_APP_STATUS_PENDING_REVIEW).count()

    context = {
        'total_users': total_users,
        'total_vendors': total_vendors,
        'total_orders': total_orders,
        'pending_vendor_apps': pending_vendor_apps, # Added stat
        'settings_form': settings_form,
        'current_settings': settings_obj,
    }
    return render(request, 'adminpanel/owner_dashboard.html', context)

@login_required
@transaction.atomic # Ensure settings save is atomic
def update_global_settings(request):
    """Handles submission of the global settings form. Requires Owner + PGP."""
    if not is_owner(request.user):
        messages.error(request, "Access Denied. Owner privileges required.")
        return redirect('adminpanel:admin_dashboard')

    if not check_pgp_auth_session(request):
        messages.error(request, "PGP authentication required to update settings.")
        return redirect('adminpanel:owner_dashboard')

    if request.method != 'POST':
        # Only allow POST requests to modify settings
        return redirect('adminpanel:owner_dashboard')

    settings_obj = GlobalSettings.load()
    if settings_obj is None:
        # Handle case where settings haven't been created yet
        logger.error("GlobalSettings object not found during update attempt.")
        messages.error(request, "Global settings record not found. Cannot update.")
        return redirect('adminpanel:owner_dashboard')

    form = GlobalSettingsForm(request.POST, instance=settings_obj)

    canary_changed = 'canary_content' in form.changed_data
    canary_sig_input = request.POST.get('canary_signature_input', '').strip()
    canary_sig_verified = False

    # --- Canary Signature Verification (if canary content changed) ---
    if canary_changed:
        if not canary_sig_input:
            form.add_error('canary_signature_input', 'PGP Signature is required to update the Warrant Canary.')
        else:
            try:
                new_canary_content = form.cleaned_data.get('canary_content', '').strip()
                # Ensure consistent date format for signature verification
                current_date_str = timezone.now().date().isoformat()
                data_to_verify = f"{new_canary_content}\n{current_date_str}"
                owner_key = request.user.pgp_public_key

                if not owner_key:
                    raise ValueError("Owner's PGP public key is missing from profile.")

                # Verify the signature using the PGP service
                # Ensure pgp_service was imported correctly and is available
                if 'pgp_service' not in locals() or pgp_service is None:
                     raise ImportError("pgp_service is not available.")

                verified = pgp_service.verify_message_signature(
                    user=request.user, # Pass user object if needed by service
                    signature=canary_sig_input,
                    expected_message=data_to_verify
                )

                if not verified:
                    logger.warning(f"Owner {request.user.username} failed Warrant Canary PGP signature verification.")
                    form.add_error('canary_signature_input', 'PGP Signature verification failed. Ensure message and date are correct.')
                else:
                    canary_sig_verified = True
                    logger.info(f"Owner {request.user.username} successfully verified Warrant Canary PGP signature.")

            except ValueError as ve: # Specific error for missing key
                logger.error(f"Cannot verify canary signature: {ve}")
                form.add_error('canary_signature_input', f"Error: {ve}")
            except Exception as e:
                logger.exception(f"Unexpected error during canary signature verification: {e}")
                form.add_error('canary_signature_input', "An server error occurred during signature verification.")

    # --- Save Settings if Form is Valid (and Canary Sig is Verified if needed) ---
    if form.is_valid(): # This check now includes the canary_signature_input errors if added above
        try:
            instance = form.save(commit=False)
            changed_data_log = list(form.changed_data)
            # Exclude the signature input field from the log of changed settings
            if 'canary_signature_input' in changed_data_log:
                changed_data_log.remove('canary_signature_input')

            fields_to_update = list(set(changed_data_log)) # Use set to avoid duplicates

            # If canary changed and signature was verified, update canary fields
            if canary_changed and canary_sig_verified:
                instance.canary_last_updated = timezone.now().date()
                instance.canary_pgp_signature = canary_sig_input # Store the verified signature
                # Ensure these fields are in the list to be updated
                fields_to_update.extend(['canary_content', 'canary_last_updated', 'canary_pgp_signature'])
                fields_to_update = list(set(fields_to_update)) # Remove potential duplicates again

            # Only save if there are actual changes to the settings fields
            if fields_to_update:
                instance.save(update_fields=fields_to_update)
                # form.save_m2m() # Save many-to-many relationships if any (likely none for GlobalSettings)

                # Log and message appropriately
                if canary_changed and canary_sig_verified:
                    messages.success(request, "Warrant Canary updated successfully!")
                    # Use AuditLogAction enum if available
                    log_action = getattr(AuditLogAction, 'CANARY_UPDATE', 'canary_update')
                    log_admin_action(request, request.user, log_action)
                    security_logger.warning(f"WARRANT CANARY UPDATED by owner {request.user.username}")

                # Log other changed settings
                other_changed_fields = [f for f in changed_data_log if f not in ['canary_content', 'canary_last_updated', 'canary_pgp_signature']]
                if other_changed_fields:
                    # Use AuditLogAction enum if available
                    log_action = getattr(AuditLogAction, 'SETTINGS_CHANGE', 'settings_change')
                    log_admin_action(request, request.user, log_action, details=f"Updated settings: {other_changed_fields}")
                    messages.success(request, "Global settings updated successfully.")
                elif not canary_changed: # No canary change and no other changes
                     messages.info(request, "No settings were changed.")


                # Redirect only if save was successful
                return redirect('adminpanel:owner_dashboard')

            else: # No fields changed (e.g., submitted form without modifications)
                 messages.info(request, "No settings were changed.")
                 return redirect('adminpanel:owner_dashboard')

        except Exception as e:
            logger.error(f"Error saving global settings: {e}", exc_info=True)
            messages.error(request, "A server error occurred while saving settings.")
            form.add_error(None, "Error saving settings. Please try again.") # Add non-field error

    # If form is invalid (or save failed), re-render the dashboard with the form containing errors
    context = {
        'settings_form': form, # Pass the form with errors back
        'current_settings': settings_obj, # Pass current settings for display
        # Include stats again if needed by the template
        'total_users': User.objects.count(),
        'total_vendors': User.objects.filter(is_vendor=True).count(),
        'total_orders': Order.objects.count(),
        'pending_vendor_apps': VendorApplication.objects.filter(status=VENDOR_APP_STATUS_PENDING_REVIEW).count(),
    }
    messages.error(request, "Settings update failed. Please review the errors below.")
    return render(request, 'adminpanel/owner_dashboard.html', context)


@login_required
def emergency_actions(request):
    """Handles critical emergency actions like freezing funds. Requires Owner + PGP Sig."""
    if not is_owner(request.user):
        messages.error(request, "Access Denied. Owner privileges required.")
        return redirect('adminpanel:admin_dashboard')

    if not check_pgp_auth_session(request):
        messages.error(request, "PGP authentication required for emergency actions.")
        return redirect('adminpanel:owner_dashboard')

    # Ensure pgp_service was imported correctly and is available
    if 'pgp_service' not in locals() or pgp_service is None:
        logger.critical("pgp_service is not available for emergency actions.")
        messages.error(request, "PGP Service is unavailable. Cannot perform actions.")
        return redirect('adminpanel:owner_dashboard')

    current_settings = GlobalSettings.load()
    if current_settings is None:
        logger.error("GlobalSettings object not found for emergency actions.")
        messages.error(request, "Global settings record not found. Cannot perform actions.")
        return redirect('adminpanel:owner_dashboard')
    context = {'current_settings': current_settings}

    if request.method == 'POST':
        action = request.POST.get('emergency_action')
        nonce = request.POST.get('action_nonce')
        signature = request.POST.get('action_signature')

        # Basic validation of required POST fields
        if not all([action, nonce, signature]):
            messages.error(request, "Missing confirmation fields. Action not performed.")
            # Re-render the GET view state, possibly indicating the failed attempt
            return render(request, 'adminpanel/emergency_actions.html', context)

        # --- Verify PGP Signature for the Action ---
        is_action_verified = False # Default to false
        try:
            is_action_verified = pgp_service.verify_action_signature(
                user=request.user,
                action_key=action, # Use action name directly as key
                nonce=nonce,
                signed_message=signature # Use 'signed_message' to match PGP service convention
            )
        except Exception as pgp_err:
            logger.error(f"Error during PGP verification for emergency action '{action}': {pgp_err}", exc_info=True)
            messages.error(request, "An error occurred during PGP signature verification.")
            context['verification_error'] = True
            return render(request, 'adminpanel/emergency_actions.html', context)


        if not is_action_verified:
            messages.error(request, "Emergency action FAILED: PGP signature verification failed.")
            security_logger.critical(
                f"FAILED emergency action attempt by {request.user.username}: "
                f"PGP verification failed for action '{action}', Nonce '{nonce}'"
            )
            context['verification_error'] = True # Add flag for template feedback
            return render(request, 'adminpanel/emergency_actions.html', context)

        # --- Signature Verified - Proceed with Action ---
        security_logger.warning(
            f"PGP VERIFIED emergency action '{action}' submitted by owner {request.user.username} (Nonce:{nonce})"
        )

        # Reload settings just before modification within the verified block
        settings_obj = GlobalSettings.load()
        if settings_obj is None:
            logger.error("GlobalSettings re-load failed before applying emergency action.")
            messages.error(request, "Global settings record could not be reloaded. Action aborted.")
            return redirect('adminpanel:owner_dashboard')


        if action == 'freeze_funds':
            if not settings_obj.freeze_funds:
                settings_obj.freeze_funds = True
                settings_obj.save(update_fields=['freeze_funds'])
                 # Use AuditLogAction enum if available
                log_action = getattr(AuditLogAction, 'FUNDS_FREEZE', 'funds_freeze')
                log_admin_action(request, request.user, log_action)
                messages.warning(request, "Emergency Fund Freeze has been ACTIVATED!")
                security_logger.critical(f"FUNDS FREEZE ACTIVATED by owner {request.user.username}")
            else:
                messages.info(request, "Funds are already frozen. No change made.")
        elif action == 'unfreeze_funds':
            if settings_obj.freeze_funds:
                settings_obj.freeze_funds = False
                settings_obj.save(update_fields=['freeze_funds'])
                 # Use AuditLogAction enum if available
                log_action = getattr(AuditLogAction, 'FUNDS_UNFREEZE', 'funds_unfreeze')
                log_admin_action(request, request.user, log_action)
                messages.success(request, "Emergency Fund Freeze has been DEACTIVATED.")
                security_logger.warning(f"FUNDS UNFREEZE performed by owner {request.user.username}")
            else:
                messages.info(request, "Funds are not currently frozen. No change made.")
        elif action == 'transfer_funds':
            # Placeholder - Implement actual fund transfer logic securely elsewhere
            logger.error("Owner fund transfer action attempted but is NOT IMPLEMENTED.")
            messages.error(request, "Emergency fund transfer action is not yet implemented.")
            security_logger.error(f"Failed fund transfer attempt by {request.user.username}: Feature not implemented.")
        else:
            messages.error(request, "Invalid emergency action specified.")
            security_logger.error(f"Invalid emergency action '{action}' submitted by {request.user.username}")

        # Redirect after action performed (or attempted)
        return redirect('adminpanel:owner_dashboard')

    # --- GET Request: Prepare Confirmation Challenge ---
    action_to_confirm = request.GET.get('confirm_action')
    message_to_sign = None
    action_nonce = None

    # Check if a valid action confirmation is requested via GET parameter
    if action_to_confirm in ['freeze_funds', 'unfreeze_funds', 'transfer_funds']:
        # Prepare context needed for the challenge message (e.g., current status)
        challenge_context = {'current_freeze_status': current_settings.freeze_funds}

        try:
            message_to_sign, action_nonce = pgp_service.generate_action_challenge(
                user=request.user,
                action_key=action_to_confirm, # Use action name directly as key
                context=challenge_context
            )
        except Exception as pgp_gen_err:
            logger.error(f"Failed to generate PGP challenge for {request.user.username}, action {action_to_confirm}: {pgp_gen_err}", exc_info=True)
            message_to_sign = None # Ensure it's None on error


        if not message_to_sign:
            messages.error(request, "Failed to generate the PGP confirmation message. Cannot proceed.")
            # Log this failure, it might indicate a PGP setup issue
            logger.error(f"Failed to generate PGP challenge for {request.user.username}, action {action_to_confirm}")
        else:
            # Pass challenge details to the template
            context.update({
                'action_to_confirm': action_to_confirm,
                'message_to_sign': message_to_sign,
                'action_nonce': action_nonce,
            })
            messages.info(request, f"Please sign the following message with your PGP key to confirm the '{action_to_confirm}' action.")

    return render(request, 'adminpanel/emergency_actions.html', context)


# --- Remaining Vendor Management Actions (Require Staff + PGP Auth) ---

# REMOVED: approve_vendor view - Logic handled by review_vendor_application

# REMOVED: reject_vendor view - Logic handled by review_vendor_application.
#          (Consider a new view for revoking status from *already approved* vendors if needed).


# TODO: Review if MarkBondPaidForm needs updates to align with data required by this view.
#       Consider removing the BTC-only limitation if manual marking for other currencies is desired.
# This view provides a manual override for the automated bond detection (via Celery task) for edge cases.
@login_required
@transaction.atomic # Ensure user update and log are atomic
def mark_bond_paid(request, user_id):
    """Manually marks a vendor's bond as paid. Requires Staff + PGP."""
    if not is_staff(request.user):
        messages.error(request, "Access Denied.")
        return redirect('/')

    if not check_pgp_auth_session(request):
        messages.error(request, "PGP authentication required to mark bond as paid.")
        return redirect('adminpanel:user_detail', user_id=user_id)

    target_user = get_object_or_404(User, id=user_id)

    # Find related Application that is awaiting bond payment
    # Ensure VendorApplication model was imported
    if 'VendorApplication' not in globals():
        logger.error("VendorApplication model not available in mark_bond_paid.")
        messages.error(request, "Required model not available.")
        return redirect('adminpanel:user_detail', user_id=user_id)

    application = VendorApplication.objects.filter(user=target_user, status=VENDOR_APP_STATUS_PENDING_BOND).first()
    if not application:
        messages.error(request, "No vendor application found in 'Pending Bond' status for this user.")
        return redirect('adminpanel:user_detail', user_id=user_id)

    # Check if bond is already marked as paid on Application (using relevant fields)
    # Check 'bond_paid_atomic' or similar field indicating successful payment confirmation
    # The exact field name might depend on updates to VendorApplication model
    bond_paid_flag = application.bond_paid_atomic is not None and application.bond_paid_atomic > 0 # Example check
    paid_txid = getattr(application, 'bond_paid_txid', None) # Example field name

    if bond_paid_flag:
        messages.warning(request, f"Vendor bond for Application #{application.id} ('{escape(target_user.username)}') appears to be already paid (TXID: {paid_txid or 'N/A'}). Status is {application.get_status_display()}.")
        return redirect('adminpanel:user_detail', user_id=user_id) # Or redirect to review view?

    if request.method == 'POST':
        form = MarkBondPaidForm(request.POST) # Form likely needs updating too
        if form.is_valid():
            currency = form.cleaned_data['bond_currency']
            amount = form.cleaned_data['bond_amount']
            txid = form.cleaned_data.get('external_txid', '')
            notes = form.cleaned_data.get('notes', 'Manual override by admin.')

            # Ensure amount is positive
            if not amount or amount <= Decimal('0.0'):
                messages.error(request, "Bond amount must be a positive value.")
                context = {'target_user': target_user, 'application': application, 'form': form}
                return render(request, 'adminpanel/vendor_mark_bond_paid.html', context) # Needs template update

            # --- Validate Currency and Convert Amount ---
            # Use the imported ATOMIC_FACTOR constant
            if currency not in ATOMIC_FACTOR:
                 messages.error(request, f"Invalid or unsupported currency '{currency}' for manual bond marking.")
                 context = {'target_user': target_user, 'application': application, 'form': form}
                 return render(request, 'adminpanel/vendor_mark_bond_paid.html', context)

            try:
                 factor = ATOMIC_FACTOR[currency]
                 amount_atomic = int(amount * factor) # Convert standard decimal to atomic integer
                 if amount_atomic <= 0: raise ValueError("Calculated atomic amount is not positive.")
            except (ValueError, TypeError, KeyError) as conv_e:
                messages.error(request, f"Invalid amount format for {currency}: {amount}")
                logger.error(f"Error converting manual bond amount {amount} {currency} to atomic: {conv_e}")
                context = {'target_user': target_user, 'application': application, 'form': form}
                return render(request, 'adminpanel/vendor_mark_bond_paid.html', context)

            # --- Update Application Status ---
            # Update the application record
            application.status = VENDOR_APP_STATUS_PENDING_REVIEW
            application.bond_currency = currency # Record the currency marked manually (check model field name)
            application.bond_paid_atomic = amount_atomic # Store atomic amount (check model field name)
            application.bond_paid_txid = txid or f"MANUAL_{secrets.token_hex(8)}" # Generate placeholder if missing (check model field name)
            # application.bond_paid_confirmations = 999 # Indicate manual confirmation (check model field name)
            application.paid_at = timezone.now() # Store payment time (check model field name)
            application.notes = (getattr(application, 'notes', "") or "") + f"\nBond manually marked paid by {request.user.username}. {notes}" # Check model field name

            # Define fields to update based on VendorApplication model definition
            update_fields = [
                 'status', 'bond_currency', 'bond_paid_atomic', 'bond_paid_txid',
                 'paid_at', 'notes', 'updated_at'
                 # Add/remove fields like 'bond_paid_confirmations' based on actual model
            ]
            application.save(update_fields=update_fields)


            log_details = f"AppID:{application.id} Bond marked paid (Manual): {amount} {currency}. TXID:{txid or 'N/A'}. Notes:{notes}"
            # Ensure 'vendor_bond_paid_mark' is a valid choice in AuditLogAction enum or use a generic one
            log_action = getattr(AuditLogAction, 'VENDOR_BOND_PAID_MARK', AuditLogAction.ADMIN_ACTION) # Default to ADMIN_ACTION if specific not found
            log_admin_action(request, request.user, log_action, target_application=application, target_user=target_user, details=log_details)
            messages.success(request, f"Vendor bond manually marked as paid for Application #{application.id} ('{escape(target_user.username)}'). Status set to Pending Review.")
            security_logger.info(f"Vendor Bond Paid (Marked Manually): AppID:{application.id} User:{target_user.username} by {request.user.username}. Amount: {amount} {currency}")

            # Notify Admins?
            try:
                 if notification_service:
                     notification_service.create_notification(
                         # recipient_group='Admin', # Target specific admins/group if possible
                         level='info',
                         message=f"Vendor Application #{application.id} ('{target_user.username}') bond was manually marked paid by {request.user.username} and requires review."
                     )
                     logger.info(f"Sent admin review notification for manually paid bond App:{application.id}")
            except Exception as notify_e:
                 logger.error(f"Failed sending admin notification for manual bond mark App:{application.id}: {notify_e}")

            # Redirect to the application review page after successfully marking bond paid
            return redirect('adminpanel:review_vendor_application', application_id=application.id)

        else: # Form is invalid
            messages.error(request, "Invalid data provided. Please check the form.")
            context = {'target_user': target_user, 'application': application, 'form': form}
            return render(request, 'adminpanel/vendor_mark_bond_paid.html', context) # Needs template update

    # GET request: Show the form to mark bond paid
    form = MarkBondPaidForm()
    # Pre-fill currency based on application if available
    if application and application.bond_currency:
         form.fields['bond_currency'].initial = application.bond_currency
    # Pre-fill amount if available on application
    if application and application.bond_amount_crypto:
         form.fields['bond_amount'].initial = application.bond_amount_crypto

    context = {'target_user': target_user, 'application': application, 'form': form}
    return render(request, 'adminpanel/vendor_mark_bond_paid.html', context) # Needs template update


# --- Updated forfeit_bond View (with Ledger Integration, Forfeit Only) ---
# TODO: Confirm the source of truth for bond amount/currency *after* vendor approval.
#       Should it remain on the application, or copied to User? (Application preferred).
#       This view now primarily uses the Application model. Remove fallback to User model fields.
@login_required
@transaction.atomic # Ensure ledger update + application update are atomic
def forfeit_bond(request, user_id):
    """ Admin marks bond forfeited, crediting market ledger. Requires Staff + PGP Auth. """
    # --- Permission Checks ---
    if not is_staff(request.user):
        messages.error(request, "Access Denied.")
        return redirect('/')
    if not check_pgp_auth_session(request):
        messages.error(request, "PGP authentication required to forfeit bond.")
        return redirect('adminpanel:user_detail', user_id=user_id)

    # --- Service Availability Check ---
    if 'ledger_service' not in locals() or ledger_service is None:
        logger.critical("Ledger service not available in forfeit_bond.")
        messages.error(request, "Ledger service unavailable. Cannot process bond action.")
        return redirect('adminpanel:user_detail', user_id=user_id)
    market_user = get_market_user() # Use the imported/fallback helper
    if market_user is None:
        logger.critical("Market User helper not available or failed in forfeit_bond.")
        messages.error(request, "Market user helper unavailable. Cannot process bond forfeiture.")
        return redirect('adminpanel:user_detail', user_id=user_id)


    # --- Target User and Bond Status Validation ---
    target_user = get_object_or_404(User, id=user_id)
    # Forfeiture primarily makes sense for approved vendors or potentially rejected apps
    # We need to find the application record that holds the bond details.

    # Find the latest application for the user that has a paid bond.
    # This covers both approved vendors (whose app status is APPROVED) and potentially
    # other scenarios where forfeiture might apply based on policy.
    # Check VendorApplication model availability
    if 'VendorApplication' not in globals():
         logger.error("VendorApplication model not available in forfeit_bond.")
         messages.error(request, "Required model not available.")
         return redirect('adminpanel:user_detail', user_id=user_id)

    application = VendorApplication.objects.filter(
        user=target_user,
        bond_paid_atomic__isnull=False, # Check the field indicating payment
        bond_paid_atomic__gt=0
        # Add status filters if forfeiture is only allowed for specific statuses (e.g., APPROVED)
        # Q(status=VENDOR_APP_STATUS_APPROVED) | Q(status=...)
    ).order_by('-created_at').first()

    bond_currency = None
    bond_amount = None # Standard Decimal amount for ledger
    bond_amount_atomic = None # Atomic amount from application

    # Get bond details SOLELY from the application record
    if application and application.bond_paid_atomic and application.bond_paid_atomic > 0:
        bond_currency = application.bond_currency # Check actual field name in model
        bond_amount_atomic = application.bond_paid_atomic

        if not bond_currency:
            logger.error(f"Missing bond_currency on Application {application.id} during forfeit attempt.")
            messages.error(request, f"Bond currency information missing for application {application.id}. Cannot forfeit.")
            return redirect('adminpanel:user_detail', user_id=user_id)

        try:
            factor = ATOMIC_FACTOR.get(bond_currency) # Uses the imported constant
            if factor:
                bond_amount = Decimal(str(bond_amount_atomic)) / factor
            else:
                raise ValueError(f"Missing ATOMIC_FACTOR for currency {bond_currency}")
        except Exception as conv_e:
            logger.error(f"Error converting atomic bond amount {bond_amount_atomic} {bond_currency} for App {application.id}: {conv_e}")
            messages.error(request, "Error processing bond amount. Cannot forfeit.")
            return redirect('adminpanel:user_detail', user_id=user_id)

        logger.info(f"Found bond info on Application {application.id}: {bond_amount_atomic} atomic {bond_currency}")
    # else: # REMOVED fallback to User model fields

    # --- Handle Missing Bond Info (if no suitable application found) ---
    if not application or not bond_currency or not bond_amount or bond_amount_atomic is None:
        logger.error(f"Could not determine valid bond amount/currency to forfeit for User {target_user.username} (ID: {target_user.id}). No suitable VendorApplication record found with paid bond.")
        messages.error(request, f"Could not find valid, paid bond information on any application for user '{escape(target_user.username)}'. Cannot forfeit.")
        return redirect('adminpanel:user_detail', user_id=user_id)

    # --- Handle POST Request (Form Submission) ---
    if request.method == 'POST':
        form = VendorActionReasonForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data.get('reason', 'No reason provided.')
            action_type = request.POST.get('action_type') # Check hidden input from form
            if action_type != 'forfeit':
                messages.error(request, "Invalid action type submitted. Expected 'forfeit'.")
                security_logger.warning(f"Invalid action_type '{action_type}' received in forfeit_bond POST for user {target_user.username}")
                return redirect('adminpanel:user_detail', user_id=user_id)

            try:
                # --- Perform Ledger Action (Credit Market User) ---
                ledger_service.credit_funds(
                    user=market_user,
                    currency=bond_currency,
                    amount=bond_amount, # Use standard Decimal amount for ledger
                    transaction_type='VENDOR_BOND_FORFEIT', # Ensure this type exists
                    notes=(f"Bond forfeit from vendor {target_user.username} (ID: {target_user.id}). "
                           f"AppID: {application.id}. Admin: {request.user.username}. Reason: {reason}")
                )

                # --- Clear Bond Info (Only on Application) ---
                # Mark bond as forfeited by setting amount to zero and updating notes. Keep TXID for record.
                application.bond_paid_atomic = 0
                # application.bond_paid_txid = None # Optional: Clear TXID? Or keep for history? Keeping for now.
                application.notes = (getattr(application, 'notes', "") or "") + f"\nBond forfeited by admin {request.user.username} on {timezone.now().date()}. Reason: {reason}" # Check model field name
                application.save(update_fields=['bond_paid_atomic', 'notes', 'updated_at'])
                logger.info(f"Cleared bond amount on Application {application.id} after forfeiture.")

                # REMOVED clearing of User model fields (vendor_bond_paid, vendor_bond_amount_*)

                # --- Logging and Success Message ---
                # Ensure 'vendor_bond_forfeit' is a valid choice in AuditLogAction enum or use a generic one
                log_action_name = getattr(AuditLogAction, 'VENDOR_BOND_FORFEIT', AuditLogAction.ADMIN_ACTION) # Default if not found
                success_msg = f"Vendor bond successfully forfeited for '{escape(target_user.username)}' from Application #{application.id}. Funds credited to market account."
                sec_log_msg = (f"Vendor Bond Forfeited (Ledger Updated): Vendor: {target_user.username}, "
                               f"AppID: {application.id}, Admin: {request.user.username}, Amount: {bond_amount} {bond_currency}. Reason: {reason}")

                log_admin_action(request, request.user, log_action_name, target_user=target_user, target_application=application, details=f"Reason: {reason}")
                messages.success(request, success_msg)
                security_logger.warning(sec_log_msg)
                return redirect('adminpanel:user_detail', user_id=user_id)

            # --- Specific Error Handling (within atomic block) ---
            except InsufficientFundsError as e: # Should not occur on credit
                messages.error(request, f"Ledger error during bond forfeit: {e}")
                logger.error(f"Ledger InsufficientFundsError during bond forfeit U:{target_user.username}, App:{application.id}: {e}", exc_info=True)
                return redirect('adminpanel:user_detail', user_id=user_id)
            except (DjangoValidationError, IntegrityError, ObjectDoesNotExist) as e: # Catch validation, DB, or missing market user errors
                messages.error(request, f"Processing error during bond forfeit: {e}")
                logger.error(f"Processing error during bond forfeit U:{target_user.username}, App:{application.id}: {e}", exc_info=True)
                return redirect('adminpanel:user_detail', user_id=user_id)
            # --- Catch Unexpected Errors ---
            except Exception as e:
                messages.error(request, "An unexpected server error occurred during bond forfeiture.")
                logger.exception(f"Unexpected error during bond forfeit for U:{target_user.username}, App:{application.id}")
                return redirect('adminpanel:user_detail', user_id=user_id)
        else: # Form is invalid
            # Re-render the confirmation page with the form errors
            template = 'adminpanel/vendor_bond_forfeit_confirm.html' # Needs template update
            context = {
                'target_user': target_user,
                'form': form, # Pass form with errors
                'action_type': 'forfeit',
                'bond_currency': bond_currency,
                'bond_amount': bond_amount,
                'application': application # Pass application for context
            }
            messages.error(request,"Invalid reason provided. Please check the form.")
            return render(request, template, context)

    # --- Handle GET Request (Show Confirmation Page) ---
    else:
        form = VendorActionReasonForm()
        template = 'adminpanel/vendor_bond_forfeit_confirm.html' # Needs template update
        context = {
            'target_user': target_user,
            'form': form,
            'action_type': 'forfeit', # Hardcode action type for the template
            'bond_currency': bond_currency,
            'bond_amount': bond_amount,
            'application': application # Pass application for context
        }
        return render(request, template, context)

# --- END OF FILE ---