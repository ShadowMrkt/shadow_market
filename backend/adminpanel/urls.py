# backend/adminpanel/urls.py
from django.urls import path
from . import views  # Assuming views.py is in the same directory as urls.py

app_name = 'adminpanel'

urlpatterns = [
    # Staff Dashboard & General Views
    path('', views.admin_dashboard, name='dashboard'),  # Main admin dashboard
    path('users/', views.user_list, name='user_list'),
    path('users/<int:user_id>/', views.user_detail, name='user_detail'),
    path('users/<int:user_id>/ban/', views.ban_user, name='user_ban'),
    # Consider adding unban URL here if needed (or confirm ban_user handles both)
    # path('users/<int:user_id>/unban/', views.ban_user, name='user_unban'),

    path('orders/', views.order_list, name='order_list'),
    path('orders/<uuid:order_id>/', views.order_detail, name='order_detail'),
    # Note: Dispute resolution handled via POST to order_detail
    # Consider adding specific dispute action URLs if logic becomes complex

    # --- VENDOR APPLICATION URLs ---
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

    # --- (Legacy?) Vendor Management Action URLs ---
    # TODO: Review if these direct user actions are still needed or if they should operate via the Application model/views
    path('users/<int:user_id>/approve-vendor/', views.approve_vendor, name='vendor_approve'),
    path('users/<int:user_id>/reject-vendor/', views.reject_vendor, name='vendor_reject'),
    path('users/<int:user_id>/mark-bond-paid/', views.mark_bond_paid, name='vendor_bond_paid_mark'),
    path('users/<int:user_id>/forfeit-bond/', views.forfeit_bond, name='vendor_bond_forfeit'),

    # Owner Specific Views
    path('owner/', views.owner_dashboard, name='owner_dashboard'),
    path('owner/settings/', views.update_global_settings, name='update_settings'),
    path('owner/emergency/', views.emergency_actions, name='emergency_actions'),

    # Removed old/replaced URLs are commented out below or removed entirely for clarity.
    # path('owner/', views.owner_panel, name='owner_panel'), # Replaced by owner_dashboard
    # path('admin/', views.admin_panel, name='admin_panel'), # Replaced by admin_dashboard
]