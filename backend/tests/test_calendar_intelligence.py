from datetime import datetime
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.calendar_intelligence import analyze_calendar_change  # noqa: E402


def event(
    event_id: str,
    title: str,
    start: str,
    end: str,
    *,
    event_category: str = "hard",
    all_day: bool = False,
) -> dict:
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    return {
        "id": event_id,
        "title": title,
        "start": start,
        "end": end,
        "duration_minutes": int((end_dt - start_dt).total_seconds() // 60),
        "all_day": all_day,
        "busy": True,
        "event_type": event_category,
        "event_category": event_category,
    }


class CalendarIntelligenceTests(unittest.TestCase):
    def test_all_day_birthday_does_not_conflict(self):
        analysis = analyze_calendar_change(
            event(
                "birthday",
                "Birthday",
                "2026-06-05T00:00:00-05:00",
                "2026-06-06T00:00:00-05:00",
                event_category="informational",
                all_day=True,
            ),
            [
                event(
                    "interview",
                    "Interview",
                    "2026-06-05T14:00:00-05:00",
                    "2026-06-05T14:30:00-05:00",
                    event_category="hard",
                )
            ],
            {},
        )

        self.assertFalse(analysis.has_conflict)
        self.assertFalse(analysis.has_buffer_issue)
        self.assertEqual(analysis.severity, "none")

    def test_interview_to_gym_creates_tight_buffer_issue(self):
        analysis = analyze_calendar_change(
            event(
                "gym-new",
                "Gym",
                "2026-06-05T14:30:00-05:00",
                "2026-06-05T15:30:00-05:00",
                event_category="flexible",
            ),
            [
                event(
                    "interview",
                    "Interview",
                    "2026-06-05T14:00:00-05:00",
                    "2026-06-05T14:30:00-05:00",
                    event_category="hard",
                )
            ],
            {},
        )

        self.assertTrue(analysis.has_buffer_issue)
        self.assertEqual(analysis.severity, "medium")
        self.assertEqual(analysis.issues[0].type, "tight_buffer")
        self.assertEqual(analysis.issues[0].minutes_between, 0)

    def test_new_meeting_overlapping_gym_suggests_moving_gym(self):
        analysis = analyze_calendar_change(
            event(
                "meeting-new",
                "Client meeting",
                "2026-06-05T14:00:00-05:00",
                "2026-06-05T14:30:00-05:00",
                event_category="hard",
            ),
            [
                event(
                    "gym",
                    "Gym",
                    "2026-06-05T14:15:00-05:00",
                    "2026-06-05T15:15:00-05:00",
                    event_category="flexible",
                )
            ],
            {},
        )

        self.assertTrue(analysis.has_conflict)
        self.assertEqual(analysis.severity, "high")
        self.assertEqual(analysis.suggested_fix.action, "move_existing_event")
        self.assertEqual(analysis.suggested_fix.event_id, "gym")
        self.assertEqual(analysis.suggested_fix.new_start, "2026-06-05T15:00:00-05:00")

    def test_new_gym_too_close_after_interview_suggests_moving_gym(self):
        analysis = analyze_calendar_change(
            event(
                "gym-new",
                "Gym",
                "2026-06-05T14:45:00-05:00",
                "2026-06-05T15:45:00-05:00",
                event_category="flexible",
            ),
            [
                event(
                    "interview",
                    "Interview",
                    "2026-06-05T14:00:00-05:00",
                    "2026-06-05T14:30:00-05:00",
                    event_category="hard",
                )
            ],
            {},
        )

        self.assertEqual(analysis.issues[0].type, "tight_buffer")
        self.assertEqual(analysis.issues[0].minutes_between, 15)
        self.assertEqual(analysis.suggested_fix.action, "move_new_event")
        self.assertEqual(analysis.suggested_fix.new_start, "2026-06-05T15:00:00-05:00")

    def test_event_at_ashwins_suggests_prep_or_travel_buffer(self):
        analysis = analyze_calendar_change(
            event(
                "party-new",
                "Party at Ashwin's",
                "2026-06-05T20:00:00-05:00",
                "2026-06-05T23:00:00-05:00",
                event_category="social",
            ),
            [],
            {},
        )

        self.assertTrue(analysis.has_buffer_issue)
        self.assertEqual(analysis.severity, "medium")
        self.assertEqual(analysis.issues[0].type, "travel_buffer")
        self.assertEqual(analysis.suggested_fix.action, "add_travel_buffer")
        self.assertEqual(analysis.suggested_fix.new_end, "2026-06-05T20:00:00-05:00")

    def test_informational_event_is_displayed_but_not_blocking(self):
        analysis = analyze_calendar_change(
            event(
                "meeting-new",
                "Client meeting",
                "2026-06-05T14:00:00-05:00",
                "2026-06-05T15:00:00-05:00",
                event_category="hard",
            ),
            [
                event(
                    "birthday",
                    "Birthday",
                    "2026-06-05T00:00:00-05:00",
                    "2026-06-06T00:00:00-05:00",
                    event_category="informational",
                    all_day=True,
                )
            ],
            {},
        )

        self.assertFalse(analysis.has_conflict)
        self.assertEqual(analysis.severity, "none")
        self.assertEqual(analysis.issues[0].type, "informational_overlap")


if __name__ == "__main__":
    unittest.main()
