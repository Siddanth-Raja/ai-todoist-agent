from http.server import BaseHTTPRequestHandler, HTTPServer
import argparse
from pathlib import Path
import sys
from threading import Event
from urllib.parse import parse_qs, urlencode, urlparse
import webbrowser

from google_auth_oauthlib.flow import InstalledAppFlow
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
ENV_PATH = BACKEND_DIR / ".env"


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

    if args.desktop:
        _run_desktop_flow(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            write_env=args.write_env,
        )
        return

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
    _print_token_result(
        granted_scopes=token_response.get("scope", "").split(),
        refresh_token=token_response.get("refresh_token"),
        client_id=settings.google_client_id,
        write_env=args.write_env,
    )


def _run_desktop_flow(client_id: str, client_secret: str, write_env: bool) -> None:
    print("Google Calendar OAuth Setup")
    print("---------------------------")
    print("Mode: desktop InstalledAppFlow")
    print(f"Client ID prefix used for token generation: {_prefix(client_id)}")
    print("Requested scopes:")
    for scope in SCOPES:
        print(f"  - {scope}")
    print("Redirect URI: generated local loopback URI on a random available port")

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
        scopes=SCOPES,
    )
    credentials = flow.run_local_server(
        port=0,
        prompt="consent",
        access_type="offline",
        include_granted_scopes="false",
    )
    _print_token_result(
        granted_scopes=_credential_scopes(credentials),
        refresh_token=credentials.refresh_token,
        client_id=client_id,
        write_env=write_env,
    )


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
        "--desktop",
        action="store_true",
        help="Use google-auth-oauthlib InstalledAppFlow for a Desktop OAuth client.",
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
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="Write the generated refresh token into backend/.env as GOOGLE_REFRESH_TOKEN.",
    )
    return parser.parse_args()


def _print_token_result(
    granted_scopes: list[str],
    refresh_token: str | None,
    client_id: str,
    write_env: bool,
) -> None:
    print("\nToken exchange complete.")
    print(f"Client ID prefix used for token generation: {_prefix(client_id)}")
    print("Granted scopes:")
    for scope in granted_scopes:
        print(f"  - {scope}")

    if refresh_token:
        print("\nRefresh token:")
        print(refresh_token)
        print("\nPut this value in backend/.env as GOOGLE_REFRESH_TOKEN.")
        if write_env:
            _write_refresh_token_to_env(refresh_token)
            loaded = _load_env_values()
            print("\nUpdated backend/.env.")
            print(
                "Client ID prefix loaded by debug_google_auth: "
                f"{_prefix(loaded.get('GOOGLE_CLIENT_ID'))}"
            )
            print(
                "Refresh token prefix loaded from .env: "
                f"{_prefix(loaded.get('GOOGLE_REFRESH_TOKEN'))}"
            )
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


def _credential_scopes(credentials) -> list[str]:
    scopes = credentials.scopes or getattr(credentials, "_scopes", None) or []
    return [str(scope) for scope in scopes]


def _write_refresh_token_to_env(refresh_token: str) -> None:
    lines: list[str] = []
    token_written = False

    if ENV_PATH.exists():
        lines = ENV_PATH.read_text().splitlines()

    updated_lines: list[str] = []
    for line in lines:
        if line.startswith("GOOGLE_REFRESH_TOKEN="):
            updated_lines.append(f"GOOGLE_REFRESH_TOKEN={refresh_token}")
            token_written = True
        else:
            updated_lines.append(line)

    if not token_written:
        if updated_lines and updated_lines[-1].strip():
            updated_lines.append("")
        updated_lines.append(f"GOOGLE_REFRESH_TOKEN={refresh_token}")

    ENV_PATH.write_text("\n".join(updated_lines) + "\n")


def _load_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values

    for line in ENV_PATH.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value.strip().strip('"').strip("'")
    return values


def _prefix(value: str | None, length: int = 8) -> str:
    if not value:
        return "(missing)"
    return f"{value[:length]}..."


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
