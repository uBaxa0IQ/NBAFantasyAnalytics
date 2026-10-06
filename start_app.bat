@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "FRONTEND_DIR=%PROJECT_ROOT%web\frontend"
set "VENV_PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe"

if not exist "%PROJECT_ROOT%.env" (
    echo Missing .env file.
    echo Copy .env.example to .env in the project root and fill in your ESPN settings.
    goto :fail
)

where npm.cmd >nul 2>&1
if errorlevel 1 (
    echo Node.js and npm are required. Install Node.js 18 or newer.
    goto :fail
)
node -e "process.exit(Number(process.versions.node.split('.')[0]) < 18 ? 1 : 0)" >nul 2>&1
if errorlevel 1 (
    echo Node.js 18 or newer is required.
    goto :fail
)

where py.exe >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
) else (
    where python.exe >nul 2>&1
    if errorlevel 1 (
        echo Python 3.10 or newer is required.
        goto :fail
    )
    set "PYTHON_CMD=python"
)

if not exist "%VENV_PYTHON%" (
    echo Creating Python virtual environment...
    %PYTHON_CMD% -m venv "%PROJECT_ROOT%.venv"
    if errorlevel 1 goto :fail
)
"%VENV_PYTHON%" -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 (
    echo Python 3.10 or newer is required.
    goto :fail
)

echo Installing backend dependencies...
"%VENV_PYTHON%" -m pip install -r "%PROJECT_ROOT%requirements.txt"
if errorlevel 1 goto :fail

if not exist "%FRONTEND_DIR%\node_modules" (
    echo Installing frontend dependencies...
    pushd "%FRONTEND_DIR%"
    call npm.cmd ci
    if errorlevel 1 (
        popd
        goto :fail
    )
    popd
)

echo Starting backend and frontend in separate windows...
start "NBA Backend" /D "%PROJECT_ROOT%" cmd /k ""%VENV_PYTHON%" -m uvicorn web.backend.main:app --reload --host 127.0.0.1 --port 8000"
start "NBA Frontend" /D "%FRONTEND_DIR%" cmd /k "npm.cmd run dev"

echo Backend API: http://localhost:8000/docs
echo Frontend:    http://127.0.0.1:5173
echo Close both server windows to stop the application.
exit /b 0

:fail
echo.
echo The application was not started.
pause
exit /b 1
