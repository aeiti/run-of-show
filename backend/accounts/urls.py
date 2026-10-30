from django.urls import path

from . import views

urlpatterns = [
    path("token/", views.LoginView.as_view()),
    path("signup/", views.SignupView.as_view()),
    path("logout/", views.LogoutView.as_view()),
    path("me/", views.MeView.as_view()),
    path("password/", views.PasswordChangeView.as_view()),
    path("password-reset/", views.PasswordResetView.as_view()),
    path("password-reset/confirm/", views.PasswordResetConfirmView.as_view()),
]
