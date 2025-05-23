# backend/store/admin.py
# Revision: 1.1 (Fix relative model import)
# Date: 2025-04-29
# Author: Gemini
# Description: Registers store models with the Django admin site.
# Changes:
# - Rev 1.1:
#   - FIXED: Changed relative model import (`from .models import ...`) to
#     absolute (`from backend.store.models import ...`) to resolve conflicting
#     model loading errors.
# - Rev 1.0: Initial version based on user provided content.

from django.contrib import admin
# --- FIX: Use absolute import path ---
from backend.store.models import (
    User, Category, Product, Order, CryptoPayment, Feedback,
    SupportTicket, TicketMessage, GlobalSettings, AuditLog
)

# --- Admin Registrations ---

# TODO: Review and potentially customize admin interfaces further.
# Consider using list_editable, search_fields, list_filter, fieldsets, etc.
# Ensure sensitive data is appropriately handled/masked if displayed.

# Note: The UserProfileAdmin seems to reference fields ('user', 'email_verified', 'vendor_bond')
# that might not exist directly on the custom User model provided earlier.
# This registration needs review based on the actual User model fields.
# @admin.register(User)
# class UserProfileAdmin(admin.ModelAdmin):
#     list_display = ('username', 'is_vendor', 'is_staff', 'is_active', 'date_joined') # Use actual User fields
#     search_fields = ('username',)
#     list_filter = ('is_vendor', 'is_staff', 'is_active')

# Register Category (Simple registration is often sufficient)
admin.site.register(Category)

# Note: The ProductAdmin references 'price' and 'available' which might need adjustment
# based on the actual Product model fields (e.g., price_btc, price_xmr, is_active).
# @admin.register(Product)
# class ProductAdmin(admin.ModelAdmin):
#     list_display = ('name', 'vendor', 'category', 'is_active') # Use actual Product fields
#     search_fields = ('name', 'vendor__username', 'category__name')
#     list_filter = ('is_active', 'category', 'vendor')

# Register Order (Simple registration)
admin.site.register(Order)

# Register CryptoPayment (Simple registration)
admin.site.register(CryptoPayment)

# Register Feedback (Simple registration)
admin.site.register(Feedback)

# Register SupportTicket (Simple registration)
admin.site.register(SupportTicket)


# Note: The TicketMessageAdmin references 'message' and 'message_preview' which might
# need adjustment based on the actual TicketMessage model (it has 'encrypted_body').
# Displaying encrypted data directly in admin is usually not useful.
# Consider showing sender, ticket, sent_at.
@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'sender', 'sent_at', 'is_read') # Use actual TicketMessage fields
    list_filter = ('ticket', 'sender', 'sent_at', 'is_read')
    search_fields = ('sender__username', 'ticket__subject')
    readonly_fields = ('ticket', 'sender', 'encrypted_body', 'sent_at') # Make messages read-only

    # Remove message_preview as 'message' field doesn't exist
    # def message_preview(self, obj):
    #     # Cannot preview encrypted body easily/safely here
    #     return "[Encrypted]"
    # message_preview.short_description = 'Message Preview'

    def has_add_permission(self, request):
        return False # Messages should likely be created via application logic, not admin

    def has_change_permission(self, request, obj=None):
        return False # Messages should be immutable


# Note: The GlobalSettingsAdmin references 'owner_wallet' which might not exist.
# Adjust list_display based on actual GlobalSettings fields.
# Using django-solo often means you don't need/want this registered here,
# as it's accessed via GlobalSettings.get_solo() and managed in its own admin view
# provided by django-solo if configured.
# Commenting out for now, assuming solo-admin handles it.
# @admin.register(GlobalSettings)
# class GlobalSettingsAdmin(admin.ModelAdmin):
#     # list_display = ('site_name', 'maintenance_mode', 'freeze_funds', 'updated_at') # Use actual fields
#     pass # Use solo-admin instead


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'actor', 'action', 'target_user', 'target_order', 'ip_address', 'details_short')
    list_filter = ('action', 'actor', 'timestamp')
    search_fields = ('actor__username', 'target_user__username', 'details', 'ip_address', 'target_order__id')
    # Make audit logs immutable in admin
    readonly_fields = [f.name for f in AuditLog._meta.fields] # Make all fields read-only dynamically
    list_per_page = 50

    def details_short(self, obj):
        return (obj.details[:75] + '...') if len(obj.details) > 75 else obj.details
    details_short.short_description = 'Details'

    def has_add_permission(self, request):
        return False # Cannot add audit logs manually

    def has_change_permission(self, request, obj=None):
        return False # Cannot change audit logs

    def has_delete_permission(self, request, obj=None):
        # Allow deletion only by superusers? Or disable completely?
        # return request.user.is_superuser # Be very careful allowing deletion
        return False # Safer default: disable deletion via admin

# --- Clean up unused/placeholder registrations ---
# Remove admin registrations for models that might not have the displayed fields
# or are handled differently (like GlobalSettings with django-solo).
# Review and uncomment/adjust the @admin.register sections above based on
# your actual models and desired admin interface.

# Example: If UserProfileAdmin was just a placeholder:
# admin.site.unregister(User) # If UserProfileAdmin was registered but incorrect

# Example: If ProductAdmin was placeholder:
# admin.site.unregister(Product) # If ProductAdmin was registered but incorrect

# --- END OF FILE ---