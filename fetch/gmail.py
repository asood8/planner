from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from googleapiclient.discovery import build

from auth.google_auth import get_credentials


def _parse_received(date_header, internal_date_ms):
    """Parse the Date header leniently; fall back to Gmail's internalDate (epoch ms)."""
    if date_header:
        try:
            received_dt = parsedate_to_datetime(date_header)
            if received_dt.tzinfo is None:
                received_dt = received_dt.replace(tzinfo=timezone.utc)
            return received_dt
        except (TypeError, ValueError, IndexError):
            pass
    if internal_date_ms:
        try:
            return datetime.fromtimestamp(int(internal_date_ms) / 1000, tz=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            pass
    return None


def get_unread_emails(creds=None, max_results=20):
    """Return unread Gmail messages as lightweight email dictionaries."""
    if creds is None:
        creds = get_credentials()

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    results = (
        service.users()
        .messages()
        .list(userId="me", q="is:unread", maxResults=max_results)
        .execute()
    )

    messages = []
    for msg in results.get("messages", []):
        msg_data = (
            service.users()
            .messages()
            .get(userId="me", id=msg["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"])
            .execute()
        )

        headers = {header["name"]: header["value"] for header in msg_data.get("payload", {}).get("headers", [])}
        received_dt = _parse_received(headers.get("Date", ""), msg_data.get("internalDate"))

        messages.append(
            {
                "id": msg_data.get("id"),
                "sender": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": received_dt,
                "snippet": msg_data.get("snippet", ""),
            }
        )

    return sorted(messages, key=lambda item: item["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
