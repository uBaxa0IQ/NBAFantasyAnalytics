from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys
import os

# Добавляем путь к текущей директории для импорта локальных модулей
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, backend_dir)

# Добавляем путь к проекту и core
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'core'))

from config import get_cors_origins
from routers import teams, analytics, simulation, players, trades, dashboard, balance

app = FastAPI()

# Настройка CORS
allowed_origins = get_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение роутеров
app.include_router(teams.router)
app.include_router(analytics.router)
app.include_router(simulation.router)
app.include_router(players.router)
app.include_router(trades.router)
app.include_router(dashboard.router)
app.include_router(balance.router)


@app.get("/")
def root():
    return {"message": "NBA Fantasy Analytics API"}
