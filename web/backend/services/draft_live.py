"""Single read-only ESPN live-draft event client with a persistent local cache."""

from __future__ import annotations

import base64
import copy
import json
import logging
import os
import struct
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from core.config import DEFAULT_TEAM_ID
from core.runtime_settings import get_draft_connection_mode


logger = logging.getLogger(__name__)


def _has_live_picks(state):
    return any(
        isinstance((pick or {}).get("player_id"), int) and pick.get("player_id") > 0
        for pick in (state or {}).get("picks") or []
    )


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def number(self, size: int) -> int:
        if self.offset + size > len(self.data):
            raise ValueError("Unexpected end of ESPN draft snapshot")
        value = int.from_bytes(self.data[self.offset:self.offset + size], "big")
        self.offset += size
        return value

    def integer(self) -> int:
        value = self.number(4)
        return value - (1 << 32) if value >= (1 << 31) else value

    def short(self) -> int:
        return self.number(2)

    def long(self) -> int:
        return self.number(8)

    def boolean(self) -> bool:
        return self.number(1) == 1

    def double(self) -> float:
        if self.offset + 8 > len(self.data):
            raise ValueError("Unexpected end of ESPN draft snapshot")
        value = struct.unpack(">d", self.data[self.offset:self.offset + 8])[0]
        self.offset += 8
        return value

    def object_version(self, supported: set[int]) -> int | None:
        if self.integer() != 1:
            return None
        version = self.integer()
        if version not in supported:
            raise ValueError(f"Unsupported ESPN draft object version: {version}")
        return version

    def objects(self, decoder):
        return [decoder(self) for _ in range(max(0, self.integer()))]


def _date(reader: _Reader):
    return reader.long() if reader.integer() else None


def _draft_block(reader: _Reader):
    if reader.object_version({1}) is None:
        return None
    values = [reader.integer(), reader.integer()]
    _date(reader)
    values.extend(reader.integer() for _ in range(5))
    return values


def _break_schedule(reader: _Reader):
    if reader.object_version({1}) is not None:
        reader.integer(); reader.integer(); reader.integer()


def _autodraft_protection(reader: _Reader):
    if reader.object_version({1}) is not None:
        reader.integer(); reader.integer(); reader.integer()


def _scoring_category(reader: _Reader):
    if reader.object_version({1, 2, 3}) is None:
        return
    reader.integer(); reader.integer(); reader.double(); reader.boolean()


def _scoring_settings(reader: _Reader):
    if reader.object_version({1}) is None:
        return
    reader.integer(); reader.integer(); reader.objects(_scoring_category)


def _draft_rules(reader: _Reader):
    version = reader.object_version({1, 2})
    if version is None:
        return
    for _ in range(5):
        reader.integer()
    _break_schedule(reader)
    _autodraft_protection(reader)
    for _ in range(4):
        reader.integer()
    for _ in range(4):
        reader.double()
    reader.integer(); reader.boolean()
    for _ in range(3):
        reader.integer()
    reader.boolean(); reader.boolean()
    _scoring_settings(reader)
    if version >= 2:
        reader.boolean()


def _draft_position(reader: _Reader):
    if reader.object_version({1}) is not None:
        reader.integer(); reader.integer(); reader.integer()


def _slot_position(reader: _Reader):
    if reader.object_version({1}) is not None:
        reader.integer(); reader.integer(); reader.integer()


def _draft_slot(reader: _Reader):
    if reader.object_version({1}) is not None:
        reader.integer(); reader.integer(); reader.integer(); reader.objects(_slot_position)


def _draft_pick(reader: _Reader):
    version = reader.object_version({1, 2, 3})
    if version is None:
        return None
    values = [reader.integer() for _ in range(7)]
    is_keeper = reader.boolean()
    autodraft_type = reader.integer()
    selector = reader.integer() if version >= 3 else None
    return {
        "league_id": values[0], "team_id": values[1], "pick_number": values[2],
        "player_id": values[3], "slot_id": values[4], "bid_amount": values[5],
        "nominating_team_id": values[6], "keeper": is_keeper,
        "autodraft_type_id": autodraft_type, "selector_user_profile_id": selector,
    }


def _draft_owner(reader: _Reader):
    if reader.object_version({1}) is not None:
        reader.integer(); reader.integer(); reader.integer()
        reader.boolean(); reader.boolean(); reader.boolean()


def _roster_item(reader: _Reader):
    if reader.object_version({1}) is None:
        return None
    values = [reader.integer() for _ in range(4)]
    reader.boolean()
    return {"league_id": values[0], "team_id": values[1], "slot_id": values[2], "player_id": values[3]}


def _draft_team(reader: _Reader):
    if reader.object_version({1, 2}) is None:
        return None
    values = [reader.integer() for _ in range(5)]
    reader.objects(_draft_owner)
    roster = [item for item in reader.objects(_roster_item) if item]
    return {"team_id": values[1], "draft_position": values[2], "roster": roster}


def _draft_list_player(reader: _Reader):
    if reader.object_version({1}) is not None:
        for _ in range(5): reader.integer()


def _draft_list(reader: _Reader):
    if reader.object_version({1}) is not None:
        reader.integer(); reader.integer(); reader.boolean(); reader.objects(_draft_list_player)


def _nomination_player(reader: _Reader):
    if reader.object_version({1}) is not None:
        for _ in range(5): reader.integer()


def _nomination_list(reader: _Reader):
    if reader.object_version({1}) is not None:
        reader.integer(); reader.integer(); reader.objects(_nomination_player)


def decode_init(payload: str) -> dict:
    raw = base64.b64decode(payload + "=" * (-len(payload) % 4))
    reader = _Reader(raw)
    if reader.object_version({1}) is None:
        raise ValueError("Empty ESPN draft snapshot")
    league_id = reader.integer()
    team_id = reader.integer()
    if reader.object_version({1}) is None:
        raise ValueError("ESPN draft league is missing")
    decoded_league_id = reader.integer()
    draft_type = reader.integer()
    universe_id = reader.integer()
    draft_date = _date(reader)
    draft_state = reader.integer()
    _draft_block(reader)
    _draft_rules(reader)
    reader.objects(_draft_position)
    reader.objects(_draft_slot)
    picks = [pick for pick in reader.objects(_draft_pick) if pick]
    teams = [team for team in reader.objects(_draft_team) if team]
    _draft_list(reader)
    _nomination_list(reader)
    return {
        "league_id": decoded_league_id or league_id, "team_id": team_id,
        "draft_type": draft_type, "universe_id": universe_id,
        "draft_date": draft_date, "draft_state": draft_state,
        "picks": picks, "teams": teams,
    }


class LiveDraftClient:
    def __init__(self):
        self._lock = threading.RLock()
        self._thread = None
        self._stop = threading.Event()
        self._key = None
        self._state = {"picks": [], "draft_state": None, "selecting_team_id": None}
        self._command_base = None
        self._draft_token = None
        self._connected_team_id = None
        self._response = None

    def _cache_path(self, league_id, season):
        return Path(".cache") / f"live_draft_{league_id}_{season}.json"

    def _save(self):
        if not self._key:
            return
        path = self._cache_path(self._key[0], self._key[1])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(
            f"{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
        )
        try:
            temporary.write_text(json.dumps(self._state), encoding="utf-8")
            temporary.replace(path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _load(self, league_id, season, draft_date):
        path = self._cache_path(league_id, season)
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if state.get("draft_date") == draft_date or _has_live_picks(state):
                self._state = state
        except (OSError, ValueError, TypeError):
            pass

    def ensure(self, league_metadata, raw_draft):
        if not raw_draft.get("draftDetail", {}).get("inProgress"):
            self.stop()
            return
        league_id, season = league_metadata.league_id, league_metadata.year
        draft_date = raw_draft.get("settings", {}).get("draftSettings", {}).get("date")
        key = (league_id, season, DEFAULT_TEAM_ID)
        with self._lock:
            if self._thread and self._thread.is_alive() and self._key == key:
                return
            previous = copy.deepcopy(self._state) if _has_live_picks(self._state) else None
            self.stop()
            self._key = key
            self._state = {"picks": [], "draft_state": 1, "selecting_team_id": None, "draft_date": draft_date}
            self._load(league_id, season, draft_date)
            if not _has_live_picks(self._state) and previous:
                previous["draft_date"] = self._state.get("draft_date", previous.get("draft_date"))
                self._state = previous
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, args=(league_metadata,), daemon=True, name="espn-live-draft")
            self._thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            response = self._response
            self._response = None
        if response is not None:
            try:
                response.close()
            except OSError:
                pass
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.2)
        self._thread = None
        with self._lock:
            self._command_base = None
            self._draft_token = None
            self._connected_team_id = None
            self._state["connected"] = False
            if self._key and _has_live_picks(self._state):
                self._save()

    def snapshot(self, league_metadata, raw_draft):
        self.ensure(league_metadata, raw_draft)
        with self._lock:
            return copy.deepcopy(self._state)

    def cached_snapshot(self, league_metadata, raw_draft):
        """Return the last matching snapshot without opening an ESPN connection."""
        league_id, season = league_metadata.league_id, league_metadata.year
        draft_date = raw_draft.get("settings", {}).get("draftSettings", {}).get("date")
        with self._lock:
            candidates = []
            if self._key and self._key[:2] == (league_id, season):
                candidates.append(copy.deepcopy(self._state))
            try:
                candidates.append(json.loads(self._cache_path(league_id, season).read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                pass
            dated_with_picks = next((
                state for state in candidates
                if state and state.get("draft_date") == draft_date and _has_live_picks(state)
            ), None)
            with_picks = next((state for state in candidates if _has_live_picks(state)), None)
            dated = next((
                state for state in candidates
                if state and state.get("draft_date") == draft_date
            ), None)
            state = dated_with_picks or with_picks or dated or {"picks": [], "draft_date": draft_date}
            state["connected"] = False
            state.pop("connection_error", None)
            return state

    def _team_identity(self, league_metadata):
        raw = league_metadata.league.espn_request.get_league()
        teams = raw.get("teams", []) or []
        # draftSecurity is authorized only for a team owned by this ESPN
        # account. DEFAULT_TEAM_ID may be a valid but foreign team after a
        # runtime league switch, which produces an otherwise opaque HTTP 401.
        swid = (league_metadata.swid or "").upper()
        team = next((item for item in teams if swid in [str(owner).upper() for owner in item.get("owners", [])]), None)
        if team is None:
            requested = DEFAULT_TEAM_ID
            team = next((item for item in teams if item.get("id") == requested), None)
        if team is None:
            raise ValueError("ESPN team for live draft was not found")
        member_id = team.get("primaryOwner") or (team.get("owners") or [None])[0]
        return int(team["id"]), member_id

    def _security_token(self, league_metadata, team_id, member_id):
        url = (
            "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/"
            f"{league_metadata.year}/segments/0/leagues/{league_metadata.league_id}/teams/{team_id}/draftSecurity"
        )
        request = urllib.request.Request(url, headers={
            "Accept": "application/json", "X-Fantasy-Source": "kona",
            "Cookie": f"espn_s2={league_metadata.espn_s2}; SWID={league_metadata.swid}",
            "User-Agent": "NBAFantasyAnalytics/1.0",
        })
        with urllib.request.urlopen(request, timeout=15) as response:
            security = json.loads(response.read().decode("utf-8"))
        return f"3:{league_metadata.league_id}:{team_id}:{member_id}:{security}"

    def _run(self, league_metadata):
        delay = 2
        while not self._stop.is_set():
            try:
                team_id, member_id = self._team_identity(league_metadata)
                token = self._security_token(league_metadata, team_id, member_id)
                # ESPN's own client concatenates the compound draft token
                # verbatim.  Generic urlencode escapes its ':' separators and
                # the draft server then misleadingly reports that the team
                # doesn't exist.
                params = (
                    f"1=3&2={league_metadata.league_id}&3={team_id}&4={member_id}"
                    f"&5={token}&6=false&7=false&8=KONA"
                    f"&nocache={int(time.time() * 1000) % 1_000_000}"
                )
                url = f"https://fantasydraft.espn.com/game-3/league-{league_metadata.league_id}/sse/JOIN?{params}"
                with self._lock:
                    self._command_base = f"https://fantasydraft.espn.com/game-3/league-{league_metadata.league_id}"
                    self._draft_token = token
                    self._connected_team_id = team_id
                request = urllib.request.Request(url, headers={
                    "Accept": "text/event-stream",
                    "Cookie": f"espn_s2={league_metadata.espn_s2}; SWID={league_metadata.swid}",
                    "Origin": "https://fantasy.espn.com",
                    "Referer": "https://fantasy.espn.com/",
                    "User-Agent": "Mozilla/5.0",
                })
                with urllib.request.urlopen(request, timeout=45) as response:
                    with self._lock:
                        self._response = response
                    try:
                        delay = 2
                        for raw_line in response:
                            if self._stop.is_set():
                                return
                            line = raw_line.decode("utf-8", "replace").strip()
                            if line.startswith("data:"):
                                self._handle(line[5:].strip())
                            elif line.startswith("ERROR"):
                                raise ConnectionError(urllib.parse.unquote_plus(line))
                    finally:
                        with self._lock:
                            if self._response is response:
                                self._response = None
            except Exception as error:
                with self._lock:
                    self._state["connection_error"] = str(error)[:240]
                logger.warning("ESPN live draft reconnect: %s", error)
                self._stop.wait(delay)
                delay = min(20, delay * 2)

    def _handle(self, message: str):
        if not message:
            return
        command, _, body = message.partition(" ")
        with self._lock:
            if command == "INIT":
                snapshot = decode_init(body)
                self._state.update(snapshot)
                self._state["connected"] = True
                self._state.pop("connection_error", None)
            elif command == "SELECTED":
                fields = body.split()
                if len(fields) >= 3:
                    team_id, player_id, slot_id = map(int, fields[:3])
                    picks = self._state.setdefault("picks", [])
                    pick = next((item for item in sorted(picks, key=lambda row: row["pick_number"]) if item.get("player_id", -1) <= 0), None)
                    if pick is None:
                        pick = {"pick_number": len(picks) + 1}
                        picks.append(pick)
                    pick.update({"team_id": team_id, "player_id": player_id, "slot_id": slot_id})
            elif command == "SELECTING":
                fields = body.split()
                if fields:
                    self._state["selecting_team_id"] = int(fields[0])
                    self._state["time_to_pick"] = int(fields[1]) if len(fields) > 1 else None
            elif command == "STATE":
                fields = body.split()
                if fields:
                    self._state["draft_state"] = int(fields[0])
            elif command == "ERROR":
                self._state["connected"] = False
                self._state["connection_error"] = urllib.parse.unquote_plus(body)[:240]
            self._state["updated_at"] = time.time()
            self._save()


live_draft_client = LiveDraftClient()


def _as_pick_number(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def overlay_live_draft(league_metadata, raw_draft):
    """Fill ESPN REST placeholder picks from the single live event stream."""
    if not hasattr(league_metadata, "league_id") or not hasattr(league_metadata, "year"):
        return raw_draft
    mode = get_draft_connection_mode()
    if mode != "analytics":
        live_draft_client.stop()
        snapshot = live_draft_client.cached_snapshot(league_metadata, raw_draft)
    else:
        snapshot = live_draft_client.snapshot(league_metadata, raw_draft)
    live_picks = {}
    for pick in snapshot.get("picks", []) or []:
        number = _as_pick_number(pick.get("pick_number"))
        player_id = pick.get("player_id", -1)
        if number and isinstance(player_id, int) and player_id > 0:
            live_picks[number] = pick
    merged = copy.deepcopy(raw_draft)
    detail = merged.setdefault("draftDetail", {})
    rest_picks = detail.setdefault("picks", []) or []
    detail["picks"] = rest_picks
    rest_by_overall = {}
    for pick in rest_picks:
        number = _as_pick_number(pick.get("overallPickNumber"))
        if number:
            rest_by_overall[number] = pick
    for number, live in live_picks.items():
        pick = rest_by_overall.get(number)
        if pick is None:
            pick = {"overallPickNumber": number, "playerId": -1}
            rest_picks.append(pick)
        pick["playerId"] = live["player_id"]
        pick["teamId"] = live.get("team_id", pick.get("teamId"))
        pick["lineupSlotId"] = live.get("slot_id", pick.get("lineupSlotId"))
    if snapshot.get("draft_state") == 2:
        detail["inProgress"] = False
        detail["drafted"] = True
    detail["liveSelectingTeamId"] = snapshot.get("selecting_team_id")
    detail["liveSource"] = mode == "analytics" and bool(snapshot.get("connected"))
    detail["liveSnapshotAvailable"] = bool(live_picks)
    detail["liveSnapshotFrozen"] = mode == "espn" and bool(live_picks)
    detail["liveUpdatedAt"] = snapshot.get("updated_at")
    detail["liveConnectionError"] = snapshot.get("connection_error") if mode == "analytics" else None
    detail["liveConnectionMode"] = mode
    return merged
