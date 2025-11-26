"""
Модуль для работы с метаданными лиги и свободными агентами.
Содержит методы получения информации о командах лиги и свободных агентах.
"""

from espn_api.basketball import League
from typing import List, Optional, Dict, Any
from .config import CATEGORIES





class LeagueMetadata:
    """Класс для работы с метаданными лиги и свободными агентами."""
    
    def __init__(self):
        """
        Инициализация класса для работы с метаданными лиги.
        """
        from .config import LEAGUE_ID, YEAR, ESPN_S2, SWID
        self.league_id = LEAGUE_ID
        self.year = YEAR
        self.espn_s2 = ESPN_S2
        self.swid = SWID
        self.league = None
        self.teams = []
    
    def connect_to_league(self) -> bool:
        """
        Подключение к лиге ESPN и получение метаданных команд.
        
        Returns:
            True если подключение успешно, False в противном случае
        """
        try:
            self.league = League(
                league_id=self.league_id,
                year=self.year,
                espn_s2=self.espn_s2,
                swid=self.swid
            )
            self.teams = self.league.teams
            return True
        except Exception as e:
            print(f"Ошибка подключения к лиге: {e}")
            return False
    
    def get_teams(self) -> List:
        """
        Получает список всех команд лиги.
        
        Returns:
            Список объектов команд лиги
        """
        if not self.teams and self.league:
            self.teams = self.league.teams
        return self.teams
    
    def get_team_by_id(self, team_id: int):
        """
        Получает команду по ID.
        
        Args:
            team_id: ID команды
            
        Returns:
            Объект команды или None если не найдена
        """
        if not self.teams:
            self.get_teams()
        
        return next((team for team in self.teams if team.team_id == team_id), None)
    
    def get_team_by_name(self, team_name: str):
        """
        Получает команду по названию.
        
        Args:
            team_name: Название команды
            
        Returns:
            Объект команды или None если не найдена
        """
        if not self.teams:
            self.get_teams()
        
        return next((team for team in self.teams if team.team_name == team_name), None)
    
    def get_teams_info(self) -> List[Dict[str, Any]]:
        """
        Получает информацию о всех командах лиги.
        
        Returns:
            Список словарей с информацией о командах:
            [{'team_id': int, 'team_name': str, 'roster_size': int}, ...]
        """
        if not self.teams:
            self.get_teams()
        
        teams_info = []
        for team in self.teams:
            roster_size = len(team.roster) if hasattr(team, 'roster') else 0
            teams_info.append({
                'team_id': team.team_id,
                'team_name': team.team_name,
                'roster_size': roster_size
            })
        
        return teams_info
    
    def get_free_agents(self, size: int = 200, position: Optional[str] = None) -> List:
        """
        Получает список свободных агентов.
        
        Args:
            size: Количество свободных агентов для получения (по умолчанию 200)
            position: Позиция для фильтрации (PG, SG, SF, PF, C) или None для всех
            
        Returns:
            Список объектов свободных агентов
        """
        if not self.league:
            if not self.connect_to_league():
                return []
        
        try:
            if position and position != "Все":
                return self.league.free_agents(size=size, position=position)
            else:
                return self.league.free_agents(size=size)
        except Exception as e:
            print(f"Ошибка получения свободных агентов: {e}")
            return []
    
    def get_team_roster(self, team_id: int) -> List:
        """
        Получает состав команды.
        
        Args:
            team_id: ID команды
            
        Returns:
            Список игроков команды
        """
        team = self.get_team_by_id(team_id)
        if not team:
            return []
        
        return team.roster if hasattr(team, 'roster') else []
    
    def get_player_stats(self, player, period: str, stats_type: str = 'total') -> Optional[Dict[str, Any]]:
        """
        Получает всю статистику игрока за указанный период из API (без фильтрации).
        
        Args:
            player: Объект игрока из ESPN API
            period: Период статистики:
                   - '2026_total' - за весь сезон
                   - '2026_last_30' - за последние 30 дней
                   - '2026_last_15' - за последние 15 дней
                   - '2026_last_7' - за последние 7 дней
                   - '2026_projected' - прогнозируемая
                   - номер недели (например, '35') - за конкретную неделю
            stats_type: Тип статистики - 'total' (общая) или 'avg' (средняя за игру)
            
        Returns:
            Словарь со всей статистикой из API или None если данные недоступны
        """
        if not hasattr(player, 'stats') or not player.stats:
            return None
        
        # Ищем статистику по указанному периоду
        period_data = player.stats.get(period)
        if not period_data or not isinstance(period_data, dict):
            return None
        
        # Получаем нужный тип статистики (total или avg)
        if stats_type == 'total':
            stats_data = period_data.get('total')
        elif stats_type == 'avg':
            stats_data = period_data.get('avg')
        else:
            return None
        
        if not stats_data or not isinstance(stats_data, dict):
            return None
        
        # Возвращаем все данные из API, преобразуя в float где возможно
        result = {}
        for key, value in stats_data.items():
            try:
                if value is not None:
                    result[key] = float(value)
                else:
                    result[key] = 0.0
            except (ValueError, TypeError):
                result[key] = value  # Оставляем как есть, если не число
        
        return result
    
    def filter_stats_by_categories(self, stats: Dict[str, Any], categories: List[str] = None) -> Dict[str, float]:
        """
        Фильтрует статистику по указанным категориям.
        
        Args:
            stats: Словарь со статистикой (все данные из API)
            categories: Список категорий для фильтрации. Если None, использует CATEGORIES из конфига.
            
        Returns:
            Словарь со статистикой только по указанным категориям
        """
        if categories is None:
            categories = CATEGORIES
        
        filtered = {}
        for category in categories:
            if category in stats:
                filtered[category] = stats[category]
            else:
                filtered[category] = 0.0
        
        return filtered
    
    def get_all_players_stats(self, period: str, stats_type: str = 'total') -> List[Dict[str, Any]]:
        """
        Получает статистику всех игроков всех команд за указанный период.
        
        Args:
            period: Период статистики:
                   - '2026_total' - за весь сезон
                   - '2026_last_30' - за последние 30 дней
                   - '2026_last_15' - за последние 15 дней
                   - '2026_last_7' - за последние 7 дней
                   - '2026_projected' - прогнозируемая
                   - номер недели (например, '35') - за конкретную неделю
            stats_type: Тип статистики - 'total' (общая) или 'avg' (средняя за игру)
            
        Returns:
            Список словарей с информацией об игроках:
            [{
                'name': str,
                'position': str,
                'team_id': int,
                'team_name': str,
                'stats': {вся статистика из API}
            }, ...]
        """
        if not self.teams:
            self.get_teams()
        
        all_players_stats = []
        
        for team in self.teams:
            roster = self.get_team_roster(team.team_id)
            
            for player in roster:
                stats = self.get_player_stats(player, period, stats_type)
                
                if stats:
                    player_data = {
                        'name': player.name,
                        'position': getattr(player, 'position', 'N/A'),
                        'team_id': team.team_id,
                        'team_name': team.team_name,
                        'stats': stats
                    }
                    all_players_stats.append(player_data)
        
        return all_players_stats
    
    def get_matchups_for_week(self, week: int) -> List[Dict[str, Any]]:
        """
        Получает все матчапы за указанную неделю с базовой информацией.
        
        Args:
            week: Номер недели матчапа
            
        Returns:
            Список словарей с информацией о матчапах:
            [{
                'week': int,
                'team1': str,
                'team2': str,
                'team1_id': int,
                'team2_id': int
            }, ...]
        """
        if not self.league:
            if not self.connect_to_league():
                return []
        
        try:
            box_scores = self.league.box_scores(matchup_period=week)
        except Exception as e:
            print(f"Ошибка получения матчапов за неделю {week}: {e}")
            return []
        
        if not box_scores:
            return []
        
        matchups = []
        for box in box_scores:
            matchup = {
                'week': week,
                'team1': box.home_team.team_name,
                'team2': box.away_team.team_name,
                'team1_id': box.home_team.team_id,
                'team2_id': box.away_team.team_id
            }
            matchups.append(matchup)
        
        return matchups
    
    def get_matchup_box_score(self, week: int, team_id: int) -> Optional[Dict[str, Any]]:
        """
        Получает Box Score команды за указанную неделю (матчап).
        
        Args:
            week: Номер недели матчапа
            team_id: ID команды
            
        Returns:
            Словарь с Box Score команды:
            {
                'week': int,
                'team_id': int,
                'team_name': str,
                'opponent_id': int,
                'opponent_name': str,
                'players': [
                    {
                        'name': str,
                        'position': str,
                        'stats': {вся статистика из API}
                    }, ...
                ],
                'totals': {вся статистика - суммарные значения команды}
            }
            или None если матчап не найден
        """
        if not self.league:
            if not self.connect_to_league():
                return None
        
        try:
            box_scores = self.league.box_scores(matchup_period=week)
        except Exception as e:
            print(f"Ошибка получения матчапов за неделю {week}: {e}")
            return None
        
        if not box_scores:
            return None
        
        # Ищем матчап команды
        matchup_box = None
        opponent_team = None
        lineup = None
        
        for box in box_scores:
            if box.home_team.team_id == team_id:
                matchup_box = box
                opponent_team = box.away_team
                lineup = box.home_lineup
                break
            elif box.away_team.team_id == team_id:
                matchup_box = box
                opponent_team = box.home_team
                lineup = box.away_lineup
                break
        
        if not matchup_box or not lineup:
            return None
        
        team = self.get_team_by_id(team_id)
        if not team:
            return None
        
        # Собираем статистику игроков
        # В матчапе статистика хранится под ключом '0', а не номером недели
        players_data = []
        matchup_stats_key = '0'
        
        # Для расчета TOTALS нужны исходные данные (FGM, FGA и т.д.)
        total_fgm = 0.0
        total_fga = 0.0
        total_ftm = 0.0
        total_fta = 0.0
        total_3pm = 0.0
        total_3pa = 0.0
        total_ast = 0.0
        total_to = 0.0
        
        for player in lineup:
            # Пропускаем игроков на IR
            if hasattr(player, 'slot_position') and player.slot_position == 'IR':
                continue
            
            # Получаем статистику игрока из матчапа (ключ '0')
            player_stats = self.get_player_stats(player, matchup_stats_key, 'total')
            
            if player_stats:
                # Получаем исходные данные для расчета TOTALS
                total_fgm += player_stats.get('FGM', 0)
                total_fga += player_stats.get('FGA', 0)
                total_ftm += player_stats.get('FTM', 0)
                total_fta += player_stats.get('FTA', 0)
                total_3pm += player_stats.get('3PM', 0)
                total_3pa += player_stats.get('3PA', 0)
                total_ast += player_stats.get('AST', 0)
                total_to += player_stats.get('TO', 0)
                
                player_data = {
                    'name': player.name,
                    'position': getattr(player, 'position', 'N/A'),
                    'stats': player_stats
                }
                players_data.append(player_data)
        
        # Рассчитываем TOTALS (суммарные значения команды)
        totals = {}
        
        # Простые категории - суммируем
        for player_data in players_data:
            stats = player_data['stats']
            for key, value in stats.items():
                if key in ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'TO', 'FGM', 'FGA', 'FTM', 'FTA', '3PA']:
                    totals[key] = totals.get(key, 0.0) + value
        
        # Рассчитываем проценты для TOTALS
        if total_fga > 0:
            totals['FG%'] = total_fgm / total_fga
        if total_fta > 0:
            totals['FT%'] = total_ftm / total_fta
        if total_3pa > 0:
            totals['3PT%'] = total_3pm / total_3pa
        if total_to > 0:
            totals['A/TO'] = total_ast / total_to
        
        return {
            'week': week,
            'team_id': team_id,
            'team_name': team.team_name,
            'opponent_id': opponent_team.team_id,
            'opponent_name': opponent_team.team_name,
            'players': players_data,
            'totals': totals
        }
    
    def get_matchup_summary(self, week: int, team1_id: int, team2_id: int) -> Optional[Dict[str, Any]]:
        """
        Получает сводку матчапа между двумя командами за указанную неделю.
        
        Args:
            week: Номер недели матчапа
            team1_id: ID первой команды
            team2_id: ID второй команды
            
        Returns:
            Словарь со сводкой матчапа:
            {
                'week': int,
                'team1': str,
                'team2': str,
                'team1_id': int,
                'team2_id': int,
                'team1_stats': {вся статистика из API},
                'team2_stats': {вся статистика из API},
                'team1_stats_filtered': {категории из конфига},
                'team2_stats_filtered': {категории из конфига},
                'category_results': {
                    'PTS': {'team1_value': float, 'team2_value': float, 'winner': 'team1'|'team2'|'tie'}, ...
                },
                'team1_wins': int,
                'team2_wins': int,
                'score': str (например, '6-5-0'),
                'winner': 'team1'|'team2'|'tie'
            }
            или None если матчап не найден
        """
        # Получаем Box Score обеих команд
        team1_box = self.get_matchup_box_score(week, team1_id)
        team2_box = self.get_matchup_box_score(week, team2_id)
        
        if not team1_box or not team2_box:
            return None
        
        # Проверяем, что команды играли друг против друга
        if (team1_box['opponent_id'] != team2_id) or (team2_box['opponent_id'] != team1_id):
            return None
        
        team1_stats = team1_box['totals']
        team2_stats = team2_box['totals']
        
        # Фильтруем статистику по категориям из конфига для сравнения
        team1_filtered = self.filter_stats_by_categories(team1_stats)
        team2_filtered = self.filter_stats_by_categories(team2_stats)
        
        # Сравниваем по категориям
        category_results = {}
        team1_wins = 0
        team2_wins = 0
        
        for category in CATEGORIES:
            team1_value = team1_filtered.get(category, 0.0)
            team2_value = team2_filtered.get(category, 0.0)
            
            # Определяем победителя категории
            if team1_value > team2_value:
                winner = 'team1'
                team1_wins += 1
            elif team2_value > team1_value:
                winner = 'team2'
                team2_wins += 1
            else:
                winner = 'tie'
            
            category_results[category] = {
                'team1_value': team1_value,
                'team2_value': team2_value,
                'winner': winner
            }
        
        # Определяем общего победителя матчапа
        if team1_wins > team2_wins:
            overall_winner = 'team1'
        elif team2_wins > team1_wins:
            overall_winner = 'team2'
        else:
            overall_winner = 'tie'
        
        ties = len(CATEGORIES) - team1_wins - team2_wins
        score = f"{team1_wins}-{team2_wins}-{ties}"
        
        return {
            'week': week,
            'team1': team1_box['team_name'],
            'team2': team2_box['team_name'],
            'team1_id': team1_id,
            'team2_id': team2_id,
            'team1_stats': team1_stats,
            'team2_stats': team2_stats,
            'team1_stats_filtered': team1_filtered,
            'team2_stats_filtered': team2_filtered,
            'category_results': category_results,
            'team1_wins': team1_wins,
            'team2_wins': team2_wins,
            'ties': ties,
            'score': score,
            'winner': overall_winner
        }

