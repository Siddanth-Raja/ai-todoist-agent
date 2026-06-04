from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.calendar_tools import check_google_auth  # noqa: E402
from app.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    diagnostics = check_google_auth(settings)

    print("Google Calendar Auth Diagnostics")
    print("--------------------------------")
    print(f"Calendar ID: {diagnostics['calendar_id']}")
    print("Scopes:")
    print(f"  Read: {', '.join(diagnostics['configured_scopes']['read'])}")
    print(f"  Write: {', '.join(diagnostics['configured_scopes']['write'])}")
    print(f"Refresh token present: {_yes_no(diagnostics['refresh_token_present'])}")
    print(f"Token refresh succeeds: {_yes_no(diagnostics['token_refresh_succeeds'])}")
    print(f"Calendar read succeeds: {_yes_no(diagnostics['calendar_read_succeeds'])}")
    print(f"First calendar name: {diagnostics['first_calendar_name'] or '(not available)'}")
    print(
        "Calendar write scope present: "
        f"{_yes_no(diagnostics['calendar_write_scope_present'])}"
    )
    print(f"Write permission status: {diagnostics['write_permission_status']}")

    granted_scopes = diagnostics.get("granted_scopes") or []
    if granted_scopes:
        print("Granted/credential scopes:")
        for scope in granted_scopes:
            print(f"  - {scope}")

    if diagnostics["errors"]:
        print("\nErrors:")
        for error in diagnostics["errors"]:
            print(f"- [{error.get('source', 'google')}] {error.get('type')}: {error.get('message')}")
            if error.get("explanation"):
                print(f"  Explanation: {error['explanation']}")
    else:
        print("\nNo Google auth errors detected.")


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


if __name__ == "__main__":
    main()
