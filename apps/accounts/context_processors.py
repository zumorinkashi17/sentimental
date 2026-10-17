from .models import User


def user_profile(request):
    # Reuse the user already resolved by ``_get_session_user`` for this request
    # instead of hitting the database a second time while rendering.
    user = getattr(request, '_sentimental_user', None)
    if user is None:
        user_id = request.session.get('user_id')
        if user_id:
            try:
                user = User.objects.get(pk=user_id)
            except User.DoesNotExist:
                user = None
        if user is not None:
            request._sentimental_user = user
    return {'user_profile': user}
