# --- START UPDATED FILE ---
# File: shadow_market/backend/store/services/reputation_service.py
# Reason: Service layer for calculating vendor reputation metrics and levels.
#         Refactored for production standards, including robust calculations,
#         transaction safety, configuration best practices, and clear logging.

# Standard Library Imports
import logging
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import timedelta
from typing import Dict, Any, Optional # Consider TypedDict for metrics structure if it grows

# Third-Party Imports
from django.utils import timezone
from django.db import transaction
from django.db.models import Avg, Count, Q, F, ExpressionWrapper, DurationField, Case, When, DecimalField
from django.conf import settings

# Local Application Imports
try:
    # BEST PRACTICE: Ensure these models are correctly defined and accessible.
    from store.models import User, Order, Feedback
except ImportError as e:
    # Logging should be configured globally in Django settings.
    # This critical log helps during startup if imports fail.
    logger_init = logging.getLogger(__name__)
    logger_init.critical(f"CRITICAL IMPORT ERROR in reputation_service.py: {e}. Check models and Django setup.")
    # Re-raising is important to halt execution if core models are missing.
    raise ImportError(f"Failed to import models in reputation_service.py: {e}") from e

logger = logging.getLogger(__name__) # Get logger instance after potential initial critical log

# --- Reputation Configuration ---

# BEST PRACTICE: Move these thresholds and configurations to Django settings
# (settings.py) or a dedicated database model (e.g., GlobalSettings)
# to allow changes without code deployment.
# Example access: getattr(settings, 'VENDOR_LEVELS_CONFIG', DEFAULT_VENDOR_LEVELS)

# Define Vendor Levels and their requirements (Example thresholds - tune these carefully!)
# Order matters: Check from highest level down.
DEFAULT_VENDOR_LEVELS = {
    "Trusted": {
        "min_total_orders": 100,
        "min_recent_orders": 20, # e.g., in last N days
        "min_avg_rating": 4.7,
        "max_dispute_rate": 2.0, # percent
        "min_vendor_age_days": 180,
        "bond_required": True,
    },
    "Established": {
        "min_total_orders": 50,
        "min_recent_orders": 10,
        "min_avg_rating": 4.5,
        "max_dispute_rate": 5.0,
        "min_vendor_age_days": 90,
        "bond_required": True,
    },
    "Verified": {
        "min_total_orders": 10,
        "min_recent_orders": 2,
        "min_avg_rating": 4.0,
        "max_dispute_rate": 10.0,
        "min_vendor_age_days": 30,
        "bond_required": True,
    },
    "New Vendor": { # Base level
        "min_total_orders": 0,
        "min_recent_orders": 0,
        "min_avg_rating": 0.0,
        "max_dispute_rate": 100.0, # Allow high rate initially
        "min_vendor_age_days": 0,
        "bond_required": False, # Or True depending on market rules
    },
}
VENDOR_LEVELS = getattr(settings, 'VENDOR_LEVELS_CONFIG', DEFAULT_VENDOR_LEVELS)

DEFAULT_RECENT_DAYS_WINDOW = 90 # How many days count as "recent" for order volume
RECENT_DAYS_WINDOW = getattr(settings, 'REPUTATION_RECENT_DAYS_WINDOW', DEFAULT_RECENT_DAYS_WINDOW)

# BEST PRACTICE: Define status constants in the Order model itself
# e.g., class Order(models.Model): FINALIZED = 'finalized'; DISPUTED = 'disputed'; ...
# Using strings directly here is less maintainable if statuses change.
STATUS_FINALIZED = 'finalized'
STATUS_DISPUTED = 'disputed'
STATUS_DISPUTE_RESOLVED = 'dispute_resolved'
# Add other relevant status constants here...


# --- Service Functions ---

def _calculate_vendor_metrics(vendor: User) -> Dict[str, Any]:
    """
    Calculates raw reputation metrics for a given vendor based on Order and Feedback data.
    Refined logic for completion/dispute rates and includes time-weighted average rating.
    Reads data but does not modify the User object.

    Args:
        vendor: The User instance (must be a vendor).

    Returns:
        A dictionary containing calculated metrics, or an empty dict if not a vendor.
        # CONSIDER: Using a TypedDict or dataclass for better structure and type safety.
    """
    if not vendor or not vendor.is_vendor:
        logger.warning(f"Attempted to calculate metrics for non-vendor: {getattr(vendor, 'username', 'N/A')}")
        return {}

    metrics: Dict[str, Any] = {}
    now = timezone.now()
    recent_cutoff_date = now - timedelta(days=RECENT_DAYS_WINDOW)

    # --- Order Metrics ---
    # Base queryset for vendor's orders
    vendor_orders = Order.objects.filter(vendor=vendor)

    # OPTIMIZATION NOTE: If performance becomes an issue with many orders,
    # consider using a single query with conditional aggregation (Count(Case(When(...))))
    # to calculate multiple counts simultaneously instead of multiple .filter().count() calls.

    # Completed Orders = Finalized only
    # Using STATUS_FINALIZED constant (assuming defined elsewhere or replace with string)
    finalized_orders = vendor_orders.filter(status=STATUS_FINALIZED)
    metrics['total_completed_orders'] = finalized_orders.count()
    metrics['recent_completed_orders'] = finalized_orders.filter(updated_at__gte=recent_cutoff_date).count()

    # Relevant Orders for Rates = Finalized + Dispute Resolved
    # Using status constants (assuming defined elsewhere or replace with strings)
    relevant_statuses_for_rates = [STATUS_FINALIZED, STATUS_DISPUTE_RESOLVED]
    relevant_orders_for_rates = vendor_orders.filter(status__in=relevant_statuses_for_rates)
    total_relevant_orders_count = relevant_orders_for_rates.count()

    # Dispute Count & Rate (Orders that were ever disputed or resolved from dispute)
    # Using status constants (assuming defined elsewhere or replace with strings)
    dispute_related_statuses = [STATUS_DISPUTED, STATUS_DISPUTE_RESOLVED]
    disputed_count = vendor_orders.filter(status__in=dispute_related_statuses).count()
    metrics['total_disputed_orders'] = disputed_count

    if total_relevant_orders_count > 0:
        # Use Decimal for precise rate calculation
        metrics['dispute_rate_percent'] = Decimal(disputed_count) / Decimal(total_relevant_orders_count) * Decimal(100)
    else:
        metrics['dispute_rate_percent'] = Decimal(0.0)
    # Round at the end or store precisely and round only for display
    metrics['dispute_rate_percent'] = metrics['dispute_rate_percent'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


    # Completion Rate (Finalized / Relevant)
    if total_relevant_orders_count > 0:
        metrics['completion_rate_percent'] = (Decimal(metrics['total_completed_orders']) / Decimal(total_relevant_orders_count)) * Decimal(100)
    else:
        # Default to 100% if no relevant orders yet (business decision)
        metrics['completion_rate_percent'] = Decimal(100.0)
    metrics['completion_rate_percent'] = metrics['completion_rate_percent'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


    # --- Feedback Metrics ---
    vendor_feedback = Feedback.objects.filter(recipient=vendor)
    metrics['rating_count'] = vendor_feedback.count()

    # Calculate Weighted Average Rating (Time Decay)
    weighted_avg = Decimal(0.0)
    if metrics['rating_count'] > 0:
        # Calculate age of feedback in days using database functions
        feedback_with_age = vendor_feedback.annotate(
            age_duration=ExpressionWrapper(
                now - F('created_at'), output_field=DurationField()
            )
        ).values('rating', 'age_duration') # Fetch only necessary fields

        total_weight = Decimal(0.0)
        weighted_sum = Decimal(0.0)

        for feedback in feedback_with_age:
            try:
                rating = Decimal(feedback['rating'])
                # Ensure age_duration is valid before calculation
                if feedback['age_duration'] is None:
                     logger.warning(f"Skipping feedback item with null age_duration for Vendor {vendor.username}")
                     continue

                # Calculate days (minimum 1 to avoid division by zero and give recent feedback full weight)
                # Convert timedelta to days as Decimal
                days_old = max(Decimal(feedback['age_duration'].total_seconds()) / Decimal(86400.0), Decimal(1.0))

                # Weighting function: Simple inverse decay (1/days_old).
                # Consider alternatives like exponential decay: weight = exp(-decay_factor * days_old)
                weight = Decimal(1.0) / days_old

                weighted_sum += rating * weight
                total_weight += weight

            except (TypeError, ValueError, InvalidOperation, AttributeError) as calc_err:
                logger.warning(
                    f"Could not process feedback item for weighted average calculation "
                    f"(Vendor: {vendor.username}, Data: {feedback}). Error: {calc_err}",
                    exc_info=True # Log traceback for debugging
                )
                continue # Skip this feedback item

        if total_weight > Decimal(0.0):
            # Calculate weighted average and round precisely using Decimal
            weighted_avg = (weighted_sum / total_weight).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            # Fallback to simple average ONLY if total_weight is zero (e.g., all feedback processing failed)
            logger.warning(f"Weighted average calculation resulted in zero total weight for Vendor {vendor.username}. Falling back to simple average.")
            simple_avg_result = vendor_feedback.aggregate(avg_rating=Avg('rating'))
            avg_rating_raw = simple_avg_result.get('avg_rating')
            if avg_rating_raw is not None:
                 # Convert simple average result to Decimal for consistency
                 weighted_avg = Decimal(avg_rating_raw).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                 weighted_avg = Decimal(0.0) # No valid ratings at all


    # Store the final calculated average rating as Decimal
    metrics['avg_rating'] = weighted_avg # Store as Decimal

    # --- Other Metrics ---
    # Vendor Age
    if vendor.approved_vendor_since:
        # Ensure approved_vendor_since is timezone-aware if 'now' is
        vendor_age = now - vendor.approved_vendor_since
        metrics['vendor_age_days'] = vendor_age.days
    else:
        metrics['vendor_age_days'] = 0

    # Bond Status (Assuming a boolean field on User model)
    metrics['bond_paid'] = getattr(vendor, 'vendor_bond_paid', False) # Use getattr for safety

    logger.debug(f"Calculated metrics for Vendor {vendor.username}: {metrics}")
    return metrics


def _determine_vendor_level(metrics: Dict[str, Any]) -> str:
    """
    Determines the vendor level name based on calculated metrics and defined thresholds.

    Args:
        metrics: The dictionary of calculated metrics from _calculate_vendor_metrics.

    Returns:
        The name (string) of the determined vendor level.
    """
    # Default level if metrics are missing (e.g., non-vendor passed validation earlier)
    default_level = "New Vendor"
    if not metrics:
        logger.warning("Attempted to determine level with empty metrics. Assigning default.")
        return default_level

    # Iterate through levels defined in VENDOR_LEVELS (ensure order is intended, highest first)
    # Python 3.7+ guarantees insertion order for dicts. If using older Python, use collections.OrderedDict
    for level_name, requirements in VENDOR_LEVELS.items():
        if level_name == default_level:
            continue # Base level is checked last if others fail

        try:
            meets_requirements = True
            # Check each requirement for the current level
            if metrics.get('total_completed_orders', 0) < requirements['min_total_orders']:
                meets_requirements = False
            elif metrics.get('recent_completed_orders', 0) < requirements['min_recent_orders']:
                meets_requirements = False
            # Compare Decimal metrics directly with float/int thresholds
            elif metrics.get('avg_rating', Decimal(0.0)) < Decimal(str(requirements['min_avg_rating'])):
                 meets_requirements = False
            elif metrics.get('dispute_rate_percent', Decimal(100.0)) > Decimal(str(requirements['max_dispute_rate'])):
                 meets_requirements = False
            elif metrics.get('vendor_age_days', 0) < requirements['min_vendor_age_days']:
                meets_requirements = False
            elif requirements['bond_required'] and not metrics.get('bond_paid', False):
                meets_requirements = False

            if meets_requirements:
                logger.debug(f"Vendor {metrics.get('vendor_username', 'N/A')} meets requirements for level: {level_name}")
                return level_name # Return the first (highest) level met

        except KeyError as req_err:
            logger.error(f"Configuration Error: Missing requirement key '{req_err}' in VENDOR_LEVELS for level '{level_name}'. Skipping level check.")
            continue # Skip this level if config is broken
        except Exception as check_err:
             logger.error(f"Error checking requirements for level '{level_name}': {check_err}", exc_info=True)
             continue # Skip level on unexpected error

    # If no higher levels were met, assign the default level
    logger.debug(f"Vendor {metrics.get('vendor_username', 'N/A')} did not meet higher level requirements. Assigning '{default_level}'.")
    return default_level


def update_vendor_reputation(vendor: User) -> bool:
    """
    Calculates reputation metrics and updates the denormalized fields on the User model.
    Uses an atomic transaction and row locking (`select_for_update`) to prevent race conditions.
    Should be called after relevant events (e.g., feedback left, order finalized) or periodically.

    Args:
        vendor: The User instance to update.

    Returns:
        True if the update was successful, False otherwise.
    """
    if not vendor or not vendor.is_vendor:
        logger.warning(f"Attempted to update reputation for non-vendor: {getattr(vendor, 'username', 'N/A')} (PK: {getattr(vendor, 'pk', 'N/A')})")
        return False

    vendor_pk = vendor.pk # Store PK for logging in case vendor object becomes unavailable
    vendor_username = vendor.username # Store username for logging

    try:
        # Use select_for_update within an atomic transaction to lock the vendor row.
        # This prevents race conditions if multiple events try to update concurrently.
        with transaction.atomic():
            # Re-fetch the vendor instance *inside* the transaction with the lock applied.
            vendor_locked = User.objects.select_for_update().get(pk=vendor_pk)

            # Ensure the locked user is still considered a vendor (status could have changed)
            if not vendor_locked.is_vendor:
                 logger.warning(f"Vendor {vendor_username} (PK: {vendor_pk}) is no longer marked as vendor during locked update. Aborting.")
                 return False # Or handle as needed - maybe clear reputation fields?

            # Calculate metrics using the locked instance (though calculation is read-only)
            metrics = _calculate_vendor_metrics(vendor_locked)
            if not metrics:
                # _calculate_vendor_metrics already logged a warning if it was a non-vendor
                logger.error(f"Failed to calculate metrics for vendor {vendor_username} (PK: {vendor_pk}) inside transaction.")
                # Transaction will rollback automatically on unhandled exception or return False
                return False # Indicate failure

            # Add username to metrics dict for logging within _determine_vendor_level
            metrics['vendor_username'] = vendor_username
            new_level_name = _determine_vendor_level(metrics)

            # --- Update Denormalized Fields on User Model ---
            # Use metrics.get() with defaults for safety, convert types as needed for model fields
            # Assuming model fields are appropriately typed (e.g., FloatField/DecimalField for rates/ratings)
            vendor_locked.vendor_level_name = new_level_name
            vendor_locked.vendor_total_orders = metrics.get('total_completed_orders', 0) # Assuming IntegerField
            # NOTE: Field name 'vendor_completed_orders_30d' might be misleading if RECENT_DAYS_WINDOW != 30
            # Consider renaming field to vendor_completed_orders_recent
            vendor_locked.vendor_completed_orders_30d = metrics.get('recent_completed_orders', 0) # Assuming IntegerField
            # Ensure rates/ratings match model field type (e.g., store as Decimal if model uses DecimalField)
            vendor_locked.vendor_completion_rate_percent = metrics.get('completion_rate_percent', Decimal('100.0'))
            vendor_locked.vendor_dispute_rate_percent = metrics.get('dispute_rate_percent', Decimal('0.0'))
            vendor_locked.vendor_avg_rating = metrics.get('avg_rating', Decimal('0.0'))
            vendor_locked.vendor_rating_count = metrics.get('rating_count', 0) # Assuming IntegerField
            vendor_locked.vendor_reputation_last_updated = timezone.now()

            # BEST PRACTICE: Use update_fields to specify exactly which fields to save.
            # This prevents accidentally overwriting other fields changed concurrently
            # (less likely here due to select_for_update, but still good practice)
            # and can be slightly more performant.
            update_fields = [
                'vendor_level_name', 'vendor_total_orders', 'vendor_completed_orders_30d',
                'vendor_completion_rate_percent', 'vendor_dispute_rate_percent',
                'vendor_avg_rating', 'vendor_rating_count', 'vendor_reputation_last_updated'
            ]

            vendor_locked.save(update_fields=update_fields)
            logger.info(f"Successfully updated reputation for Vendor {vendor_username} (PK: {vendor_pk}). New Level: {new_level_name}")

        # Transaction committed successfully if no exceptions were raised
        return True

    except User.DoesNotExist:
        logger.error(f"Vendor with PK {vendor_pk} not found during reputation update (may have been deleted).")
        return False
    except Exception as e:
        # Log the full exception traceback for debugging unexpected errors
        logger.exception(f"Unexpected error updating reputation for Vendor {vendor_username} (PK: {vendor_pk}): {e}")
        # Transaction automatically rolls back on exception
        return False


def update_all_vendor_reputations() -> None:
    """
    Periodically updates reputation for all active vendors.
    Intended to be called by a scheduled task (e.g., Celery beat).

    Handles errors for individual vendors gracefully to allow the batch job to continue.
    """
    # Check if User model is available (sanity check, should be available in Django context)
    if 'store.models.User' not in settings.INSTALLED_APPS and not hasattr(settings, 'AUTH_USER_MODEL'):
         logger.critical("User model configuration seems missing. Cannot run reputation update.")
         return

    try:
        active_vendors = User.objects.filter(is_vendor=True, is_active=True)
        total_vendors = active_vendors.count()
        success_count = 0
        fail_count = 0

        logger.info(f"Starting periodic reputation update for {total_vendors} active vendors...")

        # SCALABILITY NOTE: For a very large number of vendors (e.g., 10k+),
        # processing them sequentially in a single task might be too slow or memory-intensive.
        # Consider strategies like:
        # 1. Chunking: Process vendors in batches (e.g., using .iterator(chunk_size=...)).
        # 2. Distributed Tasks: Dispatch individual Celery tasks for each vendor or small batches.
        #    (e.g., `update_vendor_reputation.delay(vendor.pk)`) - requires vendor PK passing.

        for vendor in active_vendors.iterator(): # Use iterator() for memory efficiency with large querysets
            try:
                # Call the single-vendor update function
                if update_vendor_reputation(vendor):
                    success_count += 1
                else:
                    fail_count += 1
                    # Specific failure reason should have been logged by update_vendor_reputation
                    logger.warning(f"Reputation update failed for Vendor {vendor.username} (PK: {vendor.pk}) during periodic task.")
            except Exception as e:
                fail_count += 1
                # Log unexpected errors during the loop iteration for a specific vendor
                logger.exception(f"Unexpected error processing vendor {vendor.username} (PK: {vendor.pk}) in periodic reputation task: {e}")
                # Continue to the next vendor

        logger.info(f"Finished periodic reputation update. Processed: {total_vendors}, Success: {success_count}, Failed: {fail_count}.")

    except Exception as task_err:
         # Catch errors related to the overall task setup (e.g., database connection issues)
         logger.exception(f"Critical error during the 'update_all_vendor_reputations' task: {task_err}")


# --- END UPDATED FILE ---