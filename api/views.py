from django.http import JsonResponse
import os

def hello_view(request):
    return JsonResponse({"message": "Hello", "great":True})

def dummy_view(request):
    return JsonResponse({"used_space": 69, "allowed_space": 100, "remaining_space": 31, "status": "success"})

def health_check(request):
    """Health check endpoint for Cloud Run probes."""
    model_path = os.path.join(os.path.dirname(__file__), '..', 'textutils', 'embeddings', 'all-MiniLM-L6-v2')
    model_ready = os.path.exists(model_path)
    
    return JsonResponse({
        'status': 'healthy' if model_ready else 'degraded',
        'model_loaded': model_ready,
        'version': os.getenv('IMAGE_TAG', 'unknown'),
    })
