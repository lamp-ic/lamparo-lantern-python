"""
Django : dans urls.py —
    from lamparo_lantern.django import lantern
    urlpatterns = [path("lamparo", lantern()), ...]
"""
from typing import Optional

from . import handle


def lantern(root: Optional[str] = None):
    def view(request):
        from django.http import HttpResponse

        base = root
        if base is None:
            try:
                from django.conf import settings

                base = str(getattr(settings, "BASE_DIR", "")) or None
            except Exception:
                base = None
        status, headers, body = handle(
            request.method,
            request.path,
            lambda name: request.META.get("HTTP_" + name.upper().replace("-", "_")),
            root=base,
        )
        response = HttpResponse(body, status=status)
        for name, value in headers.items():
            response[name] = value
        return response

    view.csrf_exempt = True
    return view
