"""
Роутер для админ-панели.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from admin_db import get_db_connection, create_or_update_admin, has_admin, get_trade_logs, get_trade_stats
import hashlib

router = APIRouter(prefix="/api/admin", tags=["admin"])


class PasswordRequest(BaseModel):
    password: str


class ChangePasswordRequest(BaseModel):
    new_password: str


def hash_password(password: str) -> str:
    """Хеширует пароль используя SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Проверяет пароль."""
    return hash_password(password) == password_hash


@router.post("/verify-password")
def verify_admin_password(request: PasswordRequest):
    """
    Проверяет пароль администратора.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Получаем всех администраторов
    cursor.execute('SELECT password_hash FROM admins LIMIT 1')
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        # Если нет администраторов в БД, используем дефолтный пароль
        # В продакшене это нужно будет изменить!
        default_hash = hash_password('admin123')  # ВРЕМЕННЫЙ ПАРОЛЬ!
        if verify_password(request.password, default_hash):
            return {"success": True}
        else:
            raise HTTPException(status_code=401, detail="Неверный пароль")
    
    # Проверяем пароль (row - это кортеж, берем первый элемент)
    password_hash = row[0] if isinstance(row, tuple) else row['password_hash']
    if verify_password(request.password, password_hash):
        return {"success": True}
    else:
        raise HTTPException(status_code=401, detail="Неверный пароль")


@router.post("/change-password")
def change_admin_password(request: ChangePasswordRequest):
    """
    Изменяет пароль администратора.
    Если админа нет в БД, создает нового.
    """
    if not request.new_password or len(request.new_password) < 3:
        raise HTTPException(status_code=400, detail="Пароль должен быть не менее 3 символов")
    
    # Хешируем новый пароль
    new_password_hash = hash_password(request.new_password)
    
    # Создаем или обновляем админа
    create_or_update_admin('admin', new_password_hash)
    
    return {"success": True, "message": "Пароль успешно изменен"}


@router.get("/trade-logs")
def get_admin_trade_logs(
    limit: int = Query(100, ge=1, le=1000),
    time_period: str = Query(None, regex="^(24h|7d|30d|all)$"),
    trade_type: str = Query(None, regex="^(two-team|multi-team)$")
):
    """
    Получает логи трейдов для админ-панели.
    """
    logs = get_trade_logs(limit=limit, time_period=time_period, trade_type=trade_type)
    return {"logs": logs}


@router.get("/trade-stats")
def get_admin_trade_stats():
    """
    Получает статистику по трейдам для админ-панели.
    """
    stats = get_trade_stats()
    return stats
