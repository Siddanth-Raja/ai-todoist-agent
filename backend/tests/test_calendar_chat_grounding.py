from datetime import datetime
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.calendar_chat_grounding import (  # noqa: E402
    CalendarChatGroundingService,
    CalendarGroundingState,
)
from app.calendar_tools import CalendarReadResult  # noqa: E402


LOCAL_TZ = ZoneInfo("America/Chicago")
NOW = datetime(2026, 7, 16, 12, 0, tzinfo=LOCAL_TZ)


def event(
    event_id: str,
    title: str,
    start: str,
    end: str,
    *,
    location: str | None = None,
) -> dict:
    return {
        "id": event_id,
        "title": title,
        "start": start,
        "end": end,
        "location": location,
        "busy": True,
        "all_day": False,
        "event_type": "hard",
    }


class CalendarChatGroundingTests(unittest.TestCase):
    def setUp(self):
        self.service = CalendarChatGroundingService()
        self.empty = CalendarReadResult(events=[])

    def ground(
        self,
        message: str,
        *,
        today: CalendarReadResult | None = None,
        upcoming: CalendarReadResult | None = None,
        state: dict | None = None,
    ):
        return self.service.ground(
            message,
            today_result=today or self.empty,
            upcoming_result=upcoming or self.empty,
            local_now=NOW,
            conversation_state=state,
        )

    def test_provider_failure_is_unavailable_and_preserves_diagnostic(self):
        result = self.ground(
            "What time is my interview tomorrow?",
            upcoming=CalendarReadResult(
                events=[],
                error="Google token refresh failed.",
            ),
        )

        self.assertEqual(result.state, CalendarGroundingState.PROVIDER_UNAVAILABLE)
        self.assertIn("Calendar is unavailable", result.answer)
        self.assertNotIn("could not find", result.answer.lower())
        self.assertEqual(result.context["provider_diagnostic"], "Google token refresh failed.")
        self.assertEqual(result.warnings, ("Google token refresh failed.",))

    def test_connected_empty_is_distinct_from_provider_failure(self):
        result = self.ground("What time is my interview tomorrow?")

        self.assertEqual(result.state, CalendarGroundingState.CONNECTED_NO_MATCH)
        self.assertIn("Calendar is connected", result.answer)
        self.assertNotIn("unavailable", result.answer.lower())
        self.assertEqual(result.awaiting, "event_detail")

    def test_generic_title_and_utc_timestamp_are_grounded_in_local_time(self):
        result = self.ground(
            "What time is Product Council tomorrow?",
            upcoming=CalendarReadResult(
                events=[
                    event(
                        "product-council",
                        "Product Council",
                        "2026-07-17T19:00:00Z",
                        "2026-07-17T20:00:00Z",
                    )
                ]
            ),
        )

        self.assertEqual(result.state, CalendarGroundingState.EXACT_MATCH)
        self.assertIn("2:00 PM - 3:00 PM", result.answer)
        self.assertEqual(result.context["event_title"], "Product Council")
        self.assertEqual(result.context["target_date"], "2026-07-17")

    def test_multiple_plausible_matches_are_ambiguous_not_guessed(self):
        result = self.ground(
            "When is Design Review tomorrow?",
            upcoming=CalendarReadResult(
                events=[
                    event(
                        "xo-review",
                        "Design Review — XO",
                        "2026-07-17T14:00:00-05:00",
                        "2026-07-17T14:30:00-05:00",
                    ),
                    event(
                        "nebulo-review",
                        "Design Review — Nebulo",
                        "2026-07-17T16:00:00-05:00",
                        "2026-07-17T16:30:00-05:00",
                    ),
                ]
            ),
        )

        self.assertEqual(result.state, CalendarGroundingState.AMBIGUOUS_MATCH)
        self.assertEqual(result.awaiting, "calendar_match_clarification")
        self.assertIn("Which one do you mean?", result.answer)
        self.assertEqual(len(result.context["candidate_events"]), 2)

    def test_ambiguous_followup_retains_date_and_resolves_subject(self):
        upcoming = CalendarReadResult(
            events=[
                event(
                    "xo-review",
                    "Design Review — XO",
                    "2026-07-17T14:00:00-05:00",
                    "2026-07-17T14:30:00-05:00",
                ),
                event(
                    "nebulo-review",
                    "Design Review — Nebulo",
                    "2026-07-17T16:00:00-05:00",
                    "2026-07-17T16:30:00-05:00",
                ),
            ]
        )
        first = self.ground("When is Design Review tomorrow?", upcoming=upcoming)
        second = self.ground(
            "the XO one",
            upcoming=upcoming,
            state={
                "awaiting": first.awaiting,
                "context": first.context,
            },
        )

        self.assertEqual(second.state, CalendarGroundingState.EXACT_MATCH)
        self.assertIn("Design Review — XO", second.answer)
        self.assertIn("2:00 PM", second.answer)

    def test_exact_match_retains_subject_for_location_followup(self):
        upcoming = CalendarReadResult(
            events=[
                event(
                    "product-council",
                    "Product Council",
                    "2026-07-17T14:00:00-05:00",
                    "2026-07-17T15:00:00-05:00",
                    location="Design Studio",
                )
            ]
        )
        first = self.ground("What time is Product Council tomorrow?", upcoming=upcoming)
        second = self.ground(
            "Where is it?",
            upcoming=upcoming,
            state={"awaiting": first.awaiting, "context": first.context},
        )

        self.assertEqual(second.state, CalendarGroundingState.EXACT_MATCH)
        self.assertIn("Product Council", second.answer)
        self.assertIn("Design Studio", second.answer)

    def test_ongoing_event_remains_matchable_without_past_free_block_reasoning(self):
        result = self.ground(
            "Where is Product Council today?",
            today=CalendarReadResult(
                events=[
                    event(
                        "ongoing-council",
                        "Product Council",
                        "2026-07-16T11:30:00-05:00",
                        "2026-07-16T12:30:00-05:00",
                        location="Design Studio",
                    )
                ]
            ),
        )

        self.assertEqual(result.state, CalendarGroundingState.EXACT_MATCH)
        self.assertIn("11:30 AM - 12:30 PM", result.answer)
        self.assertIn("Design Studio", result.answer)

    def test_malformed_provider_response_is_unavailable_not_empty(self):
        result = self.ground(
            "What time is Product Council tomorrow?",
            upcoming=CalendarReadResult(
                events=[{"id": "broken", "title": "Product Council", "start": "bad"}]
            ),
        )

        self.assertEqual(result.state, CalendarGroundingState.PROVIDER_UNAVAILABLE)
        self.assertIn("none of it had readable", result.context["provider_diagnostic"])

        malformed_collection = self.ground(
            "What time is Product Council tomorrow?",
            upcoming=CalendarReadResult(events=None),
        )
        self.assertEqual(
            malformed_collection.state,
            CalendarGroundingState.PROVIDER_UNAVAILABLE,
        )
        self.assertIn(
            "malformed event collection",
            malformed_collection.context["provider_diagnostic"],
        )

        partial_malformed = self.ground(
            "What time is Product Council tomorrow?",
            upcoming=CalendarReadResult(
                events=[
                    event(
                        "valid-unrelated",
                        "Lunch",
                        "2026-07-17T12:00:00-05:00",
                        "2026-07-17T13:00:00-05:00",
                    ),
                    {"id": "broken-match", "title": "Product Council", "start": "bad"},
                ]
            ),
        )
        self.assertEqual(
            partial_malformed.state,
            CalendarGroundingState.PROVIDER_UNAVAILABLE,
        )
        self.assertIn(
            "connected no-match result cannot be trusted",
            partial_malformed.context["provider_diagnostic"],
        )

    def test_calendar_writes_and_global_planning_are_not_intercepted(self):
        for message in (
            "Schedule Product Council tomorrow at 2pm",
            "Move Product Council to 3pm",
            "Could you update my Product Council event?",
            "What should I work on right now?",
            "Do I have time to work before my next event?",
            "Can I work tomorrow?",
        ):
            with self.subTest(message=message):
                self.assertIsNone(self.ground(message))

    def test_interview_fact_is_separate_from_unsupported_preparation_assumptions(self):
        result = self.ground(
            "Do I need to wake up early for my interview tomorrow?",
            upcoming=CalendarReadResult(
                events=[
                    event(
                        "interview",
                        "Shake Shack Interview",
                        "2026-07-17T14:00:00-05:00",
                        "2026-07-17T14:30:00-05:00",
                    )
                ]
            ),
        )

        self.assertEqual(result.state, CalendarGroundingState.EXACT_MATCH)
        self.assertIn("2:00 PM - 2:30 PM", result.answer)
        self.assertIn("not enough evidence", result.answer)
        self.assertNotIn("wake up by", result.answer)


if __name__ == "__main__":
    unittest.main()
