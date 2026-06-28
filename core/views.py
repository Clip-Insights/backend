import os

from django.http import JsonResponse


def health_check(request):
    return JsonResponse({
        "status": "healthy",
        "version": os.getenv("IMAGE_TAG", "unknown"),
    })
