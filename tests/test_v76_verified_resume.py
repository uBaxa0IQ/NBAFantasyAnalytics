import pytest
from scripts import resume_v76_verified as recovery


def test_excluded_service_cannot_become_hidden_dependency():
    guard=recovery.DependencyGuard()
    for name in recovery.BLOCKED:
        with pytest.raises(ImportError,match='became an experiment dependency'):
            guard.find_spec(name)
    assert guard.find_spec('web.backend.services.draft_ml.v7_train') is None
