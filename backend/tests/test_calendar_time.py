from datetime import datetime
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.calendar_time import normalize_calendar_time  # noqa: E402


LOCAL_TZ = ZoneInfo("America/Chicago")
NOW = datetime(2026, 6, 5, 17, 45, tzinfo=LOCAL_TZ)


def event(
    title: str,
    start: str,
    end: str,
    *,
    category: str = "hard",
    busy: bool = True,
    all_day: bool = False,
) -> dict:
    return {
        "id": title.lower().replace(" ", "-"),
        "title": title,
        "start": start,
        "end": end,
        "busy": busy,
        "all_day": all_day,
        "event_category": category,
    }


class CalendarTimeContractTests(unittest.TestCase):
    def test_normalizes_utc_event_and_computes_minutes_from_local_now(self):
        state = normalize_calendar_time(
            [event("Gym", "2026-06-05T23:30:00Z", "2026-06-06T00:30:00Z")],
            now=NOW,
            local_tz=LOCAL_TZ,
        )

        self.assertEqual(state.next_event["start"], "2026-06-05T18:30:00-05:00")
        self.assertEqual(state.minutes_until_next_event, 45)
        self.assertEqual(state.current_free_block["duration_minutes"], 45)

    def test_ongoing_commitment_cannot_produce_current_free_block(self):
        state = normalize_calendar_time(
            [event("Client review", "2026-06-05T17:30:00-05:00", "2026-06-05T18:30:00-05:00")],
            now=NOW,
            local_tz=LOCAL_TZ,
        )

        self.assertIsNone(state.current_free_block)
        self.assertEqual(state.current_or_next_free_block["start"], "2026-06-05T18:30:00-05:00")
        self.assertFalse(state.current_or_next_free_block["is_current"])

    def test_all_day_and_informational_events_remain_visible_but_do_not_block(self):
        state = normalize_calendar_time(
            [
                event(
                    "Birthday",
                    "2026-06-05T00:00:00-05:00",
                    "2026-06-06T00:00:00-05:00",
                    category="informational",
                    all_day=True,
                ),
                event(
                    "Graduation reminder",
                    "2026-06-05T18:00:00-05:00",
                    "2026-06-05T19:00:00-05:00",
                    category="informational",
                ),
            ],
            now=NOW,
            local_tz=LOCAL_TZ,
        )

        self.assertEqual(len(state.remaining_events), 2)
        self.assertEqual(state.blocking_events, ())
        self.assertIsNone(state.next_event)
        self.assertEqual(state.current_free_block["end"], "2026-06-06T00:00:00-05:00")


if __name__ == "__main__":
    unittest.main()
