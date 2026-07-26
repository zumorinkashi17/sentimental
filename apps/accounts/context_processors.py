from .models import User


def user_profile(request):
    user_id = request.session.get('user_id')
    if user_id:
        try:
            return {'user_profile': User.objects.get(pk=user_id)}
        except User.DoesNotExist:
            pass
    return {'user_profile': None}
