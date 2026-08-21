"""Isolated, read-only Gmail provider and normalization boundary."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import StrEnum
import hashlib
from html.parser import HTMLParser
import hmac
import re
import time
from typing import Any, Literal

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .email_domain import (
    EmailAccountRole,
    EmailMessageIdentity,
    EmailProviderAccountIdentity,
)


from .gmail_scopes import (
    GMAIL_READONLY_SCOPE,
    PERSONAL_GMAIL_READ_SCOPES,
    TAMU_GMAIL_READ_SCOPES,
)


# Backward-compatible public name for the provider's deliberately read-only
# runtime scope set.
PERSONAL_GMAIL_SCOPES = PERSONAL_GMAIL_READ_SCOPES
GMAIL_TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_GMAIL_QUERY = "-in:spam -in:trash"
MAX_RECENT_MESSAGES = 100
MAX_REVIEW_METADATA_MESSAGES = 50
GMAIL_PAGE_SIZE = 100
MAX_GMAIL_LIST_PAGES = 20
MAX_ANALYZABLE_BODY_CHARS = 20_000
MAX_SNIPPET_CHARS = 500
INVENTORY_METADATA_HEADERS = ("From", "To", "Cc", "Bcc", "Subject", "Date")
MAX_INVENTORY_READ_ATTEMPTS = 3


class GmailProviderState(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CONNECTED = "connected"
    AUTHENTICATION_FAILURE = "authentication_failure"
    PROVIDER_FAILURE = "provider_failure"
    MALFORMED_RESPONSE = "malformed_response"
    CONNECTED_EMPTY = "connected_empty"


class GmailProviderDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    http_status: int | None = None


class GmailHealthResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: GmailProviderState
    account: EmailProviderAccountIdentity | None = None
    message_total: int | None = None
    thread_total: int | None = None
    diagnostic: GmailProviderDiagnostic | None = None


class GmailAttachmentMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str
    mime_type: str
    size: int = Field(ge=0)
    provider_attachment_id: str | None = None


class GmailMessageRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: EmailMessageIdentity
    sender: str | None = None
    recipients: tuple[str, ...] = ()
    subject: str | None = None
    internal_date: datetime | None = None
    message_date: datetime | None = None
    label_ids: tuple[str, ...] = ()
    unread: bool
    snippet: str | None = None
    body_text: str | None = None
    body_truncated: bool = False
    attachments: tuple[GmailAttachmentMetadata, ...] = ()
    has_attachment: bool | None = None
    body_accessed: bool = False
    parse_diagnostics: tuple[str, ...] = ()
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class GmailMessagePage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: GmailProviderState
    messages: tuple[GmailMessageRecord, ...] = ()
    next_page_token: str | None = None
    complete: bool
    truncated: bool
    pages_fetched: int = Field(default=0, ge=0)
    result_size_estimate: int | None = Field(default=None, ge=0)
    diagnostic: GmailProviderDiagnostic | None = None


class GmailInventoryPage(BaseModel):
    """Complete-or-explicitly-partial metadata-only label inventory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: GmailProviderState
    messages: tuple[GmailMessageRecord, ...] = ()
    complete: bool
    pages_fetched: int = Field(default=0, ge=0)
    attachment_pages_fetched: int = Field(default=0, ge=0)
    next_page_token: str | None = None
    attachment_next_page_token: str | None = None
    result_size_estimate: int | None = Field(default=None, ge=0)
    duplicate_message_count: int = Field(default=0, ge=0)
    metadata_requests: int = Field(default=0, ge=0)
    provider_retry_count: int = Field(default=0, ge=0)
    body_requests: Literal[0] = 0
    diagnostic: GmailProviderDiagnostic | None = None


class GmailThreadResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: GmailProviderState
    messages: tuple[GmailMessageRecord, ...] = ()
    diagnostic: GmailProviderDiagnostic | None = None


class GmailLabel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_label_id: str
    name: str
    label_type: str | None = None
    messages_total: int | None = Field(default=None, ge=0)
    messages_unread: int | None = Field(default=None, ge=0)
    threads_total: int | None = Field(default=None, ge=0)
    threads_unread: int | None = Field(default=None, ge=0)


class GmailLabelResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: GmailProviderState
    labels: tuple[GmailLabel, ...] = ()
    matched_label: GmailLabel | None = None
    diagnostic: GmailProviderDiagnostic | None = None


@dataclass(frozen=True)
class _GmailConnection:
    service: Any
    account: EmailProviderAccountIdentity
    message_total: int | None
    thread_total: int | None


@dataclass(frozen=True)
class _ReferenceInventory:
    complete: bool
    pages_fetched: int
    next_page_token: str | None
    result_size_estimate: int | None
    duplicate_count: int
    retry_count: int = 0
    diagnostic: GmailProviderDiagnostic | None = None


class GmailClient:
    """Read-only Gmail client. No mutation method is intentionally defined."""

    def __init__(
        self,
        settings: Settings,
        *,
        credentials_factory=Credentials,
        request_factory=GoogleAuthRequest,
        service_factory=build,
        account_role: EmailAccountRole = EmailAccountRole.PERSONAL,
        account_label: str = "Personal Gmail",
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        expected_address: str | None = None,
        allow_personal_fallback: bool = True,
        scopes: tuple[str, ...] = PERSONAL_GMAIL_SCOPES,
        require_expected_address: bool = False,
    ) -> None:
        self._client_id = client_id
        if allow_personal_fallback and self._client_id is None:
            self._client_id = getattr(settings, "personal_email_client_id", None)
        if allow_personal_fallback and self._client_id is None:
            self._client_id = getattr(
                settings, "personal_email_google_client_id", None
            ) or getattr(settings, "google_client_id", None)
        self._client_secret = client_secret
        if allow_personal_fallback and self._client_secret is None:
            self._client_secret = getattr(
                settings, "personal_email_client_secret", None
            )
        if allow_personal_fallback and self._client_secret is None:
            self._client_secret = getattr(
                settings, "personal_email_google_client_secret", None
            ) or getattr(settings, "google_client_secret", None)
        self._refresh_token = refresh_token
        if allow_personal_fallback and self._refresh_token is None:
            self._refresh_token = getattr(
                settings, "personal_email_google_refresh_token", None
            )
        self._expected_address = expected_address
        if allow_personal_fallback and self._expected_address is None:
            self._expected_address = getattr(
                settings, "personal_email_expected_address", None
            )
        self._account_role = account_role
        self._account_label = account_label
        self._scopes = scopes
        self._require_expected_address = require_expected_address
        self._credentials_factory = credentials_factory
        self._request_factory = request_factory
        self._service_factory = service_factory

    @classmethod
    def for_tamu(cls, settings: Settings, **kwargs) -> "GmailClient":
        """Build the TAMU mailbox client without credential fallback."""

        return cls(
            settings,
            account_role=EmailAccountRole.AM,
            account_label="TAMU Gmail",
            client_id=settings.tamu_email_google_client_id,
            client_secret=settings.tamu_email_google_client_secret,
            refresh_token=settings.tamu_email_google_refresh_token,
            expected_address=settings.tamu_email_expected_address,
            allow_personal_fallback=False,
            scopes=TAMU_GMAIL_READ_SCOPES,
            require_expected_address=True,
            **kwargs,
        )

    @property
    def account_role(self) -> EmailAccountRole:
        return self._account_role

    def check_health(self) -> GmailHealthResult:
        connection, error = self._connect()
        if error:
            return GmailHealthResult(state=_state_for_error(error), diagnostic=error)
        assert connection is not None
        return GmailHealthResult(
            state=GmailProviderState.CONNECTED,
            account=connection.account,
            message_total=connection.message_total,
            thread_total=connection.thread_total,
        )

    def list_recent_messages(
        self,
        *,
        max_messages: int = 20,
        page_token: str | None = None,
        query: str | None = None,
        label_ids: tuple[str, ...] = (),
    ) -> GmailMessagePage:
        if max_messages < 1 or max_messages > MAX_RECENT_MESSAGES:
            raise ValueError(
                f"max_messages must be between 1 and {MAX_RECENT_MESSAGES}"
            )
        if any(not value.strip() for value in label_ids):
            raise ValueError("label IDs cannot be blank")

        connection, error = self._connect()
        if error:
            return _message_error_result(error)
        assert connection is not None

        records: list[GmailMessageRecord] = []
        next_token = page_token
        seen_tokens: set[str] = set()
        pages_fetched = 0
        result_size_estimate: int | None = None
        complete = False
        while len(records) < max_messages:
            remaining = max_messages - len(records)
            kwargs: dict[str, Any] = {
                "userId": "me",
                "maxResults": min(remaining, GMAIL_PAGE_SIZE),
                "q": _gmail_query(query),
                "includeSpamTrash": False,
            }
            if next_token:
                kwargs["pageToken"] = next_token
            if label_ids:
                kwargs["labelIds"] = list(label_ids)

            payload, error = self._execute(
                connection.service.users().messages().list(**kwargs)
            )
            if error:
                return _message_error_result(error, pages_fetched=pages_fetched)
            pages_fetched += 1
            if not isinstance(payload, dict):
                return _message_malformed("Gmail message list response was malformed.")
            references = payload.get("messages", [])
            if not isinstance(references, list) or len(references) > remaining:
                return _message_malformed("Gmail message list entries were malformed.")
            if result_size_estimate is None:
                result_size_estimate = _optional_nonnegative_int(
                    payload.get("resultSizeEstimate")
                )

            for reference in references:
                if not _valid_message_reference(reference):
                    return _message_malformed("Gmail message identity was malformed.")
                raw, error = self._execute(
                    connection.service.users()
                    .messages()
                    .get(userId="me", id=reference["id"], format="full")
                )
                if error:
                    return _message_error_result(error, pages_fetched=pages_fetched)
                try:
                    records.append(_normalize_message(raw, connection.account))
                except (TypeError, ValueError):
                    return _message_malformed(
                        "Gmail message detail response was malformed."
                    )

            raw_next_token = payload.get("nextPageToken")
            if raw_next_token is not None and (
                not isinstance(raw_next_token, str) or not raw_next_token.strip()
            ):
                return _message_malformed("Gmail pagination token was malformed.")
            next_token = raw_next_token
            if not next_token:
                complete = True
                break
            if next_token in seen_tokens:
                return _message_malformed("Gmail pagination token repeated.")
            seen_tokens.add(next_token)
            if pages_fetched >= MAX_GMAIL_LIST_PAGES:
                break
            if not references:
                continue

        state = (
            GmailProviderState.CONNECTED
            if records
            else GmailProviderState.CONNECTED_EMPTY
        )
        return GmailMessagePage(
            state=state,
            messages=tuple(records),
            next_page_token=next_token,
            complete=complete,
            truncated=not complete,
            pages_fetched=pages_fetched,
            result_size_estimate=result_size_estimate,
        )

    def list_message_metadata(
        self,
        *,
        max_messages: int = 20,
        query: str | None = None,
        label_ids: tuple[str, ...] = (),
    ) -> GmailMessagePage:
        """Read one bounded page of headers and mailbox state without MIME bodies."""

        if max_messages < 1 or max_messages > MAX_REVIEW_METADATA_MESSAGES:
            raise ValueError(
                f"max_messages must be between 1 and {MAX_REVIEW_METADATA_MESSAGES}"
            )
        if any(not value.strip() for value in label_ids):
            raise ValueError("label IDs cannot be blank")

        connection, error = self._connect()
        if error:
            return _message_error_result(error)
        assert connection is not None

        kwargs: dict[str, Any] = {
            "userId": "me",
            "maxResults": max_messages,
            "q": _gmail_query(query),
            "includeSpamTrash": False,
        }
        if label_ids:
            kwargs["labelIds"] = list(label_ids)
        payload, error = self._execute(
            connection.service.users().messages().list(**kwargs)
        )
        if error:
            return _message_error_result(error)
        if not isinstance(payload, dict):
            return _message_malformed("Gmail metadata list response was malformed.")
        references = payload.get("messages", [])
        if not isinstance(references, list) or len(references) > max_messages:
            return _message_malformed("Gmail metadata list entries were malformed.")

        records: list[GmailMessageRecord] = []
        for reference in references:
            if not _valid_message_reference(reference):
                return _message_malformed("Gmail metadata identity was malformed.")
            raw, error = self._execute(
                connection.service.users()
                .messages()
                .get(
                    userId="me",
                    id=reference["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
            )
            if error:
                return _message_error_result(error, pages_fetched=1)
            try:
                record = _normalize_message(raw, connection.account, body_accessed=False)
            except (TypeError, ValueError):
                return _message_malformed(
                    "Gmail metadata detail response was malformed."
                )
            records.append(
                record.model_copy(
                    update={
                        "snippet": None,
                        "body_text": None,
                        "body_accessed": False,
                        "attachments": (),
                        "has_attachment": None,
                    }
                )
            )

        raw_next_token = payload.get("nextPageToken")
        if raw_next_token is not None and (
            not isinstance(raw_next_token, str) or not raw_next_token.strip()
        ):
            return _message_malformed("Gmail metadata pagination token was malformed.")
        complete = raw_next_token is None
        return GmailMessagePage(
            state=(
                GmailProviderState.CONNECTED
                if records
                else GmailProviderState.CONNECTED_EMPTY
            ),
            messages=tuple(records),
            next_page_token=raw_next_token,
            complete=complete,
            truncated=not complete,
            pages_fetched=1,
            result_size_estimate=_optional_nonnegative_int(
                payload.get("resultSizeEstimate")
            ),
        )

    def inventory_label_messages(self, *, provider_label_id: str) -> GmailInventoryPage:
        """Read every message in one exact provider label without reading bodies.

        Gmail's metadata format cannot expose attachment structure, so a second
        complete `has:attachment` identity pass supplies attachment evidence.
        Both cursors are retained and any partial/malformed pass fails closed.
        """

        if not provider_label_id.strip():
            raise ValueError("provider_label_id cannot be blank")
        connection, error = self._connect()
        if error:
            return GmailInventoryPage(
                state=_state_for_error(error), complete=False, diagnostic=error
            )
        assert connection is not None

        references, primary = self._list_all_message_references(
            connection, provider_label_id=provider_label_id, query=None
        )
        attachment_references, attachments = self._list_all_message_references(
            connection, provider_label_id=provider_label_id, query="has:attachment"
        )
        attachment_ids = {item[0] for item in attachment_references}
        diagnostic = primary.diagnostic or attachments.diagnostic
        records: list[GmailMessageRecord] = []
        metadata_requests = 0
        retry_count = primary.retry_count + attachments.retry_count
        if diagnostic is None:
            for message_id, _thread_id in references:
                raw, error, retries = self._execute_inventory_read(
                    connection.service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=message_id,
                        format="metadata",
                        metadataHeaders=list(INVENTORY_METADATA_HEADERS),
                    )
                )
                metadata_requests += 1
                retry_count += retries
                if error:
                    diagnostic = error
                    break
                try:
                    record = _normalize_message(raw, connection.account, body_accessed=False)
                except (TypeError, ValueError):
                    diagnostic = _malformed_diagnostic(
                        "Gmail inventory metadata response was malformed."
                    )
                    break
                if provider_label_id not in record.label_ids:
                    diagnostic = _malformed_diagnostic(
                        "Gmail inventory metadata did not preserve the requested label."
                    )
                    break
                records.append(
                    record.model_copy(
                        update={"has_attachment": message_id in attachment_ids}
                    )
                )

        complete = (
            diagnostic is None
            and primary.complete
            and attachments.complete
            and len(records) == len(references)
        )
        if complete:
            state = (
                GmailProviderState.CONNECTED
                if records
                else GmailProviderState.CONNECTED_EMPTY
            )
        elif diagnostic is not None:
            state = _state_for_error(diagnostic)
        else:
            state = GmailProviderState.MALFORMED_RESPONSE
            diagnostic = _malformed_diagnostic("Gmail inventory did not complete.")
        return GmailInventoryPage(
            state=state,
            messages=tuple(records),
            complete=complete,
            pages_fetched=primary.pages_fetched,
            attachment_pages_fetched=attachments.pages_fetched,
            next_page_token=primary.next_page_token,
            attachment_next_page_token=attachments.next_page_token,
            result_size_estimate=primary.result_size_estimate,
            duplicate_message_count=primary.duplicate_count,
            metadata_requests=metadata_requests,
            provider_retry_count=retry_count,
            diagnostic=diagnostic,
        )

    def _list_all_message_references(
        self,
        connection: _GmailConnection,
        *,
        provider_label_id: str,
        query: str | None,
    ) -> tuple[list[tuple[str, str]], "_ReferenceInventory"]:
        references: list[tuple[str, str]] = []
        seen_ids: set[str] = set()
        seen_tokens: set[str] = set()
        next_token: str | None = None
        pages_fetched = 0
        duplicate_count = 0
        result_size_estimate: int | None = None
        retry_count = 0
        while True:
            kwargs: dict[str, Any] = {
                "userId": "me",
                "maxResults": GMAIL_PAGE_SIZE,
                "q": _gmail_query(query),
                "labelIds": [provider_label_id],
                "includeSpamTrash": False,
            }
            if next_token:
                kwargs["pageToken"] = next_token
            payload, error, retries = self._execute_inventory_read(
                connection.service.users().messages().list(**kwargs)
            )
            retry_count += retries
            if error:
                return references, _ReferenceInventory(
                    complete=False,
                    pages_fetched=pages_fetched,
                    next_page_token=next_token,
                    result_size_estimate=result_size_estimate,
                    duplicate_count=duplicate_count,
                    retry_count=retry_count,
                    diagnostic=error,
                )
            pages_fetched += 1
            if not isinstance(payload, dict) or not isinstance(
                payload.get("messages", []), list
            ):
                error = _malformed_diagnostic(
                    "Gmail inventory list response was malformed."
                )
                return references, _ReferenceInventory(
                    complete=False,
                    pages_fetched=pages_fetched,
                    next_page_token=next_token,
                    result_size_estimate=result_size_estimate,
                    duplicate_count=duplicate_count,
                    retry_count=retry_count,
                    diagnostic=error,
                )
            if result_size_estimate is None:
                result_size_estimate = _optional_nonnegative_int(
                    payload.get("resultSizeEstimate")
                )
            for reference in payload.get("messages", []):
                if not _valid_message_reference(reference):
                    error = _malformed_diagnostic(
                        "Gmail inventory message identity was malformed."
                    )
                    return references, _ReferenceInventory(
                        complete=False,
                        pages_fetched=pages_fetched,
                        next_page_token=next_token,
                        result_size_estimate=result_size_estimate,
                        duplicate_count=duplicate_count,
                        retry_count=retry_count,
                        diagnostic=error,
                    )
                message_id = reference["id"]
                if message_id in seen_ids:
                    duplicate_count += 1
                    continue
                seen_ids.add(message_id)
                references.append((message_id, reference["threadId"]))
            raw_next = payload.get("nextPageToken")
            if raw_next is None:
                return references, _ReferenceInventory(
                    complete=True,
                    pages_fetched=pages_fetched,
                    next_page_token=None,
                    result_size_estimate=result_size_estimate,
                    duplicate_count=duplicate_count,
                    retry_count=retry_count,
                )
            if (
                not isinstance(raw_next, str)
                or not raw_next.strip()
                or raw_next in seen_tokens
            ):
                error = _malformed_diagnostic(
                    "Gmail inventory pagination token was malformed or repeated."
                )
                return references, _ReferenceInventory(
                    complete=False,
                    pages_fetched=pages_fetched,
                    next_page_token=(raw_next if isinstance(raw_next, str) else None),
                    result_size_estimate=result_size_estimate,
                    duplicate_count=duplicate_count,
                    retry_count=retry_count,
                    diagnostic=error,
                )
            seen_tokens.add(raw_next)
            next_token = raw_next

    def _execute_inventory_read(
        self, request
    ) -> tuple[Any | None, GmailProviderDiagnostic | None, int]:
        retries = 0
        for attempt in range(MAX_INVENTORY_READ_ATTEMPTS):
            payload, error = self._execute(request)
            if error is None or not _retryable_inventory_error(error):
                return payload, error, retries
            if attempt + 1 >= MAX_INVENTORY_READ_ATTEMPTS:
                return payload, error, retries
            retries += 1
            time.sleep(0.1 * (attempt + 1))
        raise AssertionError("unreachable inventory retry state")

    def get_thread(self, thread_id: str) -> GmailThreadResult:
        if not thread_id.strip():
            raise ValueError("thread_id cannot be blank")
        connection, error = self._connect()
        if error:
            return GmailThreadResult(state=_state_for_error(error), diagnostic=error)
        assert connection is not None
        payload, error = self._execute(
            connection.service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
        )
        if error:
            return GmailThreadResult(state=_state_for_error(error), diagnostic=error)
        if not isinstance(payload, dict) or payload.get("id") != thread_id:
            return _thread_malformed()
        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            return _thread_malformed()
        try:
            messages = tuple(
                _normalize_message(raw_message, connection.account)
                for raw_message in raw_messages
            )
        except (TypeError, ValueError):
            return _thread_malformed()
        if any(
            message.identity.provider_thread_id != thread_id for message in messages
        ):
            return _thread_malformed()
        return GmailThreadResult(
            state=GmailProviderState.CONNECTED,
            messages=messages,
        )

    def list_labels(self) -> GmailLabelResult:
        connection, error = self._connect()
        if error:
            return GmailLabelResult(state=_state_for_error(error), diagnostic=error)
        assert connection is not None
        payload, error = self._execute(
            connection.service.users().labels().list(userId="me")
        )
        if error:
            return GmailLabelResult(state=_state_for_error(error), diagnostic=error)
        if not isinstance(payload, dict) or not isinstance(payload.get("labels", []), list):
            return _label_malformed()
        try:
            labels = tuple(_normalize_label(item) for item in payload.get("labels", []))
        except (TypeError, ValueError):
            return _label_malformed()
        return GmailLabelResult(
            state=(
                GmailProviderState.CONNECTED
                if labels
                else GmailProviderState.CONNECTED_EMPTY
            ),
            labels=labels,
        )

    def find_label(self, name: str) -> GmailLabelResult:
        if not name.strip():
            raise ValueError("label name cannot be blank")
        result = self.list_labels()
        if result.diagnostic:
            return result
        target = name.strip().casefold()
        match = next(
            (label for label in result.labels if label.name.casefold() == target),
            None,
        )
        return GmailLabelResult(
            state=(
                GmailProviderState.CONNECTED
                if match is not None
                else GmailProviderState.CONNECTED_EMPTY
            ),
            labels=result.labels,
            matched_label=match,
        )

    def find_label_exact(self, name: str) -> GmailLabelResult:
        """Resolve a provider label by exact, case-sensitive displayed name."""

        if not name.strip() or name != name.strip():
            raise ValueError("exact label name cannot be blank or padded")
        result = self.list_labels()
        if result.diagnostic:
            return result
        match = next((label for label in result.labels if label.name == name), None)
        return GmailLabelResult(
            state=(
                GmailProviderState.CONNECTED
                if match is not None
                else GmailProviderState.CONNECTED_EMPTY
            ),
            labels=result.labels,
            matched_label=match,
        )

    def _connect(
        self,
    ) -> tuple[_GmailConnection | None, GmailProviderDiagnostic | None]:
        missing: list[str] = []
        if not self._client_id:
            missing.append("OAuth client ID")
        if not self._client_secret:
            missing.append("OAuth client secret")
        if not self._refresh_token:
            missing.append(f"{self._account_label} refresh token")
        if self._require_expected_address and not self._expected_address:
            missing.append(f"{self._account_label} expected address")
        if missing:
            return None, GmailProviderDiagnostic(
                code="not_configured",
                message=f"{self._account_label} read access is not configured.",
            )

        credentials = self._credentials_factory(
            token=None,
            refresh_token=self._refresh_token,
            token_uri=GMAIL_TOKEN_URI,
            client_id=self._client_id,
            client_secret=self._client_secret,
            scopes=list(self._scopes),
        )
        try:
            credentials.refresh(self._request_factory())
        except RefreshError:
            return None, GmailProviderDiagnostic(
                code="authentication",
                message=f"{self._account_label} rejected the configured OAuth credential.",
            )
        except (TransportError, OSError):
            return None, GmailProviderDiagnostic(
                code="provider",
                message=f"Could not reach Google while refreshing {self._account_label} access.",
            )
        except Exception:  # noqa: BLE001 - fail closed without leaking provider details.
            return None, GmailProviderDiagnostic(
                code="provider",
                message=f"{self._account_label} credential refresh failed.",
            )

        granted_scopes = getattr(credentials, "granted_scopes", None)
        if granted_scopes is not None and set(granted_scopes) != set(self._scopes):
            return None, GmailProviderDiagnostic(
                code="scope",
                message=f"{self._account_label} OAuth did not grant the exact read-only scope.",
            )

        try:
            service = self._service_factory(
                "gmail",
                "v1",
                credentials=credentials,
                cache_discovery=False,
            )
            profile = service.users().getProfile(userId="me").execute()
        except HttpError as exc:
            return None, _http_diagnostic(exc)
        except (TransportError, OSError):
            return None, GmailProviderDiagnostic(
                code="provider",
                message=f"Could not reach the {self._account_label} provider.",
            )
        except Exception:  # noqa: BLE001 - diagnostics must not expose provider data.
            return None, GmailProviderDiagnostic(
                code="provider",
                message=f"{self._account_label} profile check failed.",
            )

        if not isinstance(profile, dict):
            return None, _malformed_diagnostic("Gmail profile response was malformed.")
        profile_address = profile.get("emailAddress")
        if not isinstance(profile_address, str) or not profile_address.strip():
            return None, _malformed_diagnostic("Gmail profile identity was malformed.")
        if self._expected_address and not hmac.compare_digest(
            profile_address.strip().casefold(),
            self._expected_address.strip().casefold(),
        ):
            return None, GmailProviderDiagnostic(
                code="wrong_account",
                message=(
                    "Authenticated Gmail account does not match the configured "
                    f"{self._account_label} account."
                ),
            )

        account = EmailProviderAccountIdentity(
            provider="gmail",
            account_role=self._account_role,
            provider_account_id=_opaque_account_id(profile_address),
        )
        return (
            _GmailConnection(
                service=service,
                account=account,
                message_total=_optional_nonnegative_int(profile.get("messagesTotal")),
                thread_total=_optional_nonnegative_int(profile.get("threadsTotal")),
            ),
            None,
        )

    def _execute(self, request) -> tuple[Any | None, GmailProviderDiagnostic | None]:
        try:
            return request.execute(), None
        except HttpError as exc:
            return None, _http_diagnostic(exc)
        except (TransportError, OSError):
            return None, GmailProviderDiagnostic(
                code="provider",
                message=f"Could not reach the {self._account_label} provider.",
            )
        except Exception:  # noqa: BLE001 - never leak request or message data.
            return None, GmailProviderDiagnostic(
                code="provider",
                message=f"{self._account_label} read failed.",
            )


def personal_email_health_payload(settings: Settings) -> dict[str, Any]:
    result = GmailClient(settings).check_health()
    details: dict[str, Any] = {
        "state": result.state.value,
        "account_role": EmailAccountRole.PERSONAL.value,
        "configured_scopes": list(PERSONAL_GMAIL_SCOPES),
    }
    if result.account is not None:
        details["provider_account_id"] = result.account.provider_account_id
    if result.message_total is not None:
        details["message_total"] = result.message_total
    if result.thread_total is not None:
        details["thread_total"] = result.thread_total
    if result.diagnostic is not None:
        details["error_code"] = result.diagnostic.code
        if result.diagnostic.http_status is not None:
            details["http_status"] = result.diagnostic.http_status

    if result.state == GmailProviderState.NOT_CONFIGURED:
        return {
            "status": "warning",
            "message": (
                "Personal Gmail is not configured. Run the secure Personal Email "
                "Desktop OAuth setup after enabling the Gmail API."
            ),
            "details": details,
        }
    if result.state == GmailProviderState.CONNECTED:
        return {
            "status": "ok",
            "message": "Connected to Personal Gmail with read-only access.",
            "details": details,
        }
    if result.state == GmailProviderState.AUTHENTICATION_FAILURE:
        message = "Personal Gmail OAuth or account verification failed."
    elif result.state == GmailProviderState.MALFORMED_RESPONSE:
        message = "Personal Gmail returned an invalid profile response."
    else:
        message = "Personal Gmail provider health check failed."
    return {"status": "error", "message": message, "details": details}


def tamu_email_health_payload(settings: Settings) -> dict[str, Any]:
    result = GmailClient.for_tamu(settings).check_health()
    details: dict[str, Any] = {
        "state": result.state.value,
        "account_role": EmailAccountRole.AM.value,
        "configured_scopes": list(TAMU_GMAIL_READ_SCOPES),
    }
    if result.account is not None:
        details["provider_account_id"] = result.account.provider_account_id
    if result.message_total is not None:
        details["message_total"] = result.message_total
    if result.thread_total is not None:
        details["thread_total"] = result.thread_total
    if result.diagnostic is not None:
        details["error_code"] = result.diagnostic.code
        if result.diagnostic.http_status is not None:
            details["http_status"] = result.diagnostic.http_status

    if result.state == GmailProviderState.NOT_CONFIGURED:
        return {
            "status": "warning",
            "message": "TAMU Gmail read-only access is not configured.",
            "details": details,
        }
    if result.state == GmailProviderState.CONNECTED:
        return {
            "status": "ok",
            "message": "Connected to TAMU Gmail with read-only access.",
            "details": details,
        }
    if result.state == GmailProviderState.AUTHENTICATION_FAILURE:
        message = "TAMU Gmail OAuth or account verification failed."
    elif result.state == GmailProviderState.MALFORMED_RESPONSE:
        message = "TAMU Gmail returned an invalid profile response."
    else:
        message = "TAMU Gmail provider health check failed."
    return {"status": "error", "message": message, "details": details}


def _normalize_message(
    raw: Any,
    account: EmailProviderAccountIdentity,
    *,
    body_accessed: bool = True,
) -> GmailMessageRecord:
    if not isinstance(raw, dict):
        raise ValueError("message must be an object")
    message_id = raw.get("id")
    thread_id = raw.get("threadId")
    payload = raw.get("payload")
    if (
        not isinstance(message_id, str)
        or not message_id
        or not isinstance(thread_id, str)
        or not thread_id
        or not isinstance(payload, dict)
    ):
        raise ValueError("message identity or payload missing")

    headers = payload.get("headers", [])
    if not isinstance(headers, list):
        raise ValueError("headers malformed")
    header_values: dict[str, list[str]] = {}
    for header in headers:
        if not isinstance(header, dict):
            raise ValueError("header malformed")
        name = header.get("name")
        value = header.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("header fields malformed")
        header_values.setdefault(name.casefold(), []).append(value)

    diagnostics: list[str] = []
    internal_date = _parse_internal_date(raw.get("internalDate"), diagnostics)
    message_date = _parse_message_date(_first_header(header_values, "date"), diagnostics)
    if body_accessed:
        body_text, attachments, body_diagnostics, body_truncated = _parse_mime_payload(
            payload
        )
        diagnostics.extend(body_diagnostics)
    else:
        body_text = None
        attachments = ()
        body_truncated = False

    labels = raw.get("labelIds", [])
    if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
        raise ValueError("labels malformed")
    snippet = raw.get("snippet")
    if snippet is not None and not isinstance(snippet, str):
        raise ValueError("snippet malformed")

    recipients = tuple(
        value
        for key in ("to", "cc", "bcc")
        for value in header_values.get(key, [])
    )
    return GmailMessageRecord(
        identity=EmailMessageIdentity(
            account=account,
            provider_message_id=message_id,
            provider_thread_id=thread_id,
        ),
        sender=_first_header(header_values, "from"),
        recipients=recipients,
        subject=_first_header(header_values, "subject"),
        internal_date=internal_date,
        message_date=message_date,
        label_ids=tuple(labels),
        unread="UNREAD" in labels,
        snippet=(snippet[:MAX_SNIPPET_CHARS] if snippet else None),
        body_text=body_text,
        body_truncated=body_truncated,
        attachments=attachments,
        has_attachment=(bool(attachments) if body_accessed else None),
        body_accessed=body_accessed,
        parse_diagnostics=tuple(dict.fromkeys(diagnostics)),
        provider_metadata={
            "history_id": raw.get("historyId"),
            "size_estimate": _optional_nonnegative_int(raw.get("sizeEstimate")),
            "mime_type": payload.get("mimeType"),
        },
    )


def _parse_mime_payload(
    payload: dict[str, Any],
) -> tuple[str | None, tuple[GmailAttachmentMetadata, ...], list[str], bool]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[GmailAttachmentMetadata] = []
    diagnostics: list[str] = []
    _walk_mime(payload, plain_parts, html_parts, attachments, diagnostics)
    selected = "\n\n".join(part for part in plain_parts if part.strip())
    if not selected:
        selected = "\n\n".join(part for part in html_parts if part.strip())
    selected = selected.strip()
    truncated = len(selected) > MAX_ANALYZABLE_BODY_CHARS
    if truncated:
        selected = selected[:MAX_ANALYZABLE_BODY_CHARS]
    return selected or None, tuple(attachments), diagnostics, truncated


def _walk_mime(
    part: Any,
    plain_parts: list[str],
    html_parts: list[str],
    attachments: list[GmailAttachmentMetadata],
    diagnostics: list[str],
) -> None:
    if not isinstance(part, dict):
        diagnostics.append("malformed_mime_part")
        return
    mime_type = part.get("mimeType") or "application/octet-stream"
    filename = part.get("filename") or ""
    body = part.get("body") or {}
    if not isinstance(mime_type, str) or not isinstance(filename, str) or not isinstance(body, dict):
        diagnostics.append("malformed_mime_part")
        return
    attachment_id = body.get("attachmentId")
    size = _optional_nonnegative_int(body.get("size")) or 0
    if filename or attachment_id:
        attachments.append(
            GmailAttachmentMetadata(
                filename=filename,
                mime_type=mime_type,
                size=size,
                provider_attachment_id=(
                    attachment_id if isinstance(attachment_id, str) else None
                ),
            )
        )
        if attachment_id and not body.get("data"):
            return

    data = body.get("data")
    if data is not None:
        if not isinstance(data, str):
            diagnostics.append("malformed_body_data")
        elif mime_type in {"text/plain", "text/html"}:
            decoded = _decode_body(data, part, diagnostics)
            if decoded is not None:
                if mime_type == "text/plain":
                    plain_parts.append(decoded)
                else:
                    html_parts.append(_html_to_text(decoded))

    parts = part.get("parts", [])
    if parts is None:
        parts = []
    if not isinstance(parts, list):
        diagnostics.append("malformed_mime_parts")
        return
    for child in parts:
        _walk_mime(child, plain_parts, html_parts, attachments, diagnostics)


def _decode_body(
    data: str,
    part: dict[str, Any],
    diagnostics: list[str],
) -> str | None:
    try:
        padding = "=" * (-len(data) % 4)
        decoded = base64.b64decode(data + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        diagnostics.append("invalid_base64_body")
        return None
    charset = _mime_charset(part) or "utf-8"
    try:
        return decoded.decode(charset)
    except (LookupError, UnicodeDecodeError):
        diagnostics.append("body_text_decode_error")
        return decoded.decode("utf-8", errors="replace")


def _mime_charset(part: dict[str, Any]) -> str | None:
    headers = part.get("headers", [])
    if not isinstance(headers, list):
        return None
    for header in headers:
        if not isinstance(header, dict):
            continue
        if str(header.get("name", "")).casefold() != "content-type":
            continue
        value = str(header.get("value", ""))
        match = re.search(r"charset=[\"']?([^;\"']+)", value, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


class _BodyHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() in {"script", "style"}:
            self._ignored_depth += 1
        elif tag.casefold() in {"br", "p", "div", "li", "tr"}:
            self.text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag.casefold() in {"p", "div", "li", "tr"}:
            self.text.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.text.append(data)


def _html_to_text(value: str) -> str:
    parser = _BodyHTMLParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed HTML remains bounded text.
        return ""
    lines = (" ".join(line.split()) for line in "".join(parser.text).splitlines())
    return "\n".join(line for line in lines if line)


def _normalize_label(raw: Any) -> GmailLabel:
    if not isinstance(raw, dict):
        raise ValueError("label malformed")
    label_id = raw.get("id")
    name = raw.get("name")
    if not isinstance(label_id, str) or not label_id or not isinstance(name, str) or not name:
        raise ValueError("label identity malformed")
    return GmailLabel(
        provider_label_id=label_id,
        name=name,
        label_type=raw.get("type") if isinstance(raw.get("type"), str) else None,
        messages_total=_optional_nonnegative_int(raw.get("messagesTotal")),
        messages_unread=_optional_nonnegative_int(raw.get("messagesUnread")),
        threads_total=_optional_nonnegative_int(raw.get("threadsTotal")),
        threads_unread=_optional_nonnegative_int(raw.get("threadsUnread")),
    )


def _parse_internal_date(value: Any, diagnostics: list[str]) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        diagnostics.append("invalid_internal_date")
        return None


def _parse_message_date(value: str | None, diagnostics: list[str]) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        diagnostics.append("invalid_message_date")
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _gmail_query(query: str | None) -> str:
    normalized = query.strip() if query else ""
    return f"({normalized}) {DEFAULT_GMAIL_QUERY}" if normalized else DEFAULT_GMAIL_QUERY


def _opaque_account_id(address: str) -> str:
    digest = hashlib.sha256(f"gmail:{address.strip().casefold()}".encode("utf-8")).hexdigest()
    return f"personal-{digest[:24]}"


def _valid_message_reference(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("id"), str)
        and bool(value["id"])
        and isinstance(value.get("threadId"), str)
        and bool(value["threadId"])
    )


def _first_header(headers: dict[str, list[str]], name: str) -> str | None:
    values = headers.get(name.casefold()) or []
    return values[0] if values else None


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _http_diagnostic(exc: HttpError) -> GmailProviderDiagnostic:
    response = getattr(exc, "resp", None)
    status = getattr(response, "status", None)
    if status in {401, 403}:
        return GmailProviderDiagnostic(
            code="authentication",
            message="Personal Gmail rejected the read-only request.",
            http_status=status,
        )
    return GmailProviderDiagnostic(
        code="provider",
        message="Personal Gmail request failed.",
        http_status=status if isinstance(status, int) else None,
    )


def _malformed_diagnostic(message: str) -> GmailProviderDiagnostic:
    return GmailProviderDiagnostic(code="malformed_response", message=message)


def _state_for_error(error: GmailProviderDiagnostic) -> GmailProviderState:
    if error.code == "not_configured":
        return GmailProviderState.NOT_CONFIGURED
    if error.code in {"authentication", "scope", "wrong_account"}:
        return GmailProviderState.AUTHENTICATION_FAILURE
    if error.code == "malformed_response":
        return GmailProviderState.MALFORMED_RESPONSE
    return GmailProviderState.PROVIDER_FAILURE


def _retryable_inventory_error(error: GmailProviderDiagnostic) -> bool:
    return error.code == "provider" or (
        error.http_status is not None
        and (error.http_status == 429 or error.http_status >= 500)
    )


def _message_error_result(
    error: GmailProviderDiagnostic,
    *,
    pages_fetched: int = 0,
) -> GmailMessagePage:
    return GmailMessagePage(
        state=_state_for_error(error),
        complete=False,
        truncated=False,
        pages_fetched=pages_fetched,
        diagnostic=error,
    )


def _message_malformed(message: str) -> GmailMessagePage:
    error = _malformed_diagnostic(message)
    return _message_error_result(error)


def _thread_malformed() -> GmailThreadResult:
    error = _malformed_diagnostic("Gmail thread response was malformed.")
    return GmailThreadResult(
        state=GmailProviderState.MALFORMED_RESPONSE,
        diagnostic=error,
    )


def _label_malformed() -> GmailLabelResult:
    error = _malformed_diagnostic("Gmail label response was malformed.")
    return GmailLabelResult(
        state=GmailProviderState.MALFORMED_RESPONSE,
        diagnostic=error,
    )
