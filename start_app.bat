@echo off
start "NBA Backend" cmd /k "uvicorn web.backend.main:app --reload --host 0.0.0.0 --port 8000"
start "NBA Frontend" cmd /k "cd web\frontend && npm run dev"
echo App started!
echo Backend: http://localhost:8000/docs
echo Frontend: http://localhost:5173
pause
