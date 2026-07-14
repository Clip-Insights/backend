from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.conf import settings
from django.contrib.auth import get_user_model
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
import logging
from .utils import Util
from google.auth.exceptions import TransportError
from integrations.registry import get_oauth
from django.utils.http import urlsafe_base64_decode
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import smart_str, DjangoUnicodeDecodeError

logger = logging.getLogger(__name__)

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

            try:
                Util.send_verification_email(user)
            except Exception as exc:
                logger.error(
                    "Failed to send verification email to %s: %s", user.email, exc
                )
                return Response(
                    {
                        'msg': (
                            'Registration Successful but we could not send the '
                            'verification email. Please use resend verification.'
                        )
                    },
                    status=status.HTTP_201_CREATED,
                )
            
            return Response(
                {'msg': 'Registration Successful. Please check your email to verify your account'},
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserLoginView(APIView):
    renderer_classes = [UserRenderer]

    def post(self, request, format=None):
        serializer = UserLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {"errors": {"non_field_errors": ["Invalid Email or Password"]}},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.check_password(password):
            return Response(
                {"errors": {"non_field_errors": ["Invalid Email or Password"]}},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # authenticate() rejects inactive users; check password first, then gate on verify.
        if not user.is_active or not user.is_verified:
            if settings.ENVIRONMENT != "production":
                user.is_active = True
                user.is_verified = True
                user.save(update_fields=["is_active", "is_verified", "updated_at"])
            else:
                return Response(
                    {
                        "errors": {
                            "non_field_errors": [
                                "Please verify your email before logging in."
                            ]
                        }
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        return Response(
            {"token": get_tokens_for_user(user), "msg": "Login Successful"},
            status=status.HTTP_200_OK,
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
                if not user.is_active or not user.is_verified:
                    user.is_active = True
                    user.is_verified = True
                    user.save(update_fields=["is_active", "is_verified", "updated_at"])
            except User.DoesNotExist:
                user = User(
                    email=email,
                    name=idinfo.get("name", "") or email.split("@")[0],
                    is_verified=True,
                    is_active=True,
                )
                user.set_unusable_password()
                user.save()

            token = get_tokens_for_user(user)
            return Response(
                {'token': token, 'msg': 'Login Successful'},
                status=status.HTTP_200_OK
            )

        except ValueError as e:
            # The verifier's message says which check failed (audience, expiry,
            # clock skew, missing client id) — essential for diagnosing sign-in.
            logger.warning("Google login rejected: %s", e)
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


class ResendVerificationView(APIView):
    renderer_classes = [UserRenderer]

    def post(self, request, format=None):
        email = request.data.get("email", "").strip().lower()
        success_msg = {
            'msg': 'If an unverified account exists for that email, a verification link has been sent.'
        }

        if not email:
            return Response(success_msg, status=status.HTTP_200_OK)

        try:
            user = User.objects.get(email=email)
            if not user.is_verified:
                try:
                    Util.send_verification_email(user)
                except Exception as exc:
                    logger.error(
                        "Failed to resend verification email to %s: %s", email, exc
                    )
                    return Response(
                        {
                            'errors': {
                                'non_field_errors': [
                                    'Unable to send the verification email right now. '
                                    'Please try again later.'
                                ]
                            }
                        },
                        status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )
        except User.DoesNotExist:
            pass

        return Response(success_msg, status=status.HTTP_200_OK)
