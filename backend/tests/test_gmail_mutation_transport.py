from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.gmail_mutation_transport import GmailOrganizationGoogleTransport  # noqa: E402
from app.gmail_scopes import GMAIL_MODIFY_SCOPE  # noqa: E402


def settings() -> Settings:
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
        personal_email_google_client_id="gmail-client-sentinel",
        personal_email_google_client_secret="gmail-secret-sentinel",
        personal_email_google_refresh_token="gmail-refresh-sentinel",
        personal_email_expected_address="personal-marker",
    )


class FakeCredentials:
    granted_scopes = (GMAIL_MODIFY_SCOPE,)

    def refresh(self, request):
        self.request = request


class CredentialFactory:
    def __init__(self):
        self.kwargs = None
        self.credentials = FakeCredentials()

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self.credentials


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeMessages:
    def __init__(self, service):
        self.service = service

    def get(self, **kwargs):
        self.service.calls.append(("messages.get", kwargs))
        message_id = kwargs["id"]
        return FakeRequest(
            {
                "id": message_id,
                "threadId": f"thread-{message_id}",
                "labelIds": ["UNREAD", "INBOX"],
            }
        )

    def batchModify(self, **kwargs):  # noqa: N802 - mirrors Google API.
        self.service.calls.append(("messages.batchModify", kwargs))
        return FakeRequest({})


class FakeUsers:
    def __init__(self, service):
        self.service = service

    def getProfile(self, **kwargs):  # noqa: N802 - mirrors Google API.
        self.service.calls.append(("users.getProfile", kwargs))
        return FakeRequest({"emailAddress": "personal-marker"})

    def messages(self):
        return FakeMessages(self.service)


class FakeService:
    def __init__(self):
        self.calls = []

    def users(self):
        return FakeUsers(self)


class GmailMutationTransportTests(unittest.TestCase):
    def test_exact_state_and_label_delta_use_only_modify_scope(self):
        credentials = CredentialFactory()
        service = FakeService()
        transport = GmailOrganizationGoogleTransport(
            settings(),
            credentials_factory=credentials,
            request_factory=lambda: "request",
            service_factory=lambda *args, **kwargs: service,
        )

        states = transport.get_message_states(("message-1", "message-2"))
        result = transport.modify_message_labels(
            ("message-1", "message-2"),
            add_label_ids=("Label_existing",),
        )

        self.assertEqual(credentials.kwargs["scopes"], [GMAIL_MODIFY_SCOPE])
        self.assertEqual(len(states), 2)
        self.assertTrue(states[0].unread)
        self.assertEqual(result.successful_message_ids, ("message-1", "message-2"))
        mutation = next(value for name, value in service.calls if name == "messages.batchModify")
        self.assertEqual(
            mutation["body"],
            {
                "ids": ["message-1", "message-2"],
                "addLabelIds": ["Label_existing"],
                "removeLabelIds": [],
            },
        )
        self.assertFalse(hasattr(transport, "send"))
        self.assertFalse(hasattr(transport, "delete"))
        self.assertFalse(hasattr(transport, "trash"))
        self.assertFalse(hasattr(transport, "archive"))

    def test_live_transport_cannot_create_labels(self):
        transport = GmailOrganizationGoogleTransport(settings())
        with self.assertRaisesRegex(ValueError, "existing labels only"):
            transport.create_label("PCOS/New")


if __name__ == "__main__":
    unittest.main()
