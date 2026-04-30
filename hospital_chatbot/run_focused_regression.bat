@echo off
REM Script to run focused runtime regression tests

echo ========================================
echo Running Focused Runtime Regression Tests
echo ========================================
echo.

REM Check if server is running
echo Checking if server is running on http://127.0.0.1:8000...
curl -s http://127.0.0.1:8000/health >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Server is not running on http://127.0.0.1:8000
    echo Please start the server first:
    echo   cd backend
    echo   python -m uvicorn app:app --reload --port 8000
    pause
    exit /b 1
)

echo Server is running.
echo.

REM Run the focused regression tests
python test_focused_runtime_regression.py http://127.0.0.1:8000

if %errorlevel% neq 0 (
    echo.
    echo Tests failed!
    exit /b 1
)

echo.
echo ========================================
echo All tests completed successfully!
echo ========================================
echo.
echo Results saved to: focused_runtime_regression_results.json
pause
