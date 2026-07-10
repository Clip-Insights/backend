from django.urls import path
from account.views import UserRegistrationView
from .views import GoogleLoginView
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from account.views import (
    UserLoginView,
    UserProfileView,
    UserChangePasswordView,
    SendPasswordResetEmailView,
    UserPasswordResetView,
    UserLogoutView,
    EmailVerificationView,
    ResendVerificationView,
)

urlpatterns = [
    path('signup/', UserRegistrationView.as_view(), name='register_user'),
    path('login/', UserLoginView.as_view(), name='login'),
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('change-password/', UserChangePasswordView.as_view(), name='change-password'),
    path('reset-password/', SendPasswordResetEmailView.as_view(), name='reset-password'),
    path('reset-password/<uid>/<token>/', UserPasswordResetView.as_view(), name='reset-password-mail'),
    path('obtain-token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('refresh-token/', TokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', UserLogoutView.as_view(), name='logout'),
    path('google-login/', GoogleLoginView.as_view(), name='google-login'),
    path('verify-email/<uid>/<token>/', EmailVerificationView.as_view(), name='verify-email'),
    path('resend-verification/', ResendVerificationView.as_view(), name='resend-verification'),
]
