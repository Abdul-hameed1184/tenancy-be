from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .forms import AdminUserChangeForm, AdminUserCreationForm
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = AdminUserChangeForm
    add_form = AdminUserCreationForm
    ordering = ["-created_at"]
    list_display = ["email", "name", "role", "is_active", "created_at"]
    list_filter = ["role", "is_active", "is_staff"]
    search_fields = ["email", "name"]
    readonly_fields = ["id", "created_at", "last_login"]
    fieldsets = [
        (None, {"fields": ["id", "email", "password"]}),
        ("Profile", {"fields": ["name", "role", "phone", "avatar_url"]}),
        ("Access", {"fields": ["is_active", "is_staff", "is_superuser", "groups"]}),
        ("Dates", {"fields": ["created_at", "last_login"]}),
    ]
    add_fieldsets = [
        (
            None,
            {"classes": ["wide"], "fields": ["email", "name", "role", "password1", "password2"]},
        ),
    ]
    filter_horizontal = ["groups"]
