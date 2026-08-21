from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.email_analysis import EmailAnalysisService, EmailAnalysisState  # noqa: E402
from app.email_domain import EmailAccountRole  # noqa: E402
from app.gmail_client import (  # noqa: E402
    GMAIL_READONLY_SCOPE,
    GmailClient,
    GmailMessagePage,
    GmailMessageRecord,
    GmailProviderState,
    tamu_email_health_payload,
)
from scripts.tamu_email_oauth_setup import _is_tamu_address  # noqa: E402


def settings(**overrides) -> Settings:
    values = dict(
        todoist_api_token=None,
        google_client_id="calendar-client",
        google_client_secret="calendar-secret",
        google_refresh_token="calendar-refresh",
        google_calendar_id="primary",
        timezone="America/Chicago",
        openai_api_key=None,
        openai_model="test",
        agent_api_key="agent-key",
        personal_email_google_client_id="personal-client",
        personal_email_google_client_secret="personal-secret",
        personal_email_google_refresh_token="personal-refresh",
        personal_email_expected_address="personal@example.com",
        tamu_email_google_client_id="tamu-client",
        tamu_email_google_client_secret="tamu-secret",
        tamu_email_google_refresh_token="tamu-refresh",
        tamu_email_expected_address="student@tamu.edu",
    )
    values.update(overrides)
    return Settings(**values)


class FakeCredentials:
    granted_scopes = (GMAIL_READONLY_SCOPE,)

    def refresh(self, request):
        self.request = request


class CredentialFactory:
    def __init__(self):
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return FakeCredentials()


class Request:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class Users:
    def __init__(self, profile):
        self.profile = profile

    def getProfile(self, **kwargs):  # noqa: N802
        return Request(self.profile)


class Service:
    def __init__(self, profile):
        self.profile = profile

    def users(self):
        return Users(self.profile)


class TamuGmailProviderTests(unittest.TestCase):
    def test_tamu_identity_guard_accepts_only_tamu_domain_tree(self):
        self.assertTrue(_is_tamu_address("student@tamu.edu"))
        self.assertTrue(_is_tamu_address("student@email.tamu.edu"))
        self.assertFalse(_is_tamu_address("student@not-tamu.edu"))
        self.assertFalse(_is_tamu_address("student@tamu.edu.example.com"))

    def test_tamu_profile_uses_only_distinct_readonly_credentials_and_am_role(self):
        credential_factory = CredentialFactory()
        client = GmailClient.for_tamu(
            settings(),
            credentials_factory=credential_factory,
            request_factory=lambda: object(),
            service_factory=lambda *args, **kwargs: Service(
                {
                    "emailAddress": "student@tamu.edu",
                    "messagesTotal": 2,
                    "threadsTotal": 1,
                }
            ),
        )

        first = client.check_health()
        second = client.check_health()

        self.assertEqual(first, second)
        self.assertEqual(first.state, GmailProviderState.CONNECTED)
        self.assertEqual(first.account.account_role, EmailAccountRole.AM)
        self.assertEqual(credential_factory.kwargs["client_id"], "tamu-client")
        self.assertEqual(credential_factory.kwargs["client_secret"], "tamu-secret")
        self.assertEqual(credential_factory.kwargs["refresh_token"], "tamu-refresh")
        self.assertEqual(credential_factory.kwargs["scopes"], [GMAIL_READONLY_SCOPE])

    def test_missing_tamu_config_never_falls_back_to_other_google_credentials(self):
        client = GmailClient.for_tamu(
            settings(
                tamu_email_google_client_id=None,
                tamu_email_google_client_secret=None,
                tamu_email_google_refresh_token=None,
                tamu_email_expected_address=None,
            )
        )

        result = client.check_health()

        self.assertEqual(result.state, GmailProviderState.NOT_CONFIGURED)
        self.assertEqual(result.diagnostic.code, "not_configured")

        missing_guard = GmailClient.for_tamu(
            settings(tamu_email_expected_address=None)
        ).check_health()
        self.assertEqual(missing_guard.state, GmailProviderState.NOT_CONFIGURED)

    def test_tamu_analysis_preserves_role_and_existing_attention_logic(self):
        from app.email_domain import EmailMessageIdentity, EmailProviderAccountIdentity

        account = EmailProviderAccountIdentity(
            provider="gmail",
            account_role=EmailAccountRole.AM,
            provider_account_id="opaque-account",
        )
        record = GmailMessageRecord(
            identity=EmailMessageIdentity(
                account=account,
                provider_message_id="message-1",
                provider_thread_id="thread-1",
            ),
            sender="registrar",
            recipients=("student",),
            subject="Registration action required by August 25, 2026",
            internal_date=datetime(2026, 8, 20, tzinfo=timezone.utc),
            unread=True,
            body_text="Please submit the required form by August 25, 2026.",
            body_accessed=True,
        )
        page = GmailMessagePage(
            state=GmailProviderState.CONNECTED,
            messages=(record,),
            complete=True,
            truncated=False,
            pages_fetched=1,
        )
        client = Mock(account_role=EmailAccountRole.AM)
        client.list_recent_messages.return_value = page

        result = EmailAnalysisService().analyze_recent(client)

        self.assertEqual(result.account_role, EmailAccountRole.AM)
        self.assertEqual(result.state, EmailAnalysisState.CONNECTED_ATTENTION)
        self.assertEqual(result.provider_mutation_calls, 0)
        self.assertTrue(result.attention_candidates)

    def test_health_is_separate_and_privacy_safe(self):
        fake = Mock()
        fake.check_health.return_value = Mock(
            state=GmailProviderState.NOT_CONFIGURED,
            account=None,
            message_total=None,
            thread_total=None,
            diagnostic=None,
        )
        with patch("app.gmail_client.GmailClient.for_tamu", return_value=fake):
            payload = tamu_email_health_payload(settings())

        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["details"]["account_role"], "am")
        rendered = str(payload)
        self.assertNotIn("student@tamu.edu", rendered)
        self.assertNotIn("tamu-refresh", rendered)

    def test_provider_exposes_no_mailbox_mutations(self):
        forbidden = {
            "delete",
            "trash",
            "untrash",
            "modify",
            "send",
            "insert",
            "batch_delete",
            "batch_modify",
        }
        self.assertTrue(forbidden.isdisjoint(vars(GmailClient)))


if __name__ == "__main__":
    unittest.main()
