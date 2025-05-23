# backend/middleware/OwnerSessionMiddleware.py
# <<< Revision 1.1: Correct AUTH_USER_MODEL usage in isinstance >>>
# Revision Notes:
# - v1.1 (2025-05-18):
#   - FIXED: Used get_user_model() with isinstance() instead of settings.AUTH_USER_MODEL string
#     to resolve TypeError in process_request.
# - v1.0 (Initial or previous version):
#   - Initial creation or previous state.

import logging
from typing import Optional

from django.conf import settings
from django.contrib.auth import get_user_model # <<< ADDED IMPORT
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
# from django.utils.deprecation import MiddlewareMixin # Not strictly needed for new-style middleware

# --- Get an instance of a logger ---
logger = logging.getLogger(__name__)

class OwnerSessionMiddleware:
    """
    Custom middleware to manage session expiry for owner/superuser accounts
    differently from regular users.

    This middleware checks if the authenticated user is a superuser. If so,
    it sets the session expiry to the value defined in
    settings.OWNER_SESSION_COOKIE_AGE_SECONDS. Otherwise, it ensures the session
    expiry is set to settings.DEFAULT_SESSION_COOKIE_AGE_SECONDS.

    This middleware should be placed AFTER:
    - django.contrib.sessions.middleware.SessionMiddleware
    - django.contrib.auth.middleware.AuthenticationMiddleware
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.default_session_age = settings.DEFAULT_SESSION_COOKIE_AGE_SECONDS
        self.owner_session_age = settings.OWNER_SESSION_COOKIE_AGE_SECONDS
        logger.info(
            f"{self.__class__.__name__} initialized. "
            f"Owner session age: {self.owner_session_age} seconds."
        )


    def __call__(self, request: HttpRequest) -> HttpResponse:
        """
        Process the request: apply session expiry logic before calling the view.
        This method is called for each request.
        """
        # Process request part (can modify session before view is called)
        # This is where the original logic was, moved to process_request for clarity
        # if it were a MiddlewareMixin, or keep here for new-style.
        # For simplicity, let's do it before get_response if it modifies request/session.

        response = self.get_response(request)

        # Process response part (can modify response or session after view)
        # However, session expiry is usually set on request or before response is sent.
        # The logic for setting expiry often happens in process_request for MiddlewareMixin,
        # or directly in __call__ before get_response for new-style.
        # Here, we'll process it for the current request/session directly.
        self.process_session_expiry(request)


        return response

    def process_session_expiry(self, request: HttpRequest) -> None:
        """
        Helper method to encapsulate the session expiry logic.
        This can be called by __call__ or by process_request if using MiddlewareMixin.
        """
        user = getattr(request, 'user', None)
        session = getattr(request, 'session', None)

        if not session:
            logger.warning(f"{self.__class__.__name__}: request.session not found in process_session_expiry. Cannot modify session expiry.")
            return

        User = get_user_model() # <<< FIXED: Get the actual User model class
        is_owner = isinstance(user, User) and getattr(user, 'is_superuser', False)

        if is_owner:
            if session.get_expiry_age() != self.owner_session_age:
                session.set_expiry(self.owner_session_age)
                # logger.debug(f"Owner session expiry set to {self.owner_session_age} for user {user.username if user else 'Unknown'}")
        else: # Regular user or anonymous user
            if session.get_expiry_age() != self.default_session_age:
                session.set_expiry(self.default_session_age)
                # logger.debug(f"Default session expiry set to {self.default_session_age} for user {user.username if user and user.is_authenticated else 'Anonymous/Regular'}")

    # If you were using MiddlewareMixin, you might have:
    # def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
    #     """
    #     Checks the user and sets the session expiry if they are an owner/superuser.
    #     """
    #     self.process_session_expiry(request)
    #     return None # Continue processing other middleware and then the view


# Example of how it might have looked if using MiddlewareMixin structure (for context, not for use now):
# class OwnerSessionMiddleware(MiddlewareMixin):
#     def __init__(self, get_response):
#         super().__init__(get_response)
#         self.default_session_age = settings.DEFAULT_SESSION_COOKIE_AGE_SECONDS
#         self.owner_session_age = settings.OWNER_SESSION_COOKIE_AGE_SECONDS
#         logger.info(
#             f"{self.__class__.__name__} initialized. "
#             f"Owner session age: {self.owner_session_age} seconds."
#         )

#     def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
#         user = getattr(request, 'user', None)
#         session = getattr(request, 'session', None)

#         if not session:
#             logger.warning(f"{self.__class__.__name__}: request.session not found. Cannot modify session expiry.")
#             return None

#         User = get_user_model()
#         is_owner = isinstance(user, User) and getattr(user, 'is_superuser', False)

#         target_age = self.owner_session_age if is_owner else self.default_session_age
#         if session.get_expiry_age() != target_age:
#             session.set_expiry(target_age)
#             # logger.debug(f"Session expiry set to {target_age} for user {user.username if user and user.is_authenticated else 'Anonymous/Regular'}")
#         return None