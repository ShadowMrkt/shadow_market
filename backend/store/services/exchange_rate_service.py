# shadow_market/backend/store/services/exchange_rate_service.py
"""
Service layer for fetching and converting cryptocurrency exchange rates.

Handles interaction with external rate providers, caching, and provides
utility functions for rate retrieval and currency conversion.
Designed for reliability and precision using Decimal type.
"""
# <<< ENTERPRISE GRADE - v1.0.0 >>>

import logging
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional, List

import requests
from django.conf import settings
from django.core.cache import cache
from requests.exceptions import RequestException

# Local Application Imports
from ..models import Currency, FiatCurrency # Use choices defined in models

logger = logging.getLogger(__name__)

# --- Configuration ---
# Consider moving these to Django settings for more flexibility
# Using CoinGecko free API as an example. Replace if using a different provider.
COINGECKO_API_URL = "https://api.coingecko.com/api/v3/simple/price"
# Define the specific crypto IDs Coingecko uses (lowercase)
# Ensure these match the API's requirements.
CRYPTO_IDS = {
    Currency.BTC: 'bitcoin',
    Currency.ETH: 'ethereum',
    Currency.XMR: 'monero',
}
# Define the target fiat currencies (lowercase for CoinGecko)
FIAT_IDS = [fc.lower() for fc in FiatCurrency.values] # e.g., ['usd', 'eur']

# Cache configuration
CACHE_KEY = 'exchange_rates_cache'
# Cache timeout in seconds (e.g., 5 minutes) - Adjust based on required freshness vs API rate limits
CACHE_TIMEOUT = 60 * 5
# Request timeout for external API calls
REQUEST_TIMEOUT_SECONDS = 10 # Generous but prevents indefinite hangs

# --- Service Functions ---

def _fetch_rates_from_coingecko() -> Optional[Dict[str, Dict[str, Decimal]]]:
    """
    Internal function to fetch rates directly from the CoinGecko API.

    Returns:
        A dictionary structured like {'bitcoin': {'usd': Decimal('...'), 'eur': Decimal('...')}, ...}
        or None if the request fails or data is invalid.
    """
    if not FIAT_IDS:
        logger.warning("Exchange Rate Service: No target fiat currencies defined (FIAT_IDS is empty). Cannot fetch rates.")
        return None

    crypto_ids_param = ','.join(CRYPTO_IDS.values())
    fiat_ids_param = ','.join(FIAT_IDS)

    params = {
        'ids': crypto_ids_param,
        'vs_currencies': fiat_ids_param,
    }

    logger.debug(f"Fetching exchange rates from CoinGecko with params: {params}")
    try:
        response = requests.get(
            COINGECKO_API_URL,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={'Accept': 'application/json'} # Ensure we get JSON
        )
        response.raise_for_status()  # Raises HTTPError for bad responses (4xx or 5xx)
        data = response.json()

        # --- Data Validation and Parsing ---
        if not isinstance(data, dict):
            logger.error(f"CoinGecko API Error: Expected a dictionary response, got {type(data)}. Data: {data}")
            return None

        parsed_rates: Dict[str, Dict[str, Decimal]] = {}
        for crypto_id, rates in data.items():
            if crypto_id not in CRYPTO_IDS.values():
                logger.warning(f"CoinGecko API Warning: Received unexpected crypto ID '{crypto_id}'. Skipping.")
                continue

            if not isinstance(rates, dict):
                logger.error(f"CoinGecko API Error: Expected rates for '{crypto_id}' to be a dictionary, got {type(rates)}. Skipping.")
                continue

            parsed_fiat_rates: Dict[str, Decimal] = {}
            for fiat_id, rate_value in rates.items():
                if fiat_id not in FIAT_IDS:
                    logger.warning(f"CoinGecko API Warning: Received unexpected fiat ID '{fiat_id}' for crypto '{crypto_id}'. Skipping.")
                    continue

                try:
                    # Attempt to convert rate_value robustly (handles int, float, string)
                    rate_decimal = Decimal(str(rate_value))
                    if rate_decimal <= 0:
                        logger.error(f"CoinGecko API Error: Received non-positive rate {rate_decimal} for {crypto_id}/{fiat_id}. Skipping.")
                        continue
                    parsed_fiat_rates[fiat_id] = rate_decimal
                except (InvalidOperation, ValueError, TypeError) as e:
                    logger.error(f"CoinGecko API Error: Could not parse rate '{rate_value}' for {crypto_id}/{fiat_id} as Decimal: {e}. Skipping.")
                    continue

            if parsed_fiat_rates: # Only add if we successfully parsed some fiat rates
                 parsed_rates[crypto_id] = parsed_fiat_rates
            else:
                logger.warning(f"CoinGecko API Warning: No valid fiat rates parsed for crypto ID '{crypto_id}'.")

        if not parsed_rates:
            logger.error("CoinGecko API Error: Failed to parse any valid rates from the response.")
            return None

        logger.info(f"Successfully fetched and parsed rates for {len(parsed_rates)} crypto(s).")
        return parsed_rates

    except RequestException as e:
        logger.error(f"Network error fetching exchange rates from CoinGecko: {e}", exc_info=True)
        return None
    except Exception as e:
        # Catch other potential errors during request/parsing
        logger.error(f"Unexpected error fetching or parsing exchange rates: {e}", exc_info=True)
        return None

def get_current_rates() -> Optional[Dict[str, Dict[str, Decimal]]]:
    """
    Retrieves current exchange rates, utilizing cache first.

    Returns:
        A dictionary structured like {'bitcoin': {'usd': Decimal('...'), 'eur': Decimal('...')}, ...}
        or None if rates cannot be retrieved.
    """
    cached_rates = cache.get(CACHE_KEY)
    if cached_rates is not None:
        logger.debug("Exchange rates retrieved from cache.")
        # Ensure cached data is in the expected format (basic check)
        if isinstance(cached_rates, dict):
             return cached_rates
        else:
             logger.warning(f"Invalid data type found in exchange rate cache: {type(cached_rates)}. Ignoring cache.")
             # Proceed to fetch fresh data

    logger.info("Exchange rate cache miss or invalid data. Fetching fresh rates.")
    fetched_rates = _fetch_rates_from_coingecko()

    if fetched_rates:
        # Attempt to cache the fetched rates
        try:
             cache.set(CACHE_KEY, fetched_rates, timeout=CACHE_TIMEOUT)
             logger.debug(f"Exchange rates stored in cache with timeout {CACHE_TIMEOUT}s.")
        except Exception as e:
             # Log caching errors but don't prevent returning fetched data
             logger.error(f"Failed to store exchange rates in cache: {e}", exc_info=True)
        return fetched_rates
    else:
        logger.error("Failed to fetch fresh exchange rates. Cannot provide current rates.")
        # Potential fallback: return stale cache if available and configured?
        # For now, return None if fresh fetch fails.
        return None

def get_specific_rate(from_currency: Currency, to_currency: FiatCurrency) -> Optional[Decimal]:
    """
    Gets a specific exchange rate (e.g., BTC to USD).

    Args:
        from_currency: The Currency enum member (e.g., Currency.BTC).
        to_currency: The FiatCurrency enum member (e.g., FiatCurrency.USD).

    Returns:
        The exchange rate as a Decimal, or None if unavailable.
    """
    rates = get_current_rates()
    if not rates:
        return None

    try:
        crypto_id = CRYPTO_IDS[from_currency]
        fiat_id = to_currency.value.lower() # Get 'usd', 'eur' etc.

        rate = rates.get(crypto_id, {}).get(fiat_id)

        if rate is None:
             logger.warning(f"Rate for {from_currency.value} to {to_currency.value} not found in current rates data.")
             return None

        if not isinstance(rate, Decimal):
             logger.error(f"Invalid rate type found for {from_currency.value}/{to_currency.value}: {type(rate)}. Expected Decimal.")
             # Attempt conversion as fallback? Risky. Return None.
             return None

        return rate

    except KeyError:
        logger.error(f"Invalid currency specified: {from_currency} or {to_currency}. Check CRYPTO_IDS/FiatCurrency enum.", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error retrieving specific rate ({from_currency.value}/{to_currency.value}): {e}", exc_info=True)
        return None

def convert_usd_to_crypto(amount_usd: Decimal, crypto_currency: Currency) -> Optional[Decimal]:
    """
    Converts a USD amount to its equivalent in a specified cryptocurrency.

    Args:
        amount_usd: The amount in USD as a Decimal.
        crypto_currency: The target Currency enum member (e.g., Currency.BTC).

    Returns:
        The equivalent amount in the target cryptocurrency as a Decimal,
        or None if conversion cannot be performed (e.g., rate unavailable).
    """
    if not isinstance(amount_usd, Decimal) or amount_usd < 0:
        logger.error(f"Invalid USD amount provided for conversion: {amount_usd}. Must be a non-negative Decimal.")
        return None

    # We need the rate FROM crypto TO USD to perform the conversion
    rate_crypto_to_usd = get_specific_rate(crypto_currency, FiatCurrency.USD)

    if rate_crypto_to_usd is None:
        logger.error(f"Cannot convert USD to {crypto_currency.value}: Rate unavailable.")
        return None

    if rate_crypto_to_usd <= 0:
         logger.error(f"Cannot convert USD to {crypto_currency.value}: Invalid rate ({rate_crypto_to_usd}) obtained.")
         return None

    try:
        # Conversion: Crypto Amount = USD Amount / (USD per Crypto)
        crypto_amount = amount_usd / rate_crypto_to_usd
        # Optional: Rounding or quantization based on crypto's precision needs?
        # For now, return the precise Decimal result.
        logger.debug(f"Converted {amount_usd} USD to {crypto_amount} {crypto_currency.value} using rate {rate_crypto_to_usd} USD/{crypto_currency.value}")
        return crypto_amount
    except (InvalidOperation, ZeroDivisionError) as e:
        logger.error(f"Error during USD to {crypto_currency.value} conversion: {e}", exc_info=True)
        return None
    except Exception as e:
         logger.error(f"Unexpected error during USD to {crypto_currency.value} conversion: {e}", exc_info=True)
         return None

# --- END OF FILE ---