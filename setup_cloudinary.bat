@echo off
REM Cloudinary Configuration Helper for Windows
REM This script helps you set up image uploads

echo ========================================
echo Cloudinary Image Upload Configuration
echo ========================================
echo.

REM Check if we're in the backend directory
if not exist "manage.py" (
    echo ERROR: Please run this script from the tenancy-backend directory
    pause
    exit /b 1
)

echo Step 1: Checking current configuration...
echo.

REM Check if .env exists
if not exist ".env" (
    echo WARNING: .env file not found!
    echo Creating .env from .env.example...
    copy .env.example .env
    echo .env file created. Please configure it.
    echo.
)

REM Check if Cloudinary is configured
python -c "from django.conf import settings; import sys; sys.exit(0 if settings.CLOUDINARY_CLOUD_NAME and settings.CLOUDINARY_API_KEY and settings.CLOUDINARY_API_SECRET else 1)" 2>nul

if %ERRORLEVEL% EQU 0 (
    echo [OK] Cloudinary is already configured!
    echo.
    python -c "from django.conf import settings; print('Cloud Name:', settings.CLOUDINARY_CLOUD_NAME); print('API Key:', settings.CLOUDINARY_API_KEY[:4] + '...' + settings.CLOUDINARY_API_KEY[-4:])"
    echo.
    echo Your image uploads should be working.
    echo.
    pause
    exit /b 0
)

echo [!] Cloudinary is NOT configured
echo.
echo ========================================
echo Setup Instructions
echo ========================================
echo.
echo 1. Sign up for FREE Cloudinary account:
echo    https://cloudinary.com/users/register_free
echo.
echo 2. After signup, go to your dashboard
echo.
echo 3. Find these credentials:
echo    - Cloud name (e.g., dxyz1234)
echo    - API Key (e.g., 123456789012345)
echo    - API Secret (click "reveal" to see it)
echo.
echo 4. Copy your credentials (you'll need them next)
echo.
pause
echo.
echo ========================================
echo Enter Your Cloudinary Credentials
echo ========================================
echo.

set /p CLOUD_NAME="Enter your Cloud Name: "
set /p API_KEY="Enter your API Key: "
set /p API_SECRET="Enter your API Secret: "

if "%CLOUD_NAME%"=="" (
    echo ERROR: Cloud Name cannot be empty
    pause
    exit /b 1
)

if "%API_KEY%"=="" (
    echo ERROR: API Key cannot be empty
    pause
    exit /b 1
)

if "%API_SECRET%"=="" (
    echo ERROR: API Secret cannot be empty
    pause
    exit /b 1
)

echo.
echo ========================================
echo Adding to .env file...
echo ========================================
echo.

REM Check if Cloudinary section already exists
findstr /C:"CLOUDINARY_CLOUD_NAME" .env >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo WARNING: Cloudinary settings already exist in .env
    echo Please edit .env manually to update them.
    echo.
    echo Add these lines:
    echo CLOUDINARY_CLOUD_NAME=%CLOUD_NAME%
    echo CLOUDINARY_API_KEY=%API_KEY%
    echo CLOUDINARY_API_SECRET=%API_SECRET%
    echo CLOUDINARY_ROOT_FOLDER=pleet
    echo CLOUDINARY_SIGNATURE_ALGORITHM=sha1
    pause
    exit /b 0
)

REM Append to .env
echo. >> .env
echo # --- Image uploads (Cloudinary) --- >> .env
echo CLOUDINARY_CLOUD_NAME=%CLOUD_NAME% >> .env
echo CLOUDINARY_API_KEY=%API_KEY% >> .env
echo CLOUDINARY_API_SECRET=%API_SECRET% >> .env
echo CLOUDINARY_ROOT_FOLDER=pleet >> .env
echo CLOUDINARY_SIGNATURE_ALGORITHM=sha1 >> .env

echo [OK] Cloudinary configuration added to .env
echo.

echo ========================================
echo Testing Configuration
echo ========================================
echo.

python -c "from django.conf import settings; print('Cloud Name:', settings.CLOUDINARY_CLOUD_NAME); print('API Key:', settings.CLOUDINARY_API_KEY); print('Configured:', bool(settings.CLOUDINARY_CLOUD_NAME and settings.CLOUDINARY_API_KEY and settings.CLOUDINARY_API_SECRET))" 2>nul

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] Configuration successful!
    echo.
    echo ========================================
    echo Next Steps
    echo ========================================
    echo.
    echo 1. Restart your Django server:
    echo    python manage.py runserver
    echo.
    echo 2. Test image upload:
    echo    - Go to agent dashboard
    echo    - Create a property
    echo    - Try uploading an image
    echo.
    echo 3. Check Cloudinary dashboard:
    echo    https://cloudinary.com/console
    echo    You should see uploaded images there
    echo.
    echo Image uploads are now configured!
) else (
    echo.
    echo [!] Configuration test failed
    echo Please check your credentials and try again
    echo.
)

pause
