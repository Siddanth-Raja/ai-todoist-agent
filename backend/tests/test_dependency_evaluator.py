from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.dependency_evaluator import (  # noqa: E402
    DependencyEvaluationState,
    dependency_evaluator,
    summarize_dependency_evidence,
)
from app.project_registry import ProjectRegistrySnapshot  # noqa: E402
from app.work_domain import (  # noqa: E402
    NormalizedWorkItem,
    WorkDependency,
    WorkPriority,
    WorkStatus,
)


FREELANCE_ID = "project-freelance"
FREELANCE_PROVIDER_ID = "2bde590c-a8ab-4f4e-81eb-f7a8da8c1833"
NEBULO_ID = "project-nebulo"
NEBULO_PROVIDER_ID = "d9fdfe44-3e66-4dc0-b564-b2bcb646e635"


def registry() -> ProjectRegistrySnapshot:
    def project(canonical_id, key, provider_id):
        return {
            "canonical_project_id": canonical_id,
            "key": key,
            "name": key.title(),
            "provider_mappings": (
                {
                    "id": f"mapping-{key}",
                    "provider": "linear",
                    "resource_type": "project",
                    "provider_ref": provider_id,
                    "enabled": True,
                },
            ),
        }

    return ProjectRegistrySnapshot(
        projects=(
            project(FREELANCE_ID, "freelance", FREELANCE_PROVIDER_ID),
            project(NEBULO_ID, "nebulo", NEBULO_PROVIDER_ID),
        ),
        aliases={},
    )


def item(
    record_id: str,
    identifier: str,
    *,
    status: WorkStatus = WorkStatus.OPEN,
    blocked_by: tuple[str, ...] = (),
    relations: list[dict] | None = None,
    canonical_project_id: str = FREELANCE_ID,
    provider_project_id: str = FREELANCE_PROVIDER_ID,
    title: str | None = None,
    milestone: str | None = None,
) -> NormalizedWorkItem:
    return NormalizedWorkItem(
        provider="linear",
        provider_record_id=record_id,
        canonical_project_id=canonical_project_id,
        title=title or identifier,
        status=status,
        original_provider_status={
            WorkStatus.OPEN: "In Progress",
            WorkStatus.COMPLETED: "Done",
            WorkStatus.CANCELED: "Canceled",
        }[status],
        priority=WorkPriority.MEDIUM,
        is_executable=status == WorkStatus.OPEN,
        is_blocked=False,
        dependencies=tuple(
            WorkDependency(
                provider="linear",
                provider_record_id=blocker_id,
                dependency_type="blocked_by",
            )
            for blocker_id in blocked_by
        ),
        provider_url=f"https://linear.app/example/issue/{identifier}",
        provider_metadata={
            "issue_identifier": identifier,
            "provider_project_id": provider_project_id,
            "inverse_relations": relations or [],
            "project_milestone": (
                {"id": milestone, "name": milestone} if milestone else None
            ),
        },
    )


def relation(
    blocker_id: str,
    identifier: str,
    *,
    state_type: str | None,
    state_name: str | None = None,
    project_id: str = FREELANCE_PROVIDER_ID,
) -> dict:
    state = (
        {"type": state_type, "name": state_name or state_type.title()}
        if state_type is not None
        else None
    )
    return {
        "id": f"relation-{blocker_id}",
        "type": "blocks",
        "issue": {
            "id": blocker_id,
            "identifier": identifier,
            "title": f"Blocker {identifier}",
            "state": state,
            "url": f"https://linear.app/example/issue/{identifier}",
            "project": {"id": project_id, "name": "Renamed project"},
        },
    }


class DependencyEvaluatorTests(unittest.TestCase):
    def evaluate(self, items):
        return dependency_evaluator.evaluate(items, registry=registry())

    def test_open_blocker_is_active_and_prevents_execution(self):
        blocker = item("blocker", "SID-173")
        blocked = item(
            "blocked",
            "SID-174",
            blocked_by=("blocker",),
            relations=[relation("blocker", "SID-173", state_type="started")],
        )
        result = self.evaluate([blocker, blocked])
        by_id = {work.provider_record_id: work for work in result.work_items}
        evidence = result.evidence[0]

        self.assertEqual(evidence.evaluation_state, DependencyEvaluationState.ACTIVE)
        self.assertTrue(by_id["blocked"].is_blocked)
        self.assertFalse(by_id["blocked"].is_executable)
        self.assertIn("open SID-173", evidence.explanation)

    def test_completed_blocker_releases_execution_and_preserves_evidence(self):
        blocker = item("blocker", "SID-173", status=WorkStatus.COMPLETED)
        blocked = item(
            "blocked",
            "SID-174",
            blocked_by=("blocker",),
            relations=[relation("blocker", "SID-173", state_type="started")],
        )
        result = self.evaluate([blocker, blocked])
        by_id = {work.provider_record_id: work for work in result.work_items}
        evidence = result.evidence[0]

        self.assertEqual(evidence.evaluation_state, DependencyEvaluationState.RESOLVED)
        self.assertFalse(by_id["blocked"].is_blocked)
        self.assertTrue(by_id["blocked"].is_executable)
        self.assertEqual(by_id["blocked"].dependencies[0].provider_record_id, "blocker")
        self.assertIn("no longer blocks SID-174", evidence.explanation)

    def test_canceled_blocker_requires_review_and_prevents_execution(self):
        blocker = item("blocker", "SID-173", status=WorkStatus.CANCELED)
        blocked = item("blocked", "SID-174", blocked_by=("blocker",))
        result = self.evaluate([blocker, blocked])

        self.assertEqual(
            result.evidence[0].evaluation_state,
            DependencyEvaluationState.NEEDS_REVIEW,
        )
        self.assertTrue(result.work_items[1].is_blocked)
        self.assertFalse(result.work_items[1].is_executable)
        self.assertIn("was canceled", result.evidence[0].explanation)

    def test_missing_or_malformed_blocker_requires_review(self):
        cases = [
            [],
            [relation("blocker", "SID-173", state_type=None)],
            [{"id": "broken", "type": "blocks", "issue": {"id": "other"}}],
        ]
        for relations in cases:
            with self.subTest(relations=relations):
                blocked = item(
                    "blocked",
                    "SID-174",
                    blocked_by=("blocker",),
                    relations=relations,
                )
                result = self.evaluate([blocked])
                self.assertEqual(
                    result.evidence[0].evaluation_state,
                    DependencyEvaluationState.NEEDS_REVIEW,
                )
                self.assertFalse(result.work_items[0].is_executable)

    def test_cross_project_relation_uses_structured_state_without_reassignment(self):
        blocked = item(
            "blocked",
            "SID-174",
            blocked_by=("nebulo-blocker",),
            relations=[
                relation(
                    "nebulo-blocker",
                    "SID-103",
                    state_type="started",
                    project_id=NEBULO_PROVIDER_ID,
                )
            ],
        )
        result = self.evaluate([blocked])
        evidence = result.evidence[0]

        self.assertEqual(evidence.canonical_project_id, FREELANCE_ID)
        self.assertEqual(evidence.blocked_work.canonical_project_id, FREELANCE_ID)
        self.assertEqual(evidence.blocking_work.canonical_project_id, NEBULO_ID)
        self.assertEqual(evidence.evaluation_state, DependencyEvaluationState.ACTIVE)

    def test_multiple_dependencies_use_mixed_evidence_conservatively(self):
        completed = item("completed", "SID-170", status=WorkStatus.COMPLETED)
        open_blocker = item("open", "SID-171")
        blocked = item(
            "blocked",
            "SID-174",
            blocked_by=("completed", "open", "unknown"),
        )
        result = self.evaluate([completed, open_blocker, blocked])
        states = {evidence.evaluation_state for evidence in result.evidence}

        self.assertEqual(
            states,
            {
                DependencyEvaluationState.RESOLVED,
                DependencyEvaluationState.ACTIVE,
                DependencyEvaluationState.NEEDS_REVIEW,
            },
        )
        self.assertFalse(result.work_items[-1].is_executable)

    def test_duplicate_dependency_edges_are_evaluated_and_counted_once(self):
        blocker = item("blocker", "SID-173")
        blocked = item(
            "blocked",
            "SID-174",
            blocked_by=("blocker", "blocker"),
            relations=[
                relation("blocker", "SID-173", state_type="started"),
                relation("blocker", "SID-173", state_type="started"),
            ],
        )

        result = self.evaluate([blocker, blocked])
        summary = summarize_dependency_evidence(result.evidence)

        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(summary.active_dependency_count, 1)
        self.assertEqual(summary.active_blocked_work_count, 1)
        self.assertTrue(result.work_items[1].is_blocked)

    def test_summary_separates_active_review_and_resolved_evidence(self):
        completed = item("completed", "SID-170", status=WorkStatus.COMPLETED)
        canceled = item("canceled", "SID-171", status=WorkStatus.CANCELED)
        open_blocker = item("open", "SID-172")
        blocked = item(
            "blocked",
            "SID-174",
            blocked_by=("completed", "canceled", "open"),
        )

        result = self.evaluate([completed, canceled, open_blocker, blocked])
        summary = summarize_dependency_evidence(result.evidence)

        self.assertEqual(summary.active_dependency_count, 1)
        self.assertEqual(summary.needs_review_dependency_count, 1)
        self.assertEqual(summary.resolved_dependency_count, 1)
        self.assertEqual(summary.active_blocked_work_count, 1)
        self.assertEqual(summary.needs_review_blocked_work_count, 1)

    def test_summary_excludes_noncurrent_downstream_work_from_current_counts(self):
        open_blocker = item("open", "SID-170")
        canceled_blocker = item("canceled", "SID-171", status=WorkStatus.CANCELED)
        completed_downstream = item(
            "completed-downstream",
            "SID-172",
            status=WorkStatus.COMPLETED,
            blocked_by=("open", "canceled"),
        )

        result = self.evaluate([open_blocker, canceled_blocker, completed_downstream])
        summary = summarize_dependency_evidence(result.evidence)

        self.assertEqual(summary.active_dependency_count, 0)
        self.assertEqual(summary.needs_review_dependency_count, 0)

    def test_live_freelance_chain_releases_174_but_keeps_downstream_blocked(self):
        sid_173 = item("sid-173-uuid", "SID-173", status=WorkStatus.COMPLETED)
        sid_174 = item(
            "sid-174-uuid",
            "SID-174",
            blocked_by=("sid-173-uuid",),
        )
        downstream = [
            item(
                f"sid-{number}-uuid",
                f"SID-{number}",
                blocked_by=("sid-174-uuid",),
            )
            for number in range(175, 179)
        ]
        result = self.evaluate([sid_173, sid_174, *downstream])
        by_identifier = {
            work.provider_metadata["issue_identifier"]: work
            for work in result.work_items
        }

        self.assertTrue(by_identifier["SID-174"].is_executable)
        self.assertFalse(by_identifier["SID-174"].is_blocked)
        for number in range(175, 179):
            self.assertFalse(by_identifier[f"SID-{number}"].is_executable)
            self.assertTrue(by_identifier[f"SID-{number}"].is_blocked)

    def test_nebulo_open_blocker_is_grounded_but_keywords_and_milestones_are_not(self):
        blocker = item(
            "nebulo-blocker",
            "SID-103",
            canonical_project_id=NEBULO_ID,
            provider_project_id=NEBULO_PROVIDER_ID,
        )
        blocked = item(
            "nebulo-blocked",
            "SID-104",
            canonical_project_id=NEBULO_ID,
            provider_project_id=NEBULO_PROVIDER_ID,
            blocked_by=("nebulo-blocker",),
            milestone="Demo 2",
        )
        textual = item(
            "textual",
            "SID-105",
            canonical_project_id=NEBULO_ID,
            provider_project_id=NEBULO_PROVIDER_ID,
            title="Blocked by Demo 1",
            milestone="Demo 3",
        )
        result = self.evaluate([blocker, blocked, textual])
        by_id = {work.provider_record_id: work for work in result.work_items}

        self.assertEqual(len(result.evidence), 1)
        self.assertFalse(by_id["nebulo-blocked"].is_executable)
        self.assertTrue(by_id["textual"].is_executable)
        self.assertFalse(by_id["textual"].is_blocked)


if __name__ == "__main__":
    unittest.main()
