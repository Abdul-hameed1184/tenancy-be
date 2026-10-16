#!/bin/bash

# Email Verification Setup Checker
# Run this script to verify your email configuration is working

echo "=================================="
echo "PLEET Email Verification Checker"
echo "=================================="
echo ""

# Check if we're in the backend directory
if [ ! -f "manage.py" ]; then
    echo "❌ Error: Please run this script from the tenancy-backend directory"
    exit 1
fi

echo "✓ Found Django project"
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found. Copy .env.example to .env first"
    exit 1
fi

echo "✓ Found .env file"
echo ""

# Source the .env file
export $(grep -v '^#' .env | xargs)

echo "Checking environment variables..."
echo ""

# Check email settings
MISSING=0

if [ -z "$EMAIL_HOST" ]; then
    echo "❌ EMAIL_HOST not set"
    MISSING=1
else
    echo "✓ EMAIL_HOST: $EMAIL_HOST"
fi

if [ -z "$EMAIL_PORT" ]; then
    echo "❌ EMAIL_PORT not set"
    MISSING=1
else
    echo "✓ EMAIL_PORT: $EMAIL_PORT"
fi

if [ -z "$EMAIL_HOST_USER" ]; then
    echo "❌ EMAIL_HOST_USER not set"
    MISSING=1
else
    echo "✓ EMAIL_HOST_USER: $EMAIL_HOST_USER"
fi

if [ -z "$EMAIL_HOST_PASSWORD" ]; then
    echo "❌ EMAIL_HOST_PASSWORD not set"
    MISSING=1
else
    echo "✓ EMAIL_HOST_PASSWORD: [REDACTED]"
fi

if [ -z "$DEFAULT_FROM_EMAIL" ]; then
    echo "⚠️  DEFAULT_FROM_EMAIL not set (will use default)"
else
    echo "✓ DEFAULT_FROM_EMAIL: $DEFAULT_FROM_EMAIL"
fi

if [ -z "$FRONTEND_URL" ]; then
    echo "⚠️  FRONTEND_URL not set (will use default)"
else
    echo "✓ FRONTEND_URL: $FRONTEND_URL"
fi

echo ""

if [ $MISSING -eq 1 ]; then
    echo "❌ Some required email settings are missing. Please update your .env file."
    echo ""
    echo "Required settings for Gmail:"
    echo "EMAIL_HOST=smtp.gmail.com"
    echo "EMAIL_PORT=587"
    echo "EMAIL_USE_TLS=True"
    echo "EMAIL_HOST_USER=your-email@gmail.com"
    echo "EMAIL_HOST_PASSWORD=your-16-char-app-password"
    echo ""
    echo "Get Gmail app password: https://myaccount.google.com/apppasswords"
    exit 1
fi

echo "=================================="
echo "Testing Email Configuration"
echo "=================================="
echo ""

# Test email sending
echo "Attempting to send test email..."
python manage.py shell << EOF
from django.core.mail import send_mail
from django.conf import settings

try:
    send_mail(
        subject='PLEET Email Test',
        message='If you receive this, your email configuration is working!',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[settings.EMAIL_HOST_USER],
        fail_silently=False,
    )
    print("✓ Test email sent successfully!")
    print(f"Check {settings.EMAIL_HOST_USER} for the test email")
except Exception as e:
    print(f"❌ Failed to send email: {e}")
    print("")
    print("Common issues:")
    print("- Gmail: Make sure you're using an App Password, not your regular password")
    print("- Check if 2FA is enabled on your Google account")
    print("- Verify EMAIL_HOST and EMAIL_PORT are correct")
EOF

echo ""
echo "=================================="
echo "Process Check"
echo "=================================="
echo ""

# Check if Redis is running
if command -v redis-cli &> /dev/null; then
    if redis-cli ping &> /dev/null; then
        echo "✓ Redis is running"
    else
        echo "❌ Redis is not running. Start it with: redis-server"
        echo "   (Celery needs Redis to work)"
    fi
else
    echo "⚠️  redis-cli not found. Make sure Redis is installed and running."
fi

echo ""

# Check if Celery worker should be running
if [ "$CELERY_TASK_ALWAYS_EAGER" = "True" ] || [ "$CELERY_BROKER_URL" = "memory://" ]; then
    echo "ℹ️  Celery is in EAGER mode (tasks run synchronously)"
    echo "   Email will be sent immediately without needing a worker"
else
    echo "ℹ️  Celery is in async mode"
    echo "   Make sure Celery worker is running:"
    echo "   celery -A config worker --loglevel=info"
fi

echo ""
echo "=================================="
echo "Setup Complete!"
echo "=================================="
echo ""
echo "Next steps:"
echo "1. Start Django: python manage.py runserver"
echo "2. Start Celery worker (if not EAGER mode): celery -A config worker --loglevel=info"
echo "3. Start frontend: cd ../tenancy-frontenf && npm run dev"
echo "4. Register a test account and check your email"
echo ""
