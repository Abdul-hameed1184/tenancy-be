@echo off
REM Email Verification Setup Checker for Windows
REM Run this script to verify your email configuration is working

echo ==================================
echo PLEET Email Verification Checker
echo ==================================
echo.

REM Check if we're in the backend directory
if not exist "manage.py" (
    echo ❌ Error: Please run this script from the tenancy-backend directory
    pause
    exit /b 1
)

echo ✓ Found Django project
echo.

REM Check if .env exists
if not exist ".env" (
    echo ❌ Error: .env file not found. Copy .env.example to .env first
    pause
    exit /b 1
)

echo ✓ Found .env file
echo.
echo ==================================
echo Environment Variables Check
echo ==================================
echo.
echo Please verify these settings in your .env file:
echo.
echo Required for email:
echo   EMAIL_HOST=smtp.gmail.com
echo   EMAIL_PORT=587
echo   EMAIL_USE_TLS=True
echo   EMAIL_HOST_USER=your-email@gmail.com
echo   EMAIL_HOST_PASSWORD=your-app-password
echo   DEFAULT_FROM_EMAIL=PLEET ^<noreply@yourdomain.com^>
echo.
echo For Gmail App Password:
echo   1. Enable 2FA on your Google account
echo   2. Visit: https://myaccount.google.com/apppasswords
echo   3. Generate new app password
echo   4. Use that 16-character password in EMAIL_HOST_PASSWORD
echo.
echo ==================================
echo Testing Email Configuration
echo ==================================
echo.

REM Test email sending
echo Attempting to send test email...
python manage.py shell -c "from django.core.mail import send_mail; from django.conf import settings; send_mail('PLEET Email Test', 'If you receive this, your email configuration is working!', settings.DEFAULT_FROM_EMAIL, [settings.EMAIL_HOST_USER]); print('✓ Test email sent! Check your inbox.')"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ Failed to send email
    echo.
    echo Common issues:
    echo - Gmail: Make sure you're using an App Password, not your regular password
    echo - Check if 2FA is enabled on your Google account
    echo - Verify EMAIL_HOST and EMAIL_PORT are correct
    echo - Make sure EMAIL_HOST_PASSWORD is set in .env
)

echo.
echo ==================================
echo Process Check
echo ==================================
echo.

REM Check if Redis is running
redis-cli ping >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ✓ Redis is running
) else (
    echo ❌ Redis is not running
    echo    Start Redis or use CELERY_TASK_ALWAYS_EAGER=True in .env
    echo    for synchronous email sending during development
)

echo.
echo ==================================
echo Setup Instructions
echo ==================================
echo.
echo Next steps:
echo.
echo 1. Verify .env file has all email settings
echo 2. Start Django: python manage.py runserver
echo 3. Start Celery worker: celery -A config worker --loglevel=info
echo    OR set CELERY_TASK_ALWAYS_EAGER=True in .env for development
echo 4. Start frontend: cd ..\tenancy-frontenf ^&^& npm run dev
echo 5. Register a test account and check your email
echo.
pause
