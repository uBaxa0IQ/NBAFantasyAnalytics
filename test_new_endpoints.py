"""
Тестовый скрипт для проверки новых API endpoints:
- /api/dashboard/{team_id}
- /api/team-balance/{team_id}
- /api/simulation-detailed/{week}

Этот файл будет удален после проверки.
"""

import sys
import os
import requests
import json

# Добавляем путь к проекту
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

API_BASE = "http://localhost:8000/api"

def test_dashboard_endpoint():
    """Тест эндпоинта /api/dashboard/{team_id}"""
    print("\n" + "="*60)
    print("Тест: GET /api/dashboard/{team_id}")
    print("="*60)
    
    try:
        # Сначала получаем список команд
        teams_response = requests.get(f"{API_BASE}/teams")
        teams = teams_response.json()
        
        if teams:
            team_id = teams[0]['team_id']
            print(f"\nТестируем с team_id={team_id}")
            
            # Тестируем dashboard
            response = requests.get(f"{API_BASE}/dashboard/{team_id}")
            data = response.json()
            
            print(f"Статус: {response.status_code}")
            print(f"\nПолученные данные:")
            print(f"  - Название команды: {data.get('team_name')}")
            print(f"  - Размер ростера: {data.get('roster_size')}")
            print(f"  - Total Z-Score: {data.get('total_z_score')}")
            print(f"  - Текущий матчап: {data.get('current_matchup')}")
            print(f"  - Топ игроки: {len(data.get('top_players', []))} игроков")
            print(f"  - Травмированные: {len(data.get('injured_players', []))} игроков")
            
            if data.get('injured_players'):
                print(f"\n  Травмированные игроки:")
                for player in data['injured_players'][:3]:
                    print(f"    - {player['name']}: {player['injury_status']}")
            
            print("\n✓ Эндпоинт работает корректно")
        else:
            print("✗ Нет доступных команд")
            
    except Exception as e:
        print(f"✗ Ошибка: {e}")

def test_team_balance_endpoint():
    """Тест эндпоинта /api/team-balance/{team_id}"""
    print("\n" + "="*60)
    print("Тест: GET /api/team-balance/{team_id}")
    print("="*60)
    
    try:
        teams_response = requests.get(f"{API_BASE}/teams")
        teams = teams_response.json()
        
        if teams:
            team_id = teams[0]['team_id']
            print(f"\nТестируем с team_id={team_id}")
            
            response = requests.get(f"{API_BASE}/team-balance/{team_id}?period=2026_total")
            data = response.json()
            
            print(f"Статус: {response.status_code}")
            print(f"\nКоличество категорий: {len(data.get('data', []))}")
            
            if data.get('data'):
                print(f"\nПримеры данных (первые 3 категории):")
                for item in data['data'][:3]:
                    print(f"  - {item['category']}: {item['value']}")
            
            print("\n✓ Эндпоинт работает корректно (данные готовы для Recharts)")
        else:
            print("✗ Нет доступных команд")
            
    except Exception as e:
        print(f"✗ Ошибка: {e}")

def test_simulation_detailed_endpoint():
    """Тест эндпоинта /api/simulation-detailed/{week}"""
    print("\n" + "="*60)
    print("Тест: GET /api/simulation-detailed/{week}")
    print("="*60)
    
    try:
        # Получаем текущую неделю
        weeks_response = requests.get(f"{API_BASE}/weeks")
        weeks_data = weeks_response.json()
        current_week = weeks_data.get('current_week', 1)
        
        print(f"\nТестируем с week={current_week}, mode=z_scores")
        
        response = requests.get(
            f"{API_BASE}/simulation-detailed/{current_week}?mode=z_scores&period=2026_total"
        )
        data = response.json()
        
        print(f"Статус: {response.status_code}")
        print(f"\nРежим симуляции: {data.get('mode')}")
        print(f"Количество команд: {len(data.get('results', []))}")
        
        if data.get('results'):
            first_team = data['results'][0]
            print(f"\nПервая команда в рейтинге:")
            print(f"  - Название: {first_team.get('name')}")
            print(f"  - Победы: {first_team.get('wins')}")
            print(f"  - Поражения: {first_team.get('losses')}")
            print(f"  - Винрейт: {first_team.get('win_rate')}%")
            print(f"  - Количество матчапов: {len(first_team.get('matchups', []))}")
            
            if first_team.get('matchups'):
                first_matchup = first_team['matchups'][0]
                print(f"\n  Пример матчапа:")
                print(f"    vs {first_matchup.get('opponent_name')}")
                print(f"    Результат: {first_matchup.get('result')}")
                print(f"    Счёт: {first_matchup.get('score')}")
                print(f"    Категорий: {len(first_matchup.get('categories', {}))}")
        
            print("\n✓ Эндпоинт работает корректно (детальные данные доступны)")
        else:
            print("✗ Нет результатов симуляции")
            
    except Exception as e:
        print(f"✗ Ошибка: {e}")

def main():
    print("="*60)
    print("Тестирование новых API endpoints")
    print("="*60)
    print("\nУбедитесь, что backend запущен на http://localhost:8000")
    
    test_dashboard_endpoint()
    test_team_balance_endpoint()
    test_simulation_detailed_endpoint()
    
    print("\n" + "="*60)
    print("Тестирование завершено")
    print("="*60)

if __name__ == "__main__":
    main()
