from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.email_analysis import (  # noqa: E402
    DEFAULT_ANALYSIS_MAX_MESSAGES,
    MAX_ANALYSIS_MESSAGES,
    EmailAnalysisService,
    EmailAnalysisState,
    EmailSignalCategory,
    EmailSurfaceDecision,
)
from app.email_domain import (  # noqa: E402
    EmailAccountRole,
    EmailAttentionKind,
    EmailDeadlineState,
    EmailImportance,
    EmailMessageIdentity,
    EmailModelInterpretation,
    EmailOrganizationDisposition,
    EmailProjectAssociationState,
    EmailProviderAccountIdentity,
    EmailUrgency,
)
from app.gmail_client import (  # noqa: E402
    GmailAttachmentMetadata,
    GmailMessagePage,
    GmailMessageRecord,
    GmailProviderDiagnostic,
    GmailProviderState,
)
from app.project_registry import ProjectRegistrySnapshot  # noqa: E402


BASE_TIME = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
ACCOUNT = EmailProviderAccountIdentity(
    provider="gmail",
    account_role=EmailAccountRole.PERSONAL,
    provider_account_id="personal-account-synthetic",
)
OTHER_ACCOUNT = EmailProviderAccountIdentity(
    provider="gmail",
    account_role=EmailAccountRole.PERSONAL,
    provider_account_id="other-personal-account-synthetic",
)
REGISTRY = ProjectRegistrySnapshot(
    projects=(
        {
            "canonical_project_id": "project-pcos",
            "key": "pcos",
            "name": "PCOS",
            "keywords": ("chief of staff",),
            "people": (),
            "system_state": False,
        },
        {
            "canonical_project_id": "project-nebulo",
            "key": "nebulo",
            "name": "Nebulo",
            "keywords": ("context control",),
            "people": ("Brandon",),
            "system_state": False,
        },
        {
            "canonical_project_id": "project-xo",
            "key": "xo",
            "name": "XO",
            "keywords": ("headset prototype",),
            "people": ("Ashwin",),
            "system_state": False,
        },
        {
            "canonical_project_id": None,
            "key": "needs-classification",
            "name": "Needs Classification",
            "keywords": (),
            "people": (),
            "system_state": True,
        },
    ),
    aliases={
        "pcos": "pcos",
        "chief-of-staff": "pcos",
        "nebulo": "nebulo",
        "xo": "xo",
    },
)


def message(
    message_id: str,
    *,
    thread_id: str | None = None,
    subject: str = "Synthetic update",
    body: str = "Synthetic informational body.",
    sender: str = "Synthetic Sender",
    labels: tuple[str, ...] = ("INBOX", "UNREAD"),
    minute: int = 0,
    account: EmailProviderAccountIdentity = ACCOUNT,
    diagnostics: tuple[str, ...] = (),
    truncated: bool = False,
    attachment: bool = False,
) -> GmailMessageRecord:
    attachments = (
        GmailAttachmentMetadata(
            filename="synthetic.pdf",
            mime_type="application/pdf",
            size=128,
            provider_attachment_id="attachment-synthetic",
        ),
    ) if attachment else ()
    return GmailMessageRecord(
        identity=EmailMessageIdentity(
            account=account,
            provider_message_id=message_id,
            provider_thread_id=thread_id,
        ),
        sender=sender,
        recipients=("Synthetic Account Owner",),
        subject=subject,
        internal_date=BASE_TIME + timedelta(minutes=minute),
        message_date=BASE_TIME + timedelta(minutes=minute),
        label_ids=labels,
        unread="UNREAD" in labels,
        snippet="Synthetic bounded snippet",
        body_text=body,
        body_truncated=truncated,
        attachments=attachments,
        parse_diagnostics=diagnostics,
        provider_metadata={"mime_type": "text/plain"},
    )


def page(
    *messages: GmailMessageRecord,
    state: GmailProviderState | None = None,
    diagnostic: GmailProviderDiagnostic | None = None,
    complete: bool = True,
    truncated: bool = False,
) -> GmailMessagePage:
    resolved_state = state or (
        GmailProviderState.CONNECTED if messages else GmailProviderState.CONNECTED_EMPTY
    )
    return GmailMessagePage(
        state=resolved_state,
        messages=messages,
        complete=complete,
        truncated=truncated,
        pages_fetched=1 if messages else 0,
        result_size_estimate=len(messages),
        diagnostic=diagnostic,
    )


class FakeRegistryService:
    def snapshot(self):
        return REGISTRY


class FakeGmailClient:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def list_recent_messages(self, *, max_messages):
        self.calls.append(("list_recent_messages", max_messages))
        return self.result


class SyntheticInterpreter:
    def __init__(self):
        self.calls = []

    def interpret(self, record, evidence):
        self.calls.append((record, evidence))
        return EmailModelInterpretation(
            summary="Synthetic interpretation remains non-canonical.",
            confidence=0.8,
            uncertainty_reasons=("Synthetic test interpretation.",),
        )


class EmailAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.service = EmailAnalysisService(
            registry_service=FakeRegistryService(),
            clock=lambda: BASE_TIME,
        )

    def analyze(self, *records, **page_kwargs):
        return self.service.analyze_page(
            page(*records, **page_kwargs),
            registry=REGISTRY,
        )

    def test_academic_admin_deadline_preserves_grounded_action_and_date(self):
        result = self.analyze(
            message(
                "academic-1",
                subject="Synthetic registrar action required",
                body="Please submit the required registration form by July 25, 2026.",
            )
        )

        assessment = result.assessments[0]
        candidate = assessment.candidate
        self.assertEqual(result.state, EmailAnalysisState.CONNECTED_ATTENTION)
        self.assertIsNotNone(candidate)
        self.assertEqual(assessment.importance, EmailImportance.HIGH)
        self.assertEqual(assessment.urgency, EmailUrgency.MEDIUM)
        self.assertEqual(
            assessment.organization_disposition,
            EmailOrganizationDisposition.NEEDS_ACTION,
        )
        self.assertIn(EmailAttentionKind.ADMINISTRATIVE_REQUIREMENT, assessment.attention_kinds)
        self.assertIn(EmailAttentionKind.EXPLICIT_ACTION_REQUEST, assessment.attention_kinds)
        self.assertEqual(candidate.deadline.state, EmailDeadlineState.GROUNDED)
        self.assertEqual(str(candidate.deadline.value), "2026-07-25")
        self.assertIn("July 25, 2026", candidate.deadline.source_evidence[0].value)
        self.assertEqual(candidate.action_proposals, ())

    def test_scheduling_request_is_separate_from_importance_and_disposition(self):
        result = self.analyze(
            message(
                "schedule-1",
                subject="Synthetic meeting request",
                body="Please reply with your availability so we can schedule a meeting.",
            )
        )
        assessment = result.assessments[0]

        self.assertIn(EmailAttentionKind.SCHEDULING_REQUEST, assessment.attention_kinds)
        self.assertEqual(assessment.importance, EmailImportance.HIGH)
        self.assertEqual(assessment.urgency, EmailUrgency.MEDIUM)
        self.assertEqual(assessment.surface_decision, EmailSurfaceDecision.SURFACE)
        self.assertEqual(
            assessment.organization_disposition,
            EmailOrganizationDisposition.NEEDS_ACTION,
        )

    def test_financial_and_security_requirements_are_protected(self):
        cases = (
            ("Payment required: balance due", "Please pay by 2026-07-30."),
            ("Security alert", "Unusual activity detected; verify your account."),
        )
        for index, (subject, body) in enumerate(cases):
            with self.subTest(subject=subject):
                assessment = self.analyze(
                    message(f"protected-{index}", subject=subject, body=body)
                ).assessments[0]
                self.assertEqual(assessment.surface_decision, EmailSurfaceDecision.SURFACE)
                self.assertEqual(assessment.importance, EmailImportance.HIGH)
                self.assertIn(
                    EmailAttentionKind.ADMINISTRATIVE_REQUIREMENT,
                    assessment.attention_kinds,
                )

    def test_direct_project_communication_grounds_canonical_registry_id(self):
        assessment = self.analyze(
            message(
                "project-1",
                subject="Nebulo context control update",
                body="Brandon shared the next synthetic review note.",
            )
        ).assessments[0]

        self.assertEqual(
            assessment.project_association.state,
            EmailProjectAssociationState.GROUNDED,
        )
        self.assertEqual(
            assessment.project_association.canonical_project_id,
            "project-nebulo",
        )
        self.assertIn(EmailAttentionKind.PROJECT_COMMUNICATION, assessment.attention_kinds)
        self.assertEqual(assessment.surface_decision, EmailSurfaceDecision.SURFACE)

    def test_receipt_reference_remains_quiet_without_current_action(self):
        result = self.analyze(
            message(
                "receipt-1",
                subject="Synthetic payment confirmation",
                body="This receipt is your transaction record. No action is needed.",
                labels=("INBOX",),
            )
        )
        assessment = result.assessments[0]

        self.assertEqual(result.state, EmailAnalysisState.CONNECTED_QUIET)
        self.assertEqual(
            assessment.organization_disposition,
            EmailOrganizationDisposition.KEEP_REFERENCE,
        )
        self.assertEqual(assessment.surface_decision, EmailSurfaceDecision.QUIET)
        self.assertIsNone(assessment.candidate)

    def test_promotional_automated_mail_requires_multiple_grounded_bulk_signals(self):
        assessment = self.analyze(
            message(
                "promo-1",
                subject="Synthetic newsletter special offer",
                body="Limited offer. Shop now. Unsubscribe from this newsletter.",
                sender="no-reply synthetic sender",
                labels=("CATEGORY_PROMOTIONS",),
            )
        ).assessments[0]

        self.assertEqual(
            assessment.organization_disposition,
            EmailOrganizationDisposition.LOW_VALUE,
        )
        self.assertEqual(assessment.surface_decision, EmailSurfaceDecision.QUIET)
        self.assertGreaterEqual(len(assessment.evidence_categories), 3)

    def test_gmail_important_label_cannot_decide_alone(self):
        assessment = self.analyze(
            message(
                "label-1",
                subject="Synthetic informational update",
                body="A general update with no requested action.",
                labels=("IMPORTANT", "INBOX"),
            )
        ).assessments[0]

        self.assertEqual(assessment.importance, EmailImportance.MEDIUM)
        self.assertEqual(assessment.surface_decision, EmailSurfaceDecision.QUIET)
        self.assertEqual(
            assessment.organization_disposition,
            EmailOrganizationDisposition.KEEP_REFERENCE,
        )

    def test_protected_signal_defeats_bulk_classification(self):
        assessment = self.analyze(
            message(
                "bulk-conflict-1",
                subject="Security alert and special offer",
                body="Unusual activity detected. Verify your account. Unsubscribe here.",
                sender="no-reply synthetic sender",
                labels=("CATEGORY_PROMOTIONS",),
            )
        ).assessments[0]

        self.assertEqual(
            assessment.organization_disposition,
            EmailOrganizationDisposition.REVIEW_UNCERTAIN,
        )
        self.assertEqual(assessment.surface_decision, EmailSurfaceDecision.SURFACE)
        self.assertIn("conflicts", " ".join(assessment.review_reasons))

    def test_exact_and_ambiguous_deadlines_remain_distinct(self):
        exact = self.analyze(
            message("date-exact", body="Submit by 2026-08-04.")
        ).assessments[0].candidate.deadline
        missing_year = self.analyze(
            message("date-year", body="Submit by August 4.")
        ).assessments[0].candidate.deadline
        no_timezone = self.analyze(
            message("date-zone", body="Submit by August 4, 2026 at 3:00 PM.")
        ).assessments[0].candidate.deadline

        self.assertEqual(exact.state, EmailDeadlineState.GROUNDED)
        self.assertEqual(missing_year.state, EmailDeadlineState.AMBIGUOUS)
        self.assertIsNone(missing_year.value)
        self.assertEqual(no_timezone.state, EmailDeadlineState.AMBIGUOUS)
        self.assertIn("timezone", no_timezone.ambiguity_reason)

    def test_conflicting_fully_specified_dates_remain_ambiguous(self):
        deadline = self.analyze(
            message(
                "date-conflict",
                body="The deadline says 2026-08-04, but the form says due 2026-08-05.",
            )
        ).assessments[0].candidate.deadline

        self.assertEqual(deadline.state, EmailDeadlineState.AMBIGUOUS)
        self.assertIsNone(deadline.value)
        self.assertGreaterEqual(len(deadline.source_evidence), 2)

    def test_project_association_preserves_grounded_ambiguous_and_unresolved(self):
        grounded = self.analyze(
            message("assoc-1", subject="XO headset prototype review")
        ).assessments[0].project_association
        ambiguous = self.analyze(
            message("assoc-2", subject="XO and Nebulo joint review")
        ).assessments[0].project_association
        unresolved = self.analyze(
            message("assoc-3", subject="Synthetic unrelated update")
        ).assessments[0].project_association

        self.assertEqual(grounded.canonical_project_id, "project-xo")
        self.assertEqual(ambiguous.state, EmailProjectAssociationState.AMBIGUOUS)
        self.assertEqual(set(ambiguous.candidate_project_ids), {"project-xo", "project-nebulo"})
        self.assertEqual(unresolved.state, EmailProjectAssociationState.UNRESOLVED)
        self.assertIsNone(unresolved.canonical_project_id)

    def test_account_role_alone_never_invents_a_project(self):
        association = self.analyze(
            message("role-only", subject="Synthetic update")
        ).assessments[0].project_association

        self.assertEqual(association.state, EmailProjectAssociationState.UNRESOLVED)

    def test_repeated_messages_in_thread_deduplicate_and_preserve_latest(self):
        result = self.analyze(
            message("thread-old", thread_id="thread-synthetic", minute=1),
            message(
                "thread-new",
                thread_id="thread-synthetic",
                subject="Please review the synthetic form",
                minute=2,
            ),
        )

        self.assertEqual(result.analyzed_message_count, 2)
        self.assertEqual(result.unique_thread_count, 1)
        self.assertEqual(result.deduplication_count, 1)
        self.assertEqual(
            result.assessments[0].representative_message.provider_message_id,
            "thread-new",
        )
        self.assertEqual(result.assessments[0].source_message_count, 2)

    def test_missing_thread_id_falls_back_to_provider_message_identity(self):
        result = self.analyze(
            message("fallback-1", thread_id=None),
            message("fallback-2", thread_id=None),
        )

        self.assertEqual(result.unique_thread_count, 2)
        self.assertEqual(result.deduplication_count, 0)

    def test_waiting_requires_latest_sent_record_and_grounded_waiting_language(self):
        grounded = self.analyze(
            message("wait-in", thread_id="wait-thread", minute=1),
            message(
                "wait-out",
                thread_id="wait-thread",
                body="Following up; please let me know when you have a chance.",
                labels=("SENT",),
                minute=2,
            ),
        ).assessments[0]
        not_grounded = self.analyze(
            message(
                "wait-single",
                thread_id="wait-single-thread",
                body="Following up; please let me know.",
                labels=("SENT",),
            )
        ).assessments[0]

        self.assertEqual(
            grounded.organization_disposition,
            EmailOrganizationDisposition.WAITING,
        )
        self.assertIn(EmailSignalCategory.GROUNDED_WAITING, grounded.evidence_categories)
        self.assertNotIn(
            EmailAttentionKind.EXPLICIT_ACTION_REQUEST,
            grounded.attention_kinds,
        )
        self.assertNotEqual(
            not_grounded.organization_disposition,
            EmailOrganizationDisposition.WAITING,
        )
        self.assertEqual(not_grounded.surface_decision, EmailSurfaceDecision.QUIET)

    def test_connected_empty_and_provider_failures_remain_distinct(self):
        empty = self.analyze()
        self.assertEqual(empty.state, EmailAnalysisState.CONNECTED_EMPTY)
        cases = (
            (GmailProviderState.NOT_CONFIGURED, EmailAnalysisState.NOT_CONFIGURED),
            (GmailProviderState.AUTHENTICATION_FAILURE, EmailAnalysisState.AUTHENTICATION_FAILURE),
            (GmailProviderState.PROVIDER_FAILURE, EmailAnalysisState.PROVIDER_FAILURE),
            (GmailProviderState.MALFORMED_RESPONSE, EmailAnalysisState.MALFORMED_RESPONSE),
        )
        for provider_state, expected in cases:
            with self.subTest(provider_state=provider_state):
                diagnostic = GmailProviderDiagnostic(
                    code=provider_state.value,
                    message="Synthetic provider diagnostic without message content.",
                )
                result = self.service.analyze_page(
                    page(state=provider_state, diagnostic=diagnostic),
                    registry=REGISTRY,
                )
                self.assertEqual(result.state, expected)
                self.assertEqual(result.provider_diagnostic, diagnostic)
                self.assertEqual(result.analyzed_message_count, 0)

    def test_partial_parse_input_is_degraded_without_dropping_assessments(self):
        result = self.analyze(
            message(
                "degraded-1",
                body="Please review this synthetic request.",
                diagnostics=("invalid_base64_body",),
            )
        )

        self.assertEqual(result.state, EmailAnalysisState.DEGRADED_PARTIAL)
        self.assertEqual(result.analyzed_message_count, 1)
        self.assertEqual(result.unique_thread_count, 1)
        self.assertEqual(
            result.assessments[0].organization_disposition,
            EmailOrganizationDisposition.REVIEW_UNCERTAIN,
        )

    def test_candidate_ids_are_deterministic_opaque_and_thread_based(self):
        first = self.analyze(
            message("opaque-a", thread_id="opaque-thread", body="Please respond.")
        ).attention_candidates[0].candidate_id
        second = self.analyze(
            message("opaque-b", thread_id="opaque-thread", body="Please respond.")
        ).attention_candidates[0].candidate_id

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("email-candidate-"))
        self.assertNotIn("opaque-thread", first)
        self.assertNotIn("opaque-a", first)

    def test_injected_interpretation_remains_distinct_from_deterministic_evidence(self):
        interpreter = SyntheticInterpreter()
        service = EmailAnalysisService(
            registry_service=FakeRegistryService(),
            interpretation_provider=interpreter,
            clock=lambda: BASE_TIME,
        )
        result = service.analyze_page(
            page(message("model-seam", body="Please review the synthetic form.")),
            registry=REGISTRY,
        )
        candidate = result.attention_candidates[0]

        self.assertEqual(result.interpretation_calls, 1)
        self.assertEqual(len(interpreter.calls), 1)
        self.assertIsNotNone(candidate.model_interpretation)
        self.assertTrue(candidate.deterministic_evidence)
        self.assertNotIsInstance(
            candidate.deterministic_evidence[0],
            EmailModelInterpretation,
        )

    def test_production_default_performs_no_model_call(self):
        result = self.analyze(
            message("no-model", body="Please complete the synthetic form.")
        )

        self.assertEqual(result.interpretation_calls, 0)
        self.assertIsNone(result.attention_candidates[0].model_interpretation)

    def test_bounded_provider_call_uses_no_query_or_label_scan(self):
        client = FakeGmailClient(page(message("bounded-1")))
        result = self.service.analyze_recent(client)

        self.assertEqual(client.calls, [("list_recent_messages", DEFAULT_ANALYSIS_MAX_MESSAGES)])
        self.assertEqual(result.analyzed_message_count, 1)
        with self.assertRaisesRegex(ValueError, "between 1"):
            self.service.analyze_recent(client, max_messages=0)
        with self.assertRaisesRegex(ValueError, "between 1"):
            self.service.analyze_recent(client, max_messages=MAX_ANALYSIS_MESSAGES + 1)

    def test_no_task_calendar_memory_storage_or_mailbox_mutation_is_emitted(self):
        client = FakeGmailClient(
            page(message("side-effect-1", body="Please submit the synthetic form."))
        )
        result = self.service.analyze_recent(client, max_messages=3)
        candidate = result.attention_candidates[0]

        self.assertEqual(client.calls, [("list_recent_messages", 3)])
        self.assertEqual(candidate.action_proposals, ())
        self.assertEqual(result.provider_mutation_calls, 0)
        self.assertNotIn("approval_payload", candidate.model_dump())
        self.assertNotIn("memory", candidate.model_dump())

    def test_explanations_and_diagnostics_are_safe_categories_not_content(self):
        secret_marker = "SYNTHETIC_PRIVATE_CONTENT_MARKER"
        result = self.analyze(
            message(
                "safe-1",
                subject=secret_marker,
                body="Please complete the synthetic form.",
            )
        )
        assessment = result.assessments[0]

        self.assertNotIn(secret_marker, assessment.explanation)
        self.assertNotIn(secret_marker, str(result.provider_diagnostic))
        self.assertNotIn(secret_marker, str(assessment.candidate.provider_metadata))

    def test_inconsistent_accounts_fail_closed_without_content_diagnostic(self):
        result = self.analyze(
            message("account-1"),
            message("account-2", account=OTHER_ACCOUNT),
        )

        self.assertEqual(result.state, EmailAnalysisState.MALFORMED_RESPONSE)
        self.assertEqual(result.analyzed_message_count, 0)
        self.assertEqual(result.provider_diagnostic.code, "malformed_response")
        self.assertNotIn("account-1", result.provider_diagnostic.message)

    def test_dimensions_and_provider_completeness_remain_separate(self):
        result = self.analyze(
            message("separate-1", body="Please reply with your availability."),
            complete=False,
            truncated=True,
        )
        assessment = result.assessments[0]

        self.assertEqual(assessment.importance, EmailImportance.HIGH)
        self.assertEqual(assessment.urgency, EmailUrgency.MEDIUM)
        self.assertIn(EmailAttentionKind.SCHEDULING_REQUEST, assessment.attention_kinds)
        self.assertEqual(
            assessment.organization_disposition,
            EmailOrganizationDisposition.NEEDS_ACTION,
        )
        self.assertEqual(assessment.surface_decision, EmailSurfaceDecision.SURFACE)
        self.assertFalse(result.complete)
        self.assertTrue(result.truncated)

    def test_production_and_live_verifier_sources_preserve_privacy_boundaries(self):
        backend_dir = Path(__file__).resolve().parents[1]
        analysis_source = (backend_dir / "app" / "email_analysis.py").read_text()
        verifier_source = (
            backend_dir / "scripts" / "verify_personal_email_analysis.py"
        ).read_text()

        self.assertNotIn("import openai", analysis_source.casefold())
        self.assertNotIn("from openai", analysis_source.casefold())
        for mutation in (
            ".modify(",
            ".trash(",
            ".delete(",
            ".send(",
            ".insert(",
            ".batchModify(",
        ):
            self.assertNotIn(mutation, analysis_source)
        self.assertIn("max_messages=DEFAULT_ANALYSIS_MAX_MESSAGES", verifier_source)
        self.assertNotIn("find_label(", verifier_source)
        self.assertNotIn("list_labels(", verifier_source)
        self.assertNotIn("get_thread(", verifier_source)
        for content_field in (
            "assessment.explanation",
            "representative_message",
            "provider_message_id",
            "provider_thread_id",
            ".subject",
            ".body_text",
            ".sender",
        ):
            self.assertNotIn(content_field, verifier_source)


if __name__ == "__main__":
    unittest.main()
