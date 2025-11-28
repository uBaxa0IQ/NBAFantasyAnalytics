"""
Утилита для оптимизации состава команды.
"""

from typing import List, Dict, Any, Optional
import math


# Слоты и их ограничения
POSITIONAL_SLOTS = ['PG', 'SG', 'SF', 'PF', 'C']
FLEXIBLE_SLOTS = ['G', 'F']
UTILITY_SLOTS = ['UT'] * 3  # 3 слота UT

PERCENTAGE_CATEGORIES = ['FG%', 'FT%', '3PT%']


def normalize_percentage_value(value: float) -> float:
    """Нормализует процентное значение к формату 0.0-1.0."""
    if value > 1.0:
        return value / 100.0
    return value


def calculate_matchup_bonus(
    player: Dict[str, Any],
    team_stats: Dict[str, float],
    opponent_stats: Dict[str, float],
    punt_categories: List[str],
    return_details: bool = False
) -> float:
    """
    Рассчитывает бонус игрока за матчап.
    
    Args:
        player: Игрок с z_scores
        team_stats: Статистика команды
        opponent_stats: Статистика соперника
        punt_categories: Список пант-категорий
        return_details: Если True, возвращает детализацию по категориям
    
    Returns:
        float или tuple: Бонус за матчап (и детализация, если return_details=True)
    """
    bonus = 0.0
    z_scores = player.get('z_scores', {})
    category_details = {}
    
    for category in z_scores.keys():
        if category in punt_categories:
            continue  # Игнорируем панты
        
        team_value = team_stats.get(category, 0.0)
        opponent_value = opponent_stats.get(category, 0.0)
        
        # Нормализуем процентные категории
        if category in PERCENTAGE_CATEGORIES:
            team_value = normalize_percentage_value(team_value)
            opponent_value = normalize_percentage_value(opponent_value)
        
        player_z = z_scores.get(category, 0.0)
        category_bonus = 0.0
        reason = ""
        
        if opponent_value > team_value:
            # ОТСТАЕМ - добавляем ценность
            if team_value > 0:
                diff_pct = (opponent_value - team_value) / team_value
                if diff_pct <= 0.20:  # Отстаем не более чем на 20%
                    category_bonus = player_z * (1.0 + diff_pct * 5)  # Бонус до 2.0x
                    bonus += category_bonus
                    reason = f"Отстаем на {diff_pct*100:.1f}%"
                else:
                    reason = f"Отстаем на {diff_pct*100:.1f}% (безнадежно)"
        
        elif team_value > opponent_value * 1.2:
            # СИЛЬНО ЛИДИРУЕМ (>20%) - уменьшаем ценность
            category_bonus = -player_z * 0.3  # Штраф
            bonus += category_bonus
            diff_pct = (team_value - opponent_value) / opponent_value
            reason = f"Лидируем на {diff_pct*100:.1f}%"
        else:
            reason = "Выигрываем или нейтрально"
        
        if return_details and (category_bonus != 0.0 or reason):
            category_details[category] = {
                'bonus': category_bonus,
                'z_score': player_z,
                'reason': reason,
                'team_value': team_value,
                'opponent_value': opponent_value
            }
    
    if return_details:
        return bonus, category_details
    return bonus


def calculate_player_value(
    player: Dict[str, Any],
    team_stats: Dict[str, float],
    opponent_stats: Dict[str, float],
    punt_categories: List[str]
) -> float:
    """
    Рассчитывает общую ценность игрока.
    
    Returns:
        float: Ценность игрока
    """
    # Базовый Z-score
    z_scores = player.get('z_scores', {})
    base_z = sum(z for z in z_scores.values() if math.isfinite(z))
    
    # Бонус за матчап (без детализации)
    matchup_bonus = calculate_matchup_bonus(
        player, team_stats, opponent_stats, punt_categories, return_details=False
    )
    
    return base_z + matchup_bonus


def can_fit_all_players(players: List[Dict[str, Any]]) -> bool:
    """
    Проверяет, можно ли разместить всех игроков в 10 стартовых слотов.
    Учитывает позиции игроков и ограничения слотов.
    Использует backtracking для перебора всех возможных вариантов.
    
    Args:
        players: Список игроков
    
    Returns:
        bool: True если всех можно разместить, False если нет
    """
    if len(players) > 10:
        return False
    
    if len(players) == 0:
        return True
    
    # Для каждого игрока находим все слоты, в которые он может играть
    player_slots = []
    for player in players:
        slots = []
        eligible_slots = player.get('eligibleSlots', [])
        position = player.get('position', '')
        
        # UT - любой может играть (3 слота)
        slots.append('UT')
        
        # Позиционные слоты
        for slot in ['PG', 'SG', 'SF', 'PF', 'C']:
            if slot in eligible_slots or position == slot:
                slots.append(slot)
        
        # Гибкие слоты
        if 'G' in eligible_slots or position in ['PG', 'SG']:
            slots.append('G')
        
        if 'F' in eligible_slots or position in ['SF', 'PF']:
            slots.append('F')
        
        if not slots:
            # Игрок не может играть ни в один слот
            return False
        
        player_slots.append(slots)
    
    # Пробуем разместить всех игроков (backtracking)
    def try_place_players(player_idx: int, used_slots: dict) -> bool:
        """Рекурсивная функция для размещения игроков с backtracking."""
        if player_idx >= len(players):
            return True  # Все игроки размещены
        
        slots = player_slots[player_idx]
        
        # Пробуем разместить игрока в каждый доступный слот
        for slot in slots:
            # Проверяем, доступен ли слот
            if slot == 'UT':
                # UT - проверяем, есть ли свободные UT слоты (3 слота)
                ut_count = used_slots.get('UT', 0)
                if ut_count < 3:
                    used_slots['UT'] = ut_count + 1
                    if try_place_players(player_idx + 1, used_slots):
                        return True
                    used_slots['UT'] = ut_count  # Backtrack
            else:
                # Обычный слот - проверяем, свободен ли
                if used_slots.get(slot, 0) == 0:
                    used_slots[slot] = 1
                    if try_place_players(player_idx + 1, used_slots):
                        return True
                    used_slots[slot] = 0  # Backtrack
        
        return False
    
    # Запускаем проверку
    used_slots = {}
    return try_place_players(0, used_slots)


def can_play_in_slot(player: Dict[str, Any], slot: str) -> bool:
    """
    Проверяет, может ли игрок играть в указанном слоте.
    
    Args:
        player: Игрок с eligibleSlots или position
        slot: Название слота (PG, SG, G, UT и т.д.)
    
    Returns:
        bool: Может ли играть в слоте
    """
    # UT - любой игрок может играть
    if slot == 'UT':
        return True
    
    # Получаем eligibleSlots или position
    eligible_slots = player.get('eligibleSlots', [])
    position = player.get('position', '')
    
    # Проверяем eligibleSlots
    if eligible_slots:
        if slot in eligible_slots:
            return True
    
    # Проверяем position
    if position:
        # Позиционные слоты
        if slot == position:
            return True
        
        # Гибкие слоты
        if slot == 'G' and position in ['PG', 'SG']:
            return True
        if slot == 'F' and position in ['SF', 'PF']:
            return True
    
    return False


def optimize_lineup(
    players: List[Dict[str, Any]],
    team_stats: Dict[str, float],
    opponent_stats: Dict[str, float],
    punt_categories: List[str] = None
) -> Dict[str, Any]:
    """
    Оптимизирует состав команды - сортирует игроков по ценности.
    
    Args:
        players: Список игроков команды (исключены IR и OUT)
        team_stats: Статистика команды
        opponent_stats: Статистика соперника
        punt_categories: Список пант-категорий
    
    Returns:
        {
            'players': [player],  # Отсортированные по ценности
            'total_players': int
        }
    """
    if punt_categories is None:
        punt_categories = []
    
    # Расчет ценности игроков
    players_with_value = []
    for player in players:
        base_z = sum(z for z in player.get('z_scores', {}).values() if math.isfinite(z))
        matchup_bonus, category_details = calculate_matchup_bonus(
            player, team_stats, opponent_stats, punt_categories, return_details=True
        )
        value = base_z + matchup_bonus
        
        players_with_value.append({
            'player': player,
            'value': value,
            'base_z': base_z,
            'matchup_bonus': matchup_bonus,
            'category_details': category_details
        })
    
    # Сортируем по ценности (от большего к меньшему)
    players_with_value.sort(key=lambda x: x['value'], reverse=True)
    
    # Формируем список игроков с информацией о ценности
    players_sorted = []
    for item in players_with_value:
        player = item['player']
        players_sorted.append({
            'name': player.get('name', ''),
            'position': player.get('position', ''),
            'value': item['value'],
            'base_z': item['base_z'],
            'matchup_bonus': item['matchup_bonus'],
            'category_details': item['category_details']
        })
    
    return {
        'players': players_sorted,
        'total_players': len(players)
    }

