# backend/ledger/admin.py
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from .models import UserBalance, LedgerTransaction

@admin.register(UserBalance)
class UserBalanceAdmin(admin.ModelAdmin):
    list_display = ('user_link', 'currency', 'balance', 'locked_balance', 'available_balance_display', 'updated_at')
    list_filter = ('currency', 'user__username') # Filter by username
    search_fields = ('user__username',)
    # Make fields read-only by default to prevent accidental changes via simple admin interface
    readonly_fields = ('user', 'currency', 'balance', 'locked_balance', 'updated_at', 'available_balance_display')
    list_per_page = 50
    list_select_related = ('user',) # Optimize user lookup

    @admin.display(description='Available Balance', ordering='balance') # Allow ordering by balance column? maybe not ideal
    def available_balance_display(self, obj):
        # Display calculated property
        # Format for display
        return f"{obj.available_balance:.8f}" # Show more precision in admin

    @admin.display(description='User', ordering='user__username')
    def user_link(self, obj):
        if obj.user:
            try:
                url = reverse('admin:store_user_change', args=[obj.user.pk]) # Assumes User admin is in 'store' app
                return format_html('<a href="{}">{}</a>', url, obj.user.username)
            except Exception:
                return obj.user.username # Fallback
        return "-"

    # Prevent direct editing by default - force adjustments through actions/services
    def has_change_permission(self, request, obj=None):
        # Allow superusers to change for emergency fixes? Very risky. Disable for now.
        # return request.user.is_superuser
        return False

    def has_add_permission(self, request):
        # Balances should be created automatically on first transaction
        return False

    def has_delete_permission(self, request, obj=None):
        # Allow deletion only by superusers? Should only be done if user is purged etc.
        return request.user.is_superuser


@admin.register(LedgerTransaction)
class LedgerTransactionAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user_link', 'transaction_type', 'amount', 'currency', 'balance_after', 'related_order_link', 'external_txid_short')
    list_filter = ('transaction_type', 'currency', 'timestamp', 'user__username') # Filter by username
    search_fields = ('user__username', 'related_order__id', 'external_txid', 'notes')
    date_hierarchy = 'timestamp'
    # Make ledger entries strictly read-only in admin
    readonly_fields = [f.name for f in LedgerTransaction._meta.fields if f.name != 'id'] # Allow viewing ID but not editing others
    list_per_page = 100
    list_select_related = ('user', 'related_order__product') # Optimize lookups

    @admin.display(description='User', ordering='user__username')
    def user_link(self, obj):
        # Link to user in admin if possible
        if obj.user:
            try:
                # Assumes default django admin user change URL name for store.User
                url = reverse('admin:store_user_change', args=[obj.user.pk]) # Adjust app_label if User model moved
                return format_html('<a href="{}">{}</a>', url, obj.user.username)
            except Exception:
                return obj.user.username # Fallback
        return "-"

    @admin.display(description='Order', ordering='related_order__pk')
    def related_order_link(self, obj):
        # Link to order in admin if possible
        if obj.related_order:
            try:
                # Replace 'admin:store_order_change' with your actual Order admin change URL name if different
                url = reverse('admin:store_order_change', args=[obj.related_order.pk]) # Assumes Order in store app
                return format_html('<a href="{}">{}</a>', url, f"{str(obj.related_order.pk)[:8]}...")
            except Exception as e:
                # Log error if URL reversing fails maybe
                # logger.warning(f"Could not reverse Order admin URL: {e}")
                return obj.related_order.pk # Fallback to PK
        return "-"
    related_order_link.short_description = 'Related Order'

    @admin.display(description='Ext. TXID')
    def external_txid_short(self, obj):
        if obj.external_txid:
            # Shorten TXID display for list view
            return f"{obj.external_txid[:10]}..." if len(obj.external_txid) > 10 else obj.external_txid
        return "-"

    # Prevent manual creation/modification/deletion of ledger entries via admin
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Allow viewing only
        return False

    def has_delete_permission(self, request, obj=None):
        # Deleting ledger entries breaks audit trail - strongly discourage
        return False # Disable delete entirely