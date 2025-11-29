from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import sys
import os
import asyncio
import logging

# Добавляем путь к текущей директории для импорта локальных модулей
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, backend_dir)

# Добавляем путь к проекту и core
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'core'))

from config import get_cors_origins
from routers import teams, analytics, simulation, players, trades, dashboard, balance, lineup
from dependencies import get_league_meta

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Флаг для отслеживания процесса обновления
is_refreshing = False

async def background_refresh_task():
    """
    Фоновая задача для автоматического обновления данных лиги каждые 5 минут.
    Первое обновление происходит через 5 минут после запуска.
    """
    global is_refreshing
    
    # Ждем 5 минут перед первым обновлением
    await asyncio.sleep(300)  # 5 минут = 300 секунд
    
    while True:
        try:
            if not is_refreshing:
                is_refreshing = True
                logger.info("Начало автоматического обновления данных лиги...")
                
                # Получаем экземпляр LeagueMetadata
                league_meta = get_league_meta()
                
                # Обновляем данные
                success = league_meta.refresh_league()
                
                if success:
                    last_refresh = league_meta.get_last_refresh_time()
                    logger.info(f"Данные лиги успешно обновлены. Время: {last_refresh}")
                else:
                    logger.warning("Ошибка при автоматическом обновлении данных лиги")
                
                is_refreshing = False
            else:
                logger.warning("Пропуск обновления: предыдущее обновление еще выполняется")
        except Exception as e:
            logger.error(f"Ошибка в фоновой задаче обновления: {e}")
            is_refreshing = False
        
        # Ждем 5 минут до следующего обновления
        await asyncio.sleep(300)  # 5 минут = 300 секунд


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управление жизненным циклом приложения.
    Запускает фоновую задачу автообновления при старте.
    """
    logger.info("Запуск фоновой задачи автообновления данных (первое обновление через 5 минут)...")
    task = asyncio.create_task(background_refresh_task())
    yield
    logger.info("Остановка фоновой задачи автообновления...")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(lifespan=lifespan)

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
app.include_router(lineup.router)


@app.get("/")
def root():
    return {"message": "NBA Fantasy Analytics API"}
