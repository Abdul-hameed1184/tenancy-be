@echo off
REM Quick script to verify all agents in the database
REM Run from tenancy-backend directory

echo ============================================
echo Quick Agent Verification Script
echo ============================================
echo.

if not exist "manage.py" (
    echo ERROR: Please run from tenancy-backend directory
    pause
    exit /b 1
)

echo This will mark ALL agents as verified for testing.
echo.
set /p CONFIRM="Continue? (yes/no): "

if not "%CONFIRM%"=="yes" (
    echo Cancelled.
    pause
    exit /b 0
)

echo.
echo Verifying all agents...
echo.

python manage.py shell -c "from apps.agents.models import AgentProfile; count = AgentProfile.objects.filter(verification_status__in=['unverified', 'pending']).update(verification_status='verified'); print(f'Verified {count} agents'); print(); print('Current agents:'); [print(f'  {p.user.name} ({p.user.email}): {p.verification_status} - Agency: {p.agency or \"(not set)\"}') for p in AgentProfile.objects.all()]"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================
    echo SUCCESS!
    echo ============================================
    echo.
    echo All agents are now verified.
    echo.
    echo Next steps:
    echo 1. Refresh your frontend browser
    echo 2. Try the Assign Agent dialog again
    echo 3. Agent names should now appear!
    echo.
    echo If agents still don't appear, check that:
    echo - Agents have names set
    echo - Agents have agency field filled
    echo.
) else (
    echo.
    echo ERROR: Failed to verify agents
    echo Check the error message above
    echo.
)

pause
