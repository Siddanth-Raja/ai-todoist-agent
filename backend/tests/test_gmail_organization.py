from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.action_domain import (  # noqa: E402
    ActionEvidence,
    GmailApplyLabelPayload,
    GmailArchivePayload,
    GmailExpectedMessageState,
    GmailOrganizationManifest,
    GmailUserLabelIdentity,
    PendingActionLifecycle,
    PendingActionType,
    StoredTargetResult,
    gmail_manifest_fingerprint,
)
from app.action_executors import (  # noqa: E402
    ActionExecutionContext,
    ActionExecutionResult,
    ActionExecutorRegistry,
)
from app.email_domain import (  # noqa: E402
    EmailAccountRole,
    EmailMessageIdentity,
    EmailProviderAccountIdentity,
)
from app.email_inventory import (  # noqa: E402
    EmailInventoryState,
    EmailOrganizationProposalService,
    InventoryCoarseType,
    InventoryLabelIdentity,
    InventoryMessageFact,
    LabelInventory,
    PersonalEmailInventoryResult,
)
from app.gmail_client import GmailProviderState  # noqa: E402
from app.gmail_organization import (  # noqa: E402
    GMAIL_MODIFY_SCOPE,
    GmailBatchMutationResult,
    GmailCreatedLabel,
    GmailMutationGateRepository,
    GmailMutationGateState,
    GmailObservedMessageState,
    GmailOrganizationAdapter,
    GmailOrganizationGateError,
    GmailOrganizationProposalBuilder,
    GoogleGmailOrganizationTransport,
)
from app.pending_actions import (  # noqa: E402
    PendingActionError,
    PendingActionRepository,
    PendingActionService,
)
from app.storage import database_connection  # noqa: E402


NOW = datetime(2026, 7, 18, 18, 0, tzinfo=timezone.utc)
ACCOUNT = EmailProviderAccountIdentity(
    provider="gmail",
    account_role=EmailAccountRole.PERSONAL,
    provider_account_id="personal-gmail-test",
)
LABEL = GmailUserLabelIdentity(
    provider_label_id="Label_pcos_action",
    name="PCOS/Action",
)


def manifest(count: int = 2, *, labeled: bool = False) -> GmailOrganizationManifest:
    targets = tuple(
        GmailExpectedMessageState(
            provider_message_id=f"message-{index}",
            provider_thread_id=f"thread-{index}",
            expected_label_ids=("INBOX", "Label_pcos_action") if labeled else ("INBOX",),
            expected_unread=False,
        )
        for index in range(count)
    )
    return GmailOrganizationManifest(
        account=ACCOUNT,
        targets=targets,
        selection_fingerprint=gmail_manifest_fingerprint(ACCOUNT, targets),
        originating_proposal_id="sid-230-proposal-test",
        originating_proposal_fingerprint="sid-230-fingerprint-test",
        originating_inventory_fingerprint="sid-230-inventory-test",
        selection_criteria=("grounded deterministic metadata",),
        exclusions=("protected and uncertain excluded",),
        representative_example_tokens=("example-token",),
    )


def canary_payload(count: int = 2) -> GmailApplyLabelPayload:
    return GmailApplyLabelPayload(
        action_type="gmail_apply_label",
        manifest=manifest(count),
        label=LABEL,
        canary=True,
        hand_reviewed=True,
    )


def sid230_inventory() -> PersonalEmailInventoryResult:
    fact = InventoryMessageFact(
        identity=EmailMessageIdentity(
            account=ACCOUNT,
            provider_message_id="inventory-message",
            provider_thread_id="inventory-thread",
        ),
        sender_fingerprint="sender-token",
        unread=True,
        provider_important=False,
        label_ids=("INBOX", "UNREAD"),
        has_attachment=False,
        coarse_types=(InventoryCoarseType.ACTION,),
        uncertain=False,
    )

    def label_inventory(name, messages):
        return LabelInventory(
            label=InventoryLabelIdentity(provider_label_id=name, exact_name=name),
            state=(EmailInventoryState.COMPLETE if messages else EmailInventoryState.CONNECTED_EMPTY),
            provider_state=(GmailProviderState.CONNECTED if messages else GmailProviderState.CONNECTED_EMPTY),
            complete=True,
            messages=messages,
            message_count=len(messages),
            unique_thread_count=len(messages),
            duplicate_message_count=0,
            unread_count=sum(item.unread for item in messages),
            important_count=0,
            protected_count=0,
            uncertain_count=0,
            pages_fetched=1,
            attachment_pages_fetched=0,
            metadata_requests=len(messages),
            provider_retry_count=0,
            remaining_cursor_present=False,
            attachment_cursor_present=False,
            stable_fingerprint=f"{name}-fingerprint",
        )

    return PersonalEmailInventoryResult(
        inbox=label_inventory("INBOX", (fact,)),
        old_stuff=label_inventory("Old Stuff", ()),
        complete=True,
        stable_fingerprint="complete-inventory-fingerprint",
    )


class FakeTransport:
    def __init__(self, count: int = 2) -> None:
        self.states = {
            f"message-{index}": GmailObservedMessageState(
                provider_message_id=f"message-{index}",
                provider_thread_id=f"thread-{index}",
                label_ids=("INBOX",),
                unread=False,
            )
            for index in range(count)
        }
        self.modify_calls = 0
        self.partial = False

    def get_message_states(self, message_ids):
        return tuple(self.states[value] for value in message_ids if value in self.states)

    def modify_message_labels(
        self,
        message_ids,
        *,
        add_label_ids=(),
        remove_label_ids=(),
    ):
        self.modify_calls += 1
        successful = message_ids[:-1] if self.partial else message_ids
        failed = message_ids[-1:] if self.partial else ()
        for message_id in successful:
            previous = self.states[message_id]
            labels = (set(previous.label_ids) | set(add_label_ids)) - set(remove_label_ids)
            self.states[message_id] = previous.model_copy(
                update={"label_ids": tuple(sorted(labels)), "unread": "UNREAD" in labels}
            )
        return GmailBatchMutationResult(
            successful_message_ids=successful,
            failed_message_ids=failed,
            diagnostic_code="synthetic_partial" if failed else None,
        )

    def create_label(self, name):
        return GmailCreatedLabel(provider_label_id="Label_created", name=name)


class FakeGoogleRequest:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.value


class FakeHttpError(Exception):
    def __init__(self, status):
        super().__init__("synthetic provider error")
        self.status_code = status


class FakeGoogleMessages:
    def __init__(self):
        self.batch_bodies = []

    def get(self, **kwargs):
        message_id = kwargs["id"]
        return FakeGoogleRequest(
            {"id": message_id, "threadId": f"thread-{message_id}", "labelIds": ["INBOX"]}
        )

    def batchModify(self, **kwargs):
        body = kwargs["body"]
        self.batch_bodies.append(body)
        error = FakeHttpError(400) if "message-2" in body["ids"] else None
        return FakeGoogleRequest({}, error)


class FakeGoogleLabels:
    def create(self, **kwargs):
        return FakeGoogleRequest({"id": "Label_created", "name": kwargs["body"]["name"]})


class FakeGoogleUsers:
    def __init__(self):
        self.message_resource = FakeGoogleMessages()
        self.label_resource = FakeGoogleLabels()

    def messages(self):
        return self.message_resource

    def labels(self):
        return self.label_resource


class FakeGoogleService:
    def __init__(self):
        self.user_resource = FakeGoogleUsers()

    def users(self):
        return self.user_resource


class GmailOrganizationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = os.path.join(self.tempdir.name, "gmail-actions.sqlite3")
        self.env = patch.dict(os.environ, {"APP_DB_PATH": self.db_path})
        self.env.start()
        self.addCleanup(self.env.stop)
        with database_connection():
            pass
        self.gate = GmailMutationGateRepository()

    def authorize_synthetic_gate(self):
        return self.gate.record_manual_oauth_authorization(
            authorized_scope=GMAIL_MODIFY_SCOPE,
            approval_reference="synthetic-test-approval",
            now=NOW,
        )

    def test_default_gate_is_durable_and_blocks_before_transport(self):
        transport = FakeTransport()
        adapter = GmailOrganizationAdapter(transport, self.gate)

        self.assertEqual(self.gate.status().state, GmailMutationGateState.MANUAL_OAUTH_REQUIRED)
        with self.assertRaisesRegex(GmailOrganizationGateError, "explicit OAuth approval"):
            adapter.execute("action-test", canary_payload())
        self.assertEqual(transport.modify_calls, 0)
        self.assertEqual(GmailMutationGateRepository().status().provider_mutation_calls, 0)

    def test_injected_google_transport_batches_and_preserves_chunk_failures(self):
        service = FakeGoogleService()
        transport = GoogleGmailOrganizationTransport(service, batch_size=2)

        states = transport.get_message_states(("message-0", "message-1"))
        result = transport.modify_message_labels(
            tuple(f"message-{index}" for index in range(5)),
            add_label_ids=("Label_pcos_action",),
        )
        label = transport.create_label("PCOS/Action")

        self.assertEqual(len(states), 2)
        self.assertEqual(len(service.user_resource.message_resource.batch_bodies), 3)
        self.assertEqual(result.failed_message_ids, ("message-2", "message-3"))
        self.assertEqual(result.successful_message_ids, ("message-0", "message-1", "message-4"))
        self.assertFalse(result.outcome_unknown)
        self.assertEqual(label.provider_label_id, "Label_created")

    def test_first_live_operation_must_be_hand_reviewed_label_canary_at_most_ten(self):
        self.authorize_synthetic_gate()
        archive = GmailArchivePayload(
            action_type="gmail_archive",
            manifest=manifest(),
        )
        with self.assertRaisesRegex(GmailOrganizationGateError, "label-only canary"):
            self.gate.assert_execution_allowed(archive)
        with self.assertRaises(ValidationError):
            canary_payload(11)
        non_canary = canary_payload().model_copy(update={"canary": False})
        with self.assertRaisesRegex(GmailOrganizationGateError, "label-only canary"):
            self.gate.assert_execution_allowed(non_canary)

    def test_canary_generates_exact_separate_undo_and_blocks_later_ops(self):
        self.authorize_synthetic_gate()
        transport = FakeTransport()
        adapter = GmailOrganizationAdapter(transport, self.gate)

        result = adapter.execute("canary-action", canary_payload())

        self.assertTrue(result.complete)
        self.assertEqual(transport.modify_calls, 1)
        self.assertIsNotNone(result.undo_payload)
        self.assertEqual(result.undo_payload.action_type, PendingActionType.GMAIL_REMOVE_LABEL)
        self.assertEqual(result.undo_payload.undo_of_action_id, "canary-action")
        self.assertEqual(self.gate.status().state, GmailMutationGateState.LABEL_CANARY_UNDO_REQUIRED)
        with self.assertRaisesRegex(GmailOrganizationGateError, "exact label canary undo"):
            self.gate.assert_execution_allowed(
                GmailArchivePayload(action_type="gmail_archive", manifest=manifest(2, labeled=True))
            )

        undo_result = adapter.execute("undo-action", result.undo_payload)

        self.assertTrue(undo_result.complete)
        self.assertEqual(transport.modify_calls, 2)
        self.assertEqual(self.gate.status().state, GmailMutationGateState.CANARY_VERIFIED)

    def test_verified_adapter_keeps_one_batch_within_the_provider_limit(self):
        self.authorize_synthetic_gate()
        canary_transport = FakeTransport()
        adapter = GmailOrganizationAdapter(canary_transport, self.gate)
        canary = adapter.execute("canary-action", canary_payload())
        adapter.execute("undo-action", canary.undo_payload)

        transport = FakeTransport(1000)
        payload = GmailApplyLabelPayload(
            action_type="gmail_apply_label",
            manifest=manifest(1000),
            label=LABEL,
            hand_reviewed=True,
        )
        result = GmailOrganizationAdapter(transport, self.gate).execute(
            "bounded-batch-action",
            payload,
        )

        self.assertTrue(result.complete)
        self.assertEqual(len(result.target_results), 1000)
        self.assertEqual(transport.modify_calls, 1)
        with self.assertRaises(ValidationError):
            manifest(1001)

    def test_stale_state_and_partial_failure_are_not_reported_as_success(self):
        self.authorize_synthetic_gate()
        transport = FakeTransport()
        adapter = GmailOrganizationAdapter(transport, self.gate)
        transport.states["message-0"] = transport.states["message-0"].model_copy(
            update={"label_ids": ("INBOX", "CHANGED")}
        )
        with self.assertRaisesRegex(GmailOrganizationGateError, "fresh proposal"):
            adapter.execute("stale-action", canary_payload())
        self.assertEqual(transport.modify_calls, 0)

        transport = FakeTransport()
        transport.partial = True
        result = GmailOrganizationAdapter(transport, self.gate).execute(
            "partial-action", canary_payload()
        )
        self.assertFalse(result.complete)
        self.assertTrue(result.partial_mutation)
        self.assertIsNone(result.undo_payload)
        self.assertEqual(self.gate.status().state, GmailMutationGateState.LABEL_CANARY_REQUIRED)

    def test_strict_contract_excludes_uncertain_protected_and_system_labels(self):
        values = manifest().model_dump(mode="json")
        values["targets"][0]["uncertain"] = True
        with self.assertRaises(ValidationError):
            GmailOrganizationManifest.model_validate(values)
        values = manifest().model_dump(mode="json")
        values["targets"][0]["protected"] = True
        with self.assertRaises(ValidationError):
            GmailOrganizationManifest.model_validate(values)
        with self.assertRaises(ValidationError):
            GmailUserLabelIdentity(provider_label_id="SYSTEM_LABEL", name="PCOS/Action")
        duplicated = (manifest().targets[0], manifest().targets[0])
        with self.assertRaises(ValidationError):
            GmailOrganizationManifest(
                account=ACCOUNT,
                targets=duplicated,
                selection_fingerprint=gmail_manifest_fingerprint(ACCOUNT, duplicated),
                originating_proposal_id="proposal-test",
                originating_proposal_fingerprint="proposal-fingerprint",
                originating_inventory_fingerprint="inventory-fingerprint",
                selection_criteria=("synthetic",),
                exclusions=(),
                representative_example_tokens=(),
            )
        self.assertEqual(
            {value.value for value in PendingActionType if value.value.startswith("gmail_")},
            {
                "gmail_apply_label",
                "gmail_remove_label",
                "gmail_archive",
                "gmail_restore_inbox",
                "gmail_mark_read",
                "gmail_mark_unread",
                "gmail_create_label",
            },
        )

    def test_sid230_proposal_builds_an_exact_reviewed_canary_manifest(self):
        inventory = sid230_inventory()
        proposal_result = EmailOrganizationProposalService().propose(inventory)
        proposal = proposal_result.proposals[0]

        payload = GmailOrganizationProposalBuilder().build(
            inventory=inventory,
            proposal_result=proposal_result,
            proposal=proposal,
            selected_message_ids=("inventory-message",),
            label=LABEL,
            canary=True,
            hand_reviewed=True,
        )

        self.assertIsInstance(payload, GmailApplyLabelPayload)
        self.assertEqual(payload.manifest.originating_proposal_id, proposal.proposal_id)
        self.assertEqual(
            payload.manifest.originating_inventory_fingerprint,
            inventory.stable_fingerprint,
        )
        self.assertEqual(payload.manifest.targets[0].expected_label_ids, ("INBOX", "UNREAD"))
        self.assertTrue(payload.canary)
        with self.assertRaisesRegex(GmailOrganizationGateError, "exact subset"):
            GmailOrganizationProposalBuilder().build(
                inventory=inventory,
                proposal_result=proposal_result,
                proposal=proposal,
                selected_message_ids=("not-in-proposal",),
                label=LABEL,
                canary=True,
                hand_reviewed=True,
            )

    def test_pending_action_confirmation_is_exactly_once_and_undo_is_not_automatic(self):
        self.authorize_synthetic_gate()
        transport = FakeTransport()
        adapter = GmailOrganizationAdapter(transport, self.gate)
        registry = ActionExecutorRegistry()

        def execute(payload, context):
            result = adapter.execute(context.action_id, payload)
            return ActionExecutionResult(
                actions_taken=({"type": payload.action_type.value},) if result.complete else (),
                errors=result.errors,
                provider_references=result.provider_references,
                partial_mutation=result.partial_mutation,
                target_results=tuple(
                    StoredTargetResult(
                        target_token=item.message_token,
                        status=item.status,
                        diagnostic_code=item.diagnostic_code,
                    )
                    for item in result.target_results
                ),
                undo_payload=result.undo_payload,
                undo_confirmation_prompt="Confirm exact synthetic undo?",
            )

        for action_type in (
            PendingActionType.GMAIL_APPLY_LABEL,
            PendingActionType.GMAIL_REMOVE_LABEL,
        ):
            registry.register(action_type, execute)
        service = PendingActionService(
            repository=PendingActionRepository(),
            executor_registry=registry,
            clock=lambda: NOW,
        )
        record = service.propose_typed(
            canary_payload(),
            confirmation_prompt="Apply label to two hand-reviewed messages?",
            evidence=(
                ActionEvidence(
                    kind="sid_230_inventory",
                    source="email_inventory",
                    summary="Synthetic exact manifest with protected and uncertain mail excluded.",
                ),
            ),
            session_id="email-organization",
            source="email_organization",
        )
        context = ActionExecutionContext(
            settings=object(), tasks=(), calendar_events=(), local_now=NOW
        )

        execution = service.confirm(
            record.action_id,
            expected_version=record.version,
            expected_fingerprint=record.payload_fingerprint,
            context=context,
        )

        self.assertEqual(execution.record.lifecycle, PendingActionLifecycle.SUCCEEDED)
        self.assertEqual(len(execution.record.result.target_results), 2)
        self.assertIsNotNone(execution.undo_record)
        self.assertEqual(execution.undo_record.lifecycle, PendingActionLifecycle.PENDING)
        self.assertEqual(transport.modify_calls, 1)
        self.assertEqual(
            PendingActionRepository().get(execution.undo_record.action_id).payload_fingerprint,
            execution.undo_record.payload_fingerprint,
        )
        with self.assertRaises(PendingActionError):
            service.confirm(
                record.action_id,
                expected_version=record.version,
                expected_fingerprint=record.payload_fingerprint,
                context=context,
            )
        self.assertEqual(transport.modify_calls, 1)

    def test_ui_target_adjustment_cancels_old_identity_and_issues_new_fingerprint(self):
        service = PendingActionService(
            repository=PendingActionRepository(),
            executor_registry=ActionExecutorRegistry(),
            clock=lambda: NOW,
        )
        record = service.propose_typed(
            canary_payload(),
            confirmation_prompt="Review exact canary?",
            evidence=(
                ActionEvidence(
                    kind="sid_230_inventory",
                    source="email_inventory",
                    summary="Synthetic exact manifest.",
                ),
            ),
            session_id="email-organization",
            source="email_organization",
        )
        selected_token = hashlib.sha256(b"message-0").hexdigest()[:16]

        adjusted = service.adjust_gmail_targets(
            record.action_id,
            expected_version=record.version,
            expected_fingerprint=record.payload_fingerprint,
            selected_message_tokens=(selected_token,),
        )

        self.assertNotEqual(adjusted.action_id, record.action_id)
        self.assertNotEqual(adjusted.payload_fingerprint, record.payload_fingerprint)
        self.assertEqual(len(adjusted.payload.manifest.targets), 1)
        self.assertEqual(
            service.get(record.action_id).lifecycle,
            PendingActionLifecycle.CANCELLED,
        )
        self.assertEqual(adjusted.lifecycle, PendingActionLifecycle.PENDING)


if __name__ == "__main__":
    unittest.main()
