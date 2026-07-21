import base64
from datetime import datetime, timezone
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.email_domain import EmailAccountRole  # noqa: E402
from app.gmail_client import (  # noqa: E402
    DEFAULT_GMAIL_QUERY,
    GMAIL_READONLY_SCOPE,
    MAX_ANALYZABLE_BODY_CHARS,
    MAX_GMAIL_LIST_PAGES,
    PERSONAL_GMAIL_SCOPES,
    GmailClient,
    GmailHealthResult,
    GmailProviderDiagnostic,
    GmailProviderState,
    personal_email_health_payload,
)
from scripts.personal_email_oauth_setup import (  # noqa: E402
    REFRESH_TOKEN_ENV_KEY,
    _write_env_value,
)


def settings(
    *,
    refresh_value="personal-refresh-sentinel",
    expected_address="account-marker",
    client_id="email-client-sentinel",
    client_secret="email-secret-sentinel",
):
    return Settings(
        todoist_api_token=None,
        google_client_id="calendar-client-sentinel",
        google_client_secret="calendar-secret-sentinel",
        google_refresh_token="calendar-refresh-sentinel",
        google_calendar_id="primary",
        timezone="America/Chicago",
        openai_api_key=None,
        openai_model="test",
        agent_api_key="test-agent-key",
        personal_email_google_client_id=client_id,
        personal_email_google_client_secret=client_secret,
        personal_email_google_refresh_token=refresh_value,
        personal_email_expected_address=expected_address,
    )


class FakeCredentials:
    def __init__(self, *, refresh_error=None, granted_scopes=PERSONAL_GMAIL_SCOPES):
        self.refresh_error = refresh_error
        self.granted_scopes = granted_scopes
        self.scopes = list(PERSONAL_GMAIL_SCOPES)

    def refresh(self, request):
        if self.refresh_error:
            raise self.refresh_error


class CredentialFactory:
    def __init__(self, credentials=None):
        self.credentials = credentials or FakeCredentials()
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self.credentials


class FakeRequest:
    def __init__(self, value):
        self.value = value

    def execute(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class FakeMessages:
    def __init__(self, service):
        self.service = service

    def list(self, **kwargs):
        self.service.calls.append(("messages.list", kwargs))
        if not self.service.list_pages:
            return FakeRequest({"messages": [], "resultSizeEstimate": 0})
        return FakeRequest(self.service.list_pages.pop(0))

    def get(self, **kwargs):
        self.service.calls.append(("messages.get", kwargs))
        return FakeRequest(self.service.message_details.get(kwargs["id"], ValueError("missing")))


class FakeThreads:
    def __init__(self, service):
        self.service = service

    def get(self, **kwargs):
        self.service.calls.append(("threads.get", kwargs))
        return FakeRequest(self.service.thread_details.get(kwargs["id"], ValueError("missing")))


class FakeLabels:
    def __init__(self, service):
        self.service = service

    def list(self, **kwargs):
        self.service.calls.append(("labels.list", kwargs))
        return FakeRequest(self.service.labels_payload)


class FakeUsers:
    def __init__(self, service):
        self.service = service

    def getProfile(self, **kwargs):  # noqa: N802 - mirrors Google client.
        self.service.calls.append(("users.getProfile", kwargs))
        return FakeRequest(self.service.profile)

    def messages(self):
        return FakeMessages(self.service)

    def threads(self):
        return FakeThreads(self.service)

    def labels(self):
        return FakeLabels(self.service)


class FakeService:
    def __init__(
        self,
        *,
        profile=None,
        list_pages=None,
        message_details=None,
        thread_details=None,
        labels_payload=None,
    ):
        self.profile = profile or {
            "emailAddress": "account-marker",
            "messagesTotal": 42,
            "threadsTotal": 21,
        }
        self.list_pages = list(list_pages or [])
        self.message_details = dict(message_details or {})
        self.thread_details = dict(thread_details or {})
        self.labels_payload = labels_payload or {"labels": []}
        self.calls = []

    def users(self):
        return FakeUsers(self)


class ServiceFactory:
    def __init__(self, service):
        self.service = service
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.service


def encoded(value):
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def message(
    message_id="message-1",
    thread_id="thread-1",
    *,
    payload=None,
    labels=None,
    snippet="Bounded synthetic snippet",
):
    return {
        "id": message_id,
        "threadId": thread_id,
        "historyId": "history-1",
        "internalDate": "1784304000000",
        "labelIds": labels if labels is not None else ["INBOX", "UNREAD"],
        "snippet": snippet,
        "sizeEstimate": 512,
        "payload": payload or plain_payload("Synthetic message body"),
    }


def headers():
    return [
        {"name": "From", "value": "Sender Person"},
        {"name": "To", "value": "Account Owner"},
        {"name": "Cc", "value": "Project Collaborator"},
        {"name": "Subject", "value": "Synthetic project update"},
        {"name": "Date", "value": "Fri, 17 Jul 2026 16:00:00 +0000"},
    ]


def plain_payload(value):
    return {
        "mimeType": "text/plain",
        "headers": headers(),
        "body": {"size": len(value), "data": encoded(value)},
    }


def multipart_payload():
    return {
        "mimeType": "multipart/mixed",
        "headers": headers(),
        "body": {"size": 0},
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "filename": "",
                "body": {"size": 0},
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "filename": "",
                        "headers": [
                            {"name": "Content-Type", "value": "text/plain; charset=utf-8"}
                        ],
                        "body": {"size": 24, "data": encoded("Preferred plain body")},
                    },
                    {
                        "mimeType": "text/html",
                        "filename": "",
                        "body": {
                            "size": 64,
                            "data": encoded("<p>HTML fallback</p><script>hidden</script>"),
                        },
                    },
                ],
            },
            {
                "mimeType": "application/octet-stream",
                "filename": "synthetic.bin",
                "body": {
                    "size": 123,
                    "attachmentId": "attachment-opaque-1",
                },
            },
        ],
    }


def client(service, *, app_settings=None, credentials=None):
    credential_factory = CredentialFactory(credentials)
    service_factory = ServiceFactory(service)
    instance = GmailClient(
        app_settings or settings(),
        credentials_factory=credential_factory,
        request_factory=lambda: object(),
        service_factory=service_factory,
    )
    return instance, credential_factory, service_factory


def http_error(status):
    response = Mock(status=status, reason="provider failure")
    return HttpError(response, b"{}", uri="redacted")


class GmailProviderTests(unittest.TestCase):
    def test_exact_readonly_scope_and_no_mutation_methods(self):
        service = FakeService()
        gmail, credential_factory, service_factory = client(service)

        health = gmail.check_health()

        self.assertEqual(health.state, GmailProviderState.CONNECTED)
        self.assertEqual(PERSONAL_GMAIL_SCOPES, (GMAIL_READONLY_SCOPE,))
        self.assertEqual(
            credential_factory.kwargs["scopes"],
            ["https://www.googleapis.com/auth/gmail.readonly"],
        )
        self.assertEqual(service_factory.calls[0][0], ("gmail", "v1"))
        mutation_names = {
            "delete",
            "trash",
            "untrash",
            "modify",
            "send",
            "insert",
            "batch_delete",
            "batch_modify",
        }
        self.assertTrue(mutation_names.isdisjoint(vars(GmailClient)))

    def test_calendar_and_personal_email_credentials_remain_separate(self):
        value = settings()

        self.assertEqual(value.google_refresh_token, "calendar-refresh-sentinel")
        self.assertEqual(
            value.personal_email_google_refresh_token,
            "personal-refresh-sentinel",
        )
        self.assertNotEqual(
            value.google_refresh_token,
            value.personal_email_google_refresh_token,
        )
        self.assertEqual(value.missing_google_calendar_fields, [])
        self.assertEqual(value.missing_personal_email_fields, [])

    def test_missing_config_and_refresh_failure_are_structured(self):
        missing, _, _ = client(
            FakeService(),
            app_settings=settings(
                refresh_value=None,
                client_id=None,
                client_secret=None,
                expected_address=None,
            ),
        )
        result = missing.check_health()
        self.assertEqual(result.state, GmailProviderState.NOT_CONFIGURED)
        self.assertEqual(result.diagnostic.code, "not_configured")

        failed, _, _ = client(
            FakeService(),
            credentials=FakeCredentials(refresh_error=RefreshError("rejected")),
        )
        result = failed.check_health()
        self.assertEqual(result.state, GmailProviderState.AUTHENTICATION_FAILURE)
        self.assertEqual(result.diagnostic.code, "authentication")
        self.assertNotIn("personal-refresh-sentinel", str(result))

    def test_unexpected_scope_is_rejected(self):
        gmail, _, _ = client(
            FakeService(),
            credentials=FakeCredentials(
                granted_scopes=("https://www.googleapis.com/auth/gmail.modify",)
            ),
        )

        result = gmail.check_health()

        self.assertEqual(result.state, GmailProviderState.AUTHENTICATION_FAILURE)
        self.assertEqual(result.diagnostic.code, "scope")

    def test_provider_http_failure_and_malformed_profile_fail_closed(self):
        failed, _, _ = client(FakeService(profile=http_error(503)))
        result = failed.check_health()
        self.assertEqual(result.state, GmailProviderState.PROVIDER_FAILURE)
        self.assertEqual(result.diagnostic.http_status, 503)

        malformed, _, _ = client(FakeService(profile={"messagesTotal": 1}))
        result = malformed.check_health()
        self.assertEqual(result.state, GmailProviderState.MALFORMED_RESPONSE)
        self.assertEqual(result.diagnostic.code, "malformed_response")

    def test_wrong_account_detection_leaks_neither_account_marker(self):
        gmail, _, _ = client(
            FakeService(
                profile={
                    "emailAddress": "other-account-marker",
                    "messagesTotal": 1,
                    "threadsTotal": 1,
                }
            ),
            app_settings=settings(expected_address="expected-account-marker"),
        )

        result = gmail.check_health()

        self.assertEqual(result.state, GmailProviderState.AUTHENTICATION_FAILURE)
        self.assertEqual(result.diagnostic.code, "wrong_account")
        self.assertNotIn("other-account-marker", str(result))
        self.assertNotIn("expected-account-marker", str(result))

    def test_connected_empty_is_distinct_and_default_excludes_spam_and_trash(self):
        service = FakeService(list_pages=[{"messages": [], "resultSizeEstimate": 0}])
        gmail, _, _ = client(service)

        result = gmail.list_recent_messages(max_messages=5)

        self.assertEqual(result.state, GmailProviderState.CONNECTED_EMPTY)
        self.assertTrue(result.complete)
        self.assertFalse(result.truncated)
        list_call = next(value for name, value in service.calls if name == "messages.list")
        self.assertEqual(list_call["q"], DEFAULT_GMAIL_QUERY)
        self.assertFalse(list_call["includeSpamTrash"])
        self.assertFalse(any(name == "messages.get" for name, _ in service.calls))

    def test_message_normalization_preserves_identity_headers_time_labels_body_and_attachments(self):
        raw = message(payload=multipart_payload())
        service = FakeService(
            list_pages=[{
                "messages": [{"id": "message-1", "threadId": "thread-1"}],
                "resultSizeEstimate": 1,
            }],
            message_details={"message-1": raw},
        )
        gmail, _, _ = client(service)

        result = gmail.list_recent_messages(max_messages=1)
        record = result.messages[0]

        self.assertEqual(result.state, GmailProviderState.CONNECTED)
        self.assertEqual(record.identity.account.account_role, EmailAccountRole.PERSONAL)
        self.assertEqual(record.identity.account.provider, "gmail")
        self.assertTrue(record.identity.account.provider_account_id.startswith("personal-"))
        self.assertEqual(record.identity.provider_message_id, "message-1")
        self.assertEqual(record.identity.provider_thread_id, "thread-1")
        self.assertEqual(record.sender, "Sender Person")
        self.assertEqual(record.recipients, ("Account Owner", "Project Collaborator"))
        self.assertEqual(record.subject, "Synthetic project update")
        self.assertEqual(record.message_date, datetime(2026, 7, 17, 16, 0, tzinfo=timezone.utc))
        self.assertIsNotNone(record.internal_date)
        self.assertEqual(record.label_ids, ("INBOX", "UNREAD"))
        self.assertTrue(record.unread)
        self.assertEqual(record.snippet, "Bounded synthetic snippet")
        self.assertEqual(record.body_text, "Preferred plain body")
        self.assertFalse(record.body_truncated)
        self.assertEqual(len(record.attachments), 1)
        self.assertEqual(record.attachments[0].filename, "synthetic.bin")
        self.assertEqual(record.attachments[0].provider_attachment_id, "attachment-opaque-1")
        self.assertFalse(any(name.startswith("attachments.") for name, _ in service.calls))

    def test_html_fallback_body_bound_and_malformed_data_diagnostics(self):
        html = {
            "mimeType": "text/html",
            "headers": headers(),
            "body": {"size": 30, "data": encoded("<p>Readable <b>HTML</b></p><style>hidden</style>")},
        }
        malformed = {
            "mimeType": "text/plain",
            "headers": headers(),
            "body": {"size": 5, "data": "%%%"},
        }
        oversized = "x" * (MAX_ANALYZABLE_BODY_CHARS + 20)
        details = {
            "html": message("html", "thread-html", payload=html),
            "bad": message("bad", "thread-bad", payload=malformed),
            "large": message("large", "thread-large", payload=plain_payload(oversized)),
        }
        service = FakeService(
            list_pages=[{
                "messages": [
                    {"id": "html", "threadId": "thread-html"},
                    {"id": "bad", "threadId": "thread-bad"},
                    {"id": "large", "threadId": "thread-large"},
                ]
            }],
            message_details=details,
        )
        gmail, _, _ = client(service)

        result = gmail.list_recent_messages(max_messages=3)
        by_id = {item.identity.provider_message_id: item for item in result.messages}

        self.assertEqual(by_id["html"].body_text, "Readable HTML")
        self.assertIsNone(by_id["bad"].body_text)
        self.assertIn("invalid_base64_body", by_id["bad"].parse_diagnostics)
        self.assertEqual(len(by_id["large"].body_text), MAX_ANALYZABLE_BODY_CHARS)
        self.assertTrue(by_id["large"].body_truncated)

    def test_pagination_bounds_continuation_query_and_label_filters(self):
        details = {
            item_id: message(item_id, f"thread-{item_id}")
            for item_id in ("one", "two", "three")
        }
        service = FakeService(
            list_pages=[
                {
                    "messages": [
                        {"id": "one", "threadId": "thread-one"},
                        {"id": "two", "threadId": "thread-two"},
                    ],
                    "nextPageToken": "page-two",
                    "resultSizeEstimate": 50,
                },
                {
                    "messages": [{"id": "three", "threadId": "thread-three"}],
                    "nextPageToken": "page-three",
                    "resultSizeEstimate": 50,
                },
            ],
            message_details=details,
        )
        gmail, _, _ = client(service)

        result = gmail.list_recent_messages(
            max_messages=3,
            query="is:unread",
            label_ids=("label-1",),
        )

        self.assertEqual([item.identity.provider_message_id for item in result.messages], ["one", "two", "three"])
        self.assertEqual(result.pages_fetched, 2)
        self.assertFalse(result.complete)
        self.assertTrue(result.truncated)
        self.assertEqual(result.next_page_token, "page-three")
        self.assertEqual(result.result_size_estimate, 50)
        list_calls = [value for name, value in service.calls if name == "messages.list"]
        self.assertEqual(list_calls[0]["q"], "(is:unread) -in:spam -in:trash")
        self.assertEqual(list_calls[0]["labelIds"], ["label-1"])
        self.assertFalse(list_calls[0]["includeSpamTrash"])
        self.assertEqual(list_calls[1]["pageToken"], "page-two")
        self.assertEqual(list_calls[1]["maxResults"], 1)
        for invalid in (0, 101):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    gmail.list_recent_messages(max_messages=invalid)

        bounded_service = FakeService(
            list_pages=[
                {"messages": [], "nextPageToken": f"empty-page-{index}"}
                for index in range(1, MAX_GMAIL_LIST_PAGES + 1)
            ]
        )
        bounded, _, _ = client(bounded_service)
        bounded_result = bounded.list_recent_messages(max_messages=1)
        self.assertEqual(bounded_result.pages_fetched, MAX_GMAIL_LIST_PAGES)
        self.assertFalse(bounded_result.complete)
        self.assertTrue(bounded_result.truncated)

    def test_bounded_metadata_read_uses_headers_only_and_scrubs_body_fields(self):
        service = FakeService(
            list_pages=[{
                "messages": [{"id": "review-1", "threadId": "thread-review-1"}],
                "nextPageToken": "not-exposed-for-continuation",
                "resultSizeEstimate": 500,
            }],
            message_details={
                "review-1": message(
                    "review-1",
                    "thread-review-1",
                    snippet="Sensitive snippet must not cross the boundary",
                )
            },
        )
        gmail, _, _ = client(service)

        result = gmail.list_message_metadata(
            max_messages=1,
            query="-has:attachment",
            label_ids=("INBOX",),
        )

        self.assertEqual(result.state, GmailProviderState.CONNECTED)
        self.assertEqual(len(result.messages), 1)
        self.assertFalse(result.complete)
        self.assertTrue(result.truncated)
        record = result.messages[0]
        self.assertFalse(record.body_accessed)
        self.assertIsNone(record.body_text)
        self.assertIsNone(record.snippet)
        self.assertIsNone(record.has_attachment)
        self.assertEqual(record.attachments, ())
        list_call = next(value for name, value in service.calls if name == "messages.list")
        self.assertEqual(
            list_call["q"],
            "(-has:attachment) -in:spam -in:trash",
        )
        self.assertEqual(list_call["labelIds"], ["INBOX"])
        get_call = next(value for name, value in service.calls if name == "messages.get")
        self.assertEqual(get_call["format"], "metadata")
        self.assertEqual(get_call["metadataHeaders"], ["From", "Subject", "Date"])
        with self.assertRaises(ValueError):
            gmail.list_message_metadata(max_messages=51)

    def test_exact_thread_retrieval_and_identity_validation(self):
        first = message("first", "thread-1")
        second = message("second", "thread-1", labels=["INBOX"])
        service = FakeService(
            thread_details={
                "thread-1": {"id": "thread-1", "messages": [first, second]},
                "bad-thread": {
                    "id": "bad-thread",
                    "messages": [message("bad", "different-thread")],
                },
            }
        )
        gmail, _, _ = client(service)

        result = gmail.get_thread("thread-1")

        self.assertEqual(result.state, GmailProviderState.CONNECTED)
        self.assertEqual(len(result.messages), 2)
        self.assertTrue(all(item.identity.provider_thread_id == "thread-1" for item in result.messages))
        call = next(value for name, value in service.calls if name == "threads.get")
        self.assertEqual(call, {"userId": "me", "id": "thread-1", "format": "full"})
        malformed = gmail.get_thread("bad-thread")
        self.assertEqual(malformed.state, GmailProviderState.MALFORMED_RESPONSE)

    def test_label_discovery_and_lookup(self):
        service = FakeService(
            labels_payload={
                "labels": [
                    {"id": "INBOX", "name": "INBOX", "type": "system"},
                    {
                        "id": "label-old",
                        "name": "Old Stuff",
                        "type": "user",
                        "messagesTotal": 2100,
                        "threadsTotal": 1900,
                    },
                ]
            }
        )
        gmail, _, _ = client(service)

        labels = gmail.list_labels()
        found = gmail.find_label("old stuff")

        self.assertEqual(labels.state, GmailProviderState.CONNECTED)
        self.assertEqual(len(labels.labels), 2)
        self.assertEqual(found.matched_label.provider_label_id, "label-old")
        self.assertEqual(found.matched_label.messages_total, 2100)
        self.assertFalse(any(name == "messages.list" for name, _ in service.calls))

    def test_health_payload_is_privacy_safe_across_states(self):
        cases = [
            GmailHealthResult(state=GmailProviderState.NOT_CONFIGURED),
            GmailHealthResult(
                state=GmailProviderState.AUTHENTICATION_FAILURE,
                diagnostic=GmailProviderDiagnostic(
                    code="wrong_account",
                    message="safe generic message",
                ),
            ),
            GmailHealthResult(
                state=GmailProviderState.PROVIDER_FAILURE,
                diagnostic=GmailProviderDiagnostic(
                    code="provider",
                    message="safe generic message",
                ),
            ),
        ]
        for result in cases:
            with self.subTest(state=result.state):
                fake_client = Mock()
                fake_client.check_health.return_value = result
                with patch("app.gmail_client.GmailClient", return_value=fake_client):
                    payload = personal_email_health_payload(settings())
                rendered = str(payload)
                self.assertNotIn("account-marker", rendered)
                self.assertNotIn("refresh-sentinel", rendered)
                self.assertNotIn("secret-sentinel", rendered)
                self.assertNotIn("safe generic message", rendered)
                self.assertIn("configured_scopes", payload["details"])

    def test_settings_health_includes_personal_email_without_provider_logic(self):
        from app import main

        safe = {"status": "warning", "message": "not configured", "details": {}}
        with patch("app.main.get_settings", return_value=settings()), patch(
            "app.main._todoist_health", return_value=safe
        ), patch("app.main._google_calendar_health", return_value=safe), patch(
            "app.main.personal_email_health_payload", return_value=safe
        ) as personal, patch("app.main._openai_health", return_value=safe), patch(
            "app.main._linear_health", return_value=safe
        ):
            payload = main.settings_health(authorization="Bearer test-agent-key")

        self.assertEqual(payload["checks"]["personal_email"], safe)
        personal.assert_called_once()

    def test_oauth_env_writer_preserves_calendar_token_and_uses_owner_only_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "GOOGLE_REFRESH_TOKEN=calendar-refresh-sentinel\n"
                f"{REFRESH_TOKEN_ENV_KEY}=old-personal-sentinel\n"
            )

            _write_env_value(
                path,
                REFRESH_TOKEN_ENV_KEY,
                "new-personal-sentinel",
            )

            content = path.read_text()
            self.assertIn("GOOGLE_REFRESH_TOKEN=calendar-refresh-sentinel", content)
            self.assertIn(
                f"{REFRESH_TOKEN_ENV_KEY}=new-personal-sentinel",
                content,
            )
            self.assertNotIn("old-personal-sentinel", content)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_provider_has_no_persistence_or_write_boundary(self):
        source = (Path(__file__).resolve().parents[1] / "app" / "gmail_client.py").read_text()
        oauth_source = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "personal_email_oauth_setup.py"
        ).read_text()
        for forbidden in (
            "from .storage",
            "import sqlite",
            "create_memory",
            ".modify(",
            ".delete(",
            ".trash(",
            ".send(",
            ".attachments().get(",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("print(credentials.refresh_token)", oauth_source)


if __name__ == "__main__":
    unittest.main()
