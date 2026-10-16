from apps.common.routers import optional_slash

from . import views

urlpatterns = [
    *optional_slash("auth/register", views.RegisterView.as_view(), "auth-register"),
    *optional_slash("auth/login", views.LoginView.as_view(), "auth-login"),
    *optional_slash("auth/refresh", views.RefreshView.as_view(), "auth-refresh"),
    *optional_slash("auth/me", views.MeView.as_view(), "auth-me"),
    *optional_slash("auth/logout", views.LogoutView.as_view(), "auth-logout"),
    *optional_slash("auth/forgot-password", views.ForgotPasswordView.as_view(), "auth-forgot"),
    *optional_slash("auth/reset-password", views.ResetPasswordView.as_view(), "auth-reset"),
    *optional_slash("auth/verify-email", views.VerifyEmailView.as_view(), "auth-verify-email"),
    *optional_slash(
        "auth/resend-verification",
        views.ResendVerificationView.as_view(),
        "auth-resend-verification",
    ),
    *optional_slash("users/<uuid:pk>", views.UserDetailView.as_view(), "user-detail"),
    *optional_slash("realtime/ticket", views.WebSocketTicketView.as_view(), "realtime-ticket"),
]
