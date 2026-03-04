@echo off
echo === Sister AI Agent — Full Setup ===
echo.

:: ------------------------------------------------------------
:: 1. Check Python
:: ------------------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    echo Please install Python 3.11+ from https://python.org
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
echo [OK] Python found.

:: ------------------------------------------------------------
:: 2. Install Poetry if not present
:: ------------------------------------------------------------
poetry --version >nul 2>&1
if errorlevel 1 (
    echo [1/5] Installing Poetry...
    pip install poetry --quiet
    if errorlevel 1 (
        echo ERROR: Failed to install Poetry.
        pause
        exit /b 1
    )
    echo [OK] Poetry installed.
) else (
    echo [1/5] Poetry already installed.
)

:: ------------------------------------------------------------
:: 3. Install project dependencies
:: ------------------------------------------------------------
echo [2/5] Installing project dependencies (this may take a minute)...
poetry install --no-interaction
if errorlevel 1 (
    echo ERROR: poetry install failed. Check pyproject.toml and your internet connection.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.

:: ------------------------------------------------------------
:: 4. Create .env from .env.example (if not already present)
:: ------------------------------------------------------------
echo [3/5] Checking .env file...
if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo [OK] Created .env from .env.example.
        echo.
        echo IMPORTANT: Open .env in a text editor and fill in your API keys before continuing.
        echo   - ANTHROPIC_API_KEY
        echo   - TELEGRAM_BOT_TOKEN
        echo   - TELEGRAM_ALLOWED_USER_ID
        echo   - TELEGRAM_API_ID
        echo   - TELEGRAM_API_HASH
        echo   - TELEGRAM_PHONE
        echo.
        echo Press any key once you have saved your .env file...
        pause >nul
    ) else (
        echo WARNING: .env.example not found. Create a .env file manually.
    )
) else (
    echo [OK] .env already exists.
)

:: ------------------------------------------------------------
:: 5. Google auth
:: ------------------------------------------------------------
echo [4/5] Running Google authentication...
echo A browser window will open. Log in with the Google account and grant access.
echo Make sure config\credentials.json is present before continuing.
echo.
if not exist config\credentials.json (
    echo ERROR: config\credentials.json not found.
    echo Download OAuth credentials from Google Cloud Console and place them at config\credentials.json.
    pause
    exit /b 1
)
poetry run python auth_google.py
if errorlevel 1 (
    echo.
    echo ERROR: Google authentication failed.
    echo Check that config\credentials.json is valid and try again.
    pause
    exit /b 1
)
echo [OK] Google authentication complete.

:: ------------------------------------------------------------
:: 6. Telegram auth
:: ------------------------------------------------------------
echo [5/5] Running Telegram authentication...
echo You will receive an SMS code on your phone. Enter it when prompted.
echo.
poetry run python auth_telegram.py
if errorlevel 1 (
    echo.
    echo ERROR: Telegram authentication failed.
    echo Check TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_PHONE in your .env file.
    pause
    exit /b 1
)
echo [OK] Telegram authentication complete.

:: ------------------------------------------------------------
:: Done
:: ------------------------------------------------------------
echo.
echo === Setup complete! ===
echo.
echo To start the assistant, run:
echo     poetry run python main.py
echo.
echo For a full initial sync (recommended on first run):
echo     poetry run python main.py --full-sync
echo.
pause
