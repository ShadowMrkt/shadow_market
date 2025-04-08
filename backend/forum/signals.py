# backend/forum/signals.py
# <<< Rewritten for Enterprise Grade: Atomic, Efficient Denormalization >>>

import logging
from django.db import transaction
from django.db.models import F, Subquery, OuterRef, Max
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

# <<< BEST PRACTICE: Use try/except for model imports >>>
try:
    from .models import ForumPost, ForumThread
except ImportError as e:
    # Handle import error if models aren't found or apps aren't ready
    logging.getLogger(__name__).error(f"Error importing Forum models in signals: {e}")
    # Define dummy classes or raise to prevent signal registration errors
    class DummyModel: pass
    ForumPost = DummyModel # type: ignore
    ForumThread = DummyModel # type: ignore
    # Alternatively, raise the error if models MUST exist for the app to load
    # raise ImportError(f"Cannot import Forum models in signals: {e}") from e

logger = logging.getLogger(__name__)

# <<< BEST PRACTICE: Connect signals using the @receiver decorator >>>

@receiver(post_save, sender=ForumPost, dispatch_uid="update_thread_on_post_save")
def update_thread_on_post_save(sender, instance: ForumPost, created: bool, **kwargs):
    """
    Signal handler to update ForumThread denormalized fields when a ForumPost is saved.
    Uses efficient F() expressions for updates.
    """
    # <<< BEST PRACTICE: Check if sender is the expected model >>>
    if sender != ForumPost:
        logger.warning(f"Signal received from unexpected sender: {sender}")
        return

    thread = instance.thread
    if not thread:
        logger.warning(f"ForumPost {instance.pk} has no associated thread during post_save.")
        return

    # <<< BEST PRACTICE: Perform updates within an atomic transaction >>>
    try:
        with transaction.atomic():
            # Lock the thread row to prevent race conditions during update
            thread_locked = ForumThread.objects.select_for_update().get(pk=thread.pk)

            # Only update if the post is newly created and not soft-deleted
            # Or if an existing post is being updated (e.g., edited, undeleted - though signals don't fire on QuerySet.update())
            # Assuming 'created' means truly new post here.
            # Also assuming soft-deleted posts should not affect counts/last post
            if created and not instance.is_deleted:
                # Increment post count atomically
                thread_locked.post_count = F('post_count') + 1
                # Update last post details directly from the new instance
                thread_locked.last_post_at = instance.created_at
                thread_locked.last_post_by = instance.author
                # Save only the updated fields
                thread_locked.save(update_fields=['post_count', 'last_post_at', 'last_post_by', 'updated_at'])
                logger.debug(f"Thread {thread.pk}: Post count incremented, last post updated by new Post {instance.pk}")
            elif not created:
                # Handle updates to existing posts (e.g., undeletion, though save() might not be called)
                # If a post is undeleted (is_deleted=False), we might need to recalculate
                # If content is edited, usually only updated_at changes, no need to update thread stats
                # Complex logic for soft-delete updates might be needed here if required.
                # For now, focus on creation/deletion.
                pass

    except ForumThread.DoesNotExist:
         logger.error(f"Failed to find ForumThread {thread.pk} during post_save for Post {instance.pk}.")
    except Exception as e:
        # <<< BEST PRACTICE: Log exceptions during signal handling >>>
        logger.exception(f"Error updating ForumThread {thread.pk} on post_save for Post {instance.pk}: {e}")


@receiver(post_delete, sender=ForumPost, dispatch_uid="update_thread_on_post_delete")
def update_thread_on_post_delete(sender, instance: ForumPost, **kwargs):
    """
    Signal handler to update ForumThread denormalized fields when a ForumPost is deleted.
    Uses efficient subqueries to find the new last post and updates count atomically.
    """
    # <<< BEST PRACTICE: Check sender >>>
    if sender != ForumPost:
        logger.warning(f"Signal received from unexpected sender: {sender}")
        return

    thread = instance.thread
    if not thread:
        # Post might be deleted after thread, or relation was nullified? Log warning.
        logger.warning(f"ForumPost {instance.pk} had no associated thread during post_delete.")
        return

    # <<< BEST PRACTICE: Perform updates within an atomic transaction >>>
    try:
        with transaction.atomic():
            # Lock the thread row
            thread_locked = ForumThread.objects.select_for_update().get(pk=thread.pk)

            # --- Recalculate Last Post and Author using Subquery ---
            # <<< BEST PRACTICE: Efficient recalculation using subqueries >>>
            # Find the latest non-deleted post within the same thread
            latest_post_subquery = ForumPost.objects.filter(
                thread=OuterRef('pk'), # Reference the outer thread's pk
                is_deleted=False      # Only consider non-deleted posts
            ).order_by('-created_at') # Order by latest first

            # Use annotation with Subquery to get the latest post details directly
            # Max() aggregation used within Subquery for 'last_post_at' and conditional lookup for 'last_post_by'
            thread_update_data = ForumThread.objects.filter(pk=thread_locked.pk).annotate(
                # Count remaining non-deleted posts
                new_post_count=Count('posts', filter=models.Q(posts__is_deleted=False)),
                # Get the latest timestamp directly
                new_last_post_at=Subquery(latest_post_subquery.values('created_at')[:1]),
                # Get the author_id of the latest post
                new_last_post_by_id=Subquery(latest_post_subquery.values('author_id')[:1])
            ).values( # Select only the annotated fields needed for update
                'new_post_count',
                'new_last_post_at',
                'new_last_post_by_id'
            ).first() # Get the single dictionary result for our thread pk

            if thread_update_data:
                # Apply the recalculated values
                thread_locked.post_count = thread_update_data.get('new_post_count', 0) # Default to 0 if none found
                thread_locked.last_post_at = thread_update_data.get('new_last_post_at') # Will be None if no posts remain
                thread_locked.last_post_by_id = thread_update_data.get('new_last_post_by_id') # Will be None if no posts/author remain
                thread_locked.save(update_fields=['post_count', 'last_post_at', 'last_post_by', 'updated_at'])
                logger.info(f"Thread {thread.pk}: Stats recalculated after Post {instance.pk} deletion. Count: {thread_locked.post_count}")
            else:
                 # Should not happen if we locked the thread, but handle defensively
                 logger.error(f"Failed to retrieve update data for ForumThread {thread_locked.pk} during post_delete for Post {instance.pk}.")
                 # Manually decrement count as fallback? Risky. Better to log error.
                 # thread_locked.post_count = F('post_count') - 1 # Less safe fallback
                 # thread_locked.save(update_fields=['post_count', 'updated_at'])

    except ForumThread.DoesNotExist:
         logger.error(f"Failed find ForumThread {thread.pk} during post_delete for Post {instance.pk}.")
    except Exception as e:
        logger.exception(f"Error updating ForumThread {thread.pk} on post_delete for Post {instance.pk}: {e}")

# <<< BEST PRACTICE: Ensure signals are connected via AppConfig's ready() method >>>
# The forum/apps.py file should contain:
#
# from django.apps import AppConfig
#
# class ForumConfig(AppConfig):
#     default_auto_field = 'django.db.models.BigAutoField'
#     name = 'forum'
#
#     def ready(self):
#         import forum.signals # noqa