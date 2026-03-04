@echo off
echo === Sister AI Agent - Google Auth Setup ===
echo.

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python from https://python.org
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo [1/3] Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

echo [2/3] Installing dependencies...
.venv\Scripts\pip install --quiet google-api-python-client google-auth-oauthlib google-auth-httplib2
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo [3/3] Running Google authentication...
echo A browser window will open. Log in with your Google account and grant access.
echo.
.venv\Scripts\python auth_google.py
if errorlevel 1 (
    echo.
    echo ERROR: Authentication failed. Check that config\credentials.json is present.
    pause
    exit /b 1
)

echo.
echo === Done! token.json has been saved to config\ ===
pause
