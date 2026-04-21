"""
Роутер для админ-панели.
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from admin_db import get_db_connection, create_or_update_admin, has_admin, get_trade_logs, get_trade_stats
from dependencies import get_league_meta
from typing import Dict, Optional, List
import hashlib
import json
import ast
from pathlib import Path

router = APIRouter(prefix="/api/admin", tags=["admin"])


class PasswordRequest(BaseModel):
    password: str


class ChangePasswordRequest(BaseModel):
    new_password: str


class WeightedCoefficientsRequest(BaseModel):
    """Модель для обновления коэффициентов взвешенного периода."""
    total: float
    last_30: float
    last_15: float
    last_7: float


class LeagueSettingsRequest(BaseModel):
    """Модель для обновления настроек лиги."""
    force_weighted_mode: bool
    forced_period: Optional[str] = "2026_weighted"


class TradeOptimizationRequest(BaseModel):
    """Модель для анализа трейда с кастомными коэффициентами."""
    my_team_id: int
    their_team_id: int
    i_give: List[str]
    i_receive: List[str]
    custom_coefficients: Optional[Dict[str, float]] = None
    period: str = "2026_weighted"
    punt_categories: List[str] = []
    simulation_mode: str = "all"
    top_n_players: int = 13


class TradeAutoSearchRequest(BaseModel):
    """Модель для автопоиска оптимальных коэффициентов."""
    my_team_id: int
    their_team_id: int
    i_give: List[str]
    i_receive: List[str]
    period: str = "2026_weighted"
    punt_categories: List[str] = []
    simulation_mode: str = "all"
    top_n_players: int = 13
    step: float = 0.1  # Шаг для перебора (например, 0.1 = 10%)
    search_mode: str = "avg"  # 'avg' или 'z_score' - режим поиска


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


def get_coefficients_file_path():
    """Возвращает путь к файлу с коэффициентами."""
    return Path(__file__).parent.parent.parent / "core" / "weighted_coefficients.json"


def load_weighted_coefficients() -> Dict[str, float]:
    """
    Загружает коэффициенты из JSON файла или возвращает дефолтные из config.
    """
    coeffs_file = get_coefficients_file_path()
    
    # Пытаемся загрузить из JSON
    if coeffs_file.exists():
        try:
            with open(coeffs_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {
                    '2026_total': float(data.get('total', 0.40)),
                    '2026_last_30': float(data.get('last_30', 0.30)),
                    '2026_last_15': float(data.get('last_15', 0.20)),
                    '2026_last_7': float(data.get('last_7', 0.10))
                }
        except Exception as e:
            print(f"Error loading coefficients from JSON: {e}")
    
    # Fallback на config.py
    try:
        from core.config import WEIGHTED_PERIOD_COEFFS
        return WEIGHTED_PERIOD_COEFFS.copy()
    except:
        # Дефолтные значения
        return {
            '2026_total': 0.40,
            '2026_last_30': 0.30,
            '2026_last_15': 0.20,
            '2026_last_7': 0.10
        }


def save_weighted_coefficients(coeffs: Dict[str, float]) -> bool:
    """
    Сохраняет коэффициенты в JSON файл.
    """
    try:
        coeffs_file = get_coefficients_file_path()
        
        # Создаем директорию, если её нет
        coeffs_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Сохраняем в формате, удобном для чтения
        data = {
            'total': float(coeffs.get('2026_total', 0.40)),
            'last_30': float(coeffs.get('2026_last_30', 0.30)),
            'last_15': float(coeffs.get('2026_last_15', 0.20)),
            'last_7': float(coeffs.get('2026_last_7', 0.10))
        }
        
        with open(coeffs_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        # JSON файл успешно сохранен
        json_saved = True
        
        # Также обновляем config.py для обратной совместимости (не критично, если не получится)
        config_file = Path(__file__).parent.parent.parent / "core" / "config.py"
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Заменяем WEIGHTED_PERIOD_COEFFS
                import re
                pattern = r'WEIGHTED_PERIOD_COEFFS\s*=\s*\{[^}]+\}'
                replacement = f"""WEIGHTED_PERIOD_COEFFS = {{
    '2026_total': {coeffs.get('2026_total', 0.40)},
    '2026_last_30': {coeffs.get('2026_last_30', 0.30)},
    '2026_last_15': {coeffs.get('2026_last_15', 0.20)},
    '2026_last_7': {coeffs.get('2026_last_7', 0.10)}
}}"""
                
                new_content = re.sub(pattern, replacement, content)
                
                with open(config_file, 'w', encoding='utf-8') as f:
                    f.write(new_content)
            except Exception as e:
                # Ошибка при обновлении config.py не критична, JSON уже сохранен
                print(f"Warning: Could not update config.py: {e}")
                import traceback
                traceback.print_exc()
        
        # Возвращаем True, если JSON сохранен (даже если config.py не обновлен)
        return json_saved
    except Exception as e:
        print(f"Error saving coefficients: {e}")
        return False


@router.get("/weighted-coefficients")
def get_weighted_coefficients():
    """
    Получает текущие коэффициенты взвешенного периода.
    """
    coeffs = load_weighted_coefficients()
    return {
        "total": coeffs.get('2026_total', 0.40),
        "last_30": coeffs.get('2026_last_30', 0.30),
        "last_15": coeffs.get('2026_last_15', 0.20),
        "last_7": coeffs.get('2026_last_7', 0.10)
    }


@router.post("/weighted-coefficients")
def update_weighted_coefficients(request: WeightedCoefficientsRequest):
    """
    Обновляет коэффициенты взвешенного периода.
    """
    # Проверяем, что сумма = 1.0
    total = request.total + request.last_30 + request.last_15 + request.last_7
    if abs(total - 1.0) > 0.001:
        raise HTTPException(
            status_code=400, 
            detail=f"Сумма коэффициентов должна быть равна 1.0. Текущая сумма: {total:.3f}"
        )
    
    # Проверяем, что все коэффициенты >= 0
    if any(x < 0 for x in [request.total, request.last_30, request.last_15, request.last_7]):
        raise HTTPException(status_code=400, detail="Коэффициенты не могут быть отрицательными")
    
    # Сохраняем
    coeffs = {
        '2026_total': request.total,
        '2026_last_30': request.last_30,
        '2026_last_15': request.last_15,
        '2026_last_7': request.last_7
    }
    
    try:
        if save_weighted_coefficients(coeffs):
            return {
                "success": True,
                "message": "Коэффициенты успешно обновлены",
                "coefficients": {
                    "total": request.total,
                    "last_30": request.last_30,
                    "last_15": request.last_15,
                    "last_7": request.last_7
                }
            }
        else:
            raise HTTPException(status_code=500, detail="Ошибка при сохранении коэффициентов в файл")
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error saving coefficients: {error_details}")
        raise HTTPException(status_code=500, detail=f"Ошибка при сохранении коэффициентов: {str(e)}")


@router.get("/settings")
def get_admin_league_settings():
    """
    Получает настройки лиги для админ-панели.
    """
    from utils.settings import load_league_settings
    return load_league_settings()


@router.post("/settings")
def update_league_settings(request: LeagueSettingsRequest):
    """
    Обновляет настройки лиги.
    """
    from utils.settings import save_league_settings
    
    settings = {
        "force_weighted_mode": request.force_weighted_mode,
        "forced_period": request.forced_period
    }
    
    if save_league_settings(settings):
        return {"success": True, "message": "Настройки успешно обновлены", "settings": settings}
    else:
        raise HTTPException(status_code=500, detail="Ошибка при сохранении настроек")


@router.post("/trade-optimization")
def analyze_trade_with_custom_coefficients(
    request: TradeOptimizationRequest,
    league_meta=Depends(get_league_meta)
):
    """
    Анализирует трейд с кастомными коэффициентами взвешенного периода.
    Упрощенная версия - использует кастомные коэффициенты напрямую.
    """
    from core.z_score import calculate_z_scores
    from utils.calculations import (
        calculate_total_z,
        calculate_category_z,
        calculate_raw_stats,
        select_top_n_players
    )
    
    # Если кастомные коэффициенты не переданы, используем текущие
    if not request.custom_coefficients:
        custom_coeffs = load_weighted_coefficients()
    else:
        custom_coeffs = {
            '2026_total': request.custom_coefficients.get('2026_total', 0.40),
            '2026_last_30': request.custom_coefficients.get('2026_last_30', 0.30),
            '2026_last_15': request.custom_coefficients.get('2026_last_15', 0.20),
            '2026_last_7': request.custom_coefficients.get('2026_last_7', 0.10)
        }
    
    # Определяем exclude_ir
    exclude_ir = (request.simulation_mode == "exclude_ir")
    
    # Получаем статистику всех игроков с кастомными коэффициентами
    # Для этого получаем статистику за все 4 периода и применяем коэффициенты
    all_players_with_custom_stats = []
    
    # Получаем статистику за все периоды
    periods_data = {}
    for period_key in ['2026_total', '2026_last_30', '2026_last_15', '2026_last_7']:
        players_data = league_meta.get_all_players_stats(period_key, 'avg', exclude_ir=exclude_ir)
        periods_data[period_key] = {p['name']: p['stats'] for p in players_data}
    
    # Получаем список всех игроков
    all_players = league_meta.get_all_players_stats('2026_total', 'avg', exclude_ir=exclude_ir)
    
    # Применяем взвешенные коэффициенты для каждого игрока
    for player_info in all_players:
        player_name = player_info['name']
        weighted_stats = {}
        
        # Для процентных категорий нужны исходные данные
        percentage_components = {
            'FG%': ('FGM', 'FGA'),
            'FT%': ('FTM', 'FTA'),
            '3PT%': ('3PM', '3PA'),
            'A/TO': ('AST', 'TO')
        }
        
        pct_sums = {cat: {'num': 0.0, 'denom': 0.0} for cat in percentage_components}
        
        # Собираем все ключи статистики
        all_keys = set()
        for period_key in periods_data:
            if player_name in periods_data[period_key]:
                all_keys.update(periods_data[period_key][player_name].keys())
        
        # Применяем взвешивание
        for key in all_keys:
            if key in percentage_components:
                continue  # Процентные обработаем отдельно
            
            weighted_sum = 0.0
            for period_key, weight in custom_coeffs.items():
                if period_key in periods_data and player_name in periods_data[period_key]:
                    val = periods_data[period_key][player_name].get(key, 0.0)
                    if isinstance(val, (int, float)):
                        weighted_sum += val * weight
            
            weighted_stats[key] = weighted_sum
            
            # Собираем данные для процентных категорий
            for pct_cat, (num_key, denom_key) in percentage_components.items():
                if key == num_key or key == denom_key:
                    for period_key, weight in custom_coeffs.items():
                        if period_key in periods_data and player_name in periods_data[period_key]:
                            val = periods_data[period_key][player_name].get(key, 0.0)
                            if isinstance(val, (int, float)):
                                if key == num_key:
                                    pct_sums[pct_cat]['num'] += val * weight
                                else:
                                    pct_sums[pct_cat]['denom'] += val * weight
        
        # Рассчитываем проценты
        for pct_cat, sums in pct_sums.items():
            if sums['denom'] > 0:
                weighted_stats[pct_cat] = sums['num'] / sums['denom']
            else:
                weighted_stats[pct_cat] = 0.0
        
        all_players_with_custom_stats.append({
            'name': player_name,
            'position': player_info['position'],
            'team_id': player_info['team_id'],
            'team_name': player_info['team_name'],
            'stats': weighted_stats
        })
    
    # Теперь рассчитываем Z-scores на основе взвешенной статистики
    # Для этого нужно пересчитать метрики лиги
    from core.z_score import COUNTING_CATEGORIES, PERCENTAGE_CATEGORIES
    
    # Собираем данные для расчета метрик лиги
    counting_data = {cat: [] for cat in COUNTING_CATEGORIES}
    percentage_data = {
        'FG%': {'FGM': [], 'FGA': []},
        'FT%': {'FTM': [], 'FTA': []},
        '3PT%': {'3PM': [], '3PA': []},
        'A/TO': {'AST': [], 'TO': []}
    }
    
    for player in all_players_with_custom_stats:
        stats = player['stats']
        for cat in COUNTING_CATEGORIES:
            if cat in stats:
                counting_data[cat].append(stats[cat])
        
        if 'FGM' in stats and 'FGA' in stats:
            percentage_data['FG%']['FGM'].append(stats['FGM'])
            percentage_data['FG%']['FGA'].append(stats['FGA'])
        if 'FTM' in stats and 'FTA' in stats:
            percentage_data['FT%']['FTM'].append(stats['FTM'])
            percentage_data['FT%']['FTA'].append(stats['FTA'])
        if '3PM' in stats and '3PA' in stats:
            percentage_data['3PT%']['3PM'].append(stats['3PM'])
            percentage_data['3PT%']['3PA'].append(stats['3PA'])
        if 'AST' in stats and 'TO' in stats:
            percentage_data['A/TO']['AST'].append(stats['AST'])
            percentage_data['A/TO']['TO'].append(stats['TO'])
    
    # Рассчитываем метрики лиги
    league_metrics = {}
    import math
    
    for cat in COUNTING_CATEGORIES:
        if counting_data[cat]:
            mean = sum(counting_data[cat]) / len(counting_data[cat])
            variance = sum((x - mean) ** 2 for x in counting_data[cat]) / len(counting_data[cat])
            std = math.sqrt(variance) if variance > 0 else 0.0001
            league_metrics[cat] = {'mean': mean, 'std': std}
    
    # Weighted averages для процентных категорий
    weighted_averages = {}
    if percentage_data['FG%']['FGM'] and percentage_data['FG%']['FGA']:
        total_fgm = sum(percentage_data['FG%']['FGM'])
        total_fga = sum(percentage_data['FG%']['FGA'])
        weighted_averages['FG%'] = total_fgm / total_fga if total_fga > 0 else 0
    
    if percentage_data['FT%']['FTM'] and percentage_data['FT%']['FTA']:
        total_ftm = sum(percentage_data['FT%']['FTM'])
        total_fta = sum(percentage_data['FT%']['FTA'])
        weighted_averages['FT%'] = total_ftm / total_fta if total_fta > 0 else 0
    
    if percentage_data['3PT%']['3PM'] and percentage_data['3PT%']['3PA']:
        total_3pm = sum(percentage_data['3PT%']['3PM'])
        total_3pa = sum(percentage_data['3PT%']['3PA'])
        weighted_averages['3PT%'] = total_3pm / total_3pa if total_3pa > 0 else 0
    
    if percentage_data['A/TO']['AST'] and percentage_data['A/TO']['TO']:
        total_ast = sum(percentage_data['A/TO']['AST'])
        total_to = sum(percentage_data['A/TO']['TO'])
        weighted_averages['A/TO'] = total_ast / total_to if total_to > 0 else 0
    
    # Рассчитываем impact для процентных категорий
    impact_data = {cat: [] for cat in PERCENTAGE_CATEGORIES}
    
    for player in all_players_with_custom_stats:
        stats = player['stats']
        
        if 'FG%' in stats and 'FGA' in stats and 'FG%' in weighted_averages:
            fg_pct = stats['FG%']
            fga = stats['FGA']
            fg_avg = weighted_averages['FG%']
            impact = (fg_pct - fg_avg) * fga
            impact_data['FG%'].append(impact)
        
        if 'FT%' in stats and 'FTA' in stats and 'FT%' in weighted_averages:
            ft_pct = stats['FT%']
            fta = stats['FTA']
            ft_avg = weighted_averages['FT%']
            impact = (ft_pct - ft_avg) * fta
            impact_data['FT%'].append(impact)
        
        if '3PT%' in stats and '3PA' in stats and '3PT%' in weighted_averages:
            three_pct = stats['3PT%']
            three_pa = stats['3PA']
            three_avg = weighted_averages['3PT%']
            impact = (three_pct - three_avg) * three_pa
            impact_data['3PT%'].append(impact)
        
        if 'AST' in stats and 'TO' in stats and 'A/TO' in weighted_averages:
            ast = stats['AST']
            to = stats['TO']
            a_to_avg = weighted_averages['A/TO']
            impact = ast - to * a_to_avg
            impact_data['A/TO'].append(impact)
    
    # Рассчитываем метрики для процентных категорий
    for cat in PERCENTAGE_CATEGORIES:
        if impact_data[cat]:
            impact_mean = sum(impact_data[cat]) / len(impact_data[cat])
            variance = sum((x - impact_mean) ** 2 for x in impact_data[cat]) / len(impact_data[cat])
            impact_std = math.sqrt(variance) if variance > 0 else 0.0001
            league_metrics[cat] = {
                'weighted_avg': weighted_averages.get(cat, 0),
                'impact_mean': impact_mean,
                'impact_std': impact_std
            }
    
    # Рассчитываем Z-scores для всех игроков
    players_with_z_scores = []
    
    for player in all_players_with_custom_stats:
        stats = player['stats']
        z_scores = {}
        
        # Z-scores для счетных категорий
        for cat in COUNTING_CATEGORIES:
            if cat in stats and cat in league_metrics:
                value = stats[cat]
                mean = league_metrics[cat]['mean']
                std = league_metrics[cat]['std']
                z_score = (value - mean) / std if std > 0 else 0
                z_scores[cat] = z_score
        
        # Z-scores для процентных категорий
        if 'FG%' in stats and 'FGA' in stats and 'FG%' in league_metrics:
            fg_pct = stats['FG%']
            fga = stats['FGA']
            fg_avg = league_metrics['FG%']['weighted_avg']
            impact = (fg_pct - fg_avg) * fga
            impact_mean = league_metrics['FG%']['impact_mean']
            impact_std = league_metrics['FG%']['impact_std']
            z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
            z_scores['FG%'] = z_score
        
        if 'FT%' in stats and 'FTA' in stats and 'FT%' in league_metrics:
            ft_pct = stats['FT%']
            fta = stats['FTA']
            ft_avg = league_metrics['FT%']['weighted_avg']
            impact = (ft_pct - ft_avg) * fta
            impact_mean = league_metrics['FT%']['impact_mean']
            impact_std = league_metrics['FT%']['impact_std']
            z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
            z_scores['FT%'] = z_score
        
        if '3PT%' in stats and '3PA' in stats and '3PT%' in league_metrics:
            three_pct = stats['3PT%']
            three_pa = stats['3PA']
            three_avg = league_metrics['3PT%']['weighted_avg']
            impact = (three_pct - three_avg) * three_pa
            impact_mean = league_metrics['3PT%']['impact_mean']
            impact_std = league_metrics['3PT%']['impact_std']
            z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
            z_scores['3PT%'] = z_score
        
        if 'AST' in stats and 'TO' in stats and 'A/TO' in league_metrics:
            ast = stats['AST']
            to = stats['TO']
            a_to_avg = league_metrics['A/TO']['weighted_avg']
            impact = ast - to * a_to_avg
            impact_mean = league_metrics['A/TO']['impact_mean']
            impact_std = league_metrics['A/TO']['impact_std']
            z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
            z_scores['A/TO'] = z_score
        
        players_with_z_scores.append({
            'name': player['name'],
            'position': player['position'],
            'team_id': player['team_id'],
            'team_name': player['team_name'],
            'z_scores': z_scores,
            'stats': stats
        })
    
    # Теперь анализируем трейд (упрощенная версия)
    z_scores_by_name = {p['name']: p['z_scores'] for p in players_with_z_scores}
    
    # Фильтруем игроков по командам
    my_team_players = [p for p in players_with_z_scores if p['team_id'] == request.my_team_id]
    their_team_players = [p for p in players_with_z_scores if p['team_id'] == request.their_team_id]
    
    # Применяем режим top_n если нужно
    if request.simulation_mode == "top_n":
        my_team_players = select_top_n_players(
            my_team_players,
            request.top_n_players,
            punt_categories=request.punt_categories,
            z_scores_data=z_scores_by_name
        )
        their_team_players = select_top_n_players(
            their_team_players,
            request.top_n_players,
            punt_categories=request.punt_categories,
            z_scores_data=z_scores_by_name
        )
    
    # Расчет "До трейда"
    my_before_z = calculate_total_z(my_team_players, request.punt_categories)
    their_before_z = calculate_total_z(their_team_players, request.punt_categories)
    
    # Находим игроков для обмена
    players_i_give = [p for p in my_team_players if p['name'] in request.i_give]
    players_i_receive = [p for p in their_team_players if p['name'] in request.i_receive]
    
    # Расчет "После трейда"
    my_after_players = [p for p in my_team_players if p['name'] not in request.i_give] + players_i_receive
    their_after_players = [p for p in their_team_players if p['name'] not in request.i_receive] + players_i_give
    
    # Применяем top_n после трейда
    if request.simulation_mode == "top_n":
        my_after_players = select_top_n_players(
            my_after_players,
            request.top_n_players,
            punt_categories=request.punt_categories,
            z_scores_data=z_scores_by_name
        )
        their_after_players = select_top_n_players(
            their_after_players,
            request.top_n_players,
            punt_categories=request.punt_categories,
            z_scores_data=z_scores_by_name
        )
    
    my_after_z = calculate_total_z(my_after_players, request.punt_categories)
    their_after_z = calculate_total_z(their_after_players, request.punt_categories)
    
    # Delta
    my_delta = my_after_z - my_before_z
    their_delta = their_after_z - their_before_z
    
    # Рассчитываем симуляцию по avg
    # Создаем списки всех игроков лиги до и после трейда
    all_players_before = players_with_z_scores.copy()
    
    # Получаем имена команд
    my_team_name = None
    their_team_name = None
    for player in players_with_z_scores:
        if player['team_id'] == request.my_team_id and not my_team_name:
            my_team_name = player['team_name']
        if player['team_id'] == request.their_team_id and not their_team_name:
            their_team_name = player['team_name']
    
    # Создаем список игроков после трейда
    all_players_after = []
    for player in players_with_z_scores:
        player_copy = player.copy()
        
        # Если это игрок, которого я отдаю - переводим в их команду
        if player['team_id'] == request.my_team_id and player['name'] in request.i_give:
            player_copy['team_id'] = request.their_team_id
            player_copy['team_name'] = their_team_name
            all_players_after.append(player_copy)
        # Если это игрок, которого я получаю - переводим в мою команду
        elif player['team_id'] == request.their_team_id and player['name'] in request.i_receive:
            player_copy['team_id'] = request.my_team_id
            player_copy['team_name'] = my_team_name
            all_players_after.append(player_copy)
        # Все остальные игроки остаются как есть
        else:
            all_players_after.append(player_copy)
    
    # Временно переопределяем get_all_players_stats для использования кастомных коэффициентов
    original_get_all_stats = league_meta.get_all_players_stats
    
    def get_all_players_stats_wrapper(period, stats_type='avg', exclude_ir=False, custom_weighted_coeffs=None):
        if period == '2026_weighted':
            return original_get_all_stats(period, stats_type, exclude_ir, custom_weighted_coeffs=custom_coeffs)
        return original_get_all_stats(period, stats_type, exclude_ir, custom_weighted_coeffs)
    
    league_meta.get_all_players_stats = get_all_players_stats_wrapper
    
    try:
        # Рассчитываем симуляцию по avg
        from utils.calculations import calculate_simulation_ranks
        
        ranks_before_avg = calculate_simulation_ranks(
            all_players_before, 'team_stats_avg', league_meta, request.period, request.simulation_mode, [],
            request.top_n_players, None
        )
        ranks_after_avg = calculate_simulation_ranks(
            all_players_after, 'team_stats_avg', league_meta, request.period, request.simulation_mode, [],
            request.top_n_players, None
        )
        
        # Формируем данные о местах
        simulation_ranks_avg = {
            'my_team': {
                'before': ranks_before_avg.get(request.my_team_id, None),
                'after': ranks_after_avg.get(request.my_team_id, None),
                'delta': (ranks_after_avg.get(request.my_team_id, 0) - ranks_before_avg.get(request.my_team_id, 0)) if (request.my_team_id in ranks_after_avg and request.my_team_id in ranks_before_avg) else None
            },
            'their_team': {
                'before': ranks_before_avg.get(request.their_team_id, None),
                'after': ranks_after_avg.get(request.their_team_id, None),
                'delta': (ranks_after_avg.get(request.their_team_id, 0) - ranks_before_avg.get(request.their_team_id, 0)) if (request.their_team_id in ranks_after_avg and request.their_team_id in ranks_before_avg) else None
            }
        }
    except Exception as e:
        print(f"Error calculating simulation ranks: {e}")
        import traceback
        traceback.print_exc()
        simulation_ranks_avg = None
    finally:
        # Восстанавливаем оригинальный метод
        league_meta.get_all_players_stats = original_get_all_stats
    
    return {
        "my_team": {
            "before": round(my_before_z, 2),
            "after": round(my_after_z, 2),
            "delta": round(my_delta, 2)
        },
        "their_team": {
            "before": round(their_before_z, 2),
            "after": round(their_after_z, 2),
            "delta": round(their_delta, 2)
        },
        "simulation_avg": simulation_ranks_avg,
        "custom_coefficients_used": custom_coeffs,
        "both_positive": my_delta > 0 and their_delta > 0
    }


@router.post("/trade-optimization/auto-search")
def auto_search_optimal_coefficients(
    request: TradeAutoSearchRequest,
    league_meta=Depends(get_league_meta)
):
    """
    Автоматически ищет оптимальные коэффициенты, при которых трейд выгоден обеим командам.
    Использует grid search с заданным шагом.
    """
    # Генерируем все возможные комбинации коэффициентов
    # total, last_30, last_15, last_7 - сумма должна быть = 1.0
    
    results = []
    step = request.step
    
    # Перебираем все возможные комбинации без ограничений
    # total варьируется от 0.0 до 1.0 с шагом step
    for total in [round(x, 1) for x in [i * step for i in range(int(1.0 / step) + 1)]]:
        if total > 1.0:
            continue
        remaining = 1.0 - total
        
        # last_30 варьируется от 0.0 до remaining с шагом step
        for last_30 in [round(x, 1) for x in [i * step for i in range(int(remaining / step) + 1)]]:
            if last_30 > remaining:
                continue
            remaining_2 = remaining - last_30
            
            # last_15 варьируется от 0.0 до remaining_2 с шагом step
            for last_15 in [round(x, 1) for x in [i * step for i in range(int(remaining_2 / step) + 1)]]:
                if last_15 > remaining_2:
                    continue
                last_7 = round(remaining_2 - last_15, 1)
                
                # Проверяем, что last_7 >= 0
                if last_7 < 0:
                    continue
                
                # Проверяем, что сумма = 1.0 (с учетом округления)
                if abs(total + last_30 + last_15 + last_7 - 1.0) > 0.01:
                    continue
                
                # Анализируем трейд с этими коэффициентами
                custom_coeffs = {
                    '2026_total': total,
                    '2026_last_30': last_30,
                    '2026_last_15': last_15,
                    '2026_last_7': last_7
                }
                
                try:
                    optimization_request = TradeOptimizationRequest(
                        my_team_id=request.my_team_id,
                        their_team_id=request.their_team_id,
                        i_give=request.i_give,
                        i_receive=request.i_receive,
                        custom_coefficients=custom_coeffs,
                        period=request.period,
                        punt_categories=request.punt_categories,
                        simulation_mode=request.simulation_mode,
                        top_n_players=request.top_n_players
                    )
                    
                    result = analyze_trade_with_custom_coefficients(optimization_request, league_meta)
                    
                    # Проверяем, выгоден ли трейд обеим командам по симуляции avg
                    both_positive_avg = False
                    if result.get('simulation_avg'):
                        sim_avg = result['simulation_avg']
                        both_positive_avg = (
                            sim_avg.get('my_team', {}).get('delta') is not None and
                            sim_avg.get('their_team', {}).get('delta') is not None and
                            sim_avg['my_team']['delta'] <= 0 and  # Улучшение места (меньше = лучше)
                            sim_avg['their_team']['delta'] <= 0
                        )
                    
                    # Проверяем, выгоден ли трейд обеим командам по Z-score
                    both_positive_z = (
                        result['my_team']['delta'] > 0 and
                        result['their_team']['delta'] > 0
                    )
                    
                    # Добавляем все результаты (будем сортировать по улучшению первой команды)
                    results.append({
                        'coefficients': {
                            'total': total,
                            'last_30': last_30,
                            'last_15': last_15,
                            'last_7': last_7
                        },
                        'my_delta': result['my_team']['delta'],
                        'their_delta': result['their_team']['delta'],
                        'total_delta': result['my_team']['delta'] + result['their_team']['delta'],
                        'simulation_avg': result.get('simulation_avg'),
                        'both_positive_avg': both_positive_avg,
                        'both_positive_z': both_positive_z
                    })
                except Exception as e:
                    # Пропускаем ошибки при анализе
                    print(f"Error analyzing with coeffs {custom_coeffs}: {e}")
                    continue
    
    # Сортируем результаты в зависимости от режима поиска
    if request.search_mode == 'z_score':
        # Сортируем по Z-score: сначала те, где моя команда улучшилась (my_delta > 0), потом по величине улучшения
        results.sort(key=lambda x: (
            x.get('my_delta', 0) <= 0,  # Сначала те, где моя команда улучшилась (my_delta > 0)
            -x.get('my_delta', 0)  # Потом по величине улучшения (больше = лучше)
        ), reverse=False)
    else:
        # Сортируем по симуляции avg: чем меньше delta (или больше отрицательное значение), тем лучше (меньше место = лучше)
        results.sort(key=lambda x: (
            x.get('simulation_avg', {}).get('my_team', {}).get('delta') is None,  # Сначала те, где есть данные
            x.get('simulation_avg', {}).get('my_team', {}).get('delta', 999)  # Потом по delta (меньше = лучше)
        ))
    
    return {
        "found": len(results),
        "results": results[:50],  # Возвращаем топ-50 результатов
        "best": results[0] if results else None
    }
