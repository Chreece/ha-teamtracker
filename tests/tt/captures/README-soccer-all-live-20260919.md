# API captures - soccer `league_path: all` after ESPN's Sept 15 change

Real ESPN responses captured **2026-09-19, 14:10-14:16 UTC**, while 22 soccer
matches were in progress (EPL, Bundesliga, Serie A, EFL, SPFL, Turkish Super
Lig). They are kept so the IN / PRE / POST paths can be tested after those
matches end. Replayed by `tests/test_espn_all_live_capture_20260919.py`.

## Why these exist

ESPN stopped honoring date ranges on ~2026-09-15 (`?dates=20260919-20260925`
returns `{"code":400,"message":"Failed to get events endpoint."}`), but most of
the existing test data cannot show that:

- `mock_call_espn_api` in `tests/conftest.py` serves canned files whatever the
  `dates` parameter is, so a range URL "succeeds" in tests.
- 25 of the 32 `tests/tt/results/*.json` snapshots embed a range-style
  `api_url`.
- Older captures obtained with a range call (for example the MLB
  `espn-mlb-scoreboard-range-*` file) cannot be reproduced against the live API.

The replay mock in the new test file instead enforces the current contract:
range / comma-list scoreboard calls fail (`data: None`), the default and
single-day scoreboard serve the captured feed, and only the captured
`teams/{id}` and `teams/{id}/schedule` responses are served.

## Files

| file | endpoint | what it shows |
|---|---|---|
| `espn-soccer-all-scoreboard-live-truth-20260919T1415Z.json` | `all/scoreboard` (default, no params) | Ground truth for five events involving the teams below (trimmed from the 100-event feed: 10 post / 22 in / 68 pre). Carries `altGameNote`, which the team endpoints never do. |
| `espn-soccer-all-team-361-newcastle-20260919T1415Z.json` | `all/teams/361` | `nextEvent` for a match in progress (EPL, 2-0). |
| `espn-soccer-all-team-361-newcastle-live-score-lag-20260919T1410Z.json` | `all/teams/361` | Same match at 14:10Z: the scoreboard already showed 2-0 but the competitors here have **no `score` key**. |
| `espn-soccer-all-team-125-eintracht-frankfurt-20260919T1415Z.json` | `all/teams/125` | Live match where `score` is an object (`{"value": 2.0, "displayValue": "2"}`), not the scoreboard's `"2"`. |
| `espn-soccer-all-team-392-birmingham-20260919T1415Z.json` | `all/teams/392` | Live match whose season slug is the generic `regular-season`; the name only exists in `season.displayName`. |
| `espn-soccer-all-team-86-real-madrid-20260919T1415Z.json` | `all/teams/86` | PRE match one day out. |
| `espn-soccer-all-team-227-club-america-20260919T1415Z.json` | `all/teams/227` | PRE match; slug `torneo-apertura` has no year prefix. |
| `espn-soccer-all-team-367-tottenham-20260919T1415Z.json`, `espn-soccer-all-schedule-367-tottenham-20260919T1415Z.json` | `all/teams/367`, `.../schedule` | Match already finished hours earlier: absent from `nextEvent`, present in `/schedule`, so the sensor is POST. |

Schedules were also captured for the other five teams but omitted for size
(about 600 KB); those tests use an empty schedule.

## API behavior observed on 2026-09-19

| request | result |
|---|---|
| `scoreboard?dates=YYYYMMDD-YYYYMMDD` (also `YYYYMMDD-` and `YYYYMMDD,YYYYMMDD`) | **400** for NFL, WNBA, MLB, NHL, MLS and soccer/all; tennis/atp and golf/pga returned 200 in a one-call check |
| `scoreboard` (no params) | today only (plus a day for some sports); soccer/all is capped at 100 events even with `limit=1000` |
| `scoreboard?dates=YYYYMMDD` | that day only; days beyond about tomorrow return 0 events for soccer |
| `scoreboard?dates=YYYYMM&limit=1000` | **still works**: the whole month, past and future (MLS through 11/1, NFL through 10/30, MLB September = 369 events). Default cap is 100 without `limit`. |
| `teams/{id}` `nextEvent` | exactly one event (the next unplayed or in-progress one) |
| `teams/{id}/schedule` | full season including future games for NFL, MLB, NHL, NBA, WNBA, college football; **no future games for soccer** |

Cache headers: scoreboard `max-age=6`; team endpoints `max-age=1`.

## Caveats

- Point-in-time data. Scores and clocks are frozen at capture time.
- The team endpoint is usually within a minute of the scoreboard but is
  occasionally minutes behind: in the 14:15Z capture Newcastle's clock is 11'
  while the scoreboard was at 15'. Tests allow it to lag, never to lead.
- The `derived_league_name` fixtures from 2026-09-04 (AC Milan, Seattle, ...)
  are unaffected: they use `teams/{id}` and `/schedule`, which were not changed.
