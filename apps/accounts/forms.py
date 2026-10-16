from django import forms
from django.contrib.auth.forms import BaseUserCreationForm, UserChangeForm

from .models import User


class AdminUserCreationForm(BaseUserCreationForm):
    class Meta:
        model = User
        fields = ["email", "name", "role"]


class AdminUserChangeForm(UserChangeForm):
    avatar_url = forms.URLField(max_length=500, required=False, assume_scheme="https")

    class Meta:
        model = User
        fields = "__all__"
