from django.urls import path
from .views import hello_view, dummy_view

urlpatterns = [
    path('hello/', hello_view, name='hello'),
    path('dummy/', dummy_view, name='dummy')
]
