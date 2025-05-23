# backend/store/views/__init__.py
# Revision 13: Reverted to minimal content to break circular import.
# Date: 2025-05-03
# Author: Gemini
# --- Previous History ---
# Revision 12: Added relative imports for all view modules (Triggered Circular Import).
# Revision 11: Explicitly import shared/common views.

# Keep this file minimal to avoid circular imports.
# Imports needed across different view modules should generally be placed
# within those specific modules, or potentially in a shared 'base_views.py'
# if absolutely necessary and carefully managed.

# Example: Exposing only truly common base classes or utilities if needed.
# from .base import BaseStoreView # Example if you had a base view class here