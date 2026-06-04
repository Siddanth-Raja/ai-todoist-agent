from http.server import BaseHTTPRequestHandler, HTTPServer
import argparse
from pathlib import Path
import sys
from threading import Event
from urllib.parse import parse_qs, urlencode, urlparse
import webbrowser

import requests


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402


SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]
DEFAULT_REDIRECT_URI = "http://localhost"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    server_version = "GoogleOAuthSetup/1.0"

    def do_GET(self) -> None:  # noqa: N802 - http.server callback name.
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        self.server.auth_code = _first(params.get("code"))
        self.server.auth_error = _first(params.get("error"))
        self.server.callback_received.set()

        if self.server.auth_code:
            self._respond("Authorization received. You can return to the terminal.")
        else:
            self._respond("Authorization failed. You can return to the terminal.")

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _respond(self, message: str) -> None:
        body = f"<html><body><h1>{message}</h1></body></html>".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    args = _parse_args()
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        print("Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET in backend/.env.")
        print("The client secret is required for token exchange, but this script will not print it.")
        raise SystemExit(1)

    redirect_uri = args.redirect_uri
    auth_url = _build_auth_url(settings.google_client_id, redirect_uri)
    print("Google Calendar OAuth Setup")
    print("---------------------------")
    print("Requested scopes:")
    for scope in SCOPES:
        print(f"  - {scope}")
    print(f"\nRedirect URI: {redirect_uri}")
    print("\nConsent URL:")
    print(auth_url)

    code = None if args.manual else _receive_code(auth_url, redirect_uri)
    if not code:
        try:
            code = input("\nPaste authorization code here: ").strip()
        except EOFError:
            print("\nNo authorization code received. Re-run the script in an interactive terminal.")
            raise SystemExit(1)

    if not code:
        print("No authorization code received.")
        raise SystemExit(1)

    token_response = _exchange_code(
        code=code,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_uri=redirect_uri,
    )
    granted_scopes = token_response.get("scope", "").split()
    refresh_token = token_response.get("refresh_token")

    print("\nToken exchange complete.")
    print("Granted scopes:")
    for scope in granted_scopes:
        print(f"  - {scope}")

    if refresh_token:
        print("\nRefresh token:")
        print(refresh_token)
        print("\nPut this value in backend/.env as GOOGLE_REFRESH_TOKEN.")
    else:
        print("\nNo refresh token returned.")
        print("Because this flow uses prompt=consent and access_type=offline, this usually means Google reused prior consent or the OAuth client setup needs attention.")

    missing_scopes = [scope for scope in SCOPES if scope not in granted_scopes]
    if missing_scopes:
        print("\nWARNING: Missing expected scopes:")
        for scope in missing_scopes:
            print(f"  - {scope}")
        print("Calendar event creation will fail until calendar.events is granted.")
    else:
        print("\nAll required Calendar scopes were granted.")


def _build_auth_url(client_id: str, redirect_uri: str) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "false",
        }
    )
    return f"{AUTH_URL}?{query}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Google Calendar OAuth refresh token for this app."
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Do not start the local callback server; print the URL and prompt for a pasted code.",
    )
    parser.add_argument(
        "--redirect-uri",
        default=DEFAULT_REDIRECT_URI,
        choices=[
            "http://localhost",
            "http://localhost:8080/",
            "urn:ietf:wg:oauth:2.0:oob",
        ],
        help=(
            "OAuth redirect URI to use. Default: http://localhost. "
            "Make sure this exact URI is configured on the Google OAuth client."
        ),
    )
    return parser.parse_args()


def _receive_code(auth_url: str, redirect_uri: str) -> str | None:
    parsed_redirect = urlparse(redirect_uri)
    if parsed_redirect.scheme != "http" or parsed_redirect.hostname != "localhost":
        print(f"\nCannot start a local callback server for redirect URI: {redirect_uri}")
        print("Use --manual and paste the authorization code.")
        return None

    port = parsed_redirect.port or 80
    callback_received = Event()
    try:
        server = HTTPServer(("localhost", port), OAuthCallbackHandler)
    except OSError as exc:
        print(f"\nCould not start local callback server on {redirect_uri}: {exc}")
        print("Open the consent URL manually and paste the code if Google shows one.")
        return None

    server.auth_code = None
    server.auth_error = None
    server.callback_received = callback_received

    opened = webbrowser.open(auth_url)
    if opened:
        print(f"\nOpened browser. Waiting for Google callback on {redirect_uri} ...")
    else:
        print("\nCould not open browser automatically. Open the URL above manually.")

    try:
        while not callback_received.is_set():
            server.handle_request()
    finally:
        server.server_close()

    if server.auth_error:
        print(f"Google returned an auth error: {server.auth_error}")
        return None

    return server.auth_code


def _exchange_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict:
    response = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if response.status_code >= 400:
        print("\nToken exchange failed.")
        print(f"HTTP status: {response.status_code}")
        print(response.text)
        raise SystemExit(1)
    return response.json()


def _first(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]


if __name__ == "__main__":
    main()
