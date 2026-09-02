from django.http import JsonResponse


class ForcePasswordChangeMiddleware:
    allowed_paths = {
        "/api/v1/auth/session/",
        "/api/v1/auth/logout/",
        "/api/v1/auth/password/change/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and request.user.must_change_password
            and request.path.startswith("/api/v1/")
            and request.path not in self.allowed_paths
        ):
            return JsonResponse(
                {
                    "error": {
                        "status": 403,
                        "detail": "You must change your temporary password before continuing.",
                    }
                },
                status=403,
            )
        return self.get_response(request)
