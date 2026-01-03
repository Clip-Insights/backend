import os
import jwt
import uuid
import boto3
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
from django.db.models import Q
from django.conf import settings
from django.utils.timezone import now
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from .utils import storage_info
from .models import File, Folder
from .serializers import FileSerializer, FolderSerializer
from account.models import User
from botocore.exceptions import ClientError
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from botocore.client import Config

load_dotenv()

# Load AWS credentials from environment
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_REGION = os.getenv('AWS_REGION')
AWS_STORAGE_BUCKET_NAME = os.getenv('AWS_STORAGE_BUCKET_NAME')
AWS_S3_ENDPOINT_URL = f"https://s3.{AWS_REGION}.backblazeb2.com"

class FileAPIView(APIView):
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    permission_classes = [IsAuthenticated]

    def __init__(self):
        super().__init__()
        self.s3_client = boto3.client(
            service_name="s3",
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION,
            endpoint_url=AWS_S3_ENDPOINT_URL,
            config=Config(signature_version="s3v4"),
        )

    def get_user_id(self, request):
        """Extract user ID from JWT token."""
        user_token = request.headers.get("Authorization")
        if not user_token:
            return None, Response(
                {"error": "Authorization token is missing"}, status=status.HTTP_401_UNAUTHORIZED
            )
        try:
            payload = jwt.decode(user_token.split(" ")[1], settings.SECRET_KEY, algorithms=["HS256"])
            return payload["user_id"], None
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError):
            return None, Response(
                {"error": "Invalid token"}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        
    def get(self, request):
        """Retrieve user files."""

        user_id, error_response = self.get_user_id(request)
        if error_response:
            return error_response

        number_of_files = request.query_params.get("number_of_files")
        files = File.objects.filter(user_id=user_id).order_by("-created_date")
        if number_of_files:
            files = files[:int(number_of_files)]
        
        return Response(
            {"files": FileSerializer(files, many=True).data}, 
            status=status.HTTP_200_OK
        )

    def post(self, request):
        """Handles file upload."""

        user_id, error_response = self.get_user_id(request)
        if error_response:
            return error_response
        
        if "file" not in request.FILES:
            return Response({"error": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        file = request.FILES["file"]
        if file.content_type != "application/pdf":
            return Response(
                {"error": "Only PDF files are allowed"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        filename = file.name
        base_name, extension = os.path.splitext(filename)
        count = 0
        while File.objects.filter(user_id=user_id, name=filename).exists():
            count += 1
            filename = f"{base_name} ({count}){extension}"

        unique_id = uuid.uuid4()
        s3_key = f"userspace/{user_id}/{unique_id}.pdf"
        
        try:
            self.s3_client.upload_fileobj(
                file, AWS_STORAGE_BUCKET_NAME, s3_key,
                ExtraArgs={"ContentType": "application/pdf"}
            )
            s3_url = f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_REGION}.backblazeb2.com/{s3_key}"
            file_obj = File.objects.create(
                user_id=user_id, path=s3_url, name=filename, size=file.size, created_date=now()
            )
            return Response(
                {"status": "file uploaded", "file": FileSerializer(file_obj).data}, 
                status=status.HTTP_200_OK
            )
        except ClientError as e:
            return Response(
                {"error": f"S3 upload failed: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def patch(self, request):
        """Partially update a file (e.g., rename or move to a folder)."""
        user_id, error_response = self.get_user_id(request)
        if error_response:
            return error_response

        file_id = request.data.get("file_id")
        new_name = request.data.get("new_name")
        folder_id = request.data.get("folder_id")

        if not file_id:
            return Response(
                {"error": "File ID is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        file = File.objects.filter(id=file_id, user_id=user_id).first()
        if not file:
            return Response(
                {"error": "File not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Update the file name if provided
        if new_name:
            base_name = new_name
            count = 0
            while File.objects.filter(Q(user_id=user_id) & Q(name=new_name)).exclude(id=file_id).exists():
                count += 1
                new_name = f"{base_name} ({count})"

            file.name = new_name

        # Update the folder ID if provided
        if folder_id is not None:
            file.folder_id = folder_id

        file.save()

        return Response(
            {"message": "File updated successfully", "new_name": file.name, "folder_id": file.folder_id},
            status=status.HTTP_200_OK
        )


    def delete(self, request):
        """Delete a file."""

        user_id, error_response = self.get_user_id(request)
        if error_response:
            return error_response

        file_id = request.data.get("file_id")
        if not file_id:
            return Response(
                {"error": "File ID is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        file = File.objects.filter(id=file_id, user_id=user_id).first()
        if not file:
            return Response(
                {"error": "File not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            s3_key = file.path.split(".com/")[1]
            self.s3_client.delete_object(Bucket=AWS_STORAGE_BUCKET_NAME, Key=s3_key)
            file.delete()
            return Response(
                {"message": "File deleted successfully"}, 
                status=status.HTTP_200_OK
            )
        except ClientError as e:
            return Response(
                {"error": f"Failed to delete file from S3: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )



class FolderAPIView(APIView):
    def __init__(self):
        super().__init__()
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION,
        )

    def get(self, request):

        user_token = request.headers.get("Authorization")
        if not user_token:
            return Response(
                {"error": "Authorization token is missing"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            payload = jwt.decode(
                user_token.split(" ")[1], settings.SECRET_KEY, algorithms=["HS256"]
            )
            user_id = payload["user_id"]
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError):
            return Response(
                {"error": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED
            )
        folders = Folder.objects.filter(user_id=user_id).all()
        serializer = FolderSerializer(folders, many=True)
        return Response(serializer.data)

    def post(self, request):
        data = request.data
        user_token = request.headers.get("Authorization")

        if not user_token:
            return Response(
                {"error": "Authorization token is missing"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            payload = jwt.decode(
                user_token.split(" ")[1], settings.SECRET_KEY, algorithms=["HS256"]
            )
            user_id = payload["user_id"]
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError):
            return Response(
                {"error": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED
            )

        # Add user_id to the data
        data["user_id"] = user_id

        # Ensure the folder name is unique
        base_name = data.get("name")
        if not base_name:
            return Response(
                {"error": "Folder name is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_name = base_name
        count = 0

        # Check for duplicates and append a counter
        while Folder.objects.filter(user_id=user_id, name=new_name).exists():
            count += 1
            new_name = f"{base_name} ({count})"

        # Update the folder name in the data
        data["name"] = new_name

        # Serialize and save the folder
        serializer = FolderSerializer(data=data)
        if serializer.is_valid():
            serializer.save()  # This will now include user_id
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request):
        user_token = request.headers.get("Authorization")
        if not user_token:
            return Response({"error": "Authorization token is missing"}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            payload = jwt.decode(user_token.split(" ")[1], settings.SECRET_KEY, algorithms=["HS256"])
            user_id = payload["user_id"]
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError):
            return Response(
                {"error": "Invalid token"}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        folder_id = request.data.get("folder_id")
        new_name = request.data.get("new_name")
        if not folder_id or not new_name:
            return Response(
                {"error": "folder_id and new_name are required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        folder = Folder.objects.filter(user_id=user_id, id=folder_id).first()
        if not folder:
            return Response(
                {"error": "Folder not found or unauthorized"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        base_name = new_name
        count = 0
        while Folder.objects.filter(Q(user_id=user_id) & Q(name=new_name)).exclude(id=folder_id).exists():
            count += 1
            new_name = f"{base_name} ({count})"
        
        folder.name = new_name
        folder.save()
        return Response(
            {"success": True, "message": f"Folder renamed successfully to {new_name}", "new_folder_name": new_name}, 
            status=status.HTTP_200_OK
        )

    def delete(self, request):
        """
        Delete a folder and its associated files.
        """
        user_token = request.headers.get("Authorization")
        if not user_token:
            return Response(
                {"error": "Authorization token is missing"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            payload = jwt.decode(
                user_token.split(" ")[1], settings.SECRET_KEY, algorithms=["HS256"]
            )
            user_id = payload["user_id"]
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError):
            return Response(
                {"error": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED
            )

        # Extract folder_id from the request body
        folder_id = request.data.get("folder_id")
        if not folder_id:
            return Response(
                {"error": "folder_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate folder existence and ownership
        try:
            folder = Folder.objects.get(id=folder_id, user_id=user_id)
        except Folder.DoesNotExist:
            return Response(
                {"error": "Folder not found or access denied"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            # Get all files in the folder
            files = File.objects.filter(folder_id=folder_id, user_id=user_id)

            # Track successful and failed deletions
            s3_deletion_errors = []
            successfully_deleted_files = []

            for file in files:
                try:
                    # Extract S3 key from file path
                    s3_url_parts = file.path.split(".com/")
                    if len(s3_url_parts) == 2:
                        s3_key = s3_url_parts[1]

                        # Verify file exists in S3 before deletion
                        try:
                            self.s3_client.head_object(
                                Bucket=AWS_STORAGE_BUCKET_NAME, Key=s3_key
                            )
                        except ClientError as e:
                            if e.response["Error"]["Code"] == "404":
                                # File doesn't exist in S3, safe to remove from database
                                successfully_deleted_files.append(file.id)
                                continue
                            raise

                        # Delete file from S3
                        self.s3_client.delete_object(
                            Bucket=AWS_STORAGE_BUCKET_NAME, Key=s3_key
                        )

                        # Verify deletion
                        try:
                            self.s3_client.head_object(
                                Bucket=AWS_STORAGE_BUCKET_NAME, Key=s3_key
                            )
                            # File still exists - deletion failed
                            error_msg = f"Failed to delete {file.name}: File still exists after deletion attempt"
                            s3_deletion_errors.append(error_msg)
                        except ClientError as e:
                            if e.response["Error"]["Code"] == "404":
                                # Successful deletion
                                successfully_deleted_files.append(file.id)

                except Exception as e:
                    error_msg = f"Failed to delete {file.name}: {str(e)}"
                    s3_deletion_errors.append(error_msg)
                    continue

            # Delete only the successfully processed files from PostgreSQL
            if successfully_deleted_files:
                File.objects.filter(id__in=successfully_deleted_files).delete()

            # Only delete the folder if all files were successfully processed
            all_files_processed = len(successfully_deleted_files) == files.count()

            if all_files_processed:
                folder.delete()
                if s3_deletion_errors:
                    return Response(
                        {
                            "message": "All files were processed, but some had errors",
                            "s3_errors": s3_deletion_errors,
                            "success": True,
                        },
                        status=status.HTTP_207_MULTI_STATUS,
                    )
                return Response(
                    {
                        "message": "Folder and all associated files deleted successfully",
                        "success": True,
                    },
                    status=status.HTTP_200_OK,
                )
            else:
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

        except Exception as e:
            return Response(
                {"error": f"Deletion failed: {str(e)}", "success": False},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

   


class SearchFilesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_token = request.headers.get("Authorization")
        if not user_token:
            return Response(
                {"error": "Authorization token is missing"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            token = user_token.split(" ")[1]
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = payload["user_id"]
        except (IndexError, jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError):
            return Response(
                {"error": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED
            )

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
            return Response(
                {"message": "No matching files found."}, status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {"files": list(files)}, status=status.HTTP_200_OK,
        )


class StorageInfoAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        logger.info("Inside storage info view")
        user_token = request.headers.get("Authorization")
        if not user_token:
            return Response(
                {"error": "Authorization token is missing"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        
        try:
            token = user_token.split(" ")[1]
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = payload["user_id"]
        except (IndexError, jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError):
            return Response(
                {"error": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED
            )
        
        space_info = storage_info(user_id)
        used_space = space_info["used_space"]
        allowed_space = space_info["allowed_space"]
        remaining_space = space_info["remaining_space"]

        data = {
            "used_space": used_space,
            "remaining_space": remaining_space,
            "allowed_space": allowed_space,
            "message": "success",
        }
        logger.info(f"Storage info: {data}")
        return Response(data, status=status.HTTP_200_OK)


class MoveFileAPIView(APIView):
    def post(self, request):
        """
        Move a file to a new folder by updating its folder_id field.

        Args:
            request: The HTTP request object.

        Returns:
            Response: Success or error message.
        """
        user_token = request.headers.get("Authorization")
        if not user_token:
            return Response(
                {"error": "Authorization token is missing"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            payload = jwt.decode(
                user_token.split(" ")[1], settings.SECRET_KEY, algorithms=["HS256"]
            )
            user_id = payload["user_id"]
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError):
            return Response(
                {"error": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED
            )

        # Extract file_id and new_folder_id from the request body
        file_id = request.data.get("file_id")
        new_folder_id = request.data.get("new_folder_id")

        if not file_id or not new_folder_id:
            return Response(
                {"error": "file_id and new_folder_id are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Fetch the file object based on user_id and file_id
        file_links = File.objects.filter(user_id=user_id, id=file_id).values(
            "id", "path", "name", "created_date", "folder_id"
        )
        if not file_links:
            return Response(
                {"error": "File not found or unauthorized"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Update the folder_id field
        file = File.objects.get(id=file_id)
        file.folder_id = new_folder_id
        folder = Folder.objects.get(id=new_folder_id)
        folder_name = folder.name
        file.save()

        return Response(
            {
                "success": True,
                "message": f"File '{file.name}' moved to folder '{folder_name}'",
            },
            status=status.HTTP_200_OK,
        )


class FolderFilesAPIView(APIView):
    def get(self, request):
        logger.info("API HIT")
        # Retrieve the Authorization token from headers
        user_token = request.headers.get("Authorization")
        if not user_token:
            return Response(
                {"error": "Authorization token is missing"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Decode the token to get the user ID
        try:
            payload = jwt.decode(
                user_token.split(" ")[1], settings.SECRET_KEY, algorithms=["HS256"]
            )
            user_id = payload["user_id"]
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError):
            return Response(
                {"error": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED
            )
        
        folder_id = request.query_params.get("folder_id")

        # Validate folder existence and ownership
        folder = Folder.objects.filter(user_id=user_id, id=folder_id).first()
        logger.info(f"Folder: {folder}")

        if not folder:
            return Response(
                {"error": "Folder not found or unauthorized"},
                status=status.HTTP_404_NOT_FOUND,
            )
        folder_name = folder.name

        # Fetch files linked to the user and folder
        files = File.objects.filter(user_id=user_id, folder_id=folder_id).values(
            "id", "path", "name", "created_date", "folder_id"
        )

        response_data = {
            "folder_name": folder_name,
            "files": list(files),
        }

        return Response(response_data, status=status.HTTP_200_OK)
