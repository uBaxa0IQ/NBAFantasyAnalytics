from types import SimpleNamespace

import pytest
import requests

from core.espn_transport import BoundedEspnRequests


@pytest.mark.parametrize('method', ['league_get', 'get', 'news_get'])
def test_all_espn_reads_have_finite_timeout(monkeypatch, method):
    calls = []

    def read(url, **kwargs):
        calls.append(kwargs)
        raise requests.ReadTimeout('offline')

    monkeypatch.setattr('core.espn_transport.requests.get', read)
    client = BoundedEspnRequests('nba', 2027, 123)
    with pytest.raises(requests.ReadTimeout):
        getattr(client, method)()
    assert calls[0]['timeout'] == (5, 10)


def test_alternate_endpoint_is_bounded_and_preserves_response(monkeypatch):
    responses = iter([
        SimpleNamespace(status_code=401),
        SimpleNamespace(status_code=200, json=lambda: [{'teams': []}]),
    ])
    calls = []

    def read(url, **kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr('core.espn_transport.requests.get', read)
    assert BoundedEspnRequests('nba', 2027, 123).league_get() == {'teams': []}
    assert [call['timeout'] for call in calls] == [(5, 10), (5, 10)]
