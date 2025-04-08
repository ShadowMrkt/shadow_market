# shadow_market/backend/forum/urls.py
from django.urls import path
from . import views # Import views from the current directory

app_name = 'forum' # Namespace for URLs (e.g., {% url 'forum:index' %})

urlpatterns = [
    # Example: /forum/
    path('', views.forum_index, name='index'),

    # Example: /forum/category/general-discussion/
    path('category/<slug:category_slug>/', views.category_detail, name='category_detail'),

    # Example: /forum/category/general-discussion/create/
    path('category/<slug:category_slug>/create/', views.create_thread, name='create_thread'),

    # Example: /forum/thread/a1b2c3d4-e5f6.../
    # Note: Posting replies is handled within the thread_detail view via POST
    path('thread/<uuid:thread_id>/', views.thread_detail, name='thread_detail'),

    # If you wanted a separate URL specifically for posting replies (less common):
    # path('thread/<uuid:thread_id>/reply/', views.create_post, name='create_post'), # Assumes a separate create_post view exists
]