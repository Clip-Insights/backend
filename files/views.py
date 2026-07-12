import logging
import os
import uuid

from django.db.models import Q
from django.utils.timezone import now
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from integrations.registry import get_storage
from plans.services import LimitExceeded, get_plan_for
from .models import File, Folder
from .serializers import FileSerializer, FolderSerializer
from .utils import storage_info

logger = logging.getLogger(__name__)


def _user_id(request) -> str:
    return str(request.user.id)


def _storage_key_from_path(path: str) -> str:
    return path.split(".com/")[1]


class FileAPIView(APIView):
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = _user_id(request)
        number_of_files = request.query_params.get("number_of_files")
        files = File.objects.filter(user_id=user_id).order_by("-created_date")
        if number_of_files:
            files = files[:int(number_of_files)]
        return Response({"files": FileSerializer(files, many=True).data}, status=status.HTTP_200_OK)

    def post(self, request):
        user_id = _user_id(request)
        if "file" not in request.FILES:
            return Response({"error": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

        file = request.FILES["file"]
        if file.content_type != "application/pdf":
            return Response({"error": "Only PDF files are allowed"}, status=status.HTTP_400_BAD_REQUEST)

        plan = get_plan_for(request.user)
        if file.size > plan.max_file_size_bytes:
            raise LimitExceeded(
                reason="max_file_size",
                message=f"This file exceeds your plan's {plan.max_file_size_mb} MB per-file limit.",
            )
        if file.size > storage_info(request.user)["remaining_space"]:
            raise LimitExceeded(
                reason="storage_limit",
                message=f"You have used your {plan.storage_limit_mb} MB of storage. "
                "Delete some files or upgrade your plan.",
            )

        filename = file.name
        base_name, extension = os.path.splitext(filename)
        count = 0
        while File.objects.filter(user_id=user_id, name=filename).exists():
            count += 1
            filename = f"{base_name} ({count}){extension}"

        s3_key = f"userspace/{user_id}/{uuid.uuid4()}.pdf"
        try:
            s3_url = get_storage().upload(s3_key, file.read(), "application/pdf")
            file_obj = File.objects.create(
                user_id=user_id, path=s3_url, name=filename, size=file.size, created_date=now()
            )
            return Response(
                {"status": "file uploaded", "file": FileSerializer(file_obj).data},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response({"error": f"S3 upload failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def patch(self, request):
        user_id = _user_id(request)
        file_id = request.data.get("file_id")
        new_name = request.data.get("new_name")
        folder_id = request.data.get("folder_id")

        if not file_id:
            return Response({"error": "File ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        file = File.objects.filter(id=file_id, user_id=user_id).first()
        if not file:
            return Response({"error": "File not found"}, status=status.HTTP_404_NOT_FOUND)

        if new_name:
            base_name = new_name
            count = 0
            while File.objects.filter(Q(user_id=user_id) & Q(name=new_name)).exclude(id=file_id).exists():
                count += 1
                new_name = f"{base_name} ({count})"
            file.name = new_name

        if folder_id is not None:
            file.folder_id = folder_id

        file.save()
        return Response(
            {"message": "File updated successfully", "new_name": file.name, "folder_id": file.folder_id},
            status=status.HTTP_200_OK,
        )

    def delete(self, request):
        user_id = _user_id(request)
        file_id = request.data.get("file_id")
        if not file_id:
            return Response({"error": "File ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        file = File.objects.filter(id=file_id, user_id=user_id).first()
        if not file:
            return Response({"error": "File not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            get_storage().delete(_storage_key_from_path(file.path))
            file.delete()
            return Response({"message": "File deleted successfully"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": f"Failed to delete file from S3: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FolderAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = _user_id(request)
        folders = Folder.objects.filter(user_id=user_id).all()
        return Response(FolderSerializer(folders, many=True).data)

    def post(self, request):
        user_id = _user_id(request)
        data = request.data.copy()
        data["user_id"] = user_id

        base_name = data.get("name")
        if not base_name:
            return Response({"error": "Folder name is required"}, status=status.HTTP_400_BAD_REQUEST)

        new_name = base_name
        count = 0
        while Folder.objects.filter(user_id=user_id, name=new_name).exists():
            count += 1
            new_name = f"{base_name} ({count})"
        data["name"] = new_name

        serializer = FolderSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request):
        user_id = _user_id(request)
        folder_id = request.data.get("folder_id")
        new_name = request.data.get("new_name")
        if not folder_id or not new_name:
            return Response({"error": "folder_id and new_name are required"}, status=status.HTTP_400_BAD_REQUEST)

        folder = Folder.objects.filter(user_id=user_id, id=folder_id).first()
        if not folder:
            return Response({"error": "Folder not found or unauthorized"}, status=status.HTTP_404_NOT_FOUND)

        base_name = new_name
        count = 0
        while Folder.objects.filter(Q(user_id=user_id) & Q(name=new_name)).exclude(id=folder_id).exists():
            count += 1
            new_name = f"{base_name} ({count})"

        folder.name = new_name
        folder.save()
        return Response(
            {"success": True, "message": f"Folder renamed successfully to {new_name}", "new_folder_name": new_name},
            status=status.HTTP_200_OK,
        )

    def delete(self, request):
        user_id = _user_id(request)
        folder_id = request.data.get("folder_id")
        if not folder_id:
            return Response({"error": "folder_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            folder = Folder.objects.get(id=folder_id, user_id=user_id)
        except Folder.DoesNotExist:
            return Response({"error": "Folder not found or access denied"}, status=status.HTTP_404_NOT_FOUND)

        storage = get_storage()
        files = File.objects.filter(folder_id=folder_id, user_id=user_id)
        s3_deletion_errors = []
        successfully_deleted_files = []

        for file in files:
            try:
                s3_key = _storage_key_from_path(file.path)
                if storage.exists(s3_key):
                    storage.delete(s3_key)
                    if storage.exists(s3_key):
                        s3_deletion_errors.append(f"Failed to delete {file.name}: still exists after deletion")
                        continue
                successfully_deleted_files.append(file.id)
            except Exception as e:
                s3_deletion_errors.append(f"Failed to delete {file.name}: {str(e)}")

        if successfully_deleted_files:
            File.objects.filter(id__in=successfully_deleted_files).delete()

        all_files_processed = len(successfully_deleted_files) == files.count()
        if all_files_processed:
            folder.delete()
            if s3_deletion_errors:
                return Response(
                    {"message": "All files were processed, but some had errors", "s3_errors": s3_deletion_errors, "success": True},
                    status=status.HTTP_207_MULTI_STATUS,
                )
            return Response({"message": "Folder and all associated files deleted successfully", "success": True}, status=status.HTTP_200_OK)

        return Response(
            {
                "message": "Partial deletion completed",
                "files_deleted": len(successfully_deleted_files),
                "files_remaining": files.count() - len(successfully_deleted_files),
                "s3_errors": s3_deletion_errors,
                "success": False,
            },
            status=status.HTTP_207_MULTI_STATUS,
        )


class SearchFilesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = _user_id(request)
        search_query = request.query_params.get("query", "").strip()
        sort_order = request.query_params.get("order", "").lower()
        keyword = request.query_params.get("keyword", "").lower()

        files = File.objects.filter(user_id=user_id)
        if search_query:
            files = files.filter(name__icontains=search_query)
        if sort_order == "asc":
            files = files.order_by("name")
        elif sort_order == "desc":
            files = files.order_by("-name")
        if keyword == "latest":
            files = files.order_by("-created_date")[:3]

        files = files.values("id", "path", "name", "created_date")
        if not files.exists():
            return Response({"message": "No matching files found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"files": list(files)}, status=status.HTTP_200_OK)


class StorageInfoAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        space_info = storage_info(request.user)
        return Response(
            {
                "used_space": space_info["used_space"],
                "remaining_space": space_info["remaining_space"],
                "allowed_space": space_info["allowed_space"],
                "message": "success",
            },
            status=status.HTTP_200_OK,
        )


class MoveFileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_id = _user_id(request)
        file_id = request.data.get("file_id")
        new_folder_id = request.data.get("new_folder_id")

        if not file_id or not new_folder_id:
            return Response({"error": "file_id and new_folder_id are required"}, status=status.HTTP_400_BAD_REQUEST)

        file = File.objects.filter(user_id=user_id, id=file_id).first()
        if not file:
            return Response({"error": "File not found or unauthorized"}, status=status.HTTP_404_NOT_FOUND)

        folder = Folder.objects.get(id=new_folder_id)
        file.folder_id = new_folder_id
        file.save()
        return Response(
            {"success": True, "message": f"File '{file.name}' moved to folder '{folder.name}'"},
            status=status.HTTP_200_OK,
        )


class FolderFilesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = _user_id(request)
        folder_id = request.query_params.get("folder_id")

        folder = Folder.objects.filter(user_id=user_id, id=folder_id).first()
        if not folder:
            return Response({"error": "Folder not found or unauthorized"}, status=status.HTTP_404_NOT_FOUND)

        files = File.objects.filter(user_id=user_id, folder_id=folder_id).values(
            "id", "path", "name", "created_date", "folder_id"
        )
        return Response({"folder_name": folder.name, "files": list(files)}, status=status.HTTP_200_OK)
