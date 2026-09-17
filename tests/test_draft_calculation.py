from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest

from web.backend.services.draft_calculation import (
    DraftCalculationCoordinator,
    StaleDraftCalculation,
)


def test_identical_draft_calculations_are_single_flight():
    coordinator = DraftCalculationCoordinator()
    started = Event()
    release = Event()
    calls = 0
    calls_lock = Lock()

    def operation(cancel_check):
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        release.wait(timeout=2)
        cancel_check()
        return {"revision": 10}

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(coordinator.run_latest, (1, 1, 1), (10,), operation)
        assert started.wait(timeout=2)
        second = executor.submit(coordinator.run_latest, (1, 1, 1), (10,), operation)
        release.set()

    assert first.result() == {"revision": 10}
    assert second.result() == {"revision": 10}
    assert calls == 1


def test_new_revision_cancels_older_draft_calculation():
    coordinator = DraftCalculationCoordinator()
    old_started = Event()
    allow_old_check = Event()

    def old_operation(cancel_check):
        old_started.set()
        allow_old_check.wait(timeout=2)
        cancel_check()
        return {"revision": 10}

    with ThreadPoolExecutor(max_workers=2) as executor:
        old = executor.submit(coordinator.run_latest, (1, 1, 1), (10,), old_operation)
        assert old_started.wait(timeout=2)
        fresh = executor.submit(
            coordinator.run_latest,
            (1, 1, 1),
            (20,),
            lambda cancel_check: {"revision": 20},
        )
        assert fresh.result() == {"revision": 20}
        allow_old_check.set()
        with pytest.raises(StaleDraftCalculation):
            old.result()
