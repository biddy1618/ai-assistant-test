"""
Google OAuth2 setup script.

Run this once to authenticate and generate config/token.json.
After that, the Gmail connector will reuse the token automatically.

Usage:
    python3 auth_google.py
"""

from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

CREDENTIALS_FILE = Path("config/credentials.json")
TOKEN_FILE = Path("config/token.json")


def get_credentials() -> Credentials:
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            print("Token refreshed.")
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
            print("Auth complete.")

        TOKEN_FILE.write_text(creds.to_json())
        print(f"Token saved to {TOKEN_FILE}")

    return creds


def test_gmail(creds: Credentials) -> None:
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    print(f"\nGmail connected: {profile['emailAddress']}")
    print(f"Total messages: {profile['messagesTotal']}")


def test_calendar(creds: Credentials) -> None:
    service = build("calendar", "v3", credentials=creds)
    result = service.events().list(calendarId="primary", maxResults=1).execute()
    print(f"Calendar connected: found {result.get('summary', 'primary')} calendar")


if __name__ == "__main__":
    if not CREDENTIALS_FILE.exists():
        print(f"ERROR: {CREDENTIALS_FILE} not found. Download it from Google Cloud Console.")
        raise SystemExit(1)

    creds = get_credentials()
    test_gmail(creds)
    test_calendar(creds)
    print("\nAll good! You can now run the Gmail connector.")
