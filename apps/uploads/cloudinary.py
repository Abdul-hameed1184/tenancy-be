"""
Direct-to-Cloudinary uploads with server-signed parameters.

Cloudinary's equivalent of an S3 presigned URL is a *signed upload*:

    browser --POST /api/v1/uploads/signature {purpose}--> Django
            <-- {uploadUrl, fields: {api_key, timestamp, folder, public_id, ..., signature}}
    browser --POST multipart(file + fields)--> api.cloudinary.com   (file never touches Django)
            <-- {secure_url, public_id, bytes, format, ...}
    browser --POST /properties {photos: [secure_url]}--> Django      (URL ownership checked)

The signature is SHA-1 (or SHA-256) of the alphabetically sorted "k=v&k=v" parameters plus
the API secret, which never leaves the server. Cloudinary recomputes it and rejects the
upload if *any* signed value was changed, so the client can't pick another folder, another
public_id (overwriting someone else's image), other formats, or reuse a signature after it
expires (Cloudinary rejects timestamps older than one hour).

What a signature can't enforce is file *size*: Cloudinary has no signable size limit. Size
is bounded by the client-side check, the `c_limit` incoming transformation (stored images
are resized to at most MAX_DIMENSION px), and the account's plan limit.
"""

import hashlib
import re
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from django.conf import settings

MAX_DIMENSION = 2400


@dataclass(frozen=True)
class Purpose:
    folder: str
    roles: frozenset[str]
    formats: tuple[str, ...]
    max_bytes: int
    # Incoming transformation, applied by Cloudinary before storing the original.
    transformation: str = ""
    resource_type: str = "image"


PURPOSES: dict[str, Purpose] = {
    "property_photo": Purpose(
        folder="properties",
        roles=frozenset({"landlord"}),
        formats=("jpg", "jpeg", "png", "webp"),
        max_bytes=10 * 1024 * 1024,
        transformation=f"c_limit,w_{MAX_DIMENSION},h_{MAX_DIMENSION}",
    ),
    "property_video": Purpose(
        folder="property-videos",
        roles=frozenset({"landlord"}),
        formats=("mp4", "mov", "webm"),
        max_bytes=100 * 1024 * 1024,
        resource_type="video",
    ),
    "avatar": Purpose(
        folder="avatars",
        roles=frozenset({"admin", "landlord", "agent", "tenant"}),
        formats=("jpg", "jpeg", "png", "webp"),
        max_bytes=5 * 1024 * 1024,
        transformation="c_limit,w_800,h_800",
    ),
}


class UploadsNotConfigured(Exception):
    pass


class InvalidUpload(Exception):
    """Message is safe to show to the client."""


def is_configured() -> bool:
    return bool(
        settings.CLOUDINARY_CLOUD_NAME
        and settings.CLOUDINARY_API_KEY
        and settings.CLOUDINARY_API_SECRET
    )


def folder_for(user, purpose: str) -> str:
    return f"{settings.CLOUDINARY_ROOT_FOLDER}/{PURPOSES[purpose].folder}/{user.pk}"


def sign(params: dict, api_secret: str, algorithm: str = "sha1") -> str:
    """Cloudinary's documented signing scheme (identical to their SDKs' api_sign_request)."""
    to_sign = "&".join(f"{key}={params[key]}" for key in sorted(params) if params[key] != "")
    digest = hashlib.sha256 if algorithm == "sha256" else hashlib.sha1
    print("Cloud name:", settings.CLOUDINARY_CLOUD_NAME)
    print("API key configured:", bool(settings.CLOUDINARY_API_KEY))
    print("API key length:", len(settings.CLOUDINARY_API_KEY or ""))
    print("API key matches expected:", (
        settings.CLOUDINARY_API_KEY == 532428449186546

    ))
    return digest(f"{to_sign}{api_secret}".encode()).hexdigest()



def signed_upload(user, purpose: str, *, now: int | None = None) -> dict:
    if not is_configured():
        raise UploadsNotConfigured
    spec = PURPOSES[purpose]
    params = {
        "timestamp": now if now is not None else int(time.time()),
        "folder": folder_for(user, purpose),
        # Server-chosen and random: a client can't overwrite another user's (or its own
        # earlier) image by guessing a name.
        "public_id": uuid.uuid4().hex,
        "allowed_formats": ",".join(spec.formats),
    }
    if spec.transformation:
        params["transformation"] = spec.transformation
    signature = sign(
        params, settings.CLOUDINARY_API_SECRET, settings.CLOUDINARY_SIGNATURE_ALGORITHM
    )
    return {
        "uploadUrl": (
            f"https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/"
            f"{spec.resource_type}/upload"
        ),
        # Send every field as-is in the multipart form, together with `file`.
        "fields": {
            **{k: str(v) for k, v in params.items()},
            "api_key": settings.CLOUDINARY_API_KEY,
            "signature": signature,
        },
        "maxBytes": spec.max_bytes,
        "allowedFormats": list(spec.formats),
        "expiresAt": params["timestamp"] + 3600,
    }


_DELIVERY_PATH = re.compile(
    r"^/(?P<cloud>[^/]+)/(?P<resource_type>image|video)/upload/"
    r"(?:[^/]+/)*?(?:v\d+/)?(?P<asset>.+)\.(?P<ext>[a-z0-9]+)$",
    re.IGNORECASE,
)


def is_cloudinary_url(url: str) -> bool:
    return urlparse(url).hostname == "res.cloudinary.com"


def assert_owned_upload(url: str, *, user, purpose: str) -> None:
    """
    Accept a delivery URL only if it is ours, in this user's folder for this purpose, and
    an allowed format. That stops attaching assets uploaded by someone else, or files
    uploaded outside the signed flow.
    """
    parsed = urlparse(url)
    match = _DELIVERY_PATH.match(parsed.path)
    spec = PURPOSES[purpose]
    expected_folder = folder_for(user, purpose) + "/"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "res.cloudinary.com"
        or match is None
        or match["cloud"] != settings.CLOUDINARY_CLOUD_NAME
        or match["resource_type"] != spec.resource_type
        or not match["asset"].startswith(expected_folder)
    ):
        raise InvalidUpload("This file wasn't uploaded through PLEET for your account.")
    if match["ext"].lower() not in spec.formats:
        raise InvalidUpload("Unsupported file format.")
