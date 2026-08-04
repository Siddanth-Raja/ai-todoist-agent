from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.linear_client import (  # noqa: E402
    LinearClient,
    LinearHealthResult,
    LinearProviderError,
)
from app.linear_work_adapter import (  # noqa: E402
    linear_work_adapter,
    normalize_linear_priority,
    normalize_linear_status,
)
from app.work_domain import WorkEffortSize, WorkPriority, WorkStatus  # noqa: E402


def settings(linear_api_key="linear-secret"):
    return Settings(
        todoist_api_token=None,
        google_client_id=None,
        google_client_secret=None,
        google_refresh_token=None,
        google_calendar_id="primary",
        timezone="America/Chicago",
        openai_api_key=None,
        openai_model="test",
        agent_api_key=None,
        linear_api_key=linear_api_key,
    )


def response(payload, *, status_code=200):
    result = Mock()
    result.status_code = status_code
    result.json.return_value = payload
    if status_code >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(response=result)
    return result


def connection(nodes, *, has_next=False, cursor=None):
    return {
        "nodes": nodes,
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
    }


def issue(**overrides):
    value = {
        "id": "issue-uuid",
        "identifier": "SID-133",
        "title": "Implement Linear adapter",
        "description": "Read-only integration",
        "estimate": None,
        "priority": 2,
        "priorityLabel": "High",
        "createdAt": "2026-07-01T10:00:00.000Z",
        "updatedAt": "2026-07-12T12:00:00.000Z",
        "completedAt": None,
        "canceledAt": None,
        "dueDate": "2026-07-20",
        "url": "https://linear.app/example/issue/SID-133",
        "state": {"id": "state-started", "name": "In Progress", "type": "started"},
        "project": {"id": "project-uuid", "name": "PCOS"},
        "parent": None,
        "projectMilestone": {"id": "milestone-uuid", "name": "Milestone 3", "targetDate": "2026-07-31"},
        "assignee": {"id": "user-uuid", "name": "Siddanth", "email": "s@example.com"},
        "team": {"id": "team-uuid", "key": "SID", "name": "Siddanth"},
        "labels": connection([]),
        "relations": connection([]),
        "inverseRelations": connection([]),
    }
    value.update(overrides)
    return value


class LinearClientTests(unittest.TestCase):
    def test_missing_api_key_is_optional_and_structured(self):
        client = LinearClient(settings(None), session=Mock())
        self.assertEqual(client.check_health().state, "not_configured")
        result = client.list_issues()
        self.assertEqual(result.error.code, "not_configured")
        self.assertEqual(result.records, [])

    def test_successful_and_failed_health_checks(self):
        session = Mock()
        session.post.return_value = response({"data": {"viewer": {"id": "user-uuid"}}})
        self.assertEqual(LinearClient(settings(), session=session).check_health().state, "connected")
        self.assertEqual(session.post.call_args.kwargs["headers"]["Authorization"], "linear-secret")

        session.post.return_value = response({"data": None, "errors": [{"message": "upstream unavailable"}]})
        failed = LinearClient(settings(), session=session).check_health()
        self.assertEqual(failed.state, "provider_failure")
        self.assertEqual(failed.error.code, "provider")
        self.assertNotIn("linear-secret", failed.error.message)

    def test_http_and_graphql_authentication_failures_are_distinguished(self):
        session = Mock()
        session.post.return_value = response({}, status_code=401)
        result = LinearClient(settings(), session=session).list_projects()
        self.assertEqual(result.error.code, "authentication")
        self.assertEqual(result.error.http_status, 401)

        session.post.return_value = response({
            "errors": [{"message": "permission denied", "extensions": {"code": "FORBIDDEN"}}],
            "data": None,
        })
        health = LinearClient(settings(), session=session).check_health()
        self.assertEqual(health.state, "authentication_failure")

    def test_network_failure_is_structured_as_provider_failure(self):
        session = Mock()
        session.post.side_effect = requests.Timeout("do not expose request details")
        health = LinearClient(settings(), session=session).check_health()
        self.assertEqual(health.state, "provider_failure")
        self.assertEqual(health.error.code, "provider")
        self.assertEqual(health.error.message, "Could not reach Linear: Timeout.")

    def test_project_and_issue_pagination(self):
        session = Mock()
        session.post.side_effect = [
            response({"data": {"projects": connection([
                {"id": "project-1", "name": "PCOS", "state": "started", "url": "https://linear.app/p/1", "priority": 1, "startDate": "2026-07-01", "targetDate": "2026-07-31", "updatedAt": "2026-07-12T00:00:00Z"}
            ], has_next=True, cursor="project-cursor")}}),
            response({"data": {"projects": connection([
                {"id": "project-2", "name": "XO", "state": "planned", "url": "https://linear.app/p/2", "priority": 2, "startDate": None, "targetDate": None, "updatedAt": "2026-07-11T00:00:00Z"}
            ])}}),
        ]
        result = LinearClient(settings(), session=session).list_projects()
        self.assertEqual([project["id"] for project in result.records], ["project-1", "project-2"])
        self.assertEqual(session.post.call_args_list[1].kwargs["json"]["variables"]["after"], "project-cursor")

        session.post.side_effect = [
            response({"data": {"issues": connection([issue(id="issue-1", identifier="SID-1")], has_next=True, cursor="issue-cursor")}}),
            response({"data": {"issues": connection([issue(id="issue-2", identifier="SID-2")])}}),
        ]
        result = LinearClient(settings(), session=session).list_issues()
        self.assertEqual([record["id"] for record in result.records], ["issue-1", "issue-2"])

    def test_issue_read_uses_exact_project_uuid_filter(self):
        session = Mock()
        session.post.return_value = response(
            {"data": {"issues": connection([issue(project={"id": "exact-uuid", "name": "Renamed"})])}}
        )

        result = LinearClient(settings(), session=session).list_issues(
            project_id="exact-uuid"
        )

        self.assertIsNone(result.error)
        variables = session.post.call_args.kwargs["json"]["variables"]
        self.assertEqual(
            variables["filter"],
            {"project": {"id": {"eq": "exact-uuid"}}},
        )

    def test_nested_relations_paginate_without_losing_first_page(self):
        first = issue(
            relations=connection([
                {"id": "rel-1", "type": "blocks", "relatedIssue": {"id": "issue-2"}}
            ], has_next=True, cursor="relation-cursor")
        )
        session = Mock()
        session.post.side_effect = [
            response({"data": {"issues": connection([first])}}),
            response({"data": {"issue": {
                "relations": connection([{"id": "rel-2", "type": "blocks", "relatedIssue": {"id": "issue-3"}}]),
                "inverseRelations": connection([]),
            }}}),
        ]
        result = LinearClient(settings(), session=session).list_issues()
        self.assertIsNone(result.error)
        self.assertEqual([item["id"] for item in result.records[0]["relations"]["nodes"]], ["rel-1", "rel-2"])

    def test_malformed_or_incomplete_responses_fail_closed(self):
        session = Mock()
        session.post.return_value = response({"data": {"projects": {"nodes": []}}})
        self.assertEqual(LinearClient(settings(), session=session).list_projects().error.code, "malformed_response")

        session.post.return_value = response({"data": {"issues": connection([issue(state=None)])}})
        self.assertEqual(LinearClient(settings(), session=session).list_issues().error.code, "malformed_response")

    def test_provider_health_payload_matches_application_conventions(self):
        from app.main import _linear_health

        cases = [
            (LinearHealthResult(state="not_configured"), "warning", "not_configured"),
            (LinearHealthResult(state="connected"), "ok", "connected"),
            (
                LinearHealthResult(
                    state="authentication_failure",
                    error=LinearProviderError(code="authentication", message="safe", http_status=403),
                ),
                "error",
                "authentication_failure",
            ),
            (
                LinearHealthResult(
                    state="provider_failure",
                    error=LinearProviderError(code="provider", message="safe"),
                ),
                "error",
                "provider_failure",
            ),
        ]
        for result, expected_status, expected_state in cases:
            client = Mock()
            client.check_health.return_value = result
            with unittest.mock.patch("app.main.LinearClient", return_value=client):
                payload = _linear_health(settings())
            self.assertEqual(payload["status"], expected_status)
            self.assertEqual(payload["details"]["state"], expected_state)
            self.assertNotIn("linear-secret", str(payload))


class LinearWorkAdapterTests(unittest.TestCase):
    def test_priority_inversion_is_explicit(self):
        expected = {
            0: WorkPriority.NONE,
            4: WorkPriority.LOW,
            3: WorkPriority.MEDIUM,
            2: WorkPriority.HIGH,
            1: WorkPriority.URGENT,
        }
        for linear_priority, normalized in expected.items():
            self.assertEqual(normalize_linear_priority(linear_priority), normalized)
        self.assertEqual(normalize_linear_priority(99), WorkPriority.NONE)

    def test_workflow_status_normalization_uses_state_type(self):
        self.assertEqual(normalize_linear_status("started"), WorkStatus.OPEN)
        self.assertEqual(normalize_linear_status("completed"), WorkStatus.COMPLETED)
        self.assertEqual(normalize_linear_status("canceled"), WorkStatus.CANCELED)
        self.assertEqual(normalize_linear_status("blocked"), WorkStatus.OPEN)

    def test_identity_metadata_dates_milestone_and_nullable_mapping_are_preserved(self):
        work = linear_work_adapter.adapt_issue(issue())
        self.assertEqual(work.provider, "linear")
        self.assertEqual(work.provider_record_id, "issue-uuid")
        self.assertEqual(work.provider_metadata["issue_identifier"], "SID-133")
        self.assertEqual(work.provider_metadata["provider_project_id"], "project-uuid")
        self.assertEqual(work.provider_reference, "project-uuid")
        self.assertIsNone(work.canonical_project_id)
        self.assertEqual(work.original_provider_status, "In Progress")
        self.assertEqual(work.original_provider_priority, 2)
        self.assertEqual(work.priority, WorkPriority.HIGH)
        self.assertEqual(work.due_date.isoformat(), "2026-07-20")
        self.assertEqual(work.updated_at.isoformat(), "2026-07-12T12:00:00+00:00")
        self.assertEqual(work.provider_metadata["project_milestone"]["id"], "milestone-uuid")
        self.assertEqual(work.provider_metadata["assignee"]["id"], "user-uuid")
        self.assertEqual(work.provider_url, "https://linear.app/example/issue/SID-133")

    def test_completed_and_canceled_issues_are_not_executable(self):
        completed = linear_work_adapter.adapt_issue(issue(state={"id": "s", "name": "Done", "type": "completed"}, completedAt="2026-07-12T00:00:00Z"))
        canceled = linear_work_adapter.adapt_issue(issue(id="canceled", identifier="SID-134", state={"id": "s", "name": "Canceled", "type": "canceled"}, canceledAt="2026-07-12T00:00:00Z"))
        self.assertEqual(completed.status, WorkStatus.COMPLETED)
        self.assertFalse(completed.is_executable)
        self.assertEqual(canceled.status, WorkStatus.CANCELED)
        self.assertFalse(canceled.is_executable)

    def test_structured_estimate_and_context_labels_feed_provider_neutral_fields(self):
        structured = linear_work_adapter.adapt_issue(
            issue(
                estimate=5,
                labels=connection(
                    [
                        {"id": "one", "name": "context:VR headset"},
                        {"id": "two", "name": "environment:dedicated workspace"},
                        {"id": "three", "name": "ordinary-label"},
                    ]
                ),
            )
        )
        unknown = linear_work_adapter.adapt_issue(
            issue(id="unknown", identifier="SID-999", estimate=None, labels=connection([]))
        )

        self.assertEqual(structured.effort_size, WorkEffortSize.LARGE)
        self.assertEqual(
            structured.context_requirements,
            ("VR headset", "dedicated workspace"),
        )
        self.assertEqual(structured.provider_metadata["estimate"], 5)
        self.assertIsNone(unknown.effort_size)
        self.assertEqual(unknown.context_requirements, ())

    def test_parent_child_hierarchy_uses_canonical_container_rules(self):
        parent = issue(id="parent", identifier="SID-100", title="Parent")
        child = issue(id="child", identifier="SID-101", title="Child", parent={"id": "parent", "identifier": "SID-100"})
        items = linear_work_adapter.adapt_many([parent, child])
        by_id = {item.provider_record_id: item for item in items}
        self.assertTrue(by_id["parent"].is_container)
        self.assertFalse(by_id["parent"].is_executable)
        self.assertEqual(by_id["child"].parent_provider_record_id, "parent")
        self.assertTrue(by_id["child"].is_executable)

    def test_explicit_blocks_and_blocked_by_relations_are_preserved(self):
        source = issue(
            relations=connection([{"id": "out", "type": "blocks", "relatedIssue": {"id": "downstream", "identifier": "SID-200"}}]),
            inverseRelations=connection([{"id": "in", "type": "blocks", "issue": {"id": "blocker", "identifier": "SID-100"}}]),
        )
        work = linear_work_adapter.adapt_issue(source)
        self.assertEqual(
            {(dependency.provider_record_id, dependency.dependency_type) for dependency in work.dependencies},
            {("downstream", "blocks"), ("blocker", "blocked_by")},
        )
        self.assertFalse(work.is_blocked)
        self.assertTrue(work.is_executable)

    def test_no_dependencies_or_blocked_state_are_invented_from_text_or_status_name(self):
        source = issue(
            title="Blocked by SID-100",
            description="Wait for another milestone",
            state={"id": "state", "name": "Blocked", "type": "started"},
        )
        work = linear_work_adapter.adapt_issue(source)
        self.assertEqual(work.status, WorkStatus.OPEN)
        self.assertEqual(work.dependencies, ())
        self.assertFalse(work.is_blocked)

    def test_incomplete_issue_is_rejected_or_skipped(self):
        with self.assertRaisesRegex(ValueError, "missing required"):
            linear_work_adapter.adapt_issue(issue(identifier=None))
        self.assertEqual(linear_work_adapter.adapt_many([issue(title="")]), [])


if __name__ == "__main__":
    unittest.main()
