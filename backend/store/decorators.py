import functools
import time
import logging
from django.http import HttpResponseForbidden
from typing import Callable
from redis import Redis

logger = logging.getLogger('store')
redis_client = Redis(host='localhost', port=6379, db=0)

def secure_token_required(view_func: Callable) -> Callable:
    from django.conf import settings
    @functools.wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        token = request.headers.get('X-Secure-Token')
        if not token or token != getattr(settings, 'SECURE_OPERATION_TOKEN', None):
            logger.warning(f"[secure_token_required] Missing/invalid token for {request.user}")
            return HttpResponseForbidden("Missing or invalid secure token.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def distributed_rate_limit(limit: int, per_seconds: int) -> Callable:
    def decorator(view_func: Callable) -> Callable:
        @functools.wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            ip = request.META.get('REMOTE_ADDR')
            key = f"rate_limit:{ip}"
            try:
                current = redis_client.incr(key)
                if current == 1:
                    redis_client.expire(key, per_seconds)
                if current > limit:
                    logger.warning(f"[distributed_rate_limit] IP {ip} exceeded rate limit.")
                    return HttpResponseForbidden("Rate limit exceeded.")
            except Exception as e:
                logger.error(f"[distributed_rate_limit] Redis error: {e}")
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
