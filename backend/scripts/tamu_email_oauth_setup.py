"""Generate and securely store a distinct read-only TAMU Gmail credential."""

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
from app.gmail_scopes import TAMU_GMAIL_READ_SCOPES  # noqa: E402
from scripts.personal_email_oauth_setup import _credential_scopes, _write_env_value  # noqa: E402


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ENV_PATH = BACKEND_DIR / ".env"
REFRESH_TOKEN_ENV_KEY = "TAMU_EMAIL_GOOGLE_REFRESH_TOKEN"
EXPECTED_ADDRESS_ENV_KEY = "TAMU_EMAIL_EXPECTED_ADDRESS"
CLIENT_ID_ENV_KEY = "TAMU_EMAIL_GOOGLE_CLIENT_ID"
CLIENT_SECRET_ENV_KEY = "TAMU_EMAIL_GOOGLE_CLIENT_SECRET"


def main() -> None:
    args = _parse_args()
    settings = get_settings()
    client_id = settings.tamu_email_google_client_id
    client_secret = settings.tamu_email_google_client_secret
    if args.reuse_existing_client and (not client_id or not client_secret):
        client_id = settings.personal_email_client_id
        client_secret = settings.personal_email_client_secret
        if client_id and client_secret:
            _write_env_value(ENV_PATH, CLIENT_ID_ENV_KEY, client_id)
            _write_env_value(ENV_PATH, CLIENT_SECRET_ENV_KEY, client_secret)
            print("Copied the existing Desktop OAuth app registration into TAMU-only fields.")
            print("No existing refresh token was read, copied, or modified.")
    if not client_id or not client_secret:
        print("TAMU Gmail OAuth client configuration is missing.")
        print("Add TAMU_EMAIL_GOOGLE_CLIENT_ID and TAMU_EMAIL_GOOGLE_CLIENT_SECRET.")
        print("Personal Gmail and Calendar credentials were not used.")
        raise SystemExit(1)

    print("TAMU Gmail Read-Only OAuth Setup")
    print("---------------------------------")
    print("Provider: Texas A&M Google Workspace Gmail")
    print("Institutional sign-in: TAMU NetID through Microsoft Entra SAML and Duo")
    print("Requested Google API scope:")
    for scope in TAMU_GMAIL_READ_SCOPES:
        print(f"  - {scope}")
    print("This scope permits reading Gmail only; it cannot change or send mail.")
    print("Personal Gmail and Calendar refresh tokens will not be read or modified.")

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
        scopes=list(TAMU_GMAIL_READ_SCOPES),
    )
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        prompt="consent",
        access_type="offline",
        include_granted_scopes="false",
        open_browser=not args.no_open_browser,
        hd="tamu.edu",
    )
    if set(_credential_scopes(credentials)) != set(TAMU_GMAIL_READ_SCOPES):
        print("Google did not grant the exact read-only Gmail scope.")
        print("No TAMU credential was stored.")
        raise SystemExit(1)
    if not credentials.refresh_token:
        print("Google did not return a TAMU Gmail refresh token.")
        print("No TAMU credential was stored.")
        raise SystemExit(1)

    try:
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()
    except HttpError:
        print("The authenticated TAMU Gmail profile check failed.")
        print("No TAMU credential was stored.")
        raise SystemExit(1)
    except Exception:  # noqa: BLE001 - never expose credentials or profile details.
        print("The TAMU Gmail profile could not be verified.")
        print("No TAMU credential was stored.")
        raise SystemExit(1)

    profile_address = profile.get("emailAddress") if isinstance(profile, dict) else None
    if not isinstance(profile_address, str) or not profile_address.strip():
        print("Google returned an invalid TAMU Gmail profile response.")
        print("No TAMU credential was stored.")
        raise SystemExit(1)
    if not _is_tamu_address(profile_address):
        print("The authenticated Google account is not a tamu.edu account.")
        print("The account address was not displayed. No TAMU credential was stored.")
        raise SystemExit(1)
    expected = settings.tamu_email_expected_address
    if expected and not hmac.compare_digest(
        profile_address.strip().casefold(), expected.strip().casefold()
    ):
        print("The authenticated account does not match the configured TAMU account.")
        print("Neither account address was displayed. No TAMU credential was stored.")
        raise SystemExit(1)

    _write_env_value(ENV_PATH, REFRESH_TOKEN_ENV_KEY, credentials.refresh_token)
    _write_env_value(ENV_PATH, EXPECTED_ADDRESS_ENV_KEY, profile_address.strip())
    print("TAMU Gmail profile verification succeeded.")
    print("Stored the distinct TAMU token and wrong-account guard in ignored backend/.env.")
    print("No credential or account address was printed; backend/.env is owner-only.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Secure read-only Desktop OAuth setup for TAMU Gmail."
    )
    parser.add_argument(
        "--reuse-existing-client",
        action="store_true",
        help=(
            "Copy only the existing Desktop OAuth app ID and secret into TAMU-specific "
            "fields; never reuse an account refresh token."
        ),
    )
    parser.add_argument(
        "--no-open-browser",
        action="store_true",
        help="Print the authorization URL so it can be opened in the in-app browser.",
    )
    return parser.parse_args()


def _is_tamu_address(address: str) -> bool:
    _, separator, domain = address.strip().casefold().rpartition("@")
    return bool(separator) and (domain == "tamu.edu" or domain.endswith(".tamu.edu"))


if __name__ == "__main__":
    main()
