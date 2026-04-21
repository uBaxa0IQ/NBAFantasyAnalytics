import json
from pathlib import Path
from typing import Dict, Any

def get_settings_file_path() -> Path:
    """Возвращает путь к файлу с настройками лиги."""
    # Путь относительно этого файла: web/backend/utils/settings.py -> web/core/league_settings.json
    return Path(__file__).parent.parent.parent / "core" / "league_settings.json"

def load_league_settings() -> Dict[str, Any]:
    """
    Загружает настройки лиги из JSON файла.
    Возвращает словарь с дефолтными значениями, если файл не существует или пуст.
    """
    settings_file = get_settings_file_path()
    
    default_settings = {
        "force_weighted_mode": False,
        "forced_period": "2026_weighted"
    }
    
    if settings_file.exists():
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Объединяем с дефолтными, чтобы гарантировать наличие всех ключей
                return {**default_settings, **data}
        except Exception as e:
            print(f"Error loading league settings: {e}")
            return default_settings
    
    return default_settings

def save_league_settings(settings: Dict[str, Any]) -> bool:
    """
    Сохраняет настройки лиги в JSON файл.
    """
    try:
        settings_file = get_settings_file_path()
        
        # Создаем директорию, если её нет
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Загружаем текущие настройки, чтобы не перезатереть неизвестные поля
        current_settings = load_league_settings()
        new_settings = {**current_settings, **settings}
        
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(new_settings, f, indent=2, ensure_ascii=False)
        
        return True
    except Exception as e:
        print(f"Error saving league settings: {e}")
        return False

