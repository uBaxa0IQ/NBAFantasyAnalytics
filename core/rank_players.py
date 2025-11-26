"""
Простой скрипт для расчета Z-scores игроков и вывода топ игроков по суммарному показателю.
"""

from league_metadata import LeagueMetadata
from z_score import calculate_z_scores
from .config import LEAGUE_ID, YEAR, ESPN_S2, SWID, CATEGORIES



def main():
    print("Подключение к лиге...")
    league_meta = LeagueMetadata(LEAGUE_ID, YEAR, ESPN_S2, SWID)
    
    if not league_meta.connect_to_league():
        print("Ошибка подключения к лиге!")
        return
    
    # Выбор периода статистики
    periods = {
        '1': ('2026_total', 'За весь сезон'),
        '2': ('2026_last_30', 'За последние 30 дней'),
        '3': ('2026_last_15', 'За последние 15 дней'),
        '4': ('2026_last_7', 'За последние 7 дней'),
        '5': ('2026_projected', 'Прогнозируемая статистика')
    }
    
    print("\nДоступные периоды статистики:")
    for key, (_, description) in periods.items():
        print(f"{key} - {description}")
    
    try:
        period_choice = input("\nВыберите период (номер): ").strip()
        if period_choice not in periods:
            print("Неверный выбор! Используется период по умолчанию (весь сезон).")
            period = '2026_total'
            period_name = 'За весь сезон'
        else:
            period, period_name = periods[period_choice]
    except Exception:
        print("Ошибка ввода! Используется период по умолчанию (весь сезон).")
        period = '2026_total'
        period_name = 'За весь сезон'
    
    print(f"\nПолучение статистики игроков ({period_name})...")
    # Получаем Z-scores за выбранный период (avg статистика)
    z_scores_data = calculate_z_scores(league_meta, period)
    
    if not z_scores_data['players']:
        print("Не удалось получить данные игроков!")
        return
    
    # Получаем список команд для выбора
    teams = league_meta.get_teams()
    teams_info = league_meta.get_teams_info()
    
    print("\nДоступные команды:")
    print("0 - Все команды")
    for i, team_info in enumerate(teams_info, 1):
        print(f"{i} - {team_info['team_name']}")
    
    try:
        choice = input("\nВыберите команду (номер): ").strip()
        
        if choice == "0":
            selected_team_id = None
            selected_team_name = "Все команды"
        else:
            team_index = int(choice) - 1
            if team_index < 0 or team_index >= len(teams_info):
                print("Неверный выбор!")
                return
            selected_team_id = teams_info[team_index]['team_id']
            selected_team_name = teams_info[team_index]['team_name']
    except (ValueError, IndexError):
        print("Неверный выбор!")
        return
    
    # Рассчитываем суммарный Z-score для всех игроков лиги по всем 11 категориям
    all_players_with_total = []
    for player in z_scores_data['players']:
        z_scores = player['z_scores']
        # Суммируем только по категориям из конфига (11 категорий)
        total_z_score = sum(z_scores.get(cat, 0.0) for cat in CATEGORIES)
        all_players_with_total.append({
            **player,
            'total_z_score': total_z_score
        })
    
    # Фильтруем игроков по команде (если выбрана) для отображения
    players_with_total = all_players_with_total
    if selected_team_id:
        players_with_total = [p for p in all_players_with_total if p['team_id'] == selected_team_id]
    
    # Сортируем по суммарному Z-score (по убыванию)
    players_with_total.sort(key=lambda x: x['total_z_score'], reverse=True)
    
    # Выводим топ игроков
    print(f"\n{'='*80}")
    print(f"Топ игроков ({selected_team_name}) - {period_name}")
    print(f"{'='*80}")
    print(f"{'Ранг':<6} {'Игрок':<25} {'Команда':<20} {'Сумма Z-score':<15} {'Детали Z-scores'}")
    print(f"{'-'*80}")
    
    for rank, player in enumerate(players_with_total, 1):
        name = player['name'][:24]
        team_name = player['team_name'][:19]
        total = player['total_z_score']
        
        # Формируем строку с деталями Z-scores по всем 11 категориям
        z_details = []
        for cat in CATEGORIES:
            z_value = player['z_scores'].get(cat, 0.0)
            z_details.append(f"{cat}:{z_value:.2f}")
        details_str = ", ".join(z_details)
        
        print(f"{rank:<6} {name:<25} {team_name:<20} {total:<15.2f} {details_str}")
        
        # Ограничиваем вывод топ-20
        if rank >= 20:
            break
    
    # Рассчитываем средние Z-scores для всей лиги
    if all_players_with_total:
        # Средний суммарный Z-score по лиге
        avg_total_z_score = sum(p['total_z_score'] for p in all_players_with_total) / len(all_players_with_total)
        
        # Средние Z-scores по каждой категории по лиге
        avg_by_category = {}
        for cat in CATEGORIES:
            category_values = [p['z_scores'].get(cat, 0.0) for p in all_players_with_total]
            avg_by_category[cat] = sum(category_values) / len(category_values) if category_values else 0.0
        
        # Выводим статистику
        print(f"\n{'='*80}")
        print(f"Средние Z-scores по лиге ({period_name}, всего игроков: {len(all_players_with_total)})")
        print(f"{'='*80}")
        print(f"Средний суммарный Z-score: {avg_total_z_score:.2f}")
        print(f"\nСредние Z-scores по категориям:")
        for cat in CATEGORIES:
            print(f"  {cat:<6}: {avg_by_category[cat]:>8.2f}")


if __name__ == "__main__":
    main()

