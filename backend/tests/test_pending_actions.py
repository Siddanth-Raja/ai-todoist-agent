from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from pydantic import ValidationError

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.action_domain import (  # noqa: E402
    ACTION_PAYLOAD_ADAPTER,
    PendingActionLifecycle,
    PendingActionType,
    ProviderTargetReference,
    legacy_client_payload,
    parse_legacy_pending_action,
    payload_fingerprint,
)
from app.action_executors import (  # noqa: E402
    ActionExecutionContext,
    ActionExecutionResult,
    ActionExecutorRegistry,
    UncertainProviderOutcome,
)
from app.pending_actions import (  # noqa: E402
    PendingActionError,
    PendingActionRepository,
    PendingActionService,
)
from app.storage import database_connection  # noqa: E402
import app.agent as agent  # noqa: E402


NOW = datetime(2026, 7, 17, 18, 0, tzinfo=timezone.utc)


def legacy_actions():
    return {
        "create_todoist_task": {
            "type": "create_todoist_task",
            "intent": "capture_task",
            "confirmation_prompt": "Create synthetic task?",
            "resolved_project": "Personal",
            "task": {
                "content": "Synthetic task",
                "project_category": "Personal",
                "project_name": "To-Do",
                "section_name": "Personal",
                "due_date": "2026-07-20",
                "labels": ["synthetic"],
                "priority": 4,
            },
        },
        "create_todoist_subtask": {
            "type": "create_todoist_subtask",
            "confirmation_prompt": "Create synthetic subtask?",
            "details": {
                "parent_task_id": "parent-synthetic",
                "parent_task_title": "Synthetic parent",
                "content": "Synthetic child",
                "priority": 3,
            },
        },
        "create_many_todoist_tasks": {
            "type": "create_many_todoist_tasks",
            "confirmation_prompt": "Create synthetic tasks?",
            "details": {
                "tasks": [
                    {"content": "Synthetic one", "priority": 3},
                    {"content": "Synthetic two", "priority": 4},
                ]
            },
        },
        "create_many_todoist_subtasks": {
            "type": "create_many_todoist_subtasks",
            "confirmation_prompt": "Create synthetic subtasks?",
            "details": {
                "project_name": "To-Do",
                "section_name": "Nebulo",
                "parent_task_title": "Synthetic parent",
                "parent_task_id": "parent-synthetic",
                "tasks": [
                    {"content": "Synthetic child one", "priority": 3},
                    {"content": "Synthetic child two", "priority": 3},
                ],
            },
        },
        "create_calendar_event": {
            "type": "create_calendar_event",
            "confirmation_prompt": "Create synthetic event?",
            "resolved_project": "Nebulo",
            "calendar_event": {
                "title": "Synthetic event",
                "start": "2026-07-20T15:00:00+00:00",
                "end": "2026-07-20T16:00:00+00:00",
                "description": "Synthetic description",
            },
        },
        "update_calendar_event": {
            "type": "update_calendar_event",
            "confirmation_prompt": "Update synthetic event?",
            "details": {
                "event_id": "event-synthetic",
                "title": "Synthetic event",
                "old_start": "2026-07-20T15:00:00+00:00",
                "old_end": "2026-07-20T16:00:00+00:00",
                "new_start": "2026-07-20T16:00:00+00:00",
                "new_end": "2026-07-20T17:00:00+00:00",
            },
        },
    }


class FakeRegistryService:
    class Snapshot:
        def get_project_definition(self, reference):
            if reference == "Personal":
                return {"canonical_project_id": "project-personal"}
            if reference == "Nebulo":
                return {"canonical_project_id": "project-nebulo"}
            return None

    def snapshot(self):
        return self.Snapshot()


def executor_registry(handler=None):
    registry = ActionExecutorRegistry()
    default_handler = handler or (
        lambda payload, context: ActionExecutionResult(
            actions_taken=({"type": payload.action_type.value, "status": "success"},),
            provider_references=(
                ProviderTargetReference(
                    provider=(
                        "google_calendar"
                        if "calendar" in payload.action_type.value
                        else "todoist"
                    ),
                    resource_type="result",
                    provider_ref="result-synthetic",
                ),
            ),
        )
    )
    for action_type in PendingActionType:
        registry.register(action_type, default_handler)
    return registry


class PendingActionArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = os.path.join(self.tempdir.name, "pending.sqlite3")
        self.env = patch.dict(os.environ, {"APP_DB_PATH": self.db_path})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.service = PendingActionService(
            repository=PendingActionRepository(),
            executor_registry=executor_registry(),
            registry_service=FakeRegistryService(),
            clock=lambda: NOW,
        )
        self.context = ActionExecutionContext(
            settings=object(),
            tasks=(),
            calendar_events=(),
            local_now=NOW,
        )

    def propose(self, action_type="create_todoist_task", **kwargs):
        return self.service.propose_legacy(
            legacy_actions()[action_type],
            session_id=kwargs.pop("session_id", "session-synthetic"),
            **kwargs,
        )

    def test_every_migrated_variant_has_a_strict_discriminated_schema(self):
        parsed = {
            name: parse_legacy_pending_action(value)
            for name, value in legacy_actions().items()
        }

        self.assertEqual(set(parsed), set(legacy_actions()))
        for name, payload in parsed.items():
            self.assertEqual(payload.action_type.value, name)
            self.assertEqual(payload.schema_version, 1)
            with self.assertRaises(ValidationError):
                ACTION_PAYLOAD_ADAPTER.validate_python(
                    {**payload.model_dump(mode="json"), "unexpected": True}
                )

    def test_unknown_and_schema_invalid_variants_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown or unsupported"):
            parse_legacy_pending_action(
                {"type": "delete_email", "confirmation_prompt": "Forbidden"}
            )
        invalid = legacy_actions()["update_calendar_event"] | {
            "details": {"event_id": "event-synthetic"}
        }
        with self.assertRaises((ValidationError, ValueError)):
            parse_legacy_pending_action(invalid)

    def test_proposal_persists_full_durable_contract_without_secret_fields(self):
        record = self.propose()

        self.assertTrue(record.action_id)
        self.assertEqual(record.lifecycle, PendingActionLifecycle.PENDING)
        self.assertEqual(record.version, 1)
        self.assertEqual(record.canonical_project_id, "project-personal")
        self.assertEqual(record.provider, "todoist")
        self.assertTrue(record.target_references)
        self.assertTrue(record.evidence)
        self.assertEqual(record.payload_fingerprint, payload_fingerprint(record.payload))
        self.assertTrue(record.idempotency_key)
        self.assertEqual(record.session_id, "session-synthetic")
        dumped = record.model_dump(mode="json")
        self.assertNotIn("token", str(dumped).casefold())
        self.assertNotIn("secret", str(dumped).casefold())

    def test_additive_schema_is_idempotent_and_restart_safe(self):
        record = self.propose("create_calendar_event")
        restarted = PendingActionRepository().get(record.action_id)

        self.assertEqual(restarted, record)
        self.assertEqual(
            PendingActionService(
                repository=PendingActionRepository(),
                executor_registry=executor_registry(),
                registry_service=FakeRegistryService(),
                clock=lambda: NOW,
            ).current("session-synthetic"),
            record,
        )

    def test_idempotency_key_returns_existing_record_and_rejects_conflict(self):
        first = self.propose(idempotency_key="idempotency-synthetic")
        second = self.propose(idempotency_key="idempotency-synthetic")
        self.assertEqual(first.action_id, second.action_id)

        with self.assertRaisesRegex(PendingActionError, "different action payload"):
            self.propose(
                "create_calendar_event",
                idempotency_key="idempotency-synthetic",
            )

    def test_public_payload_contains_only_durable_confirmation_reference_and_preview(self):
        record = self.propose("create_many_todoist_subtasks")
        public = legacy_client_payload(record)

        self.assertEqual(public["action_id"], record.action_id)
        self.assertEqual(public["version"], 1)
        self.assertEqual(public["fingerprint"], record.payload_fingerprint)
        self.assertEqual(public["type"], "create_many_todoist_subtasks")
        self.assertEqual(len(public["details"]["tasks"]), 2)

    def test_confirm_claims_executes_once_and_persists_success(self):
        calls = []

        def handler(payload, context):
            calls.append(payload.action_type)
            return ActionExecutionResult(
                actions_taken=({"type": payload.action_type.value, "status": "success"},),
                provider_references=(
                    ProviderTargetReference(
                        provider="todoist",
                        resource_type="task",
                        provider_ref="task-result-synthetic",
                    ),
                ),
            )

        service = PendingActionService(
            repository=PendingActionRepository(),
            executor_registry=executor_registry(handler),
            registry_service=FakeRegistryService(),
            clock=lambda: NOW,
        )
        record = service.propose_legacy(
            legacy_actions()["create_todoist_task"],
            session_id="session-once",
        )
        execution = service.confirm(
            record.action_id,
            expected_version=record.version,
            expected_fingerprint=record.payload_fingerprint,
            context=self.context,
        )

        self.assertEqual(calls, [PendingActionType.CREATE_TODOIST_TASK])
        self.assertEqual(execution.record.lifecycle, PendingActionLifecycle.SUCCEEDED)
        self.assertEqual(execution.record.version, 3)
        self.assertEqual(execution.record.result.action_count, 1)
        self.assertEqual(
            execution.record.result.provider_references[0].provider_ref,
            "task-result-synthetic",
        )
        with self.assertRaises(PendingActionError):
            service.confirm(
                record.action_id,
                expected_version=record.version,
                expected_fingerprint=record.payload_fingerprint,
                context=self.context,
            )
        self.assertEqual(len(calls), 1)

    def test_all_six_variants_dispatch_through_the_registry(self):
        dispatched = []

        def handler(payload, context):
            dispatched.append(payload.action_type)
            return ActionExecutionResult(
                actions_taken=({"type": payload.action_type.value, "status": "success"},)
            )

        service = PendingActionService(
            repository=PendingActionRepository(),
            executor_registry=executor_registry(handler),
            registry_service=FakeRegistryService(),
            clock=lambda: NOW,
        )
        for action_type, legacy in legacy_actions().items():
            record = service.propose_legacy(
                legacy,
                session_id=f"dispatch-{action_type}",
            )
            execution = service.confirm(
                record.action_id,
                expected_version=record.version,
                expected_fingerprint=record.payload_fingerprint,
                context=self.context,
            )
            self.assertEqual(execution.record.lifecycle, PendingActionLifecycle.SUCCEEDED)

        self.assertEqual(
            dispatched,
            [PendingActionType(value) for value in legacy_actions()],
        )

    def test_simultaneous_confirmations_make_one_provider_call(self):
        call_lock = threading.Lock()
        call_count = 0

        def handler(payload, context):
            nonlocal call_count
            with call_lock:
                call_count += 1
            time.sleep(0.05)
            return ActionExecutionResult(
                actions_taken=({"type": payload.action_type.value},)
            )

        service = PendingActionService(
            repository=PendingActionRepository(),
            executor_registry=executor_registry(handler),
            registry_service=FakeRegistryService(),
            clock=lambda: NOW,
        )
        record = service.propose_legacy(
            legacy_actions()["create_todoist_task"],
            session_id="session-race",
        )

        def confirm_once():
            try:
                return service.confirm(
                    record.action_id,
                    expected_version=record.version,
                    expected_fingerprint=record.payload_fingerprint,
                    context=self.context,
                )
            except PendingActionError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: confirm_once(), range(2)))

        self.assertEqual(call_count, 1)
        self.assertEqual(sum(not isinstance(item, str) for item in outcomes), 1)

    def test_cancel_is_durable_and_terminal(self):
        record = self.propose()
        cancelled = self.service.cancel(
            record.action_id,
            expected_version=record.version,
            expected_fingerprint=record.payload_fingerprint,
        )

        self.assertEqual(cancelled.lifecycle, PendingActionLifecycle.CANCELLED)
        self.assertEqual(cancelled.version, 2)
        with self.assertRaises(PendingActionError):
            self.service.confirm(
                record.action_id,
                expected_version=cancelled.version,
                expected_fingerprint=record.payload_fingerprint,
                context=self.context,
            )

    def test_stale_version_and_tampered_fingerprint_are_rejected_before_execution(self):
        record = self.propose()
        with self.assertRaisesRegex(PendingActionError, "version is stale"):
            self.service.confirm(
                record.action_id,
                expected_version=99,
                expected_fingerprint=record.payload_fingerprint,
                context=self.context,
            )
        with self.assertRaisesRegex(PendingActionError, "fingerprint"):
            self.service.confirm(
                record.action_id,
                expected_version=record.version,
                expected_fingerprint="0" * 64,
                context=self.context,
            )
        self.assertEqual(self.service.get(record.action_id).lifecycle, PendingActionLifecycle.PENDING)

    def test_provider_failure_is_sanitized_and_not_retryable(self):
        registry = executor_registry(
            lambda payload, context: ActionExecutionResult(
                errors=("Synthetic provider included internal diagnostic text.",)
            )
        )
        service = PendingActionService(
            repository=PendingActionRepository(),
            executor_registry=registry,
            registry_service=FakeRegistryService(),
            clock=lambda: NOW,
        )
        record = service.propose_legacy(
            legacy_actions()["create_todoist_task"], session_id="failure-session"
        )
        execution = service.confirm(
            record.action_id,
            expected_version=1,
            expected_fingerprint=record.payload_fingerprint,
            context=self.context,
        )

        self.assertEqual(execution.record.lifecycle, PendingActionLifecycle.FAILED)
        self.assertEqual(execution.record.failure.code, "provider_failure")
        self.assertNotIn("internal diagnostic", execution.record.failure.message)
        self.assertIn("internal diagnostic", execution.errors[0])

    def test_uncertain_provider_outcome_is_explicit_and_blocks_retry(self):
        def uncertain(payload, context):
            raise UncertainProviderOutcome("synthetic interruption")

        service = PendingActionService(
            repository=PendingActionRepository(),
            executor_registry=executor_registry(uncertain),
            registry_service=FakeRegistryService(),
            clock=lambda: NOW,
        )
        record = service.propose_legacy(
            legacy_actions()["update_calendar_event"], session_id="unknown-session"
        )
        execution = service.confirm(
            record.action_id,
            expected_version=1,
            expected_fingerprint=record.payload_fingerprint,
            context=self.context,
        )

        self.assertEqual(execution.record.lifecycle, PendingActionLifecycle.OUTCOME_UNKNOWN)
        self.assertEqual(execution.record.failure.code, "provider_outcome_unknown")
        self.assertIn("unknown", execution.errors[0])

    def test_expired_action_cannot_execute(self):
        record = self.propose(expires_at=NOW - timedelta(seconds=1))
        with self.assertRaisesRegex(PendingActionError, "expired"):
            self.service.confirm(
                record.action_id,
                expected_version=1,
                expected_fingerprint=record.payload_fingerprint,
                context=self.context,
            )

    def test_record_and_payload_are_immutable(self):
        record = self.propose()
        with self.assertRaises(ValidationError):
            record.lifecycle = PendingActionLifecycle.SUCCEEDED
        with self.assertRaises(ValidationError):
            record.payload.task.content = "Tampered"

    def test_stored_payload_tampering_is_detected_before_claim(self):
        record = self.propose()
        with database_connection() as connection:
            payload = record.payload.model_dump(mode="json")
            payload["task"]["content"] = "Tampered stored task"
            connection.execute(
                "UPDATE pending_actions SET payload = ? WHERE id = ?",
                (json.dumps(payload), record.action_id),
            )

        with self.assertRaisesRegex(PendingActionError, "fingerprint"):
            self.service.confirm(
                record.action_id,
                expected_version=record.version,
                expected_fingerprint=record.payload_fingerprint,
                context=self.context,
            )

    def test_legacy_process_global_and_dictionary_executor_are_unreachable(self):
        self.assertFalse(hasattr(agent, "PENDING_ACTION"))
        self.assertFalse(hasattr(agent, "_execute_allowed_action"))


if __name__ == "__main__":
    unittest.main()
