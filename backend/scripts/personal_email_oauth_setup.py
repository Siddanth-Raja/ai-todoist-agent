"""Generate and securely store a distinct Personal Gmail refresh token."""

from __future__ import annotations

import argparse
import hmac
from pathlib import Path
import sys

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.gmail_scopes import (  # noqa: E402
    GMAIL_MODIFY_SCOPE,
    PERSONAL_GMAIL_READ_SCOPES,
    PERSONAL_GMAIL_REAUTH_SCOPES,
)
from app.gmail_organization import GmailMutationGateRepository  # noqa: E402


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ENV_PATH = BACKEND_DIR / ".env"
REFRESH_TOKEN_ENV_KEY = "PERSONAL_EMAIL_GOOGLE_REFRESH_TOKEN"


def main() -> None:
    args = _parse_args()
    settings = get_settings()
    client_id = settings.personal_email_client_id
    client_secret = settings.personal_email_client_secret
    if not client_id or not client_secret:
        print(
            "Personal Gmail OAuth client configuration is missing. Add either the "
            "Personal Email-specific client fields or the shared Google client fields "
            "to backend/.env."
        )
        raise SystemExit(1)

    print("Personal Gmail OAuth Setup")
    print("--------------------------")
    requested_scopes = (
        PERSONAL_GMAIL_REAUTH_SCOPES
        if args.approve_modify
        else PERSONAL_GMAIL_READ_SCOPES
    )
    print("This flow requests exactly these isolated Personal Email scopes:")
    for scope in requested_scopes:
        print(f"  - {scope}")
    if args.approve_modify:
        print("gmail.modify is the only scope added to the existing read-only grant.")
        print("This approval records OAuth authorization only; it performs no Gmail mutation.")
    print("The existing Google Calendar refresh token will not be read or modified.")
    print("A local loopback callback will be opened using a Desktop OAuth client.")

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": AUTH_URL,
                "token_uri": TOKEN_URL,
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=list(requested_scopes),
    )
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        prompt="consent",
        access_type="offline",
        include_granted_scopes="false",
        open_browser=True,
    )
    granted_scopes = _credential_scopes(credentials)
    if set(granted_scopes) != set(requested_scopes):
        print("Google did not grant the exact approved Personal Gmail scope set.")
        print("No refresh token was stored.")
        raise SystemExit(1)
    if not credentials.refresh_token:
        print("Google did not return a Personal Gmail refresh token.")
        print("No credential was stored; rerun the consent flow after checking the OAuth client.")
        raise SystemExit(1)

    try:
        service = build(
            "gmail",
            "v1",
            credentials=credentials,
            cache_discovery=False,
        )
        profile = service.users().getProfile(userId="me").execute()
    except HttpError:
        print("The authenticated Gmail profile check failed.")
        print("Confirm that the Gmail API and the exact approved scopes are configured.")
        print("No refresh token was stored.")
        raise SystemExit(1)
    except Exception:  # noqa: BLE001 - never expose credential or profile details.
        print("The Personal Gmail profile could not be verified.")
        print("No refresh token was stored.")
        raise SystemExit(1)

    profile_address = profile.get("emailAddress") if isinstance(profile, dict) else None
    if not isinstance(profile_address, str) or not profile_address.strip():
        print("Google returned an invalid Gmail profile response.")
        print("No refresh token was stored.")
        raise SystemExit(1)
    expected = settings.personal_email_expected_address
    if expected and not hmac.compare_digest(
        profile_address.strip().casefold(), expected.strip().casefold()
    ):
        print("The authenticated Gmail account is not the configured Personal account.")
        print("Neither account address will be displayed. No refresh token was stored.")
        raise SystemExit(1)

    _write_env_value(ENV_PATH, REFRESH_TOKEN_ENV_KEY, credentials.refresh_token)
    if args.approve_modify:
        GmailMutationGateRepository().record_manual_oauth_authorization(
            authorized_scope=GMAIL_MODIFY_SCOPE,
            approval_reference=args.approval_reference,
        )
    print("Personal Gmail profile verification succeeded.")
    print(f"Stored {REFRESH_TOKEN_ENV_KEY} directly in ignored backend/.env.")
    print("The refresh token was not printed. backend/.env permissions are owner-only.")
    print("Restart PCOS before running the redacted live verification script.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Secure Desktop OAuth setup for the isolated Personal Gmail client."
    )
    parser.add_argument(
        "--approve-modify",
        action="store_true",
        help="Request gmail.modify in addition to the existing gmail.readonly grant.",
    )
    parser.add_argument(
        "--approval-reference",
        default="",
        help="Non-secret reference to the explicit user approval.",
    )
    args = parser.parse_args()
    if args.approve_modify and not args.approval_reference.strip():
        parser.error("--approval-reference is required with --approve-modify")
    if not args.approve_modify and args.approval_reference:
        parser.error("--approval-reference is valid only with --approve-modify")
    return args


def _credential_scopes(credentials) -> list[str]:
    scopes = getattr(credentials, "granted_scopes", None)
    if scopes is None:
        scopes = getattr(credentials, "scopes", None) or []
    return [str(scope) for scope in scopes]


def _write_env_value(path: Path, key: str, value: str) -> None:
    if not key or "\n" in key or "=" in key:
        raise ValueError("invalid environment key")
    if not value or "\n" in value or "\r" in value:
        raise ValueError("invalid environment value")
    lines = path.read_text().splitlines() if path.exists() else []
    updated: list[str] = []
    replaced = False
    prefix = f"{key}="
    for line in lines:
        if line.startswith(prefix):
            updated.append(f"{key}={value}")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(f"{key}={value}")
    path.write_text("\n".join(updated) + "\n")
    path.chmod(0o600)


if __name__ == "__main__":
    main()
