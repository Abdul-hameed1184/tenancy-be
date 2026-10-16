#!/usr/bin/env python
"""
Test script to verify image upload configuration and URL routing.
Run this from tenancy-backend directory: python test_uploads.py
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
django.setup()

from django.conf import settings
from django.urls import reverse, resolve
from apps.uploads import cloudinary

print("=" * 70)
print("IMAGE UPLOAD CONFIGURATION TEST")
print("=" * 70)
print()

# Test 1: Check Cloudinary Configuration
print("1. Checking Cloudinary Configuration...")
print("-" * 70)

if settings.CLOUDINARY_CLOUD_NAME:
    print(f"✓ CLOUDINARY_CLOUD_NAME: {settings.CLOUDINARY_CLOUD_NAME}")
else:
    print("✗ CLOUDINARY_CLOUD_NAME: NOT SET")

if settings.CLOUDINARY_API_KEY:
    print(f"✓ CLOUDINARY_API_KEY: {settings.CLOUDINARY_API_KEY[:4]}...{settings.CLOUDINARY_API_KEY[-4:]}")
else:
    print("✗ CLOUDINARY_API_KEY: NOT SET")

if settings.CLOUDINARY_API_SECRET:
    print(f"✓ CLOUDINARY_API_SECRET: {settings.CLOUDINARY_API_SECRET[:4]}...{settings.CLOUDINARY_API_SECRET[-4:]}")
else:
    print("✗ CLOUDINARY_API_SECRET: NOT SET")

print(f"✓ CLOUDINARY_ROOT_FOLDER: {settings.CLOUDINARY_ROOT_FOLDER}")
print(f"✓ CLOUDINARY_SIGNATURE_ALGORITHM: {settings.CLOUDINARY_SIGNATURE_ALGORITHM}")
print()

is_configured = cloudinary.is_configured()
if is_configured:
    print("✅ Cloudinary is CONFIGURED and ready!")
else:
    print("❌ Cloudinary is NOT configured")
    print()
    print("To fix:")
    print("1. Sign up at: https://cloudinary.com/users/register_free")
    print("2. Add credentials to .env file")
    print("3. Restart the server")
    sys.exit(1)

print()

# Test 2: Check URL Routing
print("2. Checking URL Routing...")
print("-" * 70)

try:
    url = reverse('v1:upload-signature')
    print(f"✓ Upload signature URL: {url}")
    print(f"  Full URL: http://localhost:8000{url}")

    # Check if URL resolves
    match = resolve(url)
    print(f"✓ URL resolves to: {match.func.__name__}")
    print(f"  View class: {match.func.view_class.__name__}")
except Exception as e:
    print(f"✗ URL routing error: {e}")
    sys.exit(1)

print()

# Test 3: Check Upload Purposes
print("3. Checking Upload Purposes...")
print("-" * 70)

for purpose, spec in cloudinary.PURPOSES.items():
    print(f"✓ {purpose}:")
    print(f"  - Folder: {spec.folder}")
    print(f"  - Roles: {', '.join(spec.roles)}")
    print(f"  - Formats: {', '.join(spec.formats)}")
    print(f"  - Max size: {spec.max_bytes / (1024*1024):.1f} MB")
    print(f"  - Transformation: {spec.transformation}")
    print()

# Test 4: Test Signature Generation
print("4. Testing Signature Generation...")
print("-" * 70)

try:
    from apps.accounts.models import User

    # Try to get a landlord user for testing
    landlord = User.objects.filter(role='landlord').first()

    if landlord:
        print(f"✓ Using test user: {landlord.email} (role: {landlord.role})")

        try:
            signature_data = cloudinary.signed_upload(landlord, "property_photo")
            print("✓ Signature generated successfully!")
            print(f"  Upload URL: {signature_data['uploadUrl']}")
            print(f"  Max bytes: {signature_data['maxBytes']}")
            print(f"  Allowed formats: {', '.join(signature_data['allowedFormats'])}")
            print(f"  Expires at: {signature_data['expiresAt']} (Unix timestamp)")
            print(f"  Fields include: {', '.join(signature_data['fields'].keys())}")
        except cloudinary.UploadsNotConfigured:
            print("✗ Uploads not configured")
        except Exception as e:
            print(f"✗ Error generating signature: {e}")
    else:
        print("⚠ No landlord user found in database")
        print("  Create a landlord user to fully test signature generation")

except Exception as e:
    print(f"⚠ Cannot test with real user: {e}")

print()

# Test 5: Check Frontend Integration
print("5. Frontend Integration Check...")
print("-" * 70)

print("Frontend should call:")
print(f"  POST {url}")
print("  Headers: Authorization: Bearer <token>")
print("  Body: {{ \"purpose\": \"property_photo\" }}")
print()
print("Backend will respond with:")
print("  {{ \"uploadUrl\": \"https://api.cloudinary.com/...\",")
print("     \"fields\": {{ ... }},")
print("     \"maxBytes\": ...,")
print("     \"allowedFormats\": [...] }}")
print()
print("Frontend then uploads directly to Cloudinary URL.")
print()

# Summary
print("=" * 70)
print("SUMMARY")
print("=" * 70)

if is_configured:
    print("✅ Image uploads are CONFIGURED and READY!")
    print()
    print("Next steps:")
    print("1. Start backend: python manage.py runserver")
    print("2. Start frontend: cd ../tenancy-frontenf && npm run dev")
    print("3. Login as landlord")
    print("4. Go to agent dashboard → Create property")
    print("5. Try uploading an image")
    print()
    print("The upload should work! Check Cloudinary dashboard to see uploaded images.")
else:
    print("❌ Image uploads are NOT configured")
    print()
    print("Run: setup_cloudinary.bat")
    print("Or manually add Cloudinary credentials to .env")

print()
print("=" * 70)
