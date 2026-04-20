@echo off
echo ==========================================
echo    Hospital Chatbot Ngrok Starter
echo ==========================================
echo.
echo 1. Make sure Backend is running on port 8001
echo 2. Make sure Frontend is running on port 3000
echo.
echo Checking for ngrok...
ngrok --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] ngrok is not installed or not in PATH.
    echo Please download it from https://ngrok.com/download
    pause
    exit /b
)

echo.
echo Starting Ngrok on port 3000 (Frontend with Backend Proxy)...
echo.
echo Copy the "Forwarding" link (https://....ngrok-free.app) and send it to your friends!
echo.
ngrok http 3000
pause
