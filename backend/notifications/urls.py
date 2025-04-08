# backend/notifications/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import NotificationViewSet

app_name = 'notifications'

# Create a router and register our viewsets with it.
router = DefaultRouter()
# Use 'notifications' as the prefix for the API endpoints related to this app
router.register(r'', NotificationViewSet, basename='notification') # Register at root of this app's include

# The API URLs are now determined automatically by the router.
# GET /api/notifications/ -> List user's notifications
# GET /api/notifications/{pk}/ -> Retrieve specific notification
# POST /api/notifications/{pk}/mark-read/ -> Mark specific notification as read
# POST /api/notifications/mark-all-read/ -> Mark all user's notifications as read
urlpatterns = [
    path('', include(router.urls)),
]