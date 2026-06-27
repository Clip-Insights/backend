from django.urls import path
from .views import (
    FileAPIView,
    SearchFilesAPIView,
    StorageInfoAPIView,
    FolderAPIView,
    MoveFileAPIView,
    FolderFilesAPIView,
)

urlpatterns = [
    path("files/", FileAPIView.as_view(), name="files"),
    path("folders/", FolderAPIView.as_view(), name="folders"),
    path("search-files/", SearchFilesAPIView.as_view(), name="search-files"),
    path("storage-info/", StorageInfoAPIView.as_view(), name="storage-info"),
    path("move-file/", MoveFileAPIView.as_view(), name="move-file"),
    path("folder-files/", FolderFilesAPIView.as_view(), name="folder-files"),
]
