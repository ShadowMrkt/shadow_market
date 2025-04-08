# backend/store/admin.py
from django.contrib import admin
from .models import User, Category, Product, Order, CryptoPayment, Feedback, SupportTicket, TicketMessage, GlobalSettings, AuditLog # Add AuditLog

# ... (keep existing admin registrations) ...
@admin.register(User)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_vendor', 'email_verified', 'vendor_bond')

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'vendor', 'price', 'available')

@admin.register(TicketMessage) # <-- Change Message to TicketMessage
class TicketMessageAdmin(admin.ModelAdmin): # <-- Change MessageAdmin to TicketMessageAdmin
    list_display = ('ticket', 'sender', 'created_at', 'message_preview') # <-- Use valid fields

    # Optional helper method from previous suggestion:
    def message_preview(self, obj):
         return (obj.message[:50] + '...') if len(obj.message) > 50 else obj.message
    message_preview.short_description = 'Message Preview'

@admin.register(GlobalSettings)
class GlobalSettingsAdmin(admin.ModelAdmin):
    list_display = ('freeze_funds', 'owner_wallet', 'updated_at')

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'actor', 'action', 'target_user', 'target_order', 'ip_address', 'details_short')
    list_filter = ('action', 'actor', 'timestamp')
    search_fields = ('actor__username', 'target_user__username', 'details', 'ip_address', 'target_order__id')
    readonly_fields = ('timestamp', 'actor', 'action', 'target_user', 'target_order', 'ip_address', 'details') # Make audit logs immutable in admin
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
        return request.user.is_superuser # Be very careful allowing deletion

# Remember to run python manage.py makemigrations store and python manage.py migrate