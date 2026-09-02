"""Хранение коэффициентов универсального статистического периода."""

import json
from pathlib import Path
from typing import Dict

from .config import PERIODS, WEIGHTED_PERIOD_COEFFS


COEFFICIENTS_FILE = Path(__file__).parent.parent / "web" / "core" / "weighted_coefficients.json"


def load_weighted_coefficients() -> Dict[str, float]:
    """Возвращает коэффициенты в формате ключей периодов ESPN."""
    try:
        with COEFFICIENTS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return {
            PERIODS["total"]: float(data["total"]),
            PERIODS["last_30"]: float(data["last_30"]),
            PERIODS["last_15"]: float(data["last_15"]),
            PERIODS["last_7"]: float(data["last_7"]),
        }
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return WEIGHTED_PERIOD_COEFFS.copy()


def save_weighted_coefficients(coefficients: Dict[str, float]) -> None:
    """Сохраняет проверенные коэффициенты в пользовательском JSON-файле."""
    COEFFICIENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "total": float(coefficients[PERIODS["total"]]),
        "last_30": float(coefficients[PERIODS["last_30"]]),
        "last_15": float(coefficients[PERIODS["last_15"]]),
        "last_7": float(coefficients[PERIODS["last_7"]]),
    }
    with COEFFICIENTS_FILE.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")
