from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class CaseInsensitiveModelBackend(ModelBackend):
    """Sign in with the username in any case: "Alice" signs in as alice.

    Sign-up and the admin already refuse usernames that differ only by case.
    Should two older accounts still clash, only the exact spelling signs in.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if username is None or password is None:
            return None
        matches = list(User._default_manager.filter(**{f"{User.USERNAME_FIELD}__iexact": username})[:2])
        exact = [u for u in matches if u.get_username() == username]
        user = exact[0] if exact else matches[0] if len(matches) == 1 else None
        if user is None:
            # Hash anyway, so a missing account takes as long as a wrong password.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
