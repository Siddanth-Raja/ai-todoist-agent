"""Narrow live Gmail label transport used only after SID-150 confirmation."""

from __future__ import annotations

import hmac
from typing import Any

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import Settings
from .gmail_client import GMAIL_TOKEN_URI
from .gmail_organization import (
    GmailBatchMutationResult,
    GmailCreatedLabel,
    GmailObservedMessageState,
    GmailOrganizationGateError,
    MAX_GMAIL_MUTATION_BATCH_SIZE,
)
from .gmail_scopes import PERSONAL_GMAIL_MUTATION_SCOPES, PERSONAL_GMAIL_REAUTH_SCOPES


class GmailOrganizationGoogleTransport:
    """Exact state reads and label deltas; no send/delete/trash API exists."""

    def __init__(
        self,
        settings: Settings,
        *,
        credentials_factory=Credentials,
        request_factory=GoogleAuthRequest,
        service_factory=build,
    ) -> None:
        self._client_id = settings.personal_email_client_id
        self._client_secret = settings.personal_email_client_secret
        self._refresh_token = settings.personal_email_google_refresh_token
        self._expected_address = settings.personal_email_expected_address
        self._credentials_factory = credentials_factory
        self._request_factory = request_factory
        self._service_factory = service_factory

    def get_message_states(
        self, message_ids: tuple[str, ...]
    ) -> tuple[GmailObservedMessageState, ...]:
        _validate_message_ids(message_ids)
        service = self._connect()
        states: list[GmailObservedMessageState] = []
        for message_id in message_ids:
            try:
                payload = (
                    service.users()
                    .messages()
                    .get(userId="me", id=message_id, format="metadata", metadataHeaders=[])
                    .execute()
                )
            except HttpError as exc:
                raise GmailOrganizationGateError(
                    "provider_state_read_failed",
                    f"Gmail state revalidation failed with HTTP {_http_status(exc)}.",
                ) from exc
            except (TransportError, OSError) as exc:
                raise GmailOrganizationGateError(
                    "provider_state_read_failed",
                    "Gmail state revalidation could not reach the provider.",
                ) from exc
            if not isinstance(payload, dict):
                raise GmailOrganizationGateError(
                    "provider_state_malformed",
                    "Gmail returned malformed target state.",
                )
            provider_id = payload.get("id")
            thread_id = payload.get("threadId")
            labels = payload.get("labelIds")
            if (
                provider_id != message_id
                or not isinstance(thread_id, str)
                or not thread_id
                or not isinstance(labels, list)
                or any(not isinstance(value, str) or not value for value in labels)
            ):
                raise GmailOrganizationGateError(
                    "provider_state_malformed",
                    "Gmail returned malformed target identity or labels.",
                )
            normalized_labels = tuple(sorted(set(labels)))
            states.append(
                GmailObservedMessageState(
                    provider_message_id=provider_id,
                    provider_thread_id=thread_id,
                    label_ids=normalized_labels,
                    unread="UNREAD" in normalized_labels,
                )
            )
        return tuple(states)

    def modify_message_labels(
        self,
        message_ids: tuple[str, ...],
        *,
        add_label_ids: tuple[str, ...] = (),
        remove_label_ids: tuple[str, ...] = (),
    ) -> GmailBatchMutationResult:
        _validate_message_ids(message_ids)
        _validate_label_delta(add_label_ids, remove_label_ids)
        service = self._connect()
        try:
            (
                service.users()
                .messages()
                .batchModify(
                    userId="me",
                    body={
                        "ids": list(message_ids),
                        "addLabelIds": list(add_label_ids),
                        "removeLabelIds": list(remove_label_ids),
                    },
                )
                .execute()
            )
        except HttpError as exc:
            status = _http_status(exc)
            if status is not None and 400 <= status < 500:
                return GmailBatchMutationResult(
                    failed_message_ids=message_ids,
                    diagnostic_code=f"gmail_http_{status}",
                )
            return GmailBatchMutationResult(
                outcome_unknown=True,
                diagnostic_code="gmail_mutation_outcome_unknown",
            )
        except (TransportError, OSError):
            return GmailBatchMutationResult(
                outcome_unknown=True,
                diagnostic_code="gmail_mutation_outcome_unknown",
            )
        return GmailBatchMutationResult(successful_message_ids=message_ids)

    def create_label(self, name: str) -> GmailCreatedLabel:
        raise GmailOrganizationGateError(
            "label_creation_unavailable",
            "The live SID-231 canary transport supports existing labels only.",
        )

    def _connect(self) -> Any:
        if not self._client_id or not self._client_secret or not self._refresh_token:
            raise GmailOrganizationGateError(
                "gmail_credentials_missing",
                "The isolated Personal Gmail mutation credential is not configured.",
            )
        credentials = self._credentials_factory(
            token=None,
            refresh_token=self._refresh_token,
            token_uri=GMAIL_TOKEN_URI,
            client_id=self._client_id,
            client_secret=self._client_secret,
            scopes=list(PERSONAL_GMAIL_MUTATION_SCOPES),
        )
        try:
            credentials.refresh(self._request_factory())
        except RefreshError as exc:
            raise GmailOrganizationGateError(
                "gmail_mutation_authentication_failed",
                "Google rejected the isolated Personal Gmail mutation credential.",
            ) from exc
        except (TransportError, OSError) as exc:
            raise GmailOrganizationGateError(
                "gmail_mutation_provider_unavailable",
                "The Personal Gmail mutation credential could not be refreshed.",
            ) from exc
        granted = getattr(credentials, "granted_scopes", None)
        if granted is not None and frozenset(granted) not in {
            frozenset(PERSONAL_GMAIL_MUTATION_SCOPES),
            frozenset(PERSONAL_GMAIL_REAUTH_SCOPES),
        }:
            raise GmailOrganizationGateError(
                "gmail_mutation_scope_mismatch",
                "The write executor did not receive the exact gmail.modify access token.",
            )
        try:
            service = self._service_factory(
                "gmail", "v1", credentials=credentials, cache_discovery=False
            )
            profile = service.users().getProfile(userId="me").execute()
        except HttpError as exc:
            raise GmailOrganizationGateError(
                "gmail_mutation_profile_failed",
                f"Personal Gmail profile verification failed with HTTP {_http_status(exc)}.",
            ) from exc
        except (TransportError, OSError) as exc:
            raise GmailOrganizationGateError(
                "gmail_mutation_profile_failed",
                "Personal Gmail profile verification could not reach Google.",
            ) from exc
        address = profile.get("emailAddress") if isinstance(profile, dict) else None
        if not isinstance(address, str) or not address.strip():
            raise GmailOrganizationGateError(
                "gmail_mutation_profile_malformed",
                "Google returned an invalid Personal Gmail profile.",
            )
        if self._expected_address and not hmac.compare_digest(
            address.strip().casefold(), self._expected_address.strip().casefold()
        ):
            raise GmailOrganizationGateError(
                "gmail_mutation_wrong_account",
                "The mutation credential does not match the configured Personal account.",
            )
        return service


def _validate_message_ids(message_ids: tuple[str, ...]) -> None:
    if (
        not message_ids
        or len(message_ids) > MAX_GMAIL_MUTATION_BATCH_SIZE
        or len(message_ids) != len(set(message_ids))
        or any(not value.strip() for value in message_ids)
    ):
        raise GmailOrganizationGateError(
            "invalid_exact_manifest",
            "Gmail label operations require a bounded unique exact message manifest.",
        )


def _validate_label_delta(
    add_label_ids: tuple[str, ...], remove_label_ids: tuple[str, ...]
) -> None:
    values = (*add_label_ids, *remove_label_ids)
    if (
        not values
        or len(values) != len(set(values))
        or any(not value.strip() for value in values)
        or set(add_label_ids) & set(remove_label_ids)
    ):
        raise GmailOrganizationGateError(
            "invalid_label_delta",
            "Gmail label changes require one exact non-conflicting label delta.",
        )


def _http_status(exc: HttpError) -> int | None:
    value = getattr(getattr(exc, "resp", None), "status", None)
    return int(value) if isinstance(value, int) else None
