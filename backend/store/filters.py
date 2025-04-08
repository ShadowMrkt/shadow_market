# backend/store/filters.py

"""
Defines FilterSet classes for the store application using django-filter.
These filters are typically used with Django Rest Framework views to allow
API clients to filter querysets based on various product attributes.
"""

from django_filters.rest_framework import (
    FilterSet,
    CharFilter,
    ChoiceFilter,
    BooleanFilter,
    NumberFilter,
    DateFromToRangeFilter, # Use RangeFilter for dates for a cleaner API
    # RangeFilter, # Imported implicitly via DateFromToRangeFilter if needed separately
)
# Note: No need to import 'django_filters' directly if using 'django_filters.rest_framework'

# Import models and constants needed for choices or relations
# Ensure these paths are correct relative to your project structure.
from .models import Product, Category, User, CURRENCY_CHOICES

# --- Constants ---

# TODO: Enterprise Standard: Consider moving VENDOR_LEVEL_CHOICES to a central
# constants file, configuration, or ideally retrieve them dynamically
# from the service/model that defines vendor levels (e.g., a VendorLevel model).
# Ensure these choices are synchronized with your vendor reputation logic.
VENDOR_LEVEL_CHOICES = [
    ("New Vendor", "New Vendor"),
    ("Verified", "Verified"),
    ("Established", "Established"),
    ("Trusted", "Trusted"),
]

# --- FilterSets ---

class ProductFilter(FilterSet):
    """
    FilterSet for the Product model, providing filtering capabilities for the product list API.

    Includes filters for category, vendor, accepted currencies, price ranges,
    shipping locations, listing date range, featured status, and vendor reputation.
    """

    # --- Category Filtering ---
    category = CharFilter(
        field_name='category__slug',
        lookup_expr='iexact',
        label='Category Slug (case-insensitive exact match)'
    )
    # Example for filtering by category tree (requires django-mptt or similar):
    # category_tree = CharFilter(method='filter_category_tree', label='Category Slug (includes descendants)')

    # --- Vendor Filtering ---
    vendor = CharFilter(
        field_name='vendor__username',
        lookup_expr='iexact',
        label='Vendor Username (case-insensitive exact match)'
    )

    # --- Currency Filtering ---
    accepted = ChoiceFilter(
        choices=CURRENCY_CHOICES,
        method='filter_accepted_currency',
        label='Accepted Currency (select one)'
        # Note: This filter assumes 'accepted_currencies' is an ArrayField on the Product model.
    )

    # --- Price Range Filtering (per currency) ---
    # Assumes price fields (e.g., price_xmr) are DecimalField or FloatField on Product model.
    # Use query params like ?min_price_xmr=10&max_price_xmr=50
    min_price_xmr = NumberFilter(field_name='price_xmr', lookup_expr='gte', label='Min Price (XMR)')
    max_price_xmr = NumberFilter(field_name='price_xmr', lookup_expr='lte', label='Max Price (XMR)')
    min_price_btc = NumberFilter(field_name='price_btc', lookup_expr='gte', label='Min Price (BTC)')
    max_price_btc = NumberFilter(field_name='price_btc', lookup_expr='lte', label='Max Price (BTC)')
    min_price_eth = NumberFilter(field_name='price_eth', lookup_expr='gte', label='Min Price (ETH)')
    max_price_eth = NumberFilter(field_name='price_eth', lookup_expr='lte', label='Max Price (ETH)')

    # --- Status Filtering ---
    is_featured = BooleanFilter(field_name='is_featured', label='Is Featured Product?')

    # --- Shipping Filtering ---
    # Assumes 'ships_from' and 'ships_to' are TextField or CharField on Product model.
    # Uses 'icontains' for flexible partial matching (e.g., 'USA', 'United States').
    ships_from = CharFilter(
        field_name='ships_from',
        lookup_expr='icontains',
        label='Ships From (contains text, case-insensitive)'
    )
    ships_to = CharFilter(
        field_name='ships_to',
        lookup_expr='icontains',
        label='Ships To (contains text, case-insensitive)'
    )

    # --- Date Filtering ---
    # Uses DateFromToRangeFilter for a cleaner API endpoint.
    # Expects query params like: ?created_at_after=YYYY-MM-DD&created_at_before=YYYY-MM-DD
    # Assumes 'created_at' is a DateField or DateTimeField on Product model.
    created_at = DateFromToRangeFilter(
        field_name='created_at',
        label='Product Listed Date Range'
    )

    # --- Vendor Reputation Filtering ---
    # Assumes related User model (vendor) has 'vendor_avg_rating' (FloatField/DecimalField)
    # and 'vendor_level_name' (CharField) fields or properties.

    # Renamed from 'min_vendor_rating' for clarity as RangeFilter handles min and max.
    # Expects query params like: ?vendor_rating_min=4.0&vendor_rating_max=5.0
    # vendor_rating = RangeFilter( # Basic RangeFilter if not using DRF integration directly
    #     field_name='vendor__vendor_avg_rating',
    #     label='Vendor Average Rating Range (0.0-5.0)'
    # )
    # Using NumberFilter might be simpler if you only need min OR max separately:
    min_vendor_rating = NumberFilter(
        field_name='vendor__vendor_avg_rating',
        lookup_expr='gte',
        label='Minimum Vendor Average Rating (0.0-5.0)'
    )
    max_vendor_rating = NumberFilter(
        field_name='vendor__vendor_avg_rating',
        lookup_expr='lte',
        label='Maximum Vendor Average Rating (0.0-5.0)'
    )


    vendor_level = ChoiceFilter(
        field_name='vendor__vendor_level_name', # Assumes this field exists on User model
        choices=VENDOR_LEVEL_CHOICES,
        label='Vendor Level'
    )

    class Meta:
        model = Product
        # Define the fields available for filtering in the API.
        # Ensure these names match the filter definitions above.
        fields = [
            'category',
            'vendor',
            'accepted',
            'is_featured',
            'min_price_xmr', 'max_price_xmr',
            'min_price_btc', 'max_price_btc',
            'min_price_eth', 'max_price_eth',
            'ships_from',
            'ships_to',
            'created_at', # Handles date range (_after, _before)
            # 'vendor_rating', # Use if using RangeFilter
            'min_vendor_rating', # Separate min/max filters chosen for vendor rating
            'max_vendor_rating',
            'vendor_level',
        ]
        # Note: Search and Ordering are typically handled by different DRF filters
        # (e.g., SearchFilter, OrderingFilter) and are not included here.

    def filter_accepted_currency(self, queryset, name, value):
        """
        Custom filter method for 'accepted_currencies'.

        Filters products where the 'accepted_currencies' list/array field
        contains the specified currency code.

        *** Production Assumption ***:
        This implementation assumes 'accepted_currencies' is a PostgreSQL ArrayField.
        Adjust the lookup ('__contains') if using a different field type
        (e.g., JSONField, TextField storing comma-separated values).
        Using ArrayField with a GIN index is recommended for performance.
        """
        if not value:
             # If no value is provided for the filter, don't alter the queryset
             return queryset

        # Use '__contains' for checking membership in an ArrayField
        # Example: Product.objects.filter(accepted_currencies__contains=['XMR'])
        return queryset.filter(accepted_currencies__contains=[value])

        # --- Alternative Implementations (if not using ArrayField) ---
        # For JSONField (containing a list):
        # return queryset.filter(accepted_currencies__contains=value) # Simpler JSONField contains

        # For TextField (comma-separated, less robust, needs careful implementation):
        # from django.db.models import Q
        # return queryset.filter(
        #     Q(accepted_currencies__iexact=value) | # Exact match if only one currency
        #     Q(accepted_currencies__icontains=f'{value},') | # Starts with or middle
        #     Q(accepted_currencies__iendswith=f',{value}') # Ends with
        # )
        # Even better for TextField might be regex or finding a library. Avoid if possible.


    # Example method for filtering by category tree (uncomment and adapt if needed)
    # def filter_category_tree(self, queryset, name, value):
    #     """
    #     Filters products belonging to the specified category slug or any of its descendants.
    #     Requires a hierarchical category setup (e.g., using django-mptt).
    #     """
    #     try:
    #         category = Category.objects.get(slug=value)
    #         # Get all descendant categories including the category itself
    #         descendant_pks = category.get_descendants(include_self=True).values_list('pk', flat=True)
    #         return queryset.filter(category__pk__in=list(descendant_pks))
    #     except Category.DoesNotExist:
    #         # If the category slug doesn't exist, return no results
    #         return queryset.none()
    #     except AttributeError:
    #         # Handle cases where get_descendants might not exist (if not using mptt)
    #         # Log an error or fall back to simple category filtering
    #         print(f"Warning: Category tree filtering called, but 'get_descendants' method not found on Category model.")
    #         # Fallback to exact match? Or return none? Decide based on desired behavior.
    #         return queryset.filter(category__slug=value) # Example fallback


# --- Recommendations for Enterprise Deployment ---
#
# 1.  **Indexing:** Ensure database indexes exist for fields used in filtering, especially:
#     - `Product.category` (ForeignKey -> `Category.id`), `Category.slug`
#     - `Product.vendor` (ForeignKey -> `User.id`), `User.username`
#     - `Product.accepted_currencies` (GIN index if using ArrayField/JSONField on PostgreSQL)
#     - `Product.price_xmr`, `Product.price_btc`, `Product.price_eth`
#     - `Product.is_featured`
#     - `Product.ships_from`, `Product.ships_to` (Consider full-text index if complex searching is needed)
#     - `Product.created_at`
#     - `User.vendor_avg_rating`
#     - `User.vendor_level_name`
# 2.  **Configuration:** Move `VENDOR_LEVEL_CHOICES` to a central, configurable location.
# 3.  **Testing:** Write comprehensive unit and integration tests for these filters to ensure they behave as expected with different inputs and edge cases.
# 4.  **Monitoring:** Monitor query performance related to these filters in production.
# 5.  **Linting/Formatting:** Use tools like `black` and `flake8` or `ruff` to enforce consistent code style and catch potential issues.
# 6.  **Security:** Ensure that the fields exposed through filters do not inadvertently reveal sensitive information. Filter validation helps prevent unexpected query manipulation.
# 7.  **Field Type Consistency:** Double-check that the `field_name` references and the custom filter logic (`filter_accepted_currency`) perfectly match the actual field types defined in your `models.py`.