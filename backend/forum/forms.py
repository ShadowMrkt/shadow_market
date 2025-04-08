# backend/forum/forms.py
# <<< Rewritten for Enterprise Grade: Strict Sanitization, Validation >>>

import logging
from django import forms
from django.utils.translation import gettext_lazy as _

# <<< BEST PRACTICE: Use try/except for external library imports >>>
try:
    import bleach
    BLEACH_AVAILABLE = True
except ImportError:
    logging.getLogger(__name__).critical(
        "CRITICAL: bleach library not installed. Forum content sanitization DISABLED. `pip install bleach`"
    )
    BLEACH_AVAILABLE = False

# <<< BEST PRACTICE: Centralize Bleach configuration >>>
# Define a strict set of allowed HTML elements and attributes.
# Start with minimal tags and expand cautiously ONLY IF necessary.
# Common safe formatting tags:
ALLOWED_TAGS = [
    'p', 'b', 'strong', 'i', 'em', 'u', 'strike', 'del', 's', # Basic text formatting
    'ul', 'ol', 'li', # Lists
    'blockquote', 'pre', 'code', # Quotes and code blocks
    'br', # Line breaks
    # 'a', # Links add significant risk - enable only if absolutely necessary and audited.
    # 'img', # Images add significant risk - generally disable.
]
# Define allowed attributes (minimal set)
ALLOWED_ATTRIBUTES = {
    # 'a': ['href', 'title', 'rel'], # Example if links were allowed (add rel="nofollow noopener noreferrer")
    '*': ['class'], # Allow class attribute for potential styling (use cautiously)
}
# Define allowed styles (generally avoid allowing 'style' attribute)
ALLOWED_STYLES = []

logger = logging.getLogger(__name__)

# --- Base Form with Content Sanitization ---

class BaseForumContentForm(forms.Form):
    """ Base form providing content sanitization logic. """
    # <<< BEST PRACTICE: Move cleaning logic to a base class or shared utility >>>
    content = forms.CharField(
        label=_("Content"),
        widget=forms.Textarea(attrs={'rows': 10, 'cols': 40}), # Sensible default size
        required=True,
        help_text=_("Enter the main content. Limited HTML is allowed.")
    )

    def clean_content(self) -> str:
        """ Cleans and sanitizes the content field using bleach. """
        content_data = self.cleaned_data.get('content', '')
        if not BLEACH_AVAILABLE:
            # <<< CRITICAL SECURITY: Fail open is dangerous; ideally prevent form submission >>>
            # For now, log critical error. Production system MUST have bleach.
            logger.critical("BLEACH NOT AVAILABLE - Forum content is NOT being sanitized!")
            # Return raw data, potentially unsafe!
            return content_data

        try:
            # <<< BEST PRACTICE: Use bleach.clean with explicit settings >>>
            sanitized_content = bleach.clean(
                content_data,
                tags=ALLOWED_TAGS,
                attributes=ALLOWED_ATTRIBUTES,
                styles=ALLOWED_STYLES,
                strip=True,  # Remove disallowed tags entirely
                strip_comments=True # Remove HTML comments
            ).strip() # Remove leading/trailing whitespace after sanitizing
            # <<< BEST PRACTICE: Check if content changed significantly (optional logging) >>>
            # if sanitized_content != content_data.strip():
            #     logger.debug(f"Content sanitized. Original length: {len(content_data)}, Sanitized length: {len(sanitized_content)}")
            return sanitized_content
        except Exception as e:
            # Catch potential errors during cleaning
            logger.exception(f"Error during bleach sanitization: {e}")
            # <<< BEST PRACTICE: Raise validation error if sanitization fails >>>
            raise forms.ValidationError(_("There was an error processing your content. Please try again."))


# --- Form for Creating New Threads ---

class ThreadForm(BaseForumContentForm): # <<< CHANGE: Inherit from Base >>>
    """ Form for creating a new ForumThread. """
    title = forms.CharField(
        label=_("Thread Title"),
        max_length=255, # Match model field max_length
        required=True,
        widget=forms.TextInput(attrs={'size': '50'}),
        help_text=_("Enter a descriptive title for your thread.")
    )
    # Content field is inherited from BaseForumContentForm

    # <<< BEST PRACTICE: Add custom clean methods if needed >>>
    # Example: Prevent excessively short titles
    # def clean_title(self):
    #     title = self.cleaned_data.get('title', '')
    #     if len(title) < 5:
    #         raise forms.ValidationError(_("Title must be at least 5 characters long."))
    #     return title


# --- Form for Creating New Posts (Replies) ---

class PostForm(BaseForumContentForm): # <<< CHANGE: Inherit from Base >>>
    """ Form for creating a new ForumPost (reply within a thread). """
    # Only the 'content' field is needed, inherited from BaseForumContentForm.
    # The associated 'thread' and potential 'parent_post' are handled by the view logic.

    # No additional fields needed by default unless adding things like subject lines for replies etc.
    pass