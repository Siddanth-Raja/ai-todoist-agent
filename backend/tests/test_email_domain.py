from datetime import date, datetime, timezone
from pathlib import Path
import sys
import unittest

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.email_domain import (  # noqa: E402
    DeterministicEmailEvidence,
    EmailAccountRole,
    EmailActionProposal,
    EmailAttentionCandidate,
    EmailAttentionKind,
    EmailCandidateLifecycle,
    EmailDeadline,
    EmailDeadlineState,
    EmailEvidenceKind,
    EmailImportance,
    EmailMessageIdentity,
    EmailModelInterpretation,
    EmailOrganizationDisposition,
    EmailOrganizationSuggestion,
    EmailProjectAssociation,
    EmailProjectAssociationState,
    EmailProposalKind,
    EmailProviderAccountIdentity,
    EmailRequestedAction,
    EmailThreadState,
    EmailUrgency,
)


class EmailDomainTests(unittest.TestCase):
    def setUp(self):
        self.account = EmailProviderAccountIdentity(
            provider="provider-a",
            account_role=EmailAccountRole.PERSONAL,
            provider_account_id="account-personal-1",
        )
        self.message = EmailMessageIdentity(
            account=self.account,
            provider_message_id="message-1",
            provider_thread_id="thread-1",
        )
        self.deadline_evidence = DeterministicEmailEvidence(
            kind=EmailEvidenceKind.BODY_EXCERPT,
            source_field="text_body",
            value="Submit the synthetic form by July 25.",
        )
        self.project = EmailProjectAssociation(
            state=EmailProjectAssociationState.GROUNDED,
            canonical_project_id="project-synthetic",
            evidence=(
                DeterministicEmailEvidence(
                    kind=EmailEvidenceKind.SUBJECT,
                    source_field="subject",
                    value="Synthetic project review",
                ),
            ),
        )

    def _candidate(self, **overrides):
        values = {
            "candidate_id": "candidate-1",
            "message": self.message,
            "received_at": datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc),
            "thread_state": EmailThreadState(is_unread=True),
            "attention_kinds": (EmailAttentionKind.IMPORTANT_ATTENTION,),
            "importance": EmailImportance.HIGH,
            "urgency": EmailUrgency.LOW,
            "project_association": self.project,
            "confidence": 1.0,
            "deterministic_evidence": (self.deadline_evidence,),
        }
        values.update(overrides)
        return EmailAttentionCandidate(**values)

    def test_identity_preserves_provider_account_role_message_and_thread(self):
        second = EmailMessageIdentity(
            account=EmailProviderAccountIdentity(
                provider="provider-b",
                account_role=EmailAccountRole.AM,
                provider_account_id="account-school-1",
            ),
            provider_message_id="message-1",
            provider_thread_id="thread-1",
        )

        self.assertNotEqual(self.message, second)
        self.assertEqual(self.message.account.account_role, EmailAccountRole.PERSONAL)
        self.assertEqual(second.account.account_role, EmailAccountRole.AM)
        self.assertEqual(self.message.provider_message_id, second.provider_message_id)

    def test_thread_state_and_timestamps_remain_absent_when_unknown(self):
        candidate = self._candidate(received_at=None, thread_state=None)

        self.assertIsNone(candidate.received_at)
        self.assertIsNone(candidate.sent_at)
        self.assertIsNone(candidate.thread_state)
        with self.assertRaisesRegex(ValidationError, "at least one known fact"):
            EmailThreadState()

    def test_importance_and_urgency_are_independent(self):
        candidate = self._candidate(
            importance=EmailImportance.HIGH,
            urgency=EmailUrgency.LOW,
        )

        self.assertEqual(candidate.importance, EmailImportance.HIGH)
        self.assertEqual(candidate.urgency, EmailUrgency.LOW)

    def test_grounded_deadline_requires_value_and_exact_source_evidence(self):
        deadline = EmailDeadline(
            state=EmailDeadlineState.GROUNDED,
            value=date(2026, 7, 25),
            source_evidence=(self.deadline_evidence,),
        )
        candidate = self._candidate(
            attention_kinds=(
                EmailAttentionKind.DEADLINE,
                EmailAttentionKind.ADMINISTRATIVE_REQUIREMENT,
            ),
            deadline=deadline,
        )

        self.assertEqual(candidate.deadline.value, date(2026, 7, 25))
        self.assertEqual(
            candidate.deadline.source_evidence[0].value,
            "Submit the synthetic form by July 25.",
        )
        with self.assertRaisesRegex(ValidationError, "requires a value"):
            EmailDeadline(
                state=EmailDeadlineState.GROUNDED,
                source_evidence=(self.deadline_evidence,),
            )

    def test_ambiguous_deadline_cannot_claim_a_concrete_value(self):
        deadline = EmailDeadline(
            state=EmailDeadlineState.AMBIGUOUS,
            source_evidence=(self.deadline_evidence,),
            ambiguity_reason="The message gives a month and day but no year.",
        )
        candidate = self._candidate(
            attention_kinds=(EmailAttentionKind.DEADLINE,),
            deadline=deadline,
            confidence=0.6,
            review_reasons=("Deadline year requires review.",),
        )

        self.assertIsNone(candidate.deadline.value)
        with self.assertRaisesRegex(ValidationError, "cannot claim a concrete value"):
            EmailDeadline(
                state=EmailDeadlineState.AMBIGUOUS,
                value=date(2026, 7, 25),
                source_evidence=(self.deadline_evidence,),
                ambiguity_reason="The year is unclear.",
            )

    def test_requested_action_preserves_responsible_party_and_evidence(self):
        requested_action = EmailRequestedAction(
            description="Review and submit the synthetic form.",
            responsible_party="account owner",
            source_evidence=(self.deadline_evidence,),
        )
        candidate = self._candidate(
            attention_kinds=(EmailAttentionKind.EXPLICIT_ACTION_REQUEST,),
            requested_action=requested_action,
        )

        self.assertEqual(candidate.requested_action.responsible_party, "account owner")
        self.assertEqual(candidate.requested_action.source_evidence, (self.deadline_evidence,))

    def test_project_association_preserves_grounded_ambiguous_and_unresolved(self):
        ambiguous = EmailProjectAssociation(
            state=EmailProjectAssociationState.AMBIGUOUS,
            candidate_project_ids=("project-a", "project-b"),
        )
        unresolved = EmailProjectAssociation(
            state=EmailProjectAssociationState.UNRESOLVED,
        )

        self.assertEqual(self.project.canonical_project_id, "project-synthetic")
        self.assertIsNone(ambiguous.canonical_project_id)
        self.assertEqual(ambiguous.candidate_project_ids, ("project-a", "project-b"))
        self.assertIsNone(unresolved.canonical_project_id)
        with self.assertRaisesRegex(ValidationError, "cannot claim project identity"):
            EmailProjectAssociation(
                state=EmailProjectAssociationState.UNRESOLVED,
                candidate_project_ids=("project-a",),
            )

    def test_task_and_calendar_proposals_are_descriptive_and_non_executable(self):
        task = EmailActionProposal(
            kind=EmailProposalKind.TASK,
            title="Submit synthetic form",
            description="Possible task for later approval.",
            source_evidence=(self.deadline_evidence,),
        )
        calendar = EmailActionProposal(
            kind=EmailProposalKind.CALENDAR,
            title="Synthetic deadline",
            description="Possible Calendar entry for later approval.",
            source_evidence=(self.deadline_evidence,),
        )
        candidate = self._candidate(action_proposals=(task, calendar))

        self.assertEqual(
            [proposal.kind for proposal in candidate.action_proposals],
            [EmailProposalKind.TASK, EmailProposalKind.CALENDAR],
        )
        self.assertNotIn("is_executable", EmailActionProposal.model_fields)
        self.assertNotIn("completed", EmailActionProposal.model_fields)
        with self.assertRaises(ValidationError):
            EmailActionProposal(
                kind=EmailProposalKind.TASK,
                title="Invalid executable proposal",
                description="Must be rejected.",
                source_evidence=(self.deadline_evidence,),
                is_executable=True,
            )

    def test_deterministic_evidence_and_model_interpretation_cannot_be_conflated(self):
        interpretation = EmailModelInterpretation(
            summary="This may require administrative follow-through.",
            confidence=0.75,
            uncertainty_reasons=("The responsible party is not explicit.",),
        )
        candidate = self._candidate(
            confidence=0.75,
            review_reasons=("Responsible party needs review.",),
            model_interpretation=interpretation,
        )

        self.assertIsInstance(candidate.deterministic_evidence[0], DeterministicEmailEvidence)
        self.assertIsInstance(candidate.model_interpretation, EmailModelInterpretation)
        with self.assertRaisesRegex(ValidationError, "uncertainty reasons"):
            EmailModelInterpretation(
                summary="Unsupported certainty",
                confidence=0.75,
            )

    def test_lifecycle_supports_dismissed_resolved_and_superseded(self):
        dismissed = self._candidate(lifecycle=EmailCandidateLifecycle.DISMISSED)
        resolved = self._candidate(lifecycle=EmailCandidateLifecycle.RESOLVED)
        superseded = self._candidate(
            lifecycle=EmailCandidateLifecycle.SUPERSEDED,
            superseded_by_candidate_id="candidate-2",
        )

        self.assertEqual(dismissed.lifecycle, EmailCandidateLifecycle.DISMISSED)
        self.assertEqual(resolved.lifecycle, EmailCandidateLifecycle.RESOLVED)
        self.assertEqual(superseded.superseded_by_candidate_id, "candidate-2")
        with self.assertRaisesRegex(ValidationError, "requires its replacement"):
            self._candidate(lifecycle=EmailCandidateLifecycle.SUPERSEDED)

    def test_organization_suggestion_is_advisory_and_uncertain_mail_stays_untouched(self):
        suggestion = EmailOrganizationSuggestion(
            disposition=EmailOrganizationDisposition.KEEP_REFERENCE,
            proposed_labels=("Synthetic reference",),
        )
        candidate = self._candidate(organization_suggestion=suggestion)

        self.assertTrue(candidate.organization_suggestion.approval_required)
        self.assertNotIn("provider_action", EmailOrganizationSuggestion.model_fields)
        self.assertNotIn("approval_payload", EmailOrganizationSuggestion.model_fields)
        with self.assertRaises(ValidationError):
            EmailOrganizationSuggestion(
                disposition=EmailOrganizationDisposition.KEEP_REFERENCE,
                approval_required=False,
            )
        with self.assertRaisesRegex(ValidationError, "uncertain mail"):
            EmailOrganizationSuggestion(
                disposition=EmailOrganizationDisposition.REVIEW_UNCERTAIN,
                proposed_labels=("Maybe later",),
            )

    def test_delete_and_trash_cannot_be_represented_as_proposals(self):
        with self.assertRaises(ValidationError):
            EmailActionProposal(
                kind="delete",
                title="Forbidden",
                description="Forbidden mailbox mutation.",
                source_evidence=(self.deadline_evidence,),
            )
        for forbidden_label in (
            "delete",
            "trash",
            "Deleted",
            "TRASH",
            "trash after review",
        ):
            with self.subTest(forbidden_label=forbidden_label):
                with self.assertRaisesRegex(ValidationError, "cannot be proposed"):
                    EmailOrganizationSuggestion(
                        disposition=EmailOrganizationDisposition.LOW_VALUE,
                        proposed_labels=(forbidden_label,),
                    )

    def test_models_are_frozen_and_reject_unknown_fields(self):
        candidate = self._candidate()

        with self.assertRaises(ValidationError):
            candidate.importance = EmailImportance.LOW
        with self.assertRaises(ValidationError):
            EmailProviderAccountIdentity(
                provider="provider-a",
                account_role=EmailAccountRole.BLINN,
                provider_account_id="account-blinn-1",
                unexpected_identity_field="not-allowed",
            )


if __name__ == "__main__":
    unittest.main()
