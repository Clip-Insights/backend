import os

from django.http import JsonResponse


def health_check(request):
    model_path = os.path.join(
        os.path.dirname(__file__), "..", "videos", "embeddings", "all-MiniLM-L6-v2"
    )
    model_ready = os.path.exists(model_path)
    return JsonResponse({
        "status": "healthy" if model_ready else "degraded",
        "model_loaded": model_ready,
        "version": os.getenv("IMAGE_TAG", "unknown"),
    })
