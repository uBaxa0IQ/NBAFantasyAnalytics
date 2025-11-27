"""
Конфигурация приложения.
"""
import os


def get_cors_origins():
    """
    Получает список разрешенных источников для CORS.
    Для продакшена используйте переменную окружения CORS_ORIGINS (через запятую).
    Например: CORS_ORIGINS=http://yourdomain.com,http://www.yourdomain.com
    
    Returns:
        Список разрешенных источников
    """
    cors_origins_env = os.getenv("CORS_ORIGINS", "")
    if cors_origins_env:
        allowed_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
    else:
        # По умолчанию для разработки
        allowed_origins = [
            "http://localhost:5173",  # Vite dev server
            "http://localhost:3000",  # Docker frontend (old port)
            "http://localhost:3001",  # Docker frontend (new port)
            "http://127.0.0.1:3000",  # Docker frontend alternative
            "http://127.0.0.1:3001",  # Docker frontend alternative
        ]
    return allowed_origins

