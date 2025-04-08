# File: store/management/commands/deadmans_switch.py
# Reason: Enterprise-grade Tiered DMS command: uses GlobalSettings timestamp,
#         implements Warning, Freeze, and Critical thresholds with escalating actions.
#         Features: check-in, dry-run, force flag + PGP signature verification,
#         safety checks, recovery user exclusion, atomic transactions, row locking,
#         clear logging, configurable settings, external alerting placeholder.

# --- Revision History ---
# [Rev 1.0 - 2025-04-07]
#   - Added PGP Signature Verification: Implemented mandatory PGP signature verification
#     when using `--force`. Requires `python-gnupg` library and configuration of
#     authorized PGP keys in Django settings (`DMS_AUTHORIZED_SIGNER_KEY_IDS`).
#     - Added `--signature` argument (required with `--force`).
#     - Added `_verify_pgp_signature` helper function.
#     - Integrated verification check before executing actions.
#     - Added detailed help text and comments explaining usage.
#   - Alerting Placeholder: Added standard reminder comment about implementing
#     `_trigger_dms_alert` with a real system.
#   - Documentation/Comments: Added notes clarifying action scope (DB flags vs service calls)
#     and mentioning potential for future multi-factor triggers.
#   - Configuration: Added setting key constants for PGP configuration.
#   - Minor Refinements: Improved logging messages, consolidated some imports.
# ------------------------

import logging
import datetime # Use datetime directly for strptime if needed, though timezone.now preferred
from datetime import timedelta
from typing import Tuple, Optional, List, Dict, Any # Added Dict, Any

# <<< CHANGE [Rev 1.0] Import gnupg for PGP verification
try:
    import gnupg
except ImportError:
    gnupg = None # Handle missing library gracefully initially
# <<< END CHANGE [Rev 1.0]

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction, models
from django.db.models import Q, QuerySet
from django.utils import timezone

# --- Model Import ---
try:
    from store.models import GlobalSettings
except ImportError:
    raise CommandError("Could not import GlobalSettings model from store.models.")

# --- Constants and Configuration ---

# Default threshold values
DEFAULT_WARNING_DAYS = 15
DEFAULT_FREEZE_DAYS = 30
DEFAULT_CRITICAL_DAYS = 45

# GlobalSettings PK
GLOBAL_SETTINGS_PK = 1

# Settings keys
SETTING_KEY_ENABLED = 'DEADMAN_SWITCH_ENABLED'
SETTING_KEY_RECOVERY_USER = 'DMS_RECOVERY_USERNAME'
SETTING_KEY_WARNING_DAYS = 'DEADMAN_SWITCH_WARNING_DAYS'
SETTING_KEY_FREEZE_DAYS = 'DEADMAN_SWITCH_FREEZE_DAYS'
SETTING_KEY_CRITICAL_DAYS = 'DEADMAN_SWITCH_CRITICAL_DAYS'
# <<< CHANGE [Rev 1.0] PGP Settings Keys
SETTING_KEY_PGP_ENABLED = 'DMS_PGP_VERIFICATION_ENABLED' # Enable/disable PGP check globally
SETTING_KEY_PGP_GNUPGHOME = 'DMS_PGP_GNUPGHOME' # Optional: Path to GnuPG home directory
SETTING_KEY_PGP_AUTH_KEYS = 'DMS_AUTHORIZED_SIGNER_KEY_IDS' # List of trusted PGP Key IDs
# <<< END CHANGE [Rev 1.0]

# --- Loggers ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('django.security')

# --- User Model ---
User = get_user_model()

# --- Alerting Placeholder ---
def _trigger_dms_alert(level: str, summary: str, details: str) -> None:
    """
    *** PLACEHOLDER - IMPLEMENTATION REQUIRED ***
    This function MUST be implemented to trigger real external alerts
    (e.g., PagerDuty, Sentry custom event, Email, Slack) for production use.
    """
    log_message = f"DMS ALERT [{level.upper()}]: {summary} - Details: {details}"
    if level.lower() == 'critical':
        security_logger.critical(log_message)
    elif level.lower() == 'error':
        security_logger.error(log_message)
    else:
        security_logger.warning(log_message)
    logger.info(f"(ALERTING PLACEHOLDER) Would trigger {level} alert: {summary}")
    # --- !!! Replace below with your actual alerting integration !!! ---
    pass


# --- Management Command ---
class Command(BaseCommand):
    """
    Management command implementing a Tiered Dead Man's Switch (DMS) with PGP verification.
    ... (Existing description updated below) ...
    """
    help = """Tiered Dead Man's Switch (DMS) with PGP Signature Verification.
    Checks last check-in against Warning/Freeze/Critical thresholds.
    If triggered AND --force + --signature used AND enabled in settings, executes actions:
    - Warning: Alert only.
    - Freeze: Alert + Activate Fund Freeze.
    - Critical: Alert + Fund Freeze + Maintenance Mode + Deactivate Staff.

    Use --check-in to update timestamp. --dry-run simulates.
    Requires settings.DEADMAN_SWITCH_ENABLED = True to execute.
    Requires settings.DMS_PGP_VERIFICATION_ENABLED = True and a valid PGP signature via --signature when using --force.
    Configure trusted PGP keys via settings.DMS_AUTHORIZED_SIGNER_KEY_IDS (list).
    Optionally configure settings.DMS_RECOVERY_USERNAME to exclude one account.
    Thresholds configurable via settings (DEADMAN_SWITCH_WARNING/FREEZE/CRITICAL_DAYS).

    PGP Signing Process:
    1. Determine the highest triggered level ('warning', 'freeze', 'critical').
    2. Get the current UTC time and format it as YYYY-MM-DD_HH (e.g., 2025-04-07_17).
    3. Construct the exact string to sign: "DMS_EXECUTE_{LEVEL}_{YYYY-MM-DD_HH}"
       Example: "DMS_EXECUTE_critical_2025-04-07_17"
    4. Sign this exact string using a PGP key listed in DMS_AUTHORIZED_SIGNER_KEY_IDS.
    5. Provide the resulting ASCII-armored signature via the --signature argument.
    """

    def add_arguments(self, parser):
        """Adds command-line arguments."""
        parser.add_argument(
            '--check-in', action='store_true',
            help='Perform DMS check-in: Update last_dms_check_in_ts to now.'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Simulate the check and actions without making database changes.'
        )
        parser.add_argument(
            '--force', action='store_true',
            help='REQUIRED (along with --signature if PGP enabled) to execute actions if thresholds are exceeded and DMS is enabled.'
        )
        # <<< CHANGE [Rev 1.0] Add signature argument
        parser.add_argument(
            '--signature', type=str, default=None,
            help='REQUIRED with --force (if PGP verification enabled). ASCII-armored PGP signature signing the required confirmation string (see help text).'
        )
        # <<< END CHANGE [Rev 1.0]

    # --- Helper Methods ---

    def _get_global_settings(self, acquire_lock: bool = False) -> GlobalSettings:
        """Loads the GlobalSettings singleton object, optionally locking the row."""
        try:
            # Use .first() if singleton PK is not strictly guaranteed, otherwise get(pk=...) is fine.
            gs_query = GlobalSettings.objects
            if acquire_lock:
                self.stdout.write(self.style.NOTICE("Acquiring lock on GlobalSettings..."))
                gs = gs_query.select_for_update().get(pk=GLOBAL_SETTINGS_PK)
                self.stdout.write(self.style.NOTICE("Lock acquired."))
                return gs
            else:
                 # Use cached load() method if available, otherwise standard get()
                if hasattr(GlobalSettings, 'load') and callable(GlobalSettings.load):
                     self.stdout.write(self.style.NOTICE("Loading GlobalSettings via .load() method..."))
                     return GlobalSettings.load()
                else:
                     self.stdout.write(self.style.NOTICE("Loading GlobalSettings via standard .get()..."))
                     return gs_query.get(pk=GLOBAL_SETTINGS_PK)
        except GlobalSettings.DoesNotExist:
            msg = f"CRITICAL: GlobalSettings (pk={GLOBAL_SETTINGS_PK}) not found. Initialize first."
            _trigger_dms_alert("critical", "DMS Configuration Error", msg)
            raise CommandError(msg)
        except Exception as e:
            logger.exception("Unexpected error loading GlobalSettings.")
            msg = f"CRITICAL: Unexpected error loading GlobalSettings: {e}"
            _trigger_dms_alert("critical", "DMS System Error", msg)
            raise CommandError(msg)

    def _handle_check_in(self, gs: GlobalSettings, dry_run: bool) -> bool:
        """Updates the last_dms_check_in_ts timestamp."""
        if dry_run:
            self.stdout.write(self.style.NOTICE("[Dry Run] Would update last_dms_check_in_ts."))
            return True
        now = timezone.now()
        timestamp_str = now.isoformat()
        try:
            gs.last_dms_check_in_ts = now
            gs.save(update_fields=['last_dms_check_in_ts'])
            security_logger.warning(f"DEADMAN SWITCH CHECK-IN PERFORMED at {timestamp_str} by operator.")
            self.stdout.write(self.style.SUCCESS(f"Successfully updated last_dms_check_in_ts to {timestamp_str}."))
            return True
        except Exception as e:
            logger.exception("Failed to save DMS check-in timestamp.")
            self.stderr.write(self.style.ERROR(f"Error saving check-in timestamp: {e}"))
            _trigger_dms_alert("error", "DMS Check-in Failed", f"Failed to save timestamp {timestamp_str}. Error: {e}")
            return False

    def _perform_dms_check(self, gs: GlobalSettings) -> Tuple[Optional[str], Optional[timezone.datetime]]:
        """Checks the timestamp against configured thresholds."""
        warning_days = getattr(settings, SETTING_KEY_WARNING_DAYS, DEFAULT_WARNING_DAYS)
        freeze_days = getattr(settings, SETTING_KEY_FREEZE_DAYS, DEFAULT_FREEZE_DAYS)
        critical_days = getattr(settings, SETTING_KEY_CRITICAL_DAYS, DEFAULT_CRITICAL_DAYS)

        if not (0 < warning_days <= freeze_days <= critical_days):
            msg = f"DMS Thresholds misconfigured: 0 < WARN({warning_days}) <= FREEZE({freeze_days}) <= CRITICAL({critical_days}) must hold."
            logger.error(msg)
            _trigger_dms_alert("critical", "DMS Configuration Error", msg)
            raise CommandError(f"CRITICAL CONFIGURATION ERROR: {msg}")

        last_check_in = gs.last_dms_check_in_ts
        if last_check_in is None:
            msg = "CRITICAL: Last check-in timestamp is NULL. Run --check-in first."
            security_logger.critical(f"DEADMAN SWITCH CHECK: {msg}")
            self.stderr.write(self.style.ERROR(msg))
            _trigger_dms_alert("error", "DMS Status Unknown", msg)
            return None, None

        now = timezone.now()
        critical_time = now - timedelta(days=critical_days)
        freeze_time = now - timedelta(days=freeze_days)
        warning_time = now - timedelta(days=warning_days)
        triggered_level: Optional[str] = None
        if last_check_in < critical_time: triggered_level = 'critical'
        elif last_check_in < freeze_time: triggered_level = 'freeze'
        elif last_check_in < warning_time: triggered_level = 'warning'

        self.stdout.write("-" * 40)
        self.stdout.write(f"Last check-in:         {last_check_in.isoformat()}")
        self.stdout.write(f"Current time:          {now.isoformat()}")
        self.stdout.write("-" * 40)
        self.stdout.write(f"Warning Threshold:     {warning_time.isoformat()} ({warning_days} days ago)")
        self.stdout.write(f"Freeze Threshold:      {freeze_time.isoformat()} ({freeze_days} days ago)")
        self.stdout.write(f"Critical Threshold:    {critical_time.isoformat()} ({critical_days} days ago)")
        self.stdout.write("-" * 40)
        self.stdout.write(f"Highest Trigger Level: {self.style.WARNING(triggered_level.upper()) if triggered_level else self.style.SUCCESS('None')}")
        self.stdout.write("-" * 40)
        return triggered_level, last_check_in

    # <<< CHANGE [Rev 1.0] New PGP Verification Helper
    def _verify_pgp_signature(self, signature_data: str, triggered_level: str) -> bool:
        """
        Verifies the provided PGP signature against the expected signed content.

        Args:
            signature_data: The ASCII-armored PGP signature provided via --signature.
            triggered_level: The level being confirmed ('warning', 'freeze', 'critical').

        Returns:
            True if the signature is valid and from an authorized key, False otherwise.
        """
        if gnupg is None:
            self.stderr.write(self.style.ERROR("CRITICAL: python-gnupg library is not installed. Cannot verify PGP signature."))
            _trigger_dms_alert("critical", "DMS PGP Verification Failed", "python-gnupg library missing")
            return False

        pgp_enabled = getattr(settings, SETTING_KEY_PGP_ENABLED, False)
        if not pgp_enabled:
            self.stdout.write(self.style.WARNING("PGP Verification is disabled in settings (DMS_PGP_VERIFICATION_ENABLED=False). Skipping check."))
            # If PGP is disabled, we treat the signature check as passed, relying solely on --force.
            # This allows disabling PGP requirement without code changes if needed, but reduces security.
            return True

        # --- Configuration ---
        gnupghome = getattr(settings, SETTING_KEY_PGP_GNUPGHOME, None) # Optional path
        authorized_keys: List[str] = getattr(settings, SETTING_KEY_PGP_AUTH_KEYS, [])
        if not authorized_keys:
            self.stderr.write(self.style.ERROR("CRITICAL: PGP Verification enabled, but no DMS_AUTHORIZED_SIGNER_KEY_IDS configured in settings."))
            _trigger_dms_alert("critical", "DMS PGP Configuration Error", "No authorized PGP keys configured")
            return False

        if not signature_data:
             self.stderr.write(self.style.ERROR("CRITICAL: --force used with PGP enabled, but --signature was not provided."))
             return False

        # --- Construct Expected Signed Data ---
        # Use UTC time rounded to the nearest hour for stability against minor clock drift
        # Admin must sign the string corresponding to the *current* hour when executing.
        now_utc_rounded = timezone.now().astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        timestamp_str = now_utc_rounded.strftime('%Y-%m-%d_%H') # Example: 2025-04-07_17
        expected_signed_content = f"DMS_EXECUTE_{triggered_level}_{timestamp_str}"

        self.stdout.write(self.style.NOTICE(f"Attempting to verify PGP signature for content: '{expected_signed_content}'"))
        self.stdout.write(self.style.NOTICE(f"Expecting signature from one of keys: {', '.join(authorized_keys)}"))

        try:
            gpg = gnupg.GPG(gnupghome=gnupghome)
            # Use verify() which expects the signature block contains the signed data (detached sig not handled here)
            # OR use decrypt() if the signature block *is* the signed data (clear-signed block)
            # Assuming the admin provides a signature block created like: gpg --clearsign --armor -u <key_id> <(echo "EXPECTED_CONTENT")
            # Let's try verify first, assuming admin provides JUST the signature block for the known content.
            # This requires the admin to sign the EXACT string separately.

            # Alternative: Assume admin provides clear-signed block containing the string.
            # We use decrypt which also verifies.
            decrypted = gpg.decrypt(signature_data) # Decrypt also verifies clear-signed data

            if not decrypted:
                 # Try verify if decrypt fails (maybe it was a detached sig?) - Less likely for manual commands
                 # verified = gpg.verify_data(signature_data, expected_signed_content.encode()) # Requires detached sig + content
                 # For simplicity, stick to expecting a clear-signed block handled by decrypt()
                 self.stderr.write(self.style.ERROR("PGP Verification FAILED: Could not decrypt/verify signature data."))
                 security_logger.error("DMS PGP Verification Failed: Invalid signature format or decryption error.")
                 return False

            # Check verification status from decrypt object
            if not decrypted.valid:
                self.stderr.write(self.style.ERROR(f"PGP Verification FAILED: Signature is NOT valid. Status: {decrypted.status}"))
                security_logger.error(f"DMS PGP Verification Failed: Invalid signature (Status: {decrypted.status})")
                return False

            # Check if the signer key is in the authorized list
            signer_key_id = decrypted.key_id
            if signer_key_id not in authorized_keys:
                self.stderr.write(self.style.ERROR(f"PGP Verification FAILED: Signature is valid, but signer key ID '{signer_key_id}' is NOT in the authorized list."))
                security_logger.error(f"DMS PGP Verification Failed: Unauthorized signer key ID '{signer_key_id}'")
                return False

            # Check if the decrypted content matches exactly what we expected
            # Need to handle potential whitespace/newlines from echo/signing process
            signed_content_received = decrypted.data.decode('utf-8').strip()
            if signed_content_received != expected_signed_content:
                 self.stderr.write(self.style.ERROR("PGP Verification FAILED: Signature is valid and from authorized key, but the signed content does NOT match the expected content."))
                 self.stderr.write(f"Expected: '{expected_signed_content}'")
                 self.stderr.write(f"Received: '{signed_content_received}'")
                 security_logger.error(f"DMS PGP Verification Failed: Signed content mismatch.")
                 return False

            # All checks passed
            self.stdout.write(self.style.SUCCESS(f"PGP Signature Verified Successfully (Key ID: {signer_key_id})."))
            security_logger.warning(f"DMS action authorized via valid PGP signature from key ID {signer_key_id}.") # Log successful auth
            return True

        except FileNotFoundError:
            # Common error if gpg executable not found
            self.stderr.write(self.style.ERROR("CRITICAL: 'gpg' executable not found. Cannot perform PGP verification. Ensure GnuPG is installed and in PATH."))
            _trigger_dms_alert("critical", "DMS PGP System Error", "'gpg' executable not found")
            return False
        except Exception as e:
            logger.exception("Unexpected error during PGP verification.")
            self.stderr.write(self.style.ERROR(f"Error during PGP verification: {e}"))
            _trigger_dms_alert("critical", "DMS PGP System Error", f"Unexpected error: {e}")
            return False
    # <<< END CHANGE [Rev 1.0]

    def _get_staff_to_deactivate(self) -> QuerySet[User]:
        """Queries for active staff/superuser accounts, excluding the recovery user."""
        recovery_username = getattr(settings, SETTING_KEY_RECOVERY_USER, None)
        staff_query = User.objects.filter(is_active=True).filter(Q(is_staff=True) | Q(is_superuser=True))
        if recovery_username:
            try:
                recovery_user = User.objects.get(username=recovery_username, is_active=True)
                self.stdout.write(self.style.NOTICE(f"Excluding configured active recovery user: {recovery_user.username}"))
                staff_query = staff_query.exclude(username=recovery_username)
            except User.DoesNotExist:
                self.stderr.write(self.style.WARNING(f"Configured recovery user '{recovery_username}' not found or inactive. Exclusion skipped."))
                security_logger.warning(f"DMS: Configured recovery user '{recovery_username}' not found/inactive during staff query.")
        return staff_query

    def _run_dry_run_simulation(self, triggered_level: str, enabled_setting: bool, pgp_enabled: bool) -> None:
        """Simulates and reports the tiered actions."""
        self.stdout.write(self.style.NOTICE(f"[Dry Run] DMS Triggered at level: {triggered_level.upper()}. Actions WOULD BE:"))
        if triggered_level in ['warning', 'freeze', 'critical']:
            self.stdout.write(self.style.NOTICE(f"- Trigger DMS Alert (Level: {triggered_level.upper()})"))
        if triggered_level in ['freeze', 'critical']:
            self.stdout.write(self.style.NOTICE("- Set GlobalSettings: freeze_funds=True"))
        if triggered_level == 'critical':
            self.stdout.write(self.style.NOTICE("- Set GlobalSettings: maintenance_mode=True"))
            staff_to_deactivate = self._get_staff_to_deactivate()
            count = staff_to_deactivate.count()
            if count > 0:
                self.stdout.write(self.style.NOTICE(f"- Deactivate {count} active staff/superuser accounts:"))
                usernames = list(staff_to_deactivate.values_list('username', flat=True)[:20])
                for username in usernames: self.stdout.write(self.style.NOTICE(f"  - {username}"))
                if count > 20: self.stdout.write(self.style.NOTICE(f"  - ... and {count - 20} more."))
            else:
                 self.stdout.write(self.style.NOTICE("- No active staff/superuser accounts found to deactivate."))

        force_req = "--force"
        if pgp_enabled: force_req += " and --signature"
        if not enabled_setting:
            self.stdout.write(self.style.WARNING(f"NOTE: {SETTING_KEY_ENABLED} is False. {force_req} would have NO effect live."))
        else:
             self.stdout.write(self.style.WARNING(f"NOTE: Actions above would only execute if run LIVE with {force_req}."))

    def _execute_freeze_actions(self, gs: GlobalSettings) -> bool:
        """Executes Freeze tier actions: Set freeze flag, trigger alert."""
        self.stdout.write(self.style.WARNING("--- Executing FREEZE Tier Actions ---"))
        action_taken = False
        if not gs.freeze_funds:
            gs.freeze_funds = True
            gs.save(update_fields=['freeze_funds']) # Save immediately within this step
            self.stdout.write(self.style.WARNING("- Activating Fund Freeze... SUCCESS"))
            security_logger.error("DEADMAN SWITCH EXECUTED (FREEZE TIER): Fund Freeze activated.")
            action_taken = True
        else:
             self.stdout.write(self.style.NOTICE("- Fund Freeze is already active."))
        _trigger_dms_alert("error", "DMS Freeze Tier Activated", "Fund Freeze flag activated.")
        return action_taken

    def _execute_critical_actions(self, gs: GlobalSettings) -> bool:
        """Executes Critical tier actions: Freeze, Maintenance, Deactivate Staff, Alert."""
        self.stdout.write(self.style.ERROR("--- Executing CRITICAL Tier Actions ---"))
        actions_taken = False

        # 1. Ensure Freeze actions run first (idempotent)
        if self._execute_freeze_actions(gs):
            actions_taken = True # State changed by freeze action

        # 2. Activate Maintenance Mode
        gs_updated = False
        if not gs.maintenance_mode:
            gs.maintenance_mode = True
            gs.save(update_fields=['maintenance_mode']) # Save immediately
            self.stdout.write(self.style.ERROR("- Activating Maintenance Mode... SUCCESS"))
            security_logger.critical("DEADMAN SWITCH EXECUTED (CRITICAL TIER): Maintenance Mode activated.")
            actions_taken = True
            gs_updated = True
        else:
             self.stdout.write(self.style.NOTICE("- Maintenance Mode is already active."))

        if not gs_updated and not actions_taken: # If freeze was also already active
             self.stdout.write(self.style.NOTICE("- GlobalSettings already in desired state for Critical Tier."))

        # 3. Deactivate Staff/Superusers
        staff_to_deactivate = self._get_staff_to_deactivate()
        if staff_to_deactivate.exists():
            count = staff_to_deactivate.count()
            usernames = list(staff_to_deactivate.values_list('username', flat=True))
            usernames_str = ', '.join(usernames)
            self.stdout.write(self.style.ERROR(f"- Deactivating {count} active staff/superuser accounts..."))
            updated_count = staff_to_deactivate.update(is_active=False)
            security_logger.critical(f"DEADMAN SWITCH EXECUTED (CRITICAL TIER): Deactivated {updated_count} Staff/SU accounts: [{usernames_str}]")
            self.stdout.write(self.style.SUCCESS(f"- {updated_count} Accounts deactivated: {usernames_str}"))
            actions_taken = True
        else:
             self.stdout.write(self.style.NOTICE("- No active staff/superuser accounts found to deactivate."))

        # 4. Trigger critical alert (always, if level reached)
        _trigger_dms_alert("critical", "DMS CRITICAL Tier Activated", "Full system lockdown executed: Freeze, Maintenance, Staff Deactivation.")
        return actions_taken

    # --- Main Command Handler ---

    @transaction.atomic # Ensure all DB changes within handle succeed or fail together
    def handle(self, *args, **options):
        """Main entry point for the tiered DMS command."""
        start_time = timezone.now()
        self.stdout.write(self.style.WARNING(f"--- Tiered DMS Command Started ({start_time.isoformat()}) ---"))

        check_in_mode: bool = options['check_in']
        dry_run: bool = options['dry_run']
        force_run: bool = options['force']
        signature_data: Optional[str] = options['signature'] # <<< CHANGE [Rev 1.0] Get signature

        # --- Preliminary Checks & Setup ---
        pgp_enabled = getattr(settings, SETTING_KEY_PGP_ENABLED, False) # <<< CHANGE [Rev 1.0] Check if PGP is enabled

        # Check incompatible arguments
        if check_in_mode and (dry_run or force_run or signature_data):
            raise CommandError("Argument Conflict: --check-in cannot be used with --dry-run, --force, or --signature.")
        if dry_run and (check_in_mode or force_run or signature_data):
             raise CommandError("Argument Conflict: --dry-run cannot be used with --check-in, --force, or --signature.")
        if force_run and pgp_enabled and not signature_data:
             raise CommandError("Argument Error: --signature is required when using --force and PGP verification is enabled.")
        if signature_data and not force_run:
             self.stdout.write(self.style.WARNING("--signature provided without --force. Signature will be ignored."))


        # Determine if DB lock is needed (check-in or live forced run)
        needs_lock = check_in_mode or (force_run and not dry_run)
        try:
            gs = self._get_global_settings(acquire_lock=needs_lock)
        except CommandError as e:
            self.stderr.write(self.style.ERROR(f"Command aborted: {e}"))
            raise # Re-raise to ensure correct exit code

        # --- 1. Handle Check-in Mode ---
        if check_in_mode:
            if not self._handle_check_in(gs, dry_run): # dry_run is always False here due to conflict check
                raise CommandError("Check-in operation failed.")
            self.stdout.write(self.style.SUCCESS("Check-in process complete."))
            return # Exit after successful check-in

        # --- 2. Perform Tiered DMS Check ---
        try:
            triggered_level, last_check_in = self._perform_dms_check(gs)
        except CommandError as e: # Catches bad threshold config
            self.stderr.write(self.style.ERROR(f"Command aborted: {e}"))
            raise

        if last_check_in is None: # Should only happen if never checked in
            raise CommandError("DMS cannot proceed: Initial check-in required.")
        if triggered_level is None:
            self.stdout.write(self.style.SUCCESS("DMS thresholds not exceeded. System OK."))
            return # All clear

        # --- 3. Handle Triggered State ---
        self.stdout.write(self.style.ERROR(f"!!! DEAD MAN'S SWITCH Triggered at Level: {triggered_level.upper()} !!!"))
        enabled_setting = getattr(settings, SETTING_KEY_ENABLED, False)

        # --- 4. Handle Dry Run Simulation ---
        if dry_run:
            self._run_dry_run_simulation(triggered_level, enabled_setting, pgp_enabled) # Pass PGP status
            self.stdout.write(self.style.NOTICE("[Dry Run] Simulation complete."))
            return # Exit after simulation

        # --- 5. Handle Live Run - Safety Checks (Force, Enabled, PGP) ---
        if not force_run:
            self.stdout.write(self.style.WARNING("Threshold exceeded, but --force not provided. NO actions taken."))
            alert_details = f"Level: {triggered_level}. Last check-in: {last_check_in.isoformat()}. --force not used."
            _trigger_dms_alert("warning", "DMS Triggered - Not Forced", alert_details)
            return # Exit safely

        if not enabled_setting:
            msg = f"CRITICAL: {SETTING_KEY_ENABLED} is False. Actions ABORTED despite --force."
            security_logger.critical(f"DMS TRIGGERED ({triggered_level}) + FORCED, but DISABLED in settings. ACTIONS ABORTED.")
            self.stderr.write(self.style.ERROR(msg))
            _trigger_dms_alert("critical", "DMS Execution Aborted (Disabled)", msg)
            raise CommandError("DMS execution aborted: Feature disabled in settings.")

        # <<< CHANGE [Rev 1.0] Perform PGP Verification if enabled
        if pgp_enabled:
            self.stdout.write(self.style.NOTICE("Performing PGP signature verification..."))
            if not self._verify_pgp_signature(signature_data, triggered_level):
                msg = "CRITICAL: PGP signature verification failed. ACTIONS ABORTED."
                security_logger.critical("DMS TRIGGERED ({triggered_level}) + FORCED, but PGP verification FAILED. ACTIONS ABORTED.")
                self.stderr.write(self.style.ERROR(msg))
                _trigger_dms_alert("critical", "DMS Execution Aborted (PGP Fail)", msg)
                raise CommandError("PGP signature verification failed.")
            # PGP verified successfully if we reach here
        else:
             # PGP not enabled, --force is sufficient if it got this far
             self.stdout.write(self.style.WARNING("PGP Verification is disabled. Proceeding based on --force flag only."))
        # <<< END CHANGE [Rev 1.0]

        # --- 6. Execute Tiered Actions (Checks passed, inside atomic transaction) ---
        self.stdout.write(self.style.ERROR(f"!!! EXECUTING ACTIONS for Level: {triggered_level.upper()} !!!"))
        execution_successful = False # Tracks if state was changed
        action_summary_log = "No state changes required."
        try:
            if triggered_level == 'critical':
                execution_successful = self._execute_critical_actions(gs)
                action_summary_log = "Critical actions completed." if execution_successful else action_summary_log
            elif triggered_level == 'freeze':
                execution_successful = self._execute_freeze_actions(gs)
                action_summary_log = "Freeze actions completed." if execution_successful else action_summary_log
            elif triggered_level == 'warning':
                _trigger_dms_alert("warning", f"DMS Warning Threshold Exceeded - Actions Forced", f"Last check-in: {last_check_in.isoformat()}. Alerting only.")
                execution_successful = True # Alerting is the action
                action_summary_log = "Warning alert triggered."

            if execution_successful:
                 self.stdout.write(self.style.SUCCESS(f"--- DMS Actions ({triggered_level.upper()}) Completed: {action_summary_log} ---"))
            else:
                 self.stdout.write(self.style.NOTICE(f"--- DMS Actions ({triggered_level.upper()}) executed: {action_summary_log} ---"))

        except Exception as e:
             # Catch unexpected errors during action execution
             security_logger.critical(f"DMS EXECUTION FAILED: Unexpected error during '{triggered_level}' action: {e}", exc_info=True)
             # Atomic transaction handles rollback. Raise CommandError for non-zero exit.
             raise CommandError(f"Error executing DMS '{triggered_level}' actions: {e}. Transaction rolled back.")

        finally:
            end_time = timezone.now()
            duration = end_time - start_time
            self.stdout.write(f"--- Dead Man's Switch Command Finished ({end_time.isoformat()}) ---")
            self.stdout.write(f"--- Total Duration: {duration} ---")