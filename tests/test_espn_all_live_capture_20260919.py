"""Replay of real ESPN responses captured 2026-09-19 (after ESPN's Sept 15 change).

Unlike most of the suite, the mock here enforces ESPN's *current* API contract
instead of serving canned data for any URL:

* scoreboard calls with a date range (``dates=YYYYMMDD-YYYYMMDD``) or a comma
  list fail exactly as the live API does (HTTP 400 -> wrapper returns
  ``data: None``);
* the default / single-day scoreboard serves the captured ``live-truth`` feed;
* ``teams/{id}`` and ``teams/{id}/schedule`` serve the captured responses.

The captures were taken while matches were in progress, so they cover the
IN state (including ESPN's team endpoint lagging the scoreboard), plus PRE and
POST, and remain valid after those matches end. See
``tests/tt/captures/README-soccer-all-live-20260919.md``.
"""

import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

from freezegun import freeze_time
import pytest

from custom_components.teamtracker.const import DOMAIN
from custom_components.teamtracker.parse_espn_all import EspnAllParser
from custom_components.teamtracker.provide_espn_all import EspnAllLeaguesProvider

CAPTURES = "tests/tt/captures"
STAMP = "20260919T1415Z"
TRUTH = f"espn-soccer-all-scoreboard-live-truth-{STAMP}.json"


def _load(name: str) -> dict:
    with open(f"{CAPTURES}/{name}", encoding="utf-8") as f:
        return json.load(f)


def _contract_mock(team_id: str, team_file: str, schedule_file: str | None):
    """Serve only what the live API still serves; range scoreboard calls fail."""
    team = _load(team_file)
    schedule = _load(schedule_file) if schedule_file else {"events": []}
    truth = _load(TRUTH)

    async def call(hass, base_url, params, sensor_name, tid, file_override=False):
        dates = str((params or {}).get("dates", ""))
        result = {"url": base_url, "timestamp": None}

        if base_url.endswith("/scoreboard"):
            if re.fullmatch(r"\d{8}-\d{8}", dates) or "," in dates:
                return {**result, "data": None}  # HTTP 400 since 2026-09-15
            if dates in ("", "20260919"):
                return {**result, "data": truth}
            return {**result, "data": {"events": []}}
        if base_url.endswith(f"/teams/{team_id}/schedule"):
            return {**result, "data": schedule}
        if base_url.endswith(f"/teams/{team_id}"):
            return {**result, "data": team}
        raise AssertionError(f"unexpected ESPN call: {base_url} {params}")

    return call


async def _sensor_values(team_id: str, name: str, team_file: str, schedule_file: str | None = None):
    coordinator = SimpleNamespace(
        name=name,
        sport_path="soccer",
        league_path="all",
        league_id="XXX",
        team_id=team_id,
        conference_id="",
        hass=SimpleNamespace(data={DOMAIN: {}}),
        get_lang=lambda: "en",
    )
    provider = object.__new__(EspnAllLeaguesProvider)
    provider.TEAM_SCHEDULE_KEY = "team-schedule-key"
    provider.instance_cache = {}
    provider.lookups = {"team_list": []}
    provider._coordinator = coordinator
    provider.async_call_espn_api = AsyncMock(
        side_effect=_contract_mock(team_id, team_file, schedule_file)
    )

    response = await provider._async_fetch_scoreboard_data(None, "en")

    parser = EspnAllParser(coordinator)
    parser.setup(name, "soccer", "all", "XXX", team_id)
    return parser.parse_response(response, "en")


def _minute(clock: str) -> int:
    """'45'+1'' -> 45; \"15'\" -> 15."""
    return int(re.match(r"\d+", clock).group())


def _truth_event(short_name: str) -> dict:
    return next(e for e in _load(TRUTH)["events"] if e["shortName"] == short_name)


@freeze_time("2026-09-19 14:15:00")
@pytest.mark.asyncio
async def test_live_match_state_and_clock_via_next_event():
    """A match in progress is found and shown IN with the live clock even
    though the dated scoreboard call fails."""
    values = await _sensor_values(
        "361", "Newcastle", f"espn-soccer-all-team-361-newcastle-{STAMP}.json"
    )

    truth = _truth_event("HUL @ NEW")
    assert values.state == "IN"
    assert values.event_name == "HUL @ NEW"
    # ESPN's team endpoint can be a few minutes behind the scoreboard (the
    # capture shows 11' against the scoreboard's 15'), but never ahead of it.
    assert 0 < _minute(values.clock) <= _minute(truth["status"]["displayClock"])
    assert values.league_name == "English Premier League"


@freeze_time("2026-09-19 14:10:00")
@pytest.mark.asyncio
async def test_live_match_survives_team_endpoint_lagging_scoreboard():
    """Captured 14:10Z: the scoreboard already showed NEW 2-0 but ESPN's
    team.nextEvent competitors had no ``score`` key yet (it caught up about
    a minute later). The sensor must still be IN with the live clock, not
    NOT_FOUND or an exception; the score may be None until the next update."""
    values = await _sensor_values(
        "361",
        "Newcastle",
        "espn-soccer-all-team-361-newcastle-live-score-lag-20260919T1410Z.json",
    )

    assert values.state == "IN"
    assert values.event_name == "HUL @ NEW"
    assert values.clock == "10'"
    assert values.team_score in (None, "2")


@freeze_time("2026-09-19 14:15:00")
@pytest.mark.asyncio
async def test_live_score_object_shape_from_next_event():
    """team.nextEvent gives score as {'value': 2.0, 'displayValue': '2', ...}
    where the scoreboard gives '2'. The sensor must report the same score
    the scoreboard shows."""
    values = await _sensor_values(
        "125",
        "Eintracht Frankfurt",
        f"espn-soccer-all-team-125-eintracht-frankfurt-{STAMP}.json",
    )

    truth = _truth_event("SCF @ SGE")
    home = {c["homeAway"]: c for c in truth["competitions"][0]["competitors"]}
    assert values.state == "IN"
    assert values.team_homeaway == "home"
    assert (values.team_score, values.opponent_score) == (
        home["home"]["score"],
        home["away"]["score"],
    )


@freeze_time("2026-09-19 14:15:00")
@pytest.mark.asyncio
async def test_live_second_tier_league_name_from_season_display_name():
    """Birmingham's season slug is the generic 'regular-season', so the name
    must come from the season display name."""
    values = await _sensor_values(
        "392", "Birmingham", f"espn-soccer-all-team-392-birmingham-{STAMP}.json"
    )

    assert values.state == "IN"
    assert values.league_name == "English League Championship"


@freeze_time("2026-09-19 14:15:00")
@pytest.mark.asyncio
async def test_next_day_fixture_found_without_date_range():
    """Real Madrid's next game is tomorrow: PRE, found via team.nextEvent."""
    values = await _sensor_values(
        "86", "Real Madrid", f"espn-soccer-all-team-86-real-madrid-{STAMP}.json"
    )

    assert values.state == "PRE"
    assert values.event_name == "RMA @ ATM"
    assert values.date == "2026-09-20T14:15Z"
    assert "laliga" in values.league_name.lower()


@freeze_time("2026-09-19 14:15:00")
@pytest.mark.asyncio
async def test_pre_match_league_name_when_slug_has_no_year():
    """América's season slug is 'torneo-apertura' (no year prefix, so it
    can't be converted); the name must still resolve."""
    values = await _sensor_values(
        "227", "Club America", f"espn-soccer-all-team-227-club-america-{STAMP}.json"
    )

    assert values.state == "PRE"
    assert values.event_name == "GDL @ AME"
    assert values.league_name == "Liga BBVA MX"


@freeze_time("2026-09-19 14:15:00")
@pytest.mark.asyncio
async def test_finished_match_today_shown_as_post_from_schedule():
    """Tottenham's match finished hours earlier: not in nextEvent, but in the
    team schedule, so the sensor shows POST rather than NOT_FOUND."""
    values = await _sensor_values(
        "367",
        "Tottenham",
        f"espn-soccer-all-team-367-tottenham-{STAMP}.json",
        f"espn-soccer-all-schedule-367-tottenham-{STAMP}.json",
    )

    assert values.state == "POST"
    assert values.event_name == "AVL @ TOT"
    assert values.league_name == "English Premier League"


@pytest.mark.asyncio
async def test_contract_mock_rejects_date_ranges_like_espn():
    """Guard the harness itself: a range must fail, a single day must not."""
    call = _contract_mock("361", f"espn-soccer-all-team-361-newcastle-{STAMP}.json", None)
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard"

    ranged = await call(None, url, {"dates": "20260919-20260925"}, "t", "361")
    single = await call(None, url, {"dates": "20260919"}, "t", "361")

    assert ranged["data"] is None
    assert single["data"]["events"]
