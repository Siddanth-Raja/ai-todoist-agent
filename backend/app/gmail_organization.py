"""Credential-free Gmail organization policy and adapter for SID-231.

This module defines the mutation boundary but does not acquire credentials or
request an OAuth scope. The default durable gate blocks every execution until a
separate, explicitly approved reauthorization records the exact required scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .action_domain import (
    ActionPayload,
    GmailApplyLabelPayload,
    GmailArchivePayload,
    GmailCreateLabelPayload,
    GmailExpectedMessageState,
    GmailMarkReadPayload,
    GmailMarkUnreadPayload,
    GmailOrganizationManifest,
    GmailRemoveLabelPayload,
    GmailRestoreInboxPayload,
    GmailUserLabelIdentity,
    ProviderTargetReference,
    gmail_manifest_fingerprint,
)
from .email_inventory import (
    EmailOrganizationProposalResult,
    FutureOrganizationOperation,
    OrganizationBatchProposal,
    PersonalEmailInventoryResult,
)
from .storage import database_connection


GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
MAX_GMAIL_MUTATION_BATCH_SIZE = 1000
MAX_LIVE_LABEL_CANARY_MESSAGES = 10


class GmailMutationGateState(StrEnum):
    MANUAL_OAUTH_REQUIRED = "manual_oauth_required"
    LABEL_CANARY_REQUIRED = "label_canary_required"
    LABEL_CANARY_UNDO_REQUIRED = "label_canary_undo_required"
    CANARY_VERIFIED = "canary_verified"


class GmailOrganizationGateError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GmailMutationGateStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: GmailMutationGateState
    required_scope: Literal[GMAIL_MODIFY_SCOPE] = GMAIL_MODIFY_SCOPE
    oauth_authorized: bool
    label_canary_applied: bool
    label_canary_undo_verified: bool
    maximum_canary_messages: Literal[MAX_LIVE_LABEL_CANARY_MESSAGES] = (
        MAX_LIVE_LABEL_CANARY_MESSAGES
    )
    allowed_next_operations: tuple[str, ...]
    calendar_oauth_unchanged: Literal[True] = True
    provider_mutation_calls: int = Field(ge=0)


class GmailObservedMessageState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_message_id: str = Field(min_length=1, max_length=500)
    provider_thread_id: str | None = Field(default=None, min_length=1, max_length=500)
    label_ids: tuple[str, ...]
    unread: bool


class GmailBatchMutationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    successful_message_ids: tuple[str, ...] = ()
    failed_message_ids: tuple[str, ...] = ()
    diagnostic_code: str | None = Field(default=None, min_length=1, max_length=100)
    outcome_unknown: bool = False


class GmailCreatedLabel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_label_id: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=200)


class GmailOrganizationTransport(Protocol):
    """Narrow transport seam containing only exact organization primitives."""

    def get_message_states(
        self, message_ids: tuple[str, ...]
    ) -> tuple[GmailObservedMessageState, ...]: ...

    def modify_message_labels(
        self,
        message_ids: tuple[str, ...],
        *,
        add_label_ids: tuple[str, ...] = (),
        remove_label_ids: tuple[str, ...] = (),
    ) -> GmailBatchMutationResult: ...

    def create_label(self, name: str) -> GmailCreatedLabel: ...


class GoogleGmailOrganizationTransport:
    """Credential-independent wrapper over an injected authorized Gmail service."""

    def __init__(self, service: Any, *, batch_size: int = 100) -> None:
        if batch_size < 1 or batch_size > MAX_GMAIL_MUTATION_BATCH_SIZE:
            raise ValueError("Gmail organization batch size must be between 1 and 1000.")
        self._service = service
        self._batch_size = batch_size

    def get_message_states(
        self,
        message_ids: tuple[str, ...],
    ) -> tuple[GmailObservedMessageState, ...]:
        values: list[GmailObservedMessageState] = []
        for message_id in message_ids:
            try:
                payload = (
                    self._service.users()
                    .messages()
                    .get(userId="me", id=message_id, format="minimal")
                    .execute()
                )
            except Exception as exc:
                raise GmailOrganizationGateError(
                    "provider_state_read_failed",
                    "Gmail state revalidation failed before mutation.",
                ) from exc
            if not isinstance(payload, dict) or not str(payload.get("id") or "").strip():
                raise GmailOrganizationGateError(
                    "provider_state_malformed",
                    "Gmail returned malformed state during exact revalidation.",
                )
            values.append(
                GmailObservedMessageState(
                    provider_message_id=str(payload["id"]),
                    provider_thread_id=(
                        str(payload["threadId"])
                        if payload.get("threadId") is not None
                        else None
                    ),
                    label_ids=tuple(sorted(str(value) for value in payload.get("labelIds") or ())),
                    unread="UNREAD" in set(payload.get("labelIds") or ()),
                )
            )
        return tuple(values)

    def modify_message_labels(
        self,
        message_ids: tuple[str, ...],
        *,
        add_label_ids: tuple[str, ...] = (),
        remove_label_ids: tuple[str, ...] = (),
    ) -> GmailBatchMutationResult:
        successful: list[str] = []
        failed: list[str] = []
        diagnostic: str | None = None
        outcome_unknown = False
        for offset in range(0, len(message_ids), self._batch_size):
            chunk = message_ids[offset : offset + self._batch_size]
            try:
                (
                    self._service.users()
                    .messages()
                    .batchModify(
                        userId="me",
                        body={
                            "ids": list(chunk),
                            "addLabelIds": list(add_label_ids),
                            "removeLabelIds": list(remove_label_ids),
                        },
                    )
                    .execute()
                )
                successful.extend(chunk)
            except Exception as exc:
                failed.extend(chunk)
                status = _provider_http_status(exc)
                diagnostic = f"provider_http_{status}" if status else "provider_outcome_unknown"
                outcome_unknown = outcome_unknown or status is None or status >= 500
        return GmailBatchMutationResult(
            successful_message_ids=tuple(successful),
            failed_message_ids=tuple(failed),
            diagnostic_code=diagnostic,
            outcome_unknown=outcome_unknown,
        )

    def create_label(self, name: str) -> GmailCreatedLabel:
        try:
            payload = (
                self._service.users()
                .labels()
                .create(
                    userId="me",
                    body={
                        "name": name,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                )
                .execute()
            )
        except Exception as exc:
            status = _provider_http_status(exc)
            if status is not None and status < 500:
                raise GmailOrganizationGateError(
                    "provider_rejected_label_creation",
                    "Gmail rejected the exact label-creation request.",
                ) from exc
            raise
        if not isinstance(payload, dict):
            raise GmailOrganizationGateError(
                "provider_label_malformed",
                "Gmail returned a malformed created-label identity.",
            )
        return GmailCreatedLabel(
            provider_label_id=str(payload.get("id") or ""),
            name=str(payload.get("name") or ""),
        )


class GmailTargetExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_token: str = Field(min_length=1)
    status: Literal["succeeded", "failed", "outcome_unknown"]
    diagnostic_code: str | None = Field(default=None, min_length=1, max_length=100)


class GmailOrganizationExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    complete: bool
    partial_mutation: bool
    outcome_unknown: bool
    target_results: tuple[GmailTargetExecutionResult, ...]
    provider_references: tuple[ProviderTargetReference, ...]
    undo_payload: ActionPayload | None = None
    errors: tuple[str, ...] = ()


class GmailOrganizationProposalBuilder:
    """Convert a reviewed SID-230 proposal into one immutable typed action."""

    def build(
        self,
        *,
        inventory: PersonalEmailInventoryResult,
        proposal_result: EmailOrganizationProposalResult,
        proposal: OrganizationBatchProposal,
        selected_message_ids: tuple[str, ...],
        label: GmailUserLabelIdentity | None = None,
        canary: bool = False,
        hand_reviewed: bool = False,
    ) -> ActionPayload:
        if (
            not inventory.complete
            or proposal_result.inventory_fingerprint != inventory.stable_fingerprint
        ):
            raise GmailOrganizationGateError(
                "inventory_evidence_mismatch",
                "A complete matching SID-230 inventory is required.",
            )
        registered = {
            item.proposal_id: item for item in proposal_result.proposals
        }.get(proposal.proposal_id)
        if registered != proposal:
            raise GmailOrganizationGateError(
                "proposal_evidence_mismatch",
                "The reviewed proposal does not match the SID-230 evidence set.",
            )
        available_ids = {
            value
            for target in proposal.targets
            for value in target.provider_message_ids
        }
        selected = tuple(dict.fromkeys(selected_message_ids))
        if (
            not selected
            or len(selected) != len(selected_message_ids)
            or any(value not in available_ids for value in selected)
        ):
            raise GmailOrganizationGateError(
                "invalid_reviewed_selection",
                "The adjusted target set must be a non-empty exact subset of the proposal.",
            )
        facts = {
            item.identity.provider_message_id: item
            for source in (inventory.inbox, inventory.old_stuff)
            for item in source.messages
        }
        selected_facts = [facts.get(value) for value in selected]
        if any(item is None for item in selected_facts):
            raise GmailOrganizationGateError(
                "inventory_target_missing",
                "The reviewed target set is not present in the exact inventory.",
            )
        if any(
            item.uncertain or item.protection_reasons
            for item in selected_facts
            if item
        ):
            raise GmailOrganizationGateError(
                "protected_or_uncertain_target",
                "Protected or uncertain mail cannot enter an executable manifest.",
            )
        targets = tuple(
            GmailExpectedMessageState(
                provider_message_id=item.identity.provider_message_id,
                provider_thread_id=item.identity.provider_thread_id,
                expected_label_ids=item.label_ids,
                expected_unread=item.unread,
            )
            for item in selected_facts
            if item is not None
        )
        first_fact = selected_facts[0]
        assert first_fact is not None
        account = first_fact.identity.account
        manifest = GmailOrganizationManifest(
            account=account,
            targets=targets,
            selection_fingerprint=gmail_manifest_fingerprint(account, targets),
            originating_proposal_id=proposal.proposal_id,
            originating_proposal_fingerprint=proposal.selection_fingerprint,
            originating_inventory_fingerprint=inventory.stable_fingerprint,
            selection_criteria=(
                *proposal.selection_criteria,
                (
                    "hand-reviewed exact subset"
                    if len(selected) < proposal.exact_message_count
                    else "hand-reviewed exact manifest"
                ),
            ),
            exclusions=tuple(
                f"{item.value}: {item.count}" for item in proposal.exclusions
            ),
            representative_example_tokens=tuple(
                item.message_token for item in proposal.representative_examples
            ),
        )
        if proposal.operation == FutureOrganizationOperation.LABEL:
            approved_names = {
                value.value
                for value in (
                    *((proposal.organization_label,) if proposal.organization_label else ()),
                    *proposal.topic_labels,
                )
            }
            if label is None or label.name not in approved_names:
                raise GmailOrganizationGateError(
                    "label_identity_mismatch",
                    "The exact user label must match the reviewed SID-230 proposal.",
                )
            return GmailApplyLabelPayload(
                action_type="gmail_apply_label",
                manifest=manifest,
                label=label,
                canary=canary,
                hand_reviewed=hand_reviewed,
            )
        if label is not None or canary:
            raise GmailOrganizationGateError(
                "operation_contract_mismatch",
                "Archive and read-state proposals remain separate from label approval.",
            )
        if proposal.operation == FutureOrganizationOperation.ARCHIVE:
            return GmailArchivePayload(action_type="gmail_archive", manifest=manifest)
        if proposal.operation == FutureOrganizationOperation.MARK_READ:
            return GmailMarkReadPayload(action_type="gmail_mark_read", manifest=manifest)
        raise GmailOrganizationGateError(
            "unsupported_operation",
            "Unsupported Gmail proposal operation.",
        )


@dataclass(frozen=True)
class _GateRecord:
    authorized_scope: str | None
    approval_reference: str | None
    oauth_authorized_at: datetime | None
    canary_action_id: str | None
    canary_manifest_fingerprint: str | None
    canary_label_id: str | None
    canary_applied_at: datetime | None
    canary_undo_action_id: str | None
    canary_undo_verified_at: datetime | None
    provider_mutation_calls: int


class GmailMutationGateRepository:
    """Durable authorization and canary sequence; it stores no email content."""

    def status(self) -> GmailMutationGateStatus:
        record = self._get()
        if record.oauth_authorized_at is None:
            state = GmailMutationGateState.MANUAL_OAUTH_REQUIRED
            allowed = ()
        elif record.canary_applied_at is None:
            state = GmailMutationGateState.LABEL_CANARY_REQUIRED
            allowed = ("gmail_apply_label_canary",)
        elif record.canary_undo_verified_at is None:
            state = GmailMutationGateState.LABEL_CANARY_UNDO_REQUIRED
            allowed = ("gmail_remove_label_canary_undo",)
        else:
            state = GmailMutationGateState.CANARY_VERIFIED
            allowed = (
                "gmail_apply_label",
                "gmail_remove_label",
                "gmail_archive",
                "gmail_restore_inbox",
                "gmail_mark_read",
                "gmail_mark_unread",
                "gmail_create_label",
            )
        return GmailMutationGateStatus(
            state=state,
            oauth_authorized=record.oauth_authorized_at is not None,
            label_canary_applied=record.canary_applied_at is not None,
            label_canary_undo_verified=record.canary_undo_verified_at is not None,
            allowed_next_operations=allowed,
            provider_mutation_calls=record.provider_mutation_calls,
        )

    def record_manual_oauth_authorization(
        self,
        *,
        authorized_scope: str,
        approval_reference: str,
        now: datetime | None = None,
    ) -> GmailMutationGateStatus:
        if authorized_scope != GMAIL_MODIFY_SCOPE:
            raise GmailOrganizationGateError(
                "scope_mismatch",
                "Gmail organization requires the exact approved gmail.modify scope.",
            )
        if not approval_reference.strip():
            raise GmailOrganizationGateError(
                "approval_reference_required",
                "Manual OAuth authorization requires an explicit approval reference.",
            )
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        with database_connection() as connection:
            connection.execute(
                """
                INSERT INTO gmail_mutation_gate (
                    singleton_id, authorized_scope, approval_reference,
                    oauth_authorized_at, updated_at
                ) VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    authorized_scope = excluded.authorized_scope,
                    approval_reference = excluded.approval_reference,
                    oauth_authorized_at = excluded.oauth_authorized_at,
                    canary_action_id = NULL,
                    canary_manifest_fingerprint = NULL,
                    canary_label_id = NULL,
                    canary_applied_at = NULL,
                    canary_undo_action_id = NULL,
                    canary_undo_verified_at = NULL,
                    provider_mutation_calls = 0,
                    updated_at = excluded.updated_at
                """,
                (authorized_scope, approval_reference, timestamp, timestamp),
            )
        return self.status()

    def record_provider_mutation_call(self) -> None:
        with database_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE gmail_mutation_gate
                SET provider_mutation_calls = provider_mutation_calls + 1,
                    updated_at = ?
                WHERE singleton_id = 1 AND oauth_authorized_at IS NOT NULL
                    AND authorized_scope = ?
                """,
                (datetime.now(timezone.utc).isoformat(), GMAIL_MODIFY_SCOPE),
            )
        if cursor.rowcount != 1:
            raise GmailOrganizationGateError(
                "authorization_gate_changed",
                "Gmail authorization gate changed before the provider call.",
            )

    def assert_execution_allowed(self, payload: ActionPayload) -> None:
        record = self._get()
        if record.oauth_authorized_at is None or record.authorized_scope != GMAIL_MODIFY_SCOPE:
            raise GmailOrganizationGateError(
                "manual_oauth_required",
                "Gmail mutation is blocked until explicit OAuth approval and reauthorization.",
            )
        if record.canary_applied_at is None:
            if not (
                isinstance(payload, GmailApplyLabelPayload)
                and payload.canary
                and payload.hand_reviewed
                and len(payload.manifest.targets) <= MAX_LIVE_LABEL_CANARY_MESSAGES
            ):
                raise GmailOrganizationGateError(
                    "label_canary_required",
                    "The first live mutation must be a hand-reviewed label-only canary of at most 10 messages.",
                )
            return
        if record.canary_undo_verified_at is None:
            if not (
                isinstance(payload, GmailRemoveLabelPayload)
                and payload.canary_undo
                and payload.hand_reviewed
                and payload.undo_of_action_id == record.canary_action_id
                and payload.manifest.selection_fingerprint
                == record.canary_manifest_fingerprint
                and payload.label.provider_label_id == record.canary_label_id
            ):
                raise GmailOrganizationGateError(
                    "label_canary_undo_required",
                    "The exact label canary undo must succeed before any other Gmail operation.",
                )

    def record_success(self, action_id: str, payload: ActionPayload) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if isinstance(payload, GmailApplyLabelPayload) and payload.canary:
            post_targets = _post_states(payload)
            post_fingerprint = gmail_manifest_fingerprint(
                payload.manifest.account,
                post_targets,
            )
            with database_connection() as connection:
                connection.execute(
                    """
                    UPDATE gmail_mutation_gate
                    SET canary_action_id = ?, canary_manifest_fingerprint = ?,
                        canary_label_id = ?, canary_applied_at = ?, updated_at = ?
                    WHERE singleton_id = 1 AND oauth_authorized_at IS NOT NULL
                        AND canary_applied_at IS NULL
                    """,
                    (
                        action_id,
                        post_fingerprint,
                        payload.label.provider_label_id,
                        now,
                        now,
                    ),
                )
        elif isinstance(payload, GmailRemoveLabelPayload) and payload.canary_undo:
            with database_connection() as connection:
                connection.execute(
                    """
                    UPDATE gmail_mutation_gate
                    SET canary_undo_action_id = ?, canary_undo_verified_at = ?,
                        updated_at = ?
                    WHERE singleton_id = 1 AND canary_action_id = ?
                        AND canary_manifest_fingerprint = ? AND canary_label_id = ?
                        AND canary_undo_verified_at IS NULL
                    """,
                    (
                        action_id,
                        now,
                        now,
                        payload.undo_of_action_id,
                        payload.manifest.selection_fingerprint,
                        payload.label.provider_label_id,
                    ),
                )

    def _get(self) -> _GateRecord:
        with database_connection() as connection:
            row = connection.execute(
                "SELECT * FROM gmail_mutation_gate WHERE singleton_id = 1"
            ).fetchone()
        if row is None:
            return _GateRecord(None, None, None, None, None, None, None, None, None, 0)
        item = dict(row)
        return _GateRecord(
            authorized_scope=item["authorized_scope"],
            approval_reference=item["approval_reference"],
            oauth_authorized_at=_optional_datetime(item["oauth_authorized_at"]),
            canary_action_id=item["canary_action_id"],
            canary_manifest_fingerprint=item["canary_manifest_fingerprint"],
            canary_label_id=item["canary_label_id"],
            canary_applied_at=_optional_datetime(item["canary_applied_at"]),
            canary_undo_action_id=item["canary_undo_action_id"],
            canary_undo_verified_at=_optional_datetime(item["canary_undo_verified_at"]),
            provider_mutation_calls=int(item["provider_mutation_calls"]),
        )


class GmailOrganizationAdapter:
    """Exact-state Gmail organization adapter with no forbidden capabilities."""

    def __init__(
        self,
        transport: GmailOrganizationTransport,
        gate_repository: GmailMutationGateRepository,
    ) -> None:
        self._transport = transport
        self._gate_repository = gate_repository

    def execute(
        self, action_id: str, payload: ActionPayload
    ) -> GmailOrganizationExecutionResult:
        self._gate_repository.assert_execution_allowed(payload)
        if isinstance(payload, GmailCreateLabelPayload):
            self._gate_repository.record_provider_mutation_call()
            label = self._transport.create_label(payload.label_name)
            self._gate_repository.record_success(action_id, payload)
            return GmailOrganizationExecutionResult(
                complete=True,
                partial_mutation=False,
                outcome_unknown=False,
                target_results=(),
                provider_references=(
                    ProviderTargetReference(
                        provider="gmail",
                        resource_type="label",
                        provider_ref=label.provider_label_id,
                    ),
                ),
            )

        manifest = payload.manifest
        self._assert_current_state(manifest)
        add_labels, remove_labels = _label_delta(payload)
        message_ids = tuple(item.provider_message_id for item in manifest.targets)
        self._gate_repository.record_provider_mutation_call()
        result = self._transport.modify_message_labels(
            message_ids,
            add_label_ids=add_labels,
            remove_label_ids=remove_labels,
        )
        target_results = _target_results(message_ids, result)
        if result.outcome_unknown:
            return GmailOrganizationExecutionResult(
                complete=False,
                partial_mutation=bool(result.successful_message_ids),
                outcome_unknown=True,
                target_results=target_results,
                provider_references=_message_refs(result.successful_message_ids),
                errors=("Gmail returned an uncertain mutation outcome.",),
            )
        if result.failed_message_ids:
            return GmailOrganizationExecutionResult(
                complete=False,
                partial_mutation=bool(result.successful_message_ids),
                outcome_unknown=False,
                target_results=target_results,
                provider_references=_message_refs(result.successful_message_ids),
                errors=("Gmail organization completed only partially.",),
            )
        self._assert_post_state(payload)
        self._gate_repository.record_success(action_id, payload)
        return GmailOrganizationExecutionResult(
            complete=True,
            partial_mutation=False,
            outcome_unknown=False,
            target_results=target_results,
            provider_references=_message_refs(message_ids),
            undo_payload=_undo_payload(action_id, payload),
        )

    def _assert_current_state(self, manifest: GmailOrganizationManifest) -> None:
        ids = tuple(item.provider_message_id for item in manifest.targets)
        observed = self._transport.get_message_states(ids)
        by_id = {item.provider_message_id: item for item in observed}
        if len(by_id) != len(ids):
            raise GmailOrganizationGateError(
                "mailbox_state_incomplete",
                "Gmail state revalidation did not return the complete exact target set.",
            )
        for expected in manifest.targets:
            actual = by_id.get(expected.provider_message_id)
            if actual is None or (
                tuple(sorted(actual.label_ids)) != expected.expected_label_ids
                or actual.unread != expected.expected_unread
                or actual.provider_thread_id != expected.provider_thread_id
            ):
                raise GmailOrganizationGateError(
                    "stale_mailbox_state",
                    "Gmail target state changed; a fresh proposal and approval are required.",
                )

    def _assert_post_state(self, payload: ActionPayload) -> None:
        expected = _post_states(payload)
        observed = self._transport.get_message_states(
            tuple(item.provider_message_id for item in expected)
        )
        by_id = {item.provider_message_id: item for item in observed}
        if len(by_id) != len(expected):
            raise GmailOrganizationGateError(
                "post_state_incomplete",
                "Gmail mutation result could not be fully verified.",
            )
        for item in expected:
            actual = by_id.get(item.provider_message_id)
            if actual is None or (
                tuple(sorted(actual.label_ids)) != item.expected_label_ids
                or actual.unread != item.expected_unread
            ):
                raise GmailOrganizationGateError(
                    "post_state_mismatch",
                    "Gmail mutation result did not match the exact requested state.",
                )


def _label_delta(payload: ActionPayload) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if isinstance(payload, GmailApplyLabelPayload):
        return (payload.label.provider_label_id,), ()
    if isinstance(payload, GmailRemoveLabelPayload):
        return (), (payload.label.provider_label_id,)
    if isinstance(payload, GmailArchivePayload):
        return (), ("INBOX",)
    if isinstance(payload, GmailRestoreInboxPayload):
        return ("INBOX",), ()
    if isinstance(payload, GmailMarkReadPayload):
        return (), ("UNREAD",)
    if isinstance(payload, GmailMarkUnreadPayload):
        return ("UNREAD",), ()
    raise TypeError("Unsupported Gmail organization payload")


def _post_states(payload: ActionPayload) -> tuple[GmailExpectedMessageState, ...]:
    add_labels, remove_labels = _label_delta(payload)
    values: list[GmailExpectedMessageState] = []
    for target in payload.manifest.targets:
        labels = (set(target.expected_label_ids) | set(add_labels)) - set(remove_labels)
        unread = "UNREAD" in labels
        values.append(
            GmailExpectedMessageState(
                provider_message_id=target.provider_message_id,
                provider_thread_id=target.provider_thread_id,
                expected_label_ids=tuple(sorted(labels)),
                expected_unread=unread,
            )
        )
    return tuple(values)


def _undo_payload(action_id: str, payload: ActionPayload) -> ActionPayload:
    post = _post_states(payload)
    original = payload.manifest
    manifest = GmailOrganizationManifest(
        account=original.account,
        targets=post,
        selection_fingerprint=gmail_manifest_fingerprint(original.account, post),
        originating_proposal_id=original.originating_proposal_id,
        originating_proposal_fingerprint=original.originating_proposal_fingerprint,
        originating_inventory_fingerprint=original.originating_inventory_fingerprint,
        selection_criteria=("undo exact verified Gmail organization action",),
        exclusions=original.exclusions,
        representative_example_tokens=original.representative_example_tokens,
    )
    if isinstance(payload, GmailApplyLabelPayload):
        return GmailRemoveLabelPayload(
            action_type="gmail_remove_label",
            manifest=manifest,
            label=payload.label,
            canary_undo=payload.canary,
            hand_reviewed=payload.hand_reviewed,
            undo_of_action_id=action_id,
        )
    if isinstance(payload, GmailRemoveLabelPayload):
        return GmailApplyLabelPayload(
            action_type="gmail_apply_label",
            manifest=manifest,
            label=payload.label,
            hand_reviewed=payload.hand_reviewed,
            undo_of_action_id=action_id,
        )
    if isinstance(payload, GmailArchivePayload):
        return GmailRestoreInboxPayload(
            action_type="gmail_restore_inbox",
            manifest=manifest,
            undo_of_action_id=action_id,
        )
    if isinstance(payload, GmailRestoreInboxPayload):
        return GmailArchivePayload(
            action_type="gmail_archive",
            manifest=manifest,
            undo_of_action_id=action_id,
        )
    if isinstance(payload, GmailMarkReadPayload):
        return GmailMarkUnreadPayload(
            action_type="gmail_mark_unread",
            manifest=manifest,
            undo_of_action_id=action_id,
        )
    if isinstance(payload, GmailMarkUnreadPayload):
        return GmailMarkReadPayload(
            action_type="gmail_mark_read",
            manifest=manifest,
            undo_of_action_id=action_id,
        )
    raise TypeError("Gmail label creation has no automatic undo action")


def _target_results(
    message_ids: tuple[str, ...], result: GmailBatchMutationResult
) -> tuple[GmailTargetExecutionResult, ...]:
    successful = set(result.successful_message_ids)
    failed = set(result.failed_message_ids)
    return tuple(
        GmailTargetExecutionResult(
            message_token=_redacted_token(message_id),
            status=(
                "outcome_unknown"
                if result.outcome_unknown and message_id not in successful
                else "failed"
                if message_id in failed
                else "succeeded"
            ),
            diagnostic_code=(
                result.diagnostic_code
                if message_id in failed or result.outcome_unknown
                else None
            ),
        )
        for message_id in message_ids
    )


def _message_refs(message_ids: tuple[str, ...]) -> tuple[ProviderTargetReference, ...]:
    return tuple(
        ProviderTargetReference(
            provider="gmail", resource_type="message", provider_ref=value
        )
        for value in message_ids
    )


def _redacted_token(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _optional_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _provider_http_status(exc: Exception) -> int | None:
    response = getattr(exc, "resp", None)
    value = getattr(response, "status", None) or getattr(exc, "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
