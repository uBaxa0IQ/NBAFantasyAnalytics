import json
import pytest
from scripts import run_v74_resilient as recovery


def test_transient_access_denied_retries_without_losing_destination(tmp_path, monkeypatch):
    target = tmp_path / 'episode.json'
    target.write_text('{"old":true}')
    real_replace = recovery.os.replace
    calls = []
    def flaky(source, destination):
        calls.append(1)
        if len(calls) < 3:
            assert json.loads(target.read_text()) == {'old': True}
            raise PermissionError('simulated Windows sharing violation')
        real_replace(source, destination)
    monkeypatch.setattr(recovery.os, 'replace', flaky)
    monkeypatch.setattr(recovery.time, 'sleep', lambda _: None)
    recovery.resilient_json(target, {'new': True})
    assert len(calls) == 3
    assert json.loads(target.read_text()) == {'new': True}


def test_heartbeat_nonfatal_but_results_and_final_status_fail(tmp_path, monkeypatch):
    def locked(*args):
        raise PermissionError('locked')
    monkeypatch.setattr(recovery.os, 'replace', locked)
    monkeypatch.setattr(recovery.time, 'sleep', lambda _: None)
    recovery.resilient_json(tmp_path / 'status.json', {'phase': 'RUNNING'})
    for name, payload in [('episode.json', {'value': 1}), ('status.json', {'phase': 'COMPLETE_DIAGNOSTIC_ONLY'})]:
        with pytest.raises(PermissionError):
            recovery.resilient_json(tmp_path / name, payload)
