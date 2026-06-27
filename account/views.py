from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.contrib.auth import authenticate, get_user_model
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from .renderers import UserRenderer
from .serializers import (
    UserLoginSerializer,
    UserProfileSerializer,
    UserRegistrationSerializer,
    UserPasswordResetSerializer,
    UserChangePasswordSerializer,
    SendPasswordResetEmailSerializer,
)
import os
from dotenv import load_dotenv
from .utils import Util
from google.auth.exceptions import TransportError
from integrations.registry import get_oauth
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import smart_str, force_bytes, DjangoUnicodeDecodeError

load_dotenv()

User = get_user_model()  # This will get your custom User model


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


class UserRegistrationView(APIView):
    renderer_classes = [UserRenderer]

    def post(self, request, format=None):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            user = serializer.save()

            if settings.ENVIRONMENT != "production":
                user.is_verified = True
                user.is_active = True
                user.save(update_fields=["is_verified", "is_active", "updated_at"])
                token = get_tokens_for_user(user)
                return Response(
                    {
                        'token': token,
                        'msg': 'Registration Successful. Account verified automatically',
                    },
                    status=status.HTTP_201_CREATED
                )

            uid = urlsafe_base64_encode(force_bytes(str(user.id)))
            token = PasswordResetTokenGenerator().make_token(user)
            domain = os.getenv('EMAIL_URL_DOMAIN', 'http://localhost:3000/')
            link = domain + "verify-email/" + uid + "/" + token

            data = {
                "subject": "Verify Your Email Address",
                "link": link,
                "username": user.name,
                "to_email": user.email,
            }
            Util.send_email(data)
            
            return Response(
                {'msg': 'Registration Successful. Please check your email to verify your account'},
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserLoginView(APIView):
    renderer_classes = [UserRenderer]

    def post(self, request, format=None):
        serializer = UserLoginSerializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            email = serializer.data.get('email')
            password = serializer.data.get('password')
            user = authenticate(email=email, password=password)

            if user is not None:
                token = get_tokens_for_user(user)
                return Response(
                    {'token': token, 'msg': 'Login Successful'},
                    status=status.HTTP_200_OK
                )

        return Response(
            {'errors': {
                'non_field_errors': ['Invalid Email or Password']
            }},
            status=status.HTTP_404_NOT_FOUND
        )


class UserProfileView(APIView):
    renderer_classes = [UserRenderer]
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserChangePasswordView(APIView):
    renderer_classes = [UserRenderer]
    permission_classes = [IsAuthenticated]

    def post(self, request, format=None):
        serializer = UserChangePasswordSerializer(
            data=request.data, context={'user': request.user}
        )
        serializer.is_valid(raise_exception=True)
        return Response(
            {'msg': 'Password Changed Successfully'},
            status=status.HTTP_200_OK
        )


class SendPasswordResetEmailView(APIView):
    renderer_classes = [UserRenderer]

    def post(self, request, format=None):
        serializer = SendPasswordResetEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            {'msg': 'Password Reset link send. Please check your Email'},
            status=status.HTTP_200_OK
        )


class UserPasswordResetView(APIView):
    renderer_classes = [UserRenderer]

    def post(self, request, uid, token, format=None):
        serializer = UserPasswordResetSerializer(
            data=request.data, context={'uid': uid, 'token': token}
        )
        serializer.is_valid(raise_exception=True)
        return Response(
            {'msg': 'Password Reset Successfully'},
            status=status.HTTP_200_OK
        )


class UserLogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({'msg': 'Successfully logged out'}, status=status.HTTP_200_OK)
        except TokenError:
            return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)


class GoogleLoginView(APIView):
    renderer_classes = [UserRenderer]

    def post(self, request, format=None):
        try:
            token = request.data.get('token')
            if not token:
                return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)

            idinfo = get_oauth().verify(token)
            email = idinfo["email"]
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                # Create new user using your custom User model
                user = User.objects.create(
                    email=email,
                    name=idinfo.get('name', ''),
                    is_verified=True
                )
                user.set_unusable_password()
                user.save()

            # Generate tokens
            token = get_tokens_for_user(user)
            return Response(
                {'token': token, 'msg': 'Login Successful'},
                status=status.HTTP_200_OK
            )

        except ValueError:
            return Response(
                {'error': 'Invalid Google token'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except TransportError:
            return Response(
                {'error': 'Connection error with Google servers. Please try again.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )


class EmailVerificationView(APIView):
    renderer_classes = [UserRenderer]

    def get(self, request, uid, token, format=None):
        try:
            id = smart_str(urlsafe_base64_decode(uid))
            user = User.objects.get(id=id)
            
            if not PasswordResetTokenGenerator().check_token(user, token):
                return Response(
                    {'error': 'Token is not valid or expired'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if user.is_verified:
                return Response(
                    {'msg': 'Email already verified'},
                    status=status.HTTP_200_OK
                )
                
            user.is_verified = True
            user.is_active = True
            user.save()
            
            token = get_tokens_for_user(user)
            return Response(
                {'token': token, 'msg': 'Email verified successfully'},
                status=status.HTTP_200_OK
            )
            
        except DjangoUnicodeDecodeError:
            return Response(
                {'error': 'Invalid token'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
