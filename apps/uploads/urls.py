from apps.common.routers import optional_slash

from . import views

urlpatterns = [
    *optional_slash("uploads/signature", views.UploadSignatureView.as_view(), "upload-signature"),
]
