from django.conf import settings
from django.shortcuts import redirect


class LoginRequiredMiddleware:
    """Require login for all pages except defined exemptions."""

    def __init__(self, get_response):
        self.get_response = get_response
        static_url = settings.STATIC_URL
        if not static_url.startswith('/'):
            static_url = f'/{static_url}'
        self.exempt_paths = [
            '/accounts/login/',
            '/accounts/logout/',
            '/accounts/password_reset/',
            '/accounts/password_reset/done/',
            '/accounts/reset/',
            '/oauth/',
            '/admin/',
            static_url,
        ]

    def __call__(self, request):
        path = request.path_info
        if any(path == exempt or path.startswith(exempt) for exempt in self.exempt_paths):
            return self.get_response(request)

        if not request.session.get('user_id'):
            return redirect(f'/accounts/login/?next={request.get_full_path()}&reason=session_expired')

        return self.get_response(request)
