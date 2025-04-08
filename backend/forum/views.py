# backend/forum/views.py
# <<< Rewritten for Enterprise Grade: Optimization, Security, Pagination, Clarity >>>

import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import HttpRequest, HttpResponse, Http404, HttpResponseForbidden
from django.urls import reverse
from django.contrib import messages
from django.db import transaction
from django.conf import settings # For pagination default

# <<< BEST PRACTICE: Use try/except for local imports >>>
try:
    from .models import ForumCategory, ForumThread, ForumPost
    from .forms import ThreadForm, PostForm
    # Assuming User model is accessible via settings.AUTH_USER_MODEL if needed directly
except ImportError as e:
    logging.getLogger(__name__).critical(f"CRITICAL: Failed to import forum models/forms in views.py: {e}")
    # Define dummies or raise to prevent server start if imports fail
    raise ImportError(f"Cannot import Forum models/forms in views.py: {e}") from e

logger = logging.getLogger(__name__)

# --- Constants ---
# <<< BEST PRACTICE: Use settings for pagination size >>>
THREADS_PER_PAGE = getattr(settings, 'FORUM_THREADS_PER_PAGE', 20)
POSTS_PER_PAGE = getattr(settings, 'FORUM_POSTS_PER_PAGE', 15)

# --- Forum Views ---

def forum_index(request: HttpRequest) -> HttpResponse:
    """ Displays the list of top-level forum categories. """
    # <<< BEST PRACTICE: Filter out potential future soft-deleted categories if applicable >>>
    # Assuming ForumCategory doesn't have is_deleted for now.
    top_level_categories = ForumCategory.objects.filter(parent__isnull=True).order_by('name') # Use defined ordering
    # Consider annotating with thread/post counts if performance allows and needed on index
    # .annotate(num_threads=Count('threads', filter=Q(threads__is_deleted=False)), ...)

    context = {
        'categories': top_level_categories,
    }
    # <<< CHANGE: Explicit template path >>>
    return render(request, 'forum/index.html', context)

def category_detail(request: HttpRequest, category_id: int) -> HttpResponse:
    """ Displays threads within a specific category, handling pagination. """
    # <<< BEST PRACTICE: Use get_object_or_404 >>>
    category = get_object_or_404(ForumCategory, pk=category_id)

    # <<< BEST PRACTICE: Query optimization and filtering >>>
    thread_list = ForumThread.objects.filter(
        category=category,
        is_deleted=False # Exclude soft-deleted threads
    ).select_related( # Optimize by fetching related objects in one query
        'author', 'last_post_by'
    ).order_by('-is_sticky', '-last_post_at') # Use model's default ordering

    # <<< BEST PRACTICE: Implement pagination >>>
    paginator = Paginator(thread_list, THREADS_PER_PAGE)
    page_number = request.GET.get('page')

    try:
        threads = paginator.page(page_number)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        threads = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        threads = paginator.page(paginator.num_pages)

    context = {
        'category': category,
        'threads': threads, # Pass paginated object to template
    }
    # <<< CHANGE: Explicit template path >>>
    return render(request, 'forum/category_detail.html', context)

# <<< BEST PRACTICE: Require login to create threads >>>
@login_required
def create_thread(request: HttpRequest, category_id: int) -> HttpResponse:
    """ Handles creation of a new thread within a category. """
    category = get_object_or_404(ForumCategory, pk=category_id)

    if request.method == 'POST':
        thread_form = ThreadForm(request.POST)
        # Post form also needed for the first post's content
        # <<< CHANGE: Use prefix to distinguish forms if needed, though here context is clear >>>
        # post_form = PostForm(request.POST) # Not strictly needed if content comes from ThreadForm

        if thread_form.is_valid(): # Content is validated/sanitized by ThreadForm's clean_content
            try:
                # <<< BEST PRACTICE: Use atomic transaction for multi-step creation >>>
                with transaction.atomic():
                    # Create the thread
                    new_thread = ForumThread.objects.create(
                        category=category,
                        title=thread_form.cleaned_data['title'],
                        author=request.user # Assign logged-in user as author
                        # Denormalized fields will be updated by signals upon first post creation
                    )
                    # Create the initial post
                    ForumPost.objects.create(
                        thread=new_thread,
                        author=request.user,
                        content=thread_form.cleaned_data['content'] # Use sanitized content
                        # parent_post is null for the first post
                    )
                    # Signals should handle updating thread stats now

                messages.success(request, _("Thread created successfully."))
                # <<< BEST PRACTICE: Redirect to the new thread's detail view >>>
                # Signals should have updated the thread, maybe redirect to last page? Simple redirect for now.
                return redirect('forum:thread_detail', thread_id=new_thread.pk)

            except Exception as e:
                logger.exception(f"Error creating thread in Category {category_id} by User {request.user.username}: {e}")
                messages.error(request, _("An unexpected error occurred while creating the thread. Please try again."))
                # Fall through to render form again with errors

    else: # GET request
        thread_form = ThreadForm()
        # post_form = PostForm() # Not needed for GET

    context = {
        'category': category,
        'thread_form': thread_form,
        # 'post_form': post_form, # Not needed for GET
    }
    # <<< CHANGE: Explicit template path >>>
    return render(request, 'forum/create_thread.html', context)


def thread_detail(request: HttpRequest, thread_id: int) -> HttpResponse:
    """
    Displays posts within a thread, handles replies, checks lock status, paginates posts.
    """
    # <<< BEST PRACTICE: select_related for efficiency >>>
    thread = get_object_or_404(
        ForumThread.objects.select_related('category', 'author'),
        pk=thread_id
    )

    # <<< BEST PRACTICE: Check soft delete status >>>
    if thread.is_deleted:
        # Or maybe show a "Thread deleted" message instead of 404?
        raise Http404(_("This thread has been deleted."))

    # Handle POST requests (replies) first
    reply_form = PostForm() # Initialize form for GET display
    if request.method == 'POST':
        # <<< BEST PRACTICE: Check login status before processing POST >>>
        if not request.user.is_authenticated:
            # Redirect to login or return forbidden, depending on desired flow
            messages.warning(request, _("You must be logged in to post a reply."))
            return redirect(f"{settings.LOGIN_URL}?next={request.path}")

        # <<< BEST PRACTICE: Check if thread is locked >>>
        if thread.is_locked:
            messages.error(request, _("This thread is locked and does not allow new replies."))
            # Use HttpResponseForbidden or redirect back with error message
            return redirect('forum:thread_detail', thread_id=thread.pk) # Redirect back to thread

        reply_form = PostForm(request.POST)
        if reply_form.is_valid(): # Content is sanitized by form's clean_content
            try:
                # parent_post_id = request.POST.get('parent_post_id') # If implementing direct quote replies
                # parent_post = None
                # if parent_post_id:
                #    try: parent_post = ForumPost.objects.get(pk=parent_post_id, thread=thread)
                #    except ForumPost.DoesNotExist: messages.warning(request, _("Invalid parent post quoted."))

                # <<< BEST PRACTICE: Use atomic transaction for safety >>>
                with transaction.atomic():
                    ForumPost.objects.create(
                        thread=thread,
                        author=request.user,
                        content=reply_form.cleaned_data['content'],
                        # parent_post=parent_post # Add if implementing quotes
                    )
                    # Signals will update thread stats automatically

                messages.success(request, _("Reply posted successfully."))
                # <<< BEST PRACTICE: Redirect to the last page after posting >>>
                # Calculate last page number after the new post is considered
                post_count = ForumPost.objects.filter(thread=thread, is_deleted=False).count()
                last_page = (post_count + POSTS_PER_PAGE - 1) // POSTS_PER_PAGE
                redirect_url = reverse('forum:thread_detail', kwargs={'thread_id': thread.pk}) + f'?page={last_page}'
                return redirect(redirect_url)

            except Exception as e:
                logger.exception(f"Error saving reply in Thread {thread_id} by User {request.user.username}: {e}")
                messages.error(request, _("An unexpected error occurred while posting your reply. Please try again."))
                # Fall through to render page again with form errors

        # else: # Form is invalid, fall through to render page with form errors

    # --- GET Request Logic ---
    # <<< BEST PRACTICE: Query optimization and filtering >>>
    post_list = ForumPost.objects.filter(
        thread=thread,
        is_deleted=False # Exclude soft-deleted posts
    ).select_related( # Optimize author lookup
        'author'
    ).order_by('created_at') # Order by creation time

    # <<< BEST PRACTICE: Implement pagination >>>
    paginator = Paginator(post_list, POSTS_PER_PAGE)
    page_number = request.GET.get('page')

    try:
        posts = paginator.page(page_number)
    except PageNotAnInteger:
        posts = paginator.page(1)
    except EmptyPage:
        posts = paginator.page(paginator.num_pages)

    context = {
        'thread': thread,
        'posts': posts, # Pass paginated object
        'reply_form': reply_form, # Pass form (blank for GET, potentially with errors for POST failure)
        'is_locked': thread.is_locked, # Pass lock status for template logic
    }
    # <<< CHANGE: Explicit template path >>>
    return render(request, 'forum/thread_detail.html', context)