from social_core.exceptions import AuthForbidden
from django.contrib.auth import get_user_model

User = get_user_model()


def require_existing_user(backend, details, uid, user=None, *args, **kwargs):
    """Allow Google login only for users already registered in the system."""
    if user:
        return {'user': user}

    email = details.get('email')
    if not email:
        raise AuthForbidden(backend)

    try:
        existing_user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        raise AuthForbidden(backend)

    if not existing_user.is_active:
        raise AuthForbidden(backend)

    return {'user': existing_user}
