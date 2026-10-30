"""Accounts: sign-up, sign-in and out, the signed-in user's profile, and passwords.

Auth is DRF tokens, one per user. Changing or resetting a password replaces
the token, which signs out every other device.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .serializers import (
    MeSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetSerializer,
    SignupSerializer,
    check_password,
)

User = get_user_model()


def new_token(user):
    Token.objects.filter(user=user).delete()
    return Token.objects.create(user=user).key


class AnonymousAuthView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_scope = "auth"


class LoginView(ObtainAuthToken):
    # ObtainAuthToken switches throttling off; turn it back on.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class SignupView(AnonymousAuthView):
    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response({"token": new_token(user)}, status=status.HTTP_201_CREATED)


class LogoutView(APIView):
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        return Response(MeSerializer(request.user).data)

    def patch(self, request):
        serializer = MeSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PasswordChangeView(APIView):
    throttle_scope = "auth"

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"user": request.user})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save()
        return Response({"token": new_token(request.user)})


class PasswordResetView(AnonymousAuthView):
    """Email a reset link. Always 204, so it can't be used to find out who has an account."""

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        for user in User.objects.filter(email__iexact=email, is_active=True):
            if not user.has_usable_password():
                continue
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = f"{settings.FRONTEND_URL}/reset-password/{uid}/{token}"
            send_mail(
                "Reset your Run of Show password",
                f"Someone asked to reset the password for {user.username}.\n\n"
                f"To choose a new password, open:\n{link}\n\n"
                "If that wasn't you, ignore this email; your password hasn't changed.",
                None,
                [user.email],
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetConfirmView(AnonymousAuthView):
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(data["uid"])), is_active=True)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            user = None
        if user is None or not default_token_generator.check_token(user, data["token"]):
            return Response(
                {"detail": "This reset link is invalid or has expired. Ask for a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        check_password(data["new_password"], user)
        with transaction.atomic():
            user.set_password(data["new_password"])
            user.save()
            Token.objects.filter(user=user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
