from django.shortcuts import render
from django.http import JsonResponse

def hello_view(request):
    return JsonResponse({"message": "Hello", "great":True})

def dummy_view(request):
    return JsonResponse({"used_space": 69, "allowed_space": 100, "remaining_space": 31, "status": "success"})

