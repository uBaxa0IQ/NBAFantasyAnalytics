"""Bound ESPN reads so an upstream outage cannot occupy API workers forever."""

import requests
from espn_api.requests.espn_requests import (
    EspnFantasyRequests, ESPNAccessDenied, ESPNInvalidLeague, ESPNUnknownError,
)


class BoundedEspnRequests(EspnFantasyRequests):
    timeout = (5, 10)

    def _read(self, endpoint, params=None, headers=None):
        return requests.get(endpoint, params=params, headers=headers,
                            cookies=self.cookies, timeout=self.timeout)

    def checkRequestStatus(self, status, extend="", params=None, headers=None):
        if status == 401:
            if "/leagueHistory/" in self.LEAGUE_ENDPOINT:
                base = self.LEAGUE_ENDPOINT.split("/leagueHistory/")[0]
                self.LEAGUE_ENDPOINT = f"{base}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
            else:
                base = self.LEAGUE_ENDPOINT.split(f"/seasons/{self.year}")[0]
                self.LEAGUE_ENDPOINT = f"{base}/leagueHistory/{self.league_id}?seasonId={self.year}"
            response = self._read(self.LEAGUE_ENDPOINT + extend, params, headers)
            if response.status_code == 200:
                return response.json()
            raise ESPNAccessDenied(f"League {self.league_id} cannot be accessed")
        if status == 404:
            raise ESPNInvalidLeague(f"League {self.league_id} does not exist")
        if status != 200:
            raise ESPNUnknownError(f"ESPN returned an HTTP {status}")
        return None

    def _get(self, endpoint, params=None, headers=None, extend=""):
        response = self._read(endpoint + extend, params, headers)
        alternate = self.checkRequestStatus(response.status_code, extend, params, headers)
        data = alternate if alternate is not None else response.json()
        if self.logger:
            self.logger.log_request(endpoint=endpoint + extend, params=params,
                                    headers=headers, response=data)
        return data

    def league_get(self, params=None, headers=None, extend=""):
        data = self._get(self.LEAGUE_ENDPOINT, params, headers, extend)
        return data[0] if isinstance(data, list) else data

    def get(self, params=None, headers=None, extend=""):
        return self._get(self.ENDPOINT, params, headers, extend)

    def news_get(self, params=None, headers=None, extend=""):
        return self._get(self.NEWS_ENDPOINT, params, headers, extend)
