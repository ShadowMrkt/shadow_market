# backend/adminpanel/urls.py
from django.urls import path
from . import views  # Assuming views.py is in the same directory as urls.py

app_name = 'adminpanel'

urlpatterns = [
    # Staff Dashboard & General Views
    path('', views.admin_dashboard, name='dashboard'),  # Main admin dashboard
    path('users/', views.user_list, name='user_list'),
    path('users/<int:user_id>/', views.user_detail, name='user_detail'),
    path('users/<int:user_id>/ban/', views.ban_user, name='user_ban'), # Handles ban/unban via POST check

    path('orders/', views.order_list, name='order_list'),
    path('orders/<uuid:order_id>/', views.order_detail, name='order_detail'),
    # Note: Dispute resolution handled via POST to order_detail

    # --- VENDOR APPLICATION URLs (Primary Workflow) ---
    path(
        'applications/pending/', # List applications needing review
        views.vendor_application_list,
        name='vendor_application_list'
    ),
    path(
        'applications/<int:application_id>/review/', # Detail view for review/action
        views.review_vendor_application,
        name='review_vendor_application'
    ),

    # --- Specific Vendor Action URLs (Manual Overrides / Post-Approval Actions) ---
    # TODO: Review the necessity and security of these direct actions.
    #       Ensure templates link appropriately and permissions are strict.
    # path('users/<int:user_id>/approve-vendor/', views.approve_vendor, name='vendor_approve'), # REMOVED - Use application review view
    # path('users/<int:user_id>/reject-vendor/', views.reject_vendor, name='vendor_reject'),    # REMOVED - Use application review view
    path('users/<int:user_id>/mark-bond-paid/', views.mark_bond_paid, name='vendor_bond_paid_mark'), # Manual override for bond check
    path('users/<int:user_id>/forfeit-bond/', views.forfeit_bond, name='vendor_bond_forfeit'),     # Action to seize paid bond

    # Owner Specific Views
    path('owner/', views.owner_dashboard, name='owner_dashboard'),
    path('owner/settings/', views.update_global_settings, name='update_settings'),
    path('owner/emergency/', views.emergency_actions, name='emergency_actions'),

]# Note: The above URLs are designed to be descriptive and follow a RESTful pattern.
#       Ensure that the views.py file contains the corresponding view functions.