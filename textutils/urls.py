from django.urls import path
from .views import ChatView, SummaryView, TokenLimitView, TranscribeView

urlpatterns = [
    path('chat/', ChatView.as_view(), name='chat'),
    path('summary/', SummaryView.as_view(), name='summary'),
    path('tokenlimit/', TokenLimitView.as_view(), name='tokenlimit'),
    path('transcribe/', TranscribeView.as_view(), name='transcribe'),
]
