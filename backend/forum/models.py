# backend/forum/models.py
# <<< Rewritten for Enterprise Grade: Clarity, Indexing, Timestamps, Relationships >>>

import logging
from django.db import models
from django.conf import settings # To reference AUTH_USER_MODEL correctly
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

# <<< BEST PRACTICE: Import User model robustly >>>
try:
    User = settings.AUTH_USER_MODEL
except AttributeError:
    # Fallback or raise error if AUTH_USER_MODEL isn't set early enough
    logging.getLogger(__name__).critical("AUTH_USER_MODEL not found in settings!")
    # You might need to import directly if settings aren't fully loaded in some contexts
    # from store.models import User # Adjust import path if necessary
    raise ImportError("Could not determine User model from settings.")


# --- Forum Category ---
class ForumCategory(models.Model):
    """ Represents a category or sub-category in the forum. """
    # <<< BEST PRACTICE: Use verbose names for clarity >>>
    name = models.CharField(
        _("Category Name"),
        max_length=150,
        unique=True, # Ensure category names are unique
        help_text=_("Name of the forum category.")
    )
    description = models.TextField(
        _("Description"),
        blank=True,
        help_text=_("A brief description of the category's topic.")
    )
    # <<< BEST PRACTICE: Use ForeignKey for hierarchy >>>
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL, # If a parent category is deleted, sub-categories become top-level
        related_name='subcategories',
        verbose_name=_("Parent Category"),
        help_text=_("Leave blank for a top-level category.")
    )
    # <<< BEST PRACTICE: Track creation/update times >>>
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True, editable=False)
    # <<< BEST PRACTICE: Add ordering field if manual sorting needed >>>
    # display_order = models.PositiveIntegerField(_("Display Order"), default=0, db_index=True)

    class Meta:
        verbose_name = _("Forum Category")
        verbose_name_plural = _("Forum Categories")
        # <<< BEST PRACTICE: Define default ordering >>>
        ordering = ['parent__name', 'name'] # Order by parent name, then self name

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} -> {self.name}"
        return self.name

# --- Forum Thread ---
class ForumThread(models.Model):
    """ Represents a discussion thread within a category. """
    category = models.ForeignKey(
        ForumCategory,
        on_delete=models.CASCADE, # If category is deleted, delete its threads
        related_name='threads',
        verbose_name=_("Category"),
        db_index=True, # Index for filtering threads by category
    )
    title = models.CharField(
        _("Thread Title"),
        max_length=255,
        help_text=_("The main subject of the discussion thread.")
    )
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL, # Keep thread if author account is deleted
        null=True, # Allow anonymous/deleted author threads? Usually no, but SET_NULL requires it.
        blank=False, # Must have an author initially
        related_name='forum_threads',
        verbose_name=_("Author"),
        db_index=True,
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True, editable=False, db_index=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True, editable=False)

    # --- Status Flags ---
    is_sticky = models.BooleanField(
        _("Sticky"),
        default=False,
        db_index=True, # Index for easy filtering of sticky threads
        help_text=_("Sticky threads appear at the top of the category list.")
    )
    is_locked = models.BooleanField(
        _("Locked"),
        default=False,
        help_text=_("Locked threads do not allow new posts.")
    )
    is_deleted = models.BooleanField( # <<< BEST PRACTICE: Soft delete flag >>>
        _("Deleted"),
        default=False,
        db_index=True,
        help_text=_("Flag for soft deletion instead of hard delete.")
    )

    # --- Denormalized Fields (Managed by signals.py) ---
    # <<< BEST PRACTICE: Ensure denormalized fields can handle deletion of related objects >>>
    post_count = models.PositiveIntegerField(
        _("Post Count"),
        default=0,
        help_text=_("Total number of posts in this thread (automatically updated).")
    )
    last_post_at = models.DateTimeField(
        _("Last Post Time"),
        null=True,
        blank=True,
        db_index=True, # Index for ordering by recent activity
        help_text=_("Timestamp of the latest post (automatically updated).")
    )
    last_post_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL, # Keep thread info even if last poster is deleted
        null=True,
        blank=True,
        related_name='+', # No reverse relation needed from User
        verbose_name=_("Last Poster"),
        help_text=_("User who made the latest post (automatically updated).")
    )

    # <<< REMOVED: Signal logic moved to signals.py >>>

    class Meta:
        verbose_name = _("Forum Thread")
        verbose_name_plural = _("Forum Threads")
        # <<< BEST PRACTICE: Default ordering prioritizes sticky, then recent activity >>>
        ordering = ['-is_sticky', '-last_post_at', '-created_at']
        indexes = [
            models.Index(fields=['category', 'is_deleted', 'is_sticky', 'last_post_at']),
            models.Index(fields=['author', 'is_deleted', 'created_at']),
        ]

    def __str__(self):
        return self.title

    # <<< BEST PRACTICE: Consider adding a get_absolute_url if needed, though less common for APIs >>>
    # def get_absolute_url(self):
    #     from django.urls import reverse
    #     return reverse('forum:thread_detail', kwargs={'pk': self.pk})


# --- Forum Post ---
class ForumPost(models.Model):
    """ Represents a single post within a forum thread. """
    thread = models.ForeignKey(
        ForumThread,
        on_delete=models.CASCADE, # If thread is deleted, delete its posts
        related_name='posts',
        verbose_name=_("Thread"),
        db_index=True, # Index for retrieving posts for a thread
    )
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL, # Keep post if author is deleted, show as '[deleted]'
        null=True, # Allow posts from deleted users
        blank=False,
        related_name='forum_posts',
        verbose_name=_("Author"),
        db_index=True,
    )
    # <<< BEST PRACTICE: TextField for potentially long post content >>>
    content = models.TextField(
        _("Content"),
        help_text=_("The main body of the forum post (HTML sanitized).")
    )
    # <<< CHANGE: Use ForeignKey for replies/quoting >>>
    parent_post = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL, # If the parent post is deleted, the reply remains but loses context
        related_name='replies',
        verbose_name=_("Parent Post (Reply To)"),
        help_text=_("The post this post is replying to, if any.")
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True, editable=False, db_index=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True, editable=False)
    # <<< BEST PRACTICE: Soft delete >>>
    is_deleted = models.BooleanField(
        _("Deleted"),
        default=False,
        db_index=True,
        help_text=_("Flag for soft deletion instead of hard delete.")
    )
    # <<< BEST PRACTICE: Store IP (hashed/anonymized?) if needed for moderation, consider privacy implications >>>
    # author_ip_address = models.GenericIPAddressField(_("Author IP"), null=True, blank=True, editable=False)

    # <<< REMOVED: Signal logic moved to signals.py >>>

    class Meta:
        verbose_name = _("Forum Post")
        verbose_name_plural = _("Forum Posts")
        # <<< BEST PRACTICE: Default ordering by creation time within a thread >>>
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['thread', 'is_deleted', 'created_at']),
            models.Index(fields=['author', 'is_deleted', 'created_at']),
            models.Index(fields=['parent_post', 'is_deleted']),
        ]

    def __str__(self):
        author_name = self.author.username if self.author else '[deleted]'
        return f"Post by {author_name} in '{self.thread.title}' at {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    # Helper property
    @property
    def is_reply(self):
        return self.parent_post is not None