"""
База данных для админ-панели - логирование трейдов.
"""
import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional
import json

# Путь к базе данных
DB_PATH = os.path.join(os.path.dirname(__file__), 'admin.db')


def get_db_connection():
    """Создает и возвращает соединение с базой данных."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Инициализирует базу данных, создавая необходимые таблицы."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Таблица для логирования трейдов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trade_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            trade_type TEXT NOT NULL,
            teams_involved TEXT NOT NULL,
            team_names TEXT NOT NULL,
            players_involved TEXT NOT NULL,
            top_players TEXT NOT NULL,
            scope_mode TEXT,
            period TEXT,
            result_delta REAL,
            full_result TEXT,
            ip_address TEXT
        )
    ''')
    
    # Добавляем новые колонки если их нет (для существующих БД)
    try:
        cursor.execute('ALTER TABLE trade_logs ADD COLUMN team_names TEXT')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE trade_logs ADD COLUMN top_players TEXT')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE trade_logs ADD COLUMN full_result TEXT')
    except:
        pass
    
    # Таблица для администраторов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()


def log_trade(
    trade_type: str,
    teams_involved: List[int],
    team_names: List[str],
    players_involved: Dict,
    top_players: Dict,
    scope_mode: Optional[str] = None,
    period: Optional[str] = None,
    result_delta: Optional[float] = None,
    full_result: Optional[Dict] = None,
    ip_address: Optional[str] = None
):
    """
    Логирует анализ трейда.
    
    Args:
        trade_type: 'two-team' или 'multi-team'
        teams_involved: Список ID команд
        team_names: Список названий команд
        players_involved: Словарь с ключами 'give' и 'receive' (для two-team) 
                         или список словарей для multi-team
        top_players: Словарь с лучшими участниками трейда для каждой команды
        scope_mode: 'team' или 'trade'
        period: Период статистики
        result_delta: Изменение Z-score
        full_result: Полный результат анализа трейда
        ip_address: IP адрес клиента
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    timestamp = datetime.utcnow().isoformat()
    
    cursor.execute('''
        INSERT INTO trade_logs 
        (timestamp, trade_type, teams_involved, team_names, players_involved, top_players, scope_mode, period, result_delta, full_result, ip_address)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        timestamp,
        trade_type,
        json.dumps(teams_involved),
        json.dumps(team_names),
        json.dumps(players_involved),
        json.dumps(top_players),
        scope_mode,
        period,
        result_delta,
        json.dumps(full_result) if full_result else None,
        ip_address
    ))
    
    conn.commit()
    conn.close()


def get_trade_logs(
    limit: int = 100,
    time_period: Optional[str] = None,
    trade_type: Optional[str] = None
) -> List[Dict]:
    """
    Получает логи трейдов.
    
    Args:
        limit: Максимальное количество записей
        time_period: '24h', '7d', '30d', 'all' (None = all)
        trade_type: 'two-team', 'multi-team' или None (все)
    
    Returns:
        Список словарей с данными о трейдах
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = 'SELECT * FROM trade_logs WHERE 1=1'
    params = []
    
    # Фильтр по времени
    if time_period:
        if time_period == '24h':
            query += ' AND timestamp >= datetime("now", "-1 day")'
        elif time_period == '7d':
            query += ' AND timestamp >= datetime("now", "-7 days")'
        elif time_period == '30d':
            query += ' AND timestamp >= datetime("now", "-30 days")'
    
    # Фильтр по типу трейда
    if trade_type:
        query += ' AND trade_type = ?'
        params.append(trade_type)
    
    query += ' ORDER BY timestamp DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    conn.close()
    
    # Преобразуем Row объекты в словари
    logs = []
    for row in rows:
        # sqlite3.Row поддерживает доступ по ключу через [], но не имеет метода get()
        team_names_value = row['team_names'] if 'team_names' in row.keys() else None
        top_players_value = row['top_players'] if 'top_players' in row.keys() else None
        full_result_value = row['full_result'] if 'full_result' in row.keys() else None
        
        log = {
            'id': row['id'],
            'timestamp': row['timestamp'],
            'trade_type': row['trade_type'],
            'teams_involved': json.loads(row['teams_involved']),
            'team_names': json.loads(team_names_value) if team_names_value else [],
            'players_involved': json.loads(row['players_involved']),
            'top_players': json.loads(top_players_value) if top_players_value else {},
            'scope_mode': row['scope_mode'],
            'period': row['period'],
            'result_delta': row['result_delta'],
            'full_result': json.loads(full_result_value) if full_result_value else None,
            'ip_address': row['ip_address']
        }
        logs.append(log)
    
    return logs


def get_trade_stats() -> Dict:
    """
    Получает общую статистику по трейдам.
    
    Returns:
        Словарь со статистикой
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Общее количество трейдов
    cursor.execute('SELECT COUNT(*) as total FROM trade_logs')
    total = cursor.fetchone()['total']
    
    # Количество по типам
    cursor.execute('''
        SELECT trade_type, COUNT(*) as count 
        FROM trade_logs 
        GROUP BY trade_type
    ''')
    by_type = {row['trade_type']: row['count'] for row in cursor.fetchall()}
    
    # Количество за последние 24 часа
    cursor.execute('''
        SELECT COUNT(*) as count 
        FROM trade_logs 
        WHERE timestamp >= datetime("now", "-1 day")
    ''')
    last_24h = cursor.fetchone()['count']
    
    # Количество за последние 7 дней
    cursor.execute('''
        SELECT COUNT(*) as count 
        FROM trade_logs 
        WHERE timestamp >= datetime("now", "-7 days")
    ''')
    last_7d = cursor.fetchone()['count']
    
    conn.close()
    
    return {
        'total': total,
        'by_type': by_type,
        'last_24h': last_24h,
        'last_7d': last_7d
    }


def create_or_update_admin(username: str, password_hash: str) -> bool:
    """
    Создает или обновляет пароль администратора.
    
    Args:
        username: Имя пользователя (обычно 'admin')
        password_hash: Хеш пароля
    
    Returns:
        True если успешно
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    timestamp = datetime.utcnow().isoformat()
    
    # Проверяем, существует ли админ
    cursor.execute('SELECT id FROM admins WHERE username = ?', (username,))
    existing = cursor.fetchone()
    
    if existing:
        # Обновляем существующего админа
        cursor.execute('''
            UPDATE admins 
            SET password_hash = ? 
            WHERE username = ?
        ''', (password_hash, username))
    else:
        # Создаем нового админа
        cursor.execute('''
            INSERT INTO admins (username, password_hash, created_at)
            VALUES (?, ?, ?)
        ''', (username, password_hash, timestamp))
    
    conn.commit()
    conn.close()
    
    return True


def has_admin() -> bool:
    """
    Проверяет, есть ли хотя бы один администратор в БД.
    
    Returns:
        True если есть админ
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) as count FROM admins')
    count = cursor.fetchone()['count']
    
    conn.close()
    
    return count > 0


# Инициализация базы при импорте
init_db()

