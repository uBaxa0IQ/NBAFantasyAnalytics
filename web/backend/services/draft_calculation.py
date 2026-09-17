"""Single-flight, latest-only coordination for live draft calculations."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Lock


class StaleDraftCalculation(RuntimeError):
    """Raised when a newer live-draft calculation supersedes this one."""


@dataclass(frozen=True)
class CalculationToken:
    coordinator: "DraftCalculationCoordinator"
    key: tuple
    generation: int

    def ensure_current(self):
        if not self.coordinator.is_current(self.key, self.generation):
            raise StaleDraftCalculation("Расчёт отменён: уже запущен более свежий снимок драфта")


class DraftCalculationCoordinator:
    """Coalesce identical work and cancel older revisions for one team."""

    def __init__(self):
        self._lock = Lock()
        self._generation = {}
        self._running = {}
        self._cache = {}

    def is_current(self, key, generation):
        with self._lock:
            return self._generation.get(key) == generation

    def run_latest(self, key, request_key, operation):
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] == request_key:
                return cached[1]

            running = self._running.get(key)
            if running and running["request_key"] == request_key:
                owner = False
                entry = running
            else:
                generation = self._generation.get(key, 0) + 1
                self._generation[key] = generation
                entry = {
                    "request_key": request_key,
                    "generation": generation,
                    "event": Event(),
                    "result": None,
                    "error": None,
                }
                self._running[key] = entry
                owner = True

        if not owner:
            entry["event"].wait()
            if entry["error"] is not None:
                raise entry["error"]
            return entry["result"]

        token = CalculationToken(self, key, entry["generation"])
        try:
            result = operation(token.ensure_current)
            token.ensure_current()
            entry["result"] = result
            with self._lock:
                self._cache[key] = (request_key, result)
            return result
        except Exception as error:
            entry["error"] = error
            raise
        finally:
            with self._lock:
                if self._running.get(key) is entry:
                    self._running.pop(key, None)
            entry["event"].set()


draft_calculations = DraftCalculationCoordinator()
