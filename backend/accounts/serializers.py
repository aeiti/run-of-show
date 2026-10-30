from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import profile_for

User = get_user_model()


def check_password(password, user=None):
    try:
        password_validation.validate_password(password, user)
    except DjangoValidationError as e:
        raise serializers.ValidationError(e.messages)
    return password


def check_email_free(email, user=None):
    clash = User.objects.filter(email__iexact=email)
    if user is not None:
        clash = clash.exclude(pk=user.pk)
    if clash.exists():
        raise serializers.ValidationError("An account with this email already exists.")
    return email


class MeSerializer(serializers.ModelSerializer):
    """The signed-in user: Django's user fields plus their profile."""

    display_name = serializers.CharField(source="profile.display_name", max_length=100, allow_blank=True, required=False)
    preferences = serializers.JSONField(source="profile.preferences", required=False)
    is_admin = serializers.BooleanField(source="is_staff", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "display_name", "preferences", "is_admin"]
        read_only_fields = ["id", "username"]
        extra_kwargs = {"email": {"required": False}}

    def to_representation(self, user):
        profile_for(user)
        return super().to_representation(user)

    def validate_email(self, value):
        return check_email_free(value, self.instance)

    def validate_preferences(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Preferences must be an object.")
        return value

    def update(self, user, validated_data):
        profile_data = validated_data.pop("profile", {})
        if profile_data:
            profile = profile_for(user)
            if "preferences" in profile_data:
                # Merge, so the UI can change one preference without resending the rest.
                profile_data["preferences"] = {**profile.preferences, **profile_data["preferences"]}
            for field, value in profile_data.items():
                setattr(profile, field, value)
            profile.save()
        return super().update(user, validated_data)


class AdminUserSerializer(serializers.ModelSerializer):
    """A user as an admin manages them. ``is_active`` false means suspended."""

    display_name = serializers.CharField(source="profile.display_name", max_length=100, allow_blank=True, required=False)
    is_admin = serializers.BooleanField(source="is_staff", required=False)
    password = serializers.CharField(write_only=True, trim_whitespace=False, required=False)
    productions_owned = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "display_name",
            "is_admin",
            "is_active",
            "password",
            "productions_owned",
            "date_joined",
            "last_login",
        ]
        read_only_fields = ["id", "date_joined", "last_login"]
        extra_kwargs = {"email": {"required": True}}

    def to_representation(self, user):
        profile_for(user)
        return super().to_representation(user)

    def validate_username(self, value):
        User.username_validator(value)
        clash = User.objects.filter(username__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("That username is taken.")
        return value

    def validate_email(self, value):
        return check_email_free(value, self.instance)

    def validate(self, data):
        if self.instance is None and not data.get("password"):
            raise serializers.ValidationError({"password": "Set a password for the new account."})
        if data.get("password"):
            candidate = self.instance or User(username=data.get("username", ""), email=data.get("email", ""))
            try:
                check_password(data["password"], candidate)
            except serializers.ValidationError as e:
                raise serializers.ValidationError({"password": e.detail})
        # An admin can't lock themselves out.
        me = self.context["request"].user
        if self.instance is not None and self.instance.pk == me.pk:
            if data.get("is_staff") is False:
                raise serializers.ValidationError({"is_admin": "You can't remove your own admin access."})
            if data.get("is_active") is False:
                raise serializers.ValidationError({"is_active": "You can't suspend yourself."})
        return data

    def create(self, data):
        profile_data = data.pop("profile", {})
        password = data.pop("password")
        user = User(**data)
        user.set_password(password)
        user.save()
        self._save_profile(user, profile_data)
        return user

    def update(self, user, data):
        profile_data = data.pop("profile", {})
        password = data.pop("password", None)
        user = super().update(user, data)
        if password:
            user.set_password(password)
            user.save()
        self._save_profile(user, profile_data)
        return user

    def _save_profile(self, user, profile_data):
        if "display_name" in profile_data:
            profile = profile_for(user)
            profile.display_name = profile_data["display_name"]
            profile.save()


class SignupSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    display_name = serializers.CharField(max_length=100, allow_blank=True, required=False)

    def validate_username(self, value):
        User.username_validator(value)
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("That username is taken.")
        return value

    def validate_email(self, value):
        return check_email_free(value)

    def validate(self, data):
        # Run the validators against an unsaved user so "too similar to your
        # username" can fire.
        try:
            check_password(data["password"], User(username=data["username"], email=data["email"]))
        except serializers.ValidationError as e:
            raise serializers.ValidationError({"password": e.detail})
        return data

    def create(self, data):
        user = User.objects.create_user(username=data["username"], email=data["email"], password=data["password"])
        profile = profile_for(user)
        profile.display_name = data.get("display_name", "")
        profile.save()
        return user


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False)

    def validate_current_password(self, value):
        if not self.context["user"].check_password(value):
            raise serializers.ValidationError("That isn't your current password.")
        return value

    def validate_new_password(self, value):
        return check_password(value, self.context["user"])


class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(trim_whitespace=False)
