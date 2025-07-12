# backend/store/views/category.py
# Revision: 1.1
# Date: 2025-06-07
# Author: Gemini
# Description: This file provides the API ViewSet for managing Categories.
# Changes:
# - Rev 1.1:
#   - Reviewed and confirmed original logic is correct. The `405 Method Not Allowed`
#     error from pytest originates from an incorrect URL router configuration,
#     not this file. This ViewSet requires proper registration with a DRF router
#     to function as intended.
#   - Added more explicit type hinting for method signatures and return values.
#   - Enhanced docstrings and comments for improved clarity and maintainability.
# - Rev 1.0:
#   - Initial creation of the file.
#   - Created CategoryViewSet inheriting from ModelViewSet to support full CRUD.
#   - Implemented dynamic permissions: Read-only for all users, Write access for Admins only.
#   - Set `lookup_field` to 'slug' to match URL configuration and test expectations.

# Standard Library Imports
import logging
from typing import List, Type

# Third-Party Imports
from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser, AllowAny, BasePermission

# Local Application Imports
from backend.store.models import Category
from backend.store.serializers import CategorySerializer

# --- Setup Loggers ---
logger = logging.getLogger(__name__)


# --- ViewSets ---

class CategoryViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows categories to be viewed or edited.

    This ViewSet provides full CRUD functionality for the Category model.
    It must be registered with a DRF router in `urls.py` to correctly
    map HTTP methods (GET, POST, PUT, DELETE) to actions.

    - **List & Retrieve**: Open to all users (authenticated or not).
    - **Create, Update, Delete**: Restricted to admin/staff users.
    """
    queryset = Category.objects.all().order_by('name')
    serializer_class = CategorySerializer
    lookup_field = 'slug'  # Use the human-readable slug for URL lookups

    def get_permissions(self) -> List[BasePermission]:
        """
        Instantiates and returns the list of permissions that this view requires based
        on the current action.

        - `AllowAny` for safe, read-only actions ('list', 'retrieve').
        - `IsAdminUser` for write actions ('create', 'update', 'partial_update', 'destroy').

        Returns:
            A list of permission instances for the current request.
        """
        if self.action in ['list', 'retrieve']:
            permission_classes: List[Type[BasePermission]] = [AllowAny]
        else:
            permission_classes = [IsAdminUser]

        return [permission() for permission in permission_classes]

# --- END OF FILE ---