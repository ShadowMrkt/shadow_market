#!/usr/bin/env python
# <<< Revised manage.py for robustness >>>
"""Django's command-line utility for administrative tasks."""
import os
import sys
import logging # <<< BEST PRACTICE: Use logging for early messages >>>

# <<< BEST PRACTICE: Setup basic logging early for script issues >>>
logging.basicConfig(level=logging.INFO, format='%(levelname)s:manage.py:%(message)s')

def main():
    """Runs administrative tasks."""
    # <<< CHANGE: Prioritize externally set DJANGO_SETTINGS_MODULE >>>
    # Check if the settings module is already set in the environment
    settings_module = os.environ.get('DJANGO_SETTINGS_MODULE')

    if settings_module:
        logging.info(f"Using settings module specified in environment: '{settings_module}'")
    else:
        # Default to development settings ONLY if not set externally
        # <<< BEST PRACTICE: Make default explicit and log it >>>
        default_settings = 'mymarketplace.settings.dev'
        logging.info(f"DJANGO_SETTINGS_MODULE not set in environment, defaulting to: '{default_settings}'")
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', default_settings)
        # <<< BEST PRACTICE: Add a warning if defaulting (potential dev setting use) >>>
        # This warning is helpful during development setup but might be noisy in well-configured prod.
        # Consider removing this warning line before final production deployment if logs are clean.
        # logging.warning("Defaulting DJANGO_SETTINGS_MODULE. Ensure this is intended (e.g., for development).")

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        # <<< BEST PRACTICE: Provide helpful error message for ImportError >>>
        logging.error(f"ImportError: Couldn't import Django: {exc}")
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    except Exception as e:
        # Catch any other potential startup errors
        logging.exception(f"Unexpected error during Django import or setup: {e}")
        raise # Re-raise unexpected exceptions

    try:
        execute_from_command_line(sys.argv)
    except Exception as e:
        # <<< BEST PRACTICE: Log exceptions occurring during command execution >>>
        logging.exception(f"Exception during command execution ({sys.argv}): {e}")
        sys.exit(1) # Exit with error status if command fails

if __name__ == '__main__':
    main()