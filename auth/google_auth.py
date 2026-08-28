import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def get_credentials():
    """Return valid Google API credentials, creating and caching them on first use."""
    if TOKEN_FILE.exists():
        try:
            with TOKEN_FILE.open("r", encoding="utf-8") as handle:
                token_data = json.load(handle)

            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            if creds and creds.valid:
                return creds

            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with TOKEN_FILE.open("w", encoding="utf-8") as handle:
                    handle.write(creds.to_json())
                return creds
        except Exception as e:
            print(f"Token load failed: {e}, re-authenticating...")

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)

    with TOKEN_FILE.open("w", encoding="utf-8") as handle:
        handle.write(creds.to_json())

    return creds
