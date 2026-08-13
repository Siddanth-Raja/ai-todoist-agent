from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.activity_domain import ActivityFreshness  # noqa: E402
from app.calendar_time import normalize_calendar_time  # noqa: E402
from app.calendar_tools import CalendarReadResult  # noqa: E402
from app.morning_corrections import (  # noqa: E402
    MorningCorrectionRequest,
    MorningCorrectionService,
    MorningCorrectionType,
)
from app.morning_state import (  # noqa: E402
    MORNING_STATE_SCHEMA_VERSION,
    MorningAvailability,
    MorningChangeWindow,
    MorningCheckpointMode,
    MorningCheckpointSelection,
    MorningConfidence,
    MorningFactType,
    MorningFreshness,
    MorningProjectState,
    MorningSectionId,
    MorningStateService,
    MorningStatement,
)
from app.project_activity_focus import (  # noqa: E402
    ExplicitProjectIntent,
    ProjectActivityFocus,
    ProjectActivityWindow,
    ProjectFocusConfidence,
    ProjectFocusEvidence,
    ProjectFocusState,
    ProviderCoverage,
    ProviderCoverageState,
)
from app.provider_changes import (  # noqa: E402
    ChangeComparisonState,
    ChangeCoverage,
    CompletionState,
    ProviderEvidenceReference,
    ProviderObservation,
    _encode_cursor,
    provider_change_service,
)
from app.reality_reconciliation import (  # noqa: E402
    ProviderRecordIdentity,
    RealityAvailability,
    RealityClassification,
    RealityConfidence,
    RealityEvidence,
    RealityEvidenceType,
    RealityFreshness,
    RealityIdentityState,
    RealityItem,
    SafeResolution,
    TemporalActionability,
    WorkIdentity,
)
from app.storage import database_connection, ensure_database  # noqa: E402


LOCAL_TZ = ZoneInfo("America/Chicago")
NOW = datetime(2026, 8, 7, 10, 30, tzinfo=LOCAL_TZ)


def coverage(
    provider="linear",
    *,
    state=ProviderCoverageState.FRESH,
    project_id="project-pcos",
):
    return ProviderCoverage(
        provider=provider,
        provider_reference=f"{provider}-scope",
        state=state,
        observed_at=NOW,
        historical_coverage_start=NOW - timedelta(days=60),
        detail=None,
    )


def focus(
    project_id,
    project_key,
    state,
    *,
    confidence=ProjectFocusConfidence.HIGH,
    freshness=ActivityFreshness.FRESH,
    explicit_intent=None,
    confirmation_question=None,
    coverage_state=ProviderCoverageState.FRESH,
):
    evidence = ProjectFocusEvidence(
        evidence_key=f"focus:{project_id}:{state.value}",
        category="work_updated",
        canonical_project_id=project_id,
        source_kind="normalized_work",
        provider="linear",
        provider_record_type="issue",
        provider_record_id=f"{project_key}-1",
        source_timestamp=NOW - timedelta(hours=1),
        observed_at=NOW,
        freshness=freshness,
        summary="Attributable project focus evidence.",
    )
    windows = tuple(
        ProjectActivityWindow(
            days=days,
            starts_at=NOW - timedelta(days=days),
            ends_at=NOW,
            evidence_count=1,
            categories=("work_updated",),
        )
        for days in (7, 14, 30)
    )
    return ProjectActivityFocus(
        canonical_project_id=project_id,
        canonical_project_key=project_key,
        evaluated_at=NOW,
        primary_state=state,
        evidence=(evidence,),
        evidence_total_count=1,
        evidence_returned_count=1,
        evaluated_windows=windows,
        confidence=confidence,
        freshness=freshness,
        provider_coverage=(
            coverage(state=coverage_state, project_id=project_id),
        ),
        explicit_intent=explicit_intent,
        explicitly_confirmed=explicit_intent is not None,
        inferred=explicit_intent is None,
        user_confirmation_recommended=confirmation_question is not None,
        confirmation_question=confirmation_question,
        confirmation_reason=(
            "The current focus interpretation needs review."
            if confirmation_question
            else None
        ),
    )


def evidence(
    project_id,
    record_id,
    *,
    provider="linear",
    evidence_type=RealityEvidenceType.WORK_STATE,
    claim="open",
    freshness=RealityFreshness.FRESH,
    availability=RealityAvailability.AVAILABLE,
    linked=True,
):
    work = WorkIdentity(provider="linear", provider_record_id=record_id)
    return RealityEvidence(
        evidence_id=f"evidence:{provider}:{record_id}:{claim}",
        evidence_type=evidence_type,
        canonical_project_id=project_id,
        normalized_work_identity=work,
        provider_identity=ProviderRecordIdentity(
            provider=provider,
            provider_record_type="message" if provider == "gmail" else "issue",
            provider_record_id=f"{provider}-{record_id}",
            provider_reference=f"{provider}-scope",
        ),
        linked_work_identity=work if linked else None,
        claim=claim,
        observed_state=claim,
        source_timestamp=NOW - timedelta(hours=2),
        observed_at=NOW,
        freshness=freshness,
        availability=availability,
        trustworthy=True,
        summary=f"{provider} reports {claim}.",
    )


def reality_item(
    project_id,
    project_key,
    record_id,
    classification,
    *,
    title=None,
    temporal=None,
    evidences=None,
    confidence=RealityConfidence.HIGH,
    resolution=None,
):
    identity = WorkIdentity(provider="linear", provider_record_id=record_id)
    evidences = tuple(evidences or (evidence(project_id, record_id),))
    return RealityItem(
        reality_item_id=f"reality:{project_id}:{record_id}",
        reconciliation_id=f"reality:{project_id}:{record_id}",
        canonical_project_id=project_id,
        canonical_project_key=project_key,
        normalized_work_identity=identity,
        provider_identity=ProviderRecordIdentity(
            provider="linear",
            provider_record_type="issue",
            provider_record_id=record_id,
        ),
        title=title or record_id,
        classification=classification,
        classification_reason=f"Shared SID-243 classification: {classification.value}.",
        temporal=temporal or TemporalActionability(),
        identity_state=RealityIdentityState.EXACT,
        confidence=confidence,
        evidence=evidences,
        evidence_version=f"version-{record_id}",
        proposed_safe_resolution=resolution,
    )


def project(
    project_id,
    project_key,
    name,
    focus_state,
    items=(),
    *,
    complete=True,
    **focus_kwargs,
):
    return MorningProjectState(
        canonical_project_id=project_id,
        canonical_project_key=project_key,
        name=name,
        focus=focus(project_id, project_key, focus_state, **focus_kwargs),
        reality_items=tuple(items),
        reality_complete=complete,
        reality_total_count=len(tuple(items)),
        provider_diagnostics=() if complete else ("todoist: missing_history",),
    )


def change_window(*, complete=True):
    change_coverage = ChangeCoverage(
        provider="linear",
        scope_id="linear-scope",
        canonical_project_id="project-pcos",
        state=(
            ChangeComparisonState.COMPLETE_NO_CHANGES
            if complete
            else ChangeComparisonState.INCOMPLETE_HISTORY
        ),
        observed_at=NOW,
        historical_coverage_start=NOW - timedelta(days=60),
        retained_from=NOW - timedelta(days=60),
        last_success_at=NOW,
        observation_count=10,
    )
    checkpoint = MorningCheckpointSelection(
        consumer_id="morning-state",
        mode=MorningCheckpointMode.RETAINED_HISTORY_FALLBACK,
        selected_since=NOW - timedelta(days=30),
        fallback_scopes=("linear:linear-scope",),
        coverage_complete=complete,
        retained_boundaries=(NOW - timedelta(days=60),),
        diagnostics=() if complete else ("history incomplete",),
    )
    return MorningChangeWindow(
        checkpoint=checkpoint,
        coverage=(change_coverage,),
        total_count=0,
    )


def calendar(events=(), error=None):
    result = CalendarReadResult(events=list(events), error=error)
    state = normalize_calendar_time(list(events), now=NOW, local_tz=LOCAL_TZ)
    return state, result


class MorningStateTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.env = patch.dict(
            os.environ,
            {"APP_DB_PATH": os.path.join(self.tempdir.name, "morning-state.sqlite3")},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        ensure_database()

    def synthesize(
        self,
        projects,
        *,
        changes=None,
        events=(),
        calendar_error=None,
        section_limit=12,
    ):
        state, result = calendar(events, calendar_error)
        return MorningStateService().synthesize(
            projects=projects,
            change_window=changes or change_window(),
            calendar_state=state,
            calendar_result=result,
            evaluated_at=NOW,
            section_limit=section_limit,
        )

    def test_typed_contract_contains_all_five_sections_and_schema_version(self):
        result = self.synthesize(
            [project("project-pcos", "pcos", "PCOS", ProjectFocusState.ACTIVE_MOMENTUM)]
        )
        self.assertEqual(result.schema_version, MORNING_STATE_SCHEMA_VERSION)
        self.assertEqual(
            {
                result.changes_since_meaningful_check.section_id,
                result.attention_today.section_id,
                result.handled_paused_waiting.section_id,
                result.project_momentum_constraints.section_id,
                result.realistic_day_shape.section_id,
            },
            set(MorningSectionId),
        )
        for section in (
            result.changes_since_meaningful_check,
            result.attention_today,
            result.handled_paused_waiting,
            result.project_momentum_constraints,
            result.realistic_day_shape,
        ):
            self.assertEqual(section.schema_version, 1)
            self.assertTrue(section.statements)

    def test_statement_contract_requires_provenance_and_timezone_aware_time(self):
        with self.assertRaisesRegex(ValueError, "evidence references"):
            MorningStatement(
                statement_id="missing-evidence",
                section=MorningSectionId.ATTENTION_TODAY,
                classification=RealityClassification.UNKNOWN,
                status="unknown",
                summary="Unknown.",
                reason="No evidence.",
                source_evidence_references=(),
                observed_at=NOW,
                freshness=MorningFreshness.UNKNOWN,
                availability=MorningAvailability.UNKNOWN,
                fact_type=MorningFactType.DETERMINISTIC_CONCLUSION,
                confidence=MorningConfidence.UNKNOWN,
            )
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            MorningStatement(
                statement_id="naive",
                section=MorningSectionId.ATTENTION_TODAY,
                classification=RealityClassification.UNKNOWN,
                status="unknown",
                summary="Unknown.",
                reason="No time zone.",
                source_evidence_references=("evidence",),
                observed_at=datetime(2026, 8, 7, 10),
                freshness=MorningFreshness.UNKNOWN,
                availability=MorningAvailability.UNKNOWN,
                fact_type=MorningFactType.DETERMINISTIC_CONCLUSION,
                confidence=MorningConfidence.UNKNOWN,
            )

    def test_representative_cross_project_synthesis_is_grounded(self):
        mismatch_id = "freelance-follow-up"
        mismatch = reality_item(
            "project-freelance",
            "freelance",
            mismatch_id,
            RealityClassification.POTENTIAL_MISMATCH,
            title="Client follow-up",
            evidences=(
                evidence("project-freelance", mismatch_id, claim="open"),
                evidence(
                    "project-freelance",
                    mismatch_id,
                    provider="gmail",
                    evidence_type=RealityEvidenceType.COMMUNICATION_OUTCOME,
                    claim="sent",
                ),
            ),
            confidence=RealityConfidence.MEDIUM,
            resolution=SafeResolution(
                code="review_mark_work_handled",
                summary="Review the linked sent/open mismatch.",
                target_work_identity=WorkIdentity(
                    provider="linear", provider_record_id=mismatch_id
                ),
            ),
        )
        tomorrow = reality_item(
            "project-pcos",
            "pcos",
            "tomorrow-only",
            RealityClassification.UPCOMING_NOT_ACTIONABLE,
            temporal=TemporalActionability(
                earliest_useful_action_at=NOW + timedelta(days=1),
                action_possible_now=True,
                action_useful_now=False,
            ),
        )
        waiting = reality_item(
            "project-nebulo",
            "nebulo",
            "external-constraint",
            RealityClassification.WAITING,
            temporal=TemporalActionability(
                waiting_until=NOW + timedelta(days=3),
                action_possible_now=False,
                action_useful_now=False,
            ),
        )
        projects = [
            project("project-pcos", "pcos", "PCOS", ProjectFocusState.ACTIVE_MOMENTUM, (tomorrow,)),
            project("project-freelance", "freelance", "Freelance", ProjectFocusState.ACTIVE_MOMENTUM, (mismatch,)),
            project("project-xo", "xo", "XO", ProjectFocusState.DEDICATED_SESSION_NEEDED),
            project("project-nebulo", "nebulo", "Nebulo", ProjectFocusState.WAITING_EXTERNAL, (waiting,)),
        ]
        event = {
            "id": "class-1",
            "title": "Class",
            "start": (NOW + timedelta(hours=5)).isoformat(),
            "end": (NOW + timedelta(hours=6)).isoformat(),
            "busy": True,
            "all_day": False,
            "event_category": "hard",
        }
        result = self.synthesize(projects, events=(event,))
        attention = result.attention_today.statements
        self.assertEqual(attention[0].classification, RealityClassification.POTENTIAL_MISMATCH)
        self.assertEqual(result.briefing.primary_kind, "review")
        self.assertEqual(result.briefing.primary_statement_id, attention[0].statement_id)
        self.assertIn("not a command", result.briefing.summary)
        self.assertEqual(attention[0].suggested_action.performs_provider_mutation, False)
        self.assertTrue(any("open" in item for item in attention[0].source_evidence_summaries))
        self.assertTrue(any("sent" in item for item in attention[0].source_evidence_summaries))
        self.assertNotIn("tomorrow-only", [item.linked_work_identity.provider_record_id for item in attention if item.linked_work_identity])
        support_ids = {
            item.linked_work_identity.provider_record_id
            for item in result.handled_paused_waiting.statements
            if item.linked_work_identity
        }
        self.assertIn("tomorrow-only", support_ids)
        self.assertIn("external-constraint", support_ids)
        pulse = {item.canonical_project_key: item for item in result.project_momentum_constraints.statements}
        self.assertEqual(pulse["pcos"].status, "active_momentum")
        self.assertEqual(pulse["freelance"].status, "active_momentum")
        self.assertEqual(pulse["xo"].status, "dedicated_session_needed")
        self.assertEqual(pulse["nebulo"].status, "waiting_external")
        free_block = next(
            item for item in result.realistic_day_shape.statements if item.status == "usable_free_block"
        )
        self.assertIn("free block", free_block.summary)
        self.assertIsNone(free_block.suggested_action)

    def test_needs_action_leads_and_preparation_appears_only_from_reality(self):
        due = reality_item(
            "project-pcos",
            "pcos",
            "due-now",
            RealityClassification.NEEDS_ACTION,
            temporal=TemporalActionability(
                due_at=NOW,
                action_possible_now=True,
                action_useful_now=True,
            ),
        )
        preparation = reality_item(
            "project-pcos",
            "pcos",
            "prepare-now",
            RealityClassification.NEEDS_ACTION,
            temporal=TemporalActionability(
                preparation_window_start=NOW,
                hard_deadline=NOW + timedelta(days=1),
                action_possible_now=True,
                action_useful_now=True,
            ),
        )
        result = self.synthesize(
            [project("project-pcos", "pcos", "PCOS", ProjectFocusState.ACTIVE_MOMENTUM, (due, preparation,))]
        )
        self.assertEqual(
            [item.classification for item in result.attention_today.statements],
            [RealityClassification.NEEDS_ACTION, RealityClassification.NEEDS_ACTION],
        )
        self.assertEqual(result.urgent_attention_count, 2)
        self.assertEqual(result.overall_classification, RealityClassification.NEEDS_ACTION)
        self.assertEqual(result.briefing.primary_kind, "move")
        self.assertEqual(
            result.briefing.primary_statement_id,
            result.attention_today.statements[0].statement_id,
        )
        self.assertIn("One move", result.briefing.headline)

    def test_structured_due_date_and_explicit_title_date_conflict_becomes_review_first(self):
        suspicious = reality_item(
            "project-pcos",
            "pcos",
            "date-conflict",
            RealityClassification.NEEDS_ACTION,
            title="try to move in Aug 15th",
            temporal=TemporalActionability(
                due_date=NOW.date(),
                action_possible_now=True,
                action_useful_now=True,
            ),
        )
        result = self.synthesize(
            [project("project-pcos", "pcos", "PCOS", ProjectFocusState.ACTIVE_MOMENTUM, (suspicious,))]
        )
        self.assertEqual(result.attention_today.statements[0].classification, RealityClassification.NEEDS_ACTION)
        self.assertEqual(result.briefing.primary_kind, "review")
        self.assertEqual(result.briefing.headline, "Confirm the move-in task’s date.")
        self.assertEqual(
            result.briefing.primary_caution,
            "The task title says Aug 15, but its Linear due date says Aug 7.",
        )
        self.assertEqual(
            result.briefing.review_cautions[result.briefing.primary_statement_id],
            result.briefing.primary_caution,
        )

    def test_tomorrow_only_never_competes_for_attention(self):
        tomorrow = reality_item(
            "project-pcos",
            "pcos",
            "tomorrow",
            RealityClassification.UPCOMING_NOT_ACTIONABLE,
            temporal=TemporalActionability(
                earliest_useful_action_at=NOW + timedelta(days=1),
                action_useful_now=False,
            ),
        )
        result = self.synthesize(
            [project("project-pcos", "pcos", "PCOS", ProjectFocusState.ACTIVE_MOMENTUM, (tomorrow,))]
        )
        self.assertEqual(result.attention_today.statements[0].status, "no_urgent_attention")
        self.assertEqual(
            result.handled_paused_waiting.statements[0].classification,
            RealityClassification.UPCOMING_NOT_ACTIONABLE,
        )

    def test_wrong_context_correction_stays_reviewable_without_becoming_urgent(self):
        mismatch = reality_item(
            "project-pcos",
            "pcos",
            "disputed-context",
            RealityClassification.POTENTIAL_MISMATCH,
        )
        projects = [
            project(
                "project-pcos",
                "pcos",
                "PCOS",
                ProjectFocusState.ACTIVE_MOMENTUM,
                (mismatch,),
            )
        ]
        initial = self.synthesize(projects)
        statement = initial.attention_today.statements[0]
        MorningCorrectionService().create(
            MorningCorrectionRequest(
                synthesis_id=initial.synthesis_id,
                evaluated_at=initial.evaluated_at,
                statement_id=statement.statement_id,
                evidence_version=statement.evidence_version,
                correction_type=MorningCorrectionType.WRONG_CONTEXT,
                correcting_actor="user-primary",
                idempotency_key="wrong-context-visible",
            ),
            synthesis=initial,
            created_at=NOW,
        )

        corrected = self.synthesize(projects)
        visible = next(
            item
            for item in corrected.attention_today.statements
            if item.linked_work_identity
            and item.linked_work_identity.provider_record_id == "disputed-context"
        )
        self.assertEqual(visible.classification, RealityClassification.UNKNOWN)
        self.assertIn("explicitly disputed", visible.reason)
        self.assertEqual(corrected.urgent_attention_count, 0)

    def test_waiting_and_handled_reassure_without_becoming_attention(self):
        items = (
            reality_item("project-pcos", "pcos", "handled", RealityClassification.ALREADY_HANDLED),
            reality_item("project-pcos", "pcos", "waiting", RealityClassification.WAITING),
        )
        result = self.synthesize(
            [project("project-pcos", "pcos", "PCOS", ProjectFocusState.ACTIVE_MOMENTUM, items)]
        )
        self.assertEqual(result.urgent_attention_count, 0)
        self.assertEqual(
            {item.classification for item in result.handled_paused_waiting.statements},
            {RealityClassification.ALREADY_HANDLED, RealityClassification.WAITING},
        )
        self.assertEqual(result.briefing.handled_count, 1)
        self.assertEqual(result.briefing.waiting_count, 1)
        self.assertEqual(result.briefing.upcoming_count, 0)
        self.assertLessEqual(len(result.briefing.support_statement_ids), 3)

    def test_intentional_pause_requires_explicit_focus_state(self):
        intent = ExplicitProjectIntent(
            id="pause-1",
            canonical_project_id="project-xo",
            confirmed_state=ProjectFocusState.INTENTIONALLY_PAUSED,
            reason="Waiting for a reviewed restart window.",
            confirmed_at=NOW - timedelta(days=1),
            review_after=NOW + timedelta(days=7),
        )
        paused = project(
            "project-xo",
            "xo",
            "XO",
            ProjectFocusState.INTENTIONALLY_PAUSED,
            explicit_intent=intent,
        )
        quiet = project(
            "project-nebulo",
            "nebulo",
            "Nebulo",
            ProjectFocusState.QUIET_POSSIBLE_DRIFT,
        )
        result = self.synthesize((paused, quiet))
        pauses = [item for item in result.handled_paused_waiting.statements if item.status == "intentionally_paused"]
        self.assertEqual(len(pauses), 1)
        self.assertEqual(pauses[0].canonical_project_key, "xo")
        self.assertEqual(pauses[0].fact_type, MorningFactType.EXPLICIT_FACT)
        quiet_pulse = next(item for item in result.project_momentum_constraints.statements if item.canonical_project_key == "nebulo")
        self.assertEqual(quiet_pulse.classification, RealityClassification.UNKNOWN)
        self.assertEqual(quiet_pulse.fact_type, MorningFactType.INFERENCE)

    def test_focused_confirmation_question_is_preserved(self):
        project_state = project(
            "project-xo",
            "xo",
            "XO",
            ProjectFocusState.DEDICATED_SESSION_NEEDED,
            confirmation_question="Should XO remain queued for a dedicated session?",
        )
        result = self.synthesize((project_state,))
        pulse = result.project_momentum_constraints.statements[0]
        self.assertEqual(pulse.suggested_action.code, "confirm_project_focus")
        self.assertEqual(pulse.suggested_action.performs_provider_mutation, False)

    def test_no_action_is_first_class_only_with_complete_evidence(self):
        complete = self.synthesize(
            [project("project-pcos", "pcos", "PCOS", ProjectFocusState.ACTIVE_MOMENTUM)]
        )
        self.assertTrue(complete.no_urgent_attention)
        self.assertEqual(complete.overall_classification, RealityClassification.NO_MEANINGFUL_CHANGE)
        self.assertIsNone(complete.briefing.primary_kind)
        self.assertIsNone(complete.briefing.primary_statement_id)
        self.assertIn("without an urgent catch-up", complete.briefing.headline)
        incomplete = self.synthesize(
            [project("project-pcos", "pcos", "PCOS", ProjectFocusState.INSUFFICIENT_EVIDENCE, complete=False)]
        )
        self.assertFalse(incomplete.no_urgent_attention)
        self.assertEqual(incomplete.overall_classification, RealityClassification.UNKNOWN)
        self.assertEqual(incomplete.attention_today.statements[0].classification, RealityClassification.UNKNOWN)
        self.assertIn("evidence gaps", incomplete.briefing.headline)

    def test_briefing_compresses_many_under_control_items_without_losing_counts(self):
        items = tuple(
            reality_item(
                "project-pcos",
                "pcos",
                f"handled-{index:02d}",
                RealityClassification.ALREADY_HANDLED,
            )
            for index in range(18)
        ) + tuple(
            reality_item(
                "project-pcos",
                "pcos",
                f"waiting-{index:02d}",
                RealityClassification.WAITING,
            )
            for index in range(7)
        ) + tuple(
            reality_item(
                "project-pcos",
                "pcos",
                f"later-{index:02d}",
                RealityClassification.UPCOMING_NOT_ACTIONABLE,
            )
            for index in range(5)
        )
        result = self.synthesize(
            [project("project-pcos", "pcos", "PCOS", ProjectFocusState.ACTIVE_MOMENTUM, items)]
        )
        self.assertEqual(result.briefing.handled_count, 18)
        self.assertEqual(result.briefing.waiting_count, 7)
        self.assertEqual(result.briefing.upcoming_count, 5)
        self.assertEqual(len(result.briefing.support_statement_ids), 3)
        self.assertEqual(result.handled_paused_waiting.total_count, 30)

    def test_briefing_change_projection_counts_only_real_provider_events(self):
        calm = self.synthesize(
            [project("project-pcos", "pcos", "PCOS", ProjectFocusState.ACTIVE_MOMENTUM)]
        )
        self.assertEqual(calm.briefing.material_change_count, 0)
        self.assertEqual(calm.briefing.material_change_statement_ids, ())

    def test_stale_and_failed_evidence_remain_visible(self):
        stale_item = reality_item(
            "project-pcos",
            "pcos",
            "stale",
            RealityClassification.UNKNOWN,
            evidences=(
                evidence(
                    "project-pcos",
                    "stale",
                    freshness=RealityFreshness.STALE,
                    availability=RealityAvailability.UNAVAILABLE,
                ),
            ),
            confidence=RealityConfidence.LOW,
        )
        result = self.synthesize(
            [project("project-pcos", "pcos", "PCOS", ProjectFocusState.INSUFFICIENT_EVIDENCE, (stale_item,), complete=False)],
            changes=change_window(complete=False),
            calendar_error="Calendar provider failed",
        )
        self.assertFalse(result.complete_evidence)
        self.assertEqual(result.changes_since_meaningful_check.statements[0].classification, RealityClassification.UNKNOWN)
        self.assertEqual(result.realistic_day_shape.statements[0].availability, MorningAvailability.UNAVAILABLE)
        self.assertIn("Calendar provider failed", result.provider_diagnostics)

    def test_large_free_block_is_context_not_a_manufactured_command(self):
        event = {
            "id": "afternoon-event",
            "title": "Afternoon commitment",
            "start": (NOW + timedelta(hours=5)).isoformat(),
            "end": (NOW + timedelta(hours=6)).isoformat(),
            "busy": True,
            "all_day": False,
            "event_category": "hard",
        }
        result = self.synthesize(
            [project("project-pcos", "pcos", "PCOS", ProjectFocusState.ACTIVE_MOMENTUM)],
            events=(event,),
        )
        free = next(item for item in result.realistic_day_shape.statements if item.status == "usable_free_block")
        self.assertIn("300-minute", free.summary)
        self.assertEqual(free.classification, RealityClassification.NO_MEANINGFUL_CHANGE)
        self.assertIsNone(free.suggested_action)

    def test_scheduled_commitment_never_claims_attendance_or_completion(self):
        event = {
            "id": "meeting",
            "title": "Project meeting",
            "start": (NOW + timedelta(hours=1)).isoformat(),
            "end": (NOW + timedelta(hours=2)).isoformat(),
            "busy": True,
            "all_day": False,
            "event_category": "hard",
        }
        result = self.synthesize(
            [project("project-pcos", "pcos", "PCOS", ProjectFocusState.ACTIVE_MOMENTUM)],
            events=(event,),
        )
        commitment = next(item for item in result.realistic_day_shape.statements if item.status == "fixed_commitment")
        self.assertIn("scheduled", commitment.summary)
        self.assertIn("not attendance or completion", commitment.reason)

    def test_complete_set_counts_are_preserved_before_bounding(self):
        items = tuple(
            reality_item(
                "project-pcos",
                "pcos",
                f"due-{index:02d}",
                RealityClassification.NEEDS_ACTION,
                temporal=TemporalActionability(
                    due_at=NOW + timedelta(minutes=index),
                    action_possible_now=True,
                    action_useful_now=True,
                ),
            )
            for index in range(20)
        )
        result = self.synthesize(
            [project("project-pcos", "pcos", "PCOS", ProjectFocusState.ACTIVE_MOMENTUM, items)],
            section_limit=5,
        )
        self.assertEqual(result.attention_today.total_count, 20)
        self.assertEqual(result.attention_today.returned_count, 5)
        self.assertTrue(result.attention_today.truncated)
        self.assertEqual(result.urgent_attention_count, 20)

    def test_order_and_repeated_reads_are_deterministic(self):
        items = tuple(
            reality_item(
                "project-pcos",
                "pcos",
                record_id,
                RealityClassification.NEEDS_ACTION,
                temporal=TemporalActionability(
                    due_at=NOW + timedelta(hours=offset),
                    action_possible_now=True,
                    action_useful_now=True,
                ),
            )
            for record_id, offset in (("later", 2), ("earlier", 1))
        )
        projects = [project("project-pcos", "pcos", "PCOS", ProjectFocusState.ACTIVE_MOMENTUM, items)]
        first = self.synthesize(projects)
        second = self.synthesize(projects)
        self.assertEqual(first.model_dump(), second.model_dump())
        self.assertEqual(
            [item.linked_work_identity.provider_record_id for item in first.attention_today.statements],
            ["earlier", "later"],
        )

    def test_canonical_identity_not_title_controls_statement_identity(self):
        first = reality_item(
            "project-pcos",
            "pcos",
            "issue-1",
            RealityClassification.UNKNOWN,
            title="Same title",
        )
        second = reality_item(
            "project-freelance",
            "freelance",
            "issue-2",
            RealityClassification.UNKNOWN,
            title="Same title",
        )
        result = self.synthesize(
            (
                project("project-pcos", "pcos", "PCOS", ProjectFocusState.INSUFFICIENT_EVIDENCE, (first,), complete=False),
                project("project-freelance", "freelance", "Freelance", ProjectFocusState.INSUFFICIENT_EVIDENCE, (second,), complete=False),
            )
        )
        pulse_ids = {item.statement_id for item in result.project_momentum_constraints.statements}
        self.assertEqual(len(pulse_ids), 2)
        self.assertNotEqual(first.reality_item_id, second.reality_item_id)

    def test_checkpoint_metadata_documents_non_mutating_fallback(self):
        window = change_window()
        result = self.synthesize(
            [project("project-pcos", "pcos", "PCOS", ProjectFocusState.ACTIVE_MOMENTUM)],
            changes=window,
        )
        self.assertEqual(result.checkpoint.mode, MorningCheckpointMode.RETAINED_HISTORY_FALLBACK)
        self.assertEqual(result.checkpoint.fallback_days, 30)
        self.assertFalse(result.checkpoint.ordinary_read_acknowledges)


class MorningCheckpointSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.env = patch.dict(
            os.environ,
            {"APP_DB_PATH": os.path.join(self.tempdir.name, "morning.sqlite3")},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        ensure_database()
        self.service = MorningStateService(change_service=provider_change_service)

    def observation(self, *, priority, observed_at, updated_at):
        return ProviderObservation(
            canonical_project_id="project-pcos",
            provider="linear",
            scope_id="linear-project",
            provider_record_type="issue",
            provider_record_id="issue-1",
            provider_revision=updated_at.isoformat(),
            source_created_at=NOW - timedelta(days=60),
            source_updated_at=updated_at,
            observed_at=observed_at,
            normalized_status="started",
            completion_state=CompletionState.INCOMPLETE,
            priority=priority,
            evidence=ProviderEvidenceReference(
                provider_reference="linear-project",
                provider_identifier="SID-244",
            ),
        )

    def observe(self, *, priority, observed_at, updated_at):
        return provider_change_service.observe_scope(
            provider="linear",
            scope_id="linear-project",
            canonical_project_id="project-pcos",
            observations=(
                self.observation(
                    priority=priority,
                    observed_at=observed_at,
                    updated_at=updated_at,
                ),
            ),
            observed_at=observed_at,
            historical_coverage_start=NOW - timedelta(days=60),
        )

    def test_no_checkpoint_uses_complete_retained_history_fallback(self):
        self.observe(
            priority=1,
            observed_at=NOW - timedelta(hours=2),
            updated_at=NOW - timedelta(hours=3),
        )
        changed = self.observe(
            priority=2,
            observed_at=NOW,
            updated_at=NOW - timedelta(hours=1),
        )
        window = self.service._change_window(
            consumer_id="morning-state",
            evaluated_at=NOW,
        )
        self.assertEqual(window.checkpoint.mode, MorningCheckpointMode.RETAINED_HISTORY_FALLBACK)
        self.assertTrue(window.checkpoint.coverage_complete)
        self.assertEqual(window.total_count, len(changed.changes))
        self.assertEqual(
            {item.id for item in window.changes},
            {item.id for item in changed.changes},
        )

    def test_explicit_checkpoint_is_preferred_and_ordinary_read_does_not_advance_it(self):
        self.observe(
            priority=1,
            observed_at=NOW - timedelta(hours=3),
            updated_at=NOW - timedelta(hours=4),
        )
        first_change = self.observe(
            priority=2,
            observed_at=NOW - timedelta(hours=2),
            updated_at=NOW - timedelta(hours=2, minutes=30),
        ).changes[0]
        provider_change_service.acknowledge(
            consumer_id="morning-state",
            provider="linear",
            scope_id="linear-project",
            through_cursor=_encode_cursor(
                first_change.effective_at.isoformat(),
                first_change.event_position,
            ),
            acknowledged_at=NOW - timedelta(hours=1),
        )
        second_change = self.observe(
            priority=3,
            observed_at=NOW,
            updated_at=NOW - timedelta(minutes=30),
        ).changes[0]
        with database_connection() as connection:
            before = connection.execute(
                "SELECT * FROM provider_change_consumers"
            ).fetchall()
        first = self.service._change_window(
            consumer_id="morning-state", evaluated_at=NOW
        )
        second = self.service._change_window(
            consumer_id="morning-state", evaluated_at=NOW
        )
        with database_connection() as connection:
            after = connection.execute(
                "SELECT * FROM provider_change_consumers"
            ).fetchall()
        self.assertEqual(first.checkpoint.mode, MorningCheckpointMode.ACKNOWLEDGED_CHECKPOINT)
        self.assertEqual([item.id for item in first.changes], [second_change.id])
        self.assertEqual(first.model_dump(), second.model_dump())
        self.assertEqual([tuple(row) for row in before], [tuple(row) for row in after])

    def test_retained_boundary_after_fallback_is_explicitly_incomplete(self):
        self.observe(
            priority=1,
            observed_at=NOW - timedelta(hours=1),
            updated_at=NOW - timedelta(hours=2),
        )
        with database_connection() as connection:
            connection.execute(
                "UPDATE provider_change_scopes SET retained_from = ?",
                ((NOW - timedelta(days=5)).isoformat(),),
            )
        window = self.service._change_window(
            consumer_id="morning-state", evaluated_at=NOW
        )
        self.assertFalse(window.checkpoint.coverage_complete)
        self.assertTrue(
            any("does not completely cover" in item for item in window.checkpoint.diagnostics)
        )

    def test_future_skewed_checkpoint_falls_back_without_poisoning_order(self):
        self.observe(
            priority=1,
            observed_at=NOW - timedelta(hours=1),
            updated_at=NOW - timedelta(hours=2),
        )
        provider_change_service.acknowledge(
            consumer_id="morning-state",
            provider="linear",
            scope_id="linear-project",
            through_cursor=_encode_cursor(
                (NOW + timedelta(days=2)).isoformat(),
                999,
            ),
            acknowledged_at=NOW,
        )
        window = self.service._change_window(
            consumer_id="morning-state", evaluated_at=NOW
        )
        self.assertEqual(window.checkpoint.mode, MorningCheckpointMode.RETAINED_HISTORY_FALLBACK)
        self.assertTrue(
            any("future-skewed" in item for item in window.checkpoint.diagnostics)
        )


if __name__ == "__main__":
    unittest.main()
