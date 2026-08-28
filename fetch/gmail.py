from datetime import datetime, timezone

from googleapiclient.discovery import build

from auth.google_auth import get_credentials


def get_unread_emails(creds=None, max_results=20):
    """Return unread Gmail messages as lightweight email dictionaries."""
    if creds is None:
        creds = get_credentials()

    service = build("gmail", "v1", credentials=creds)

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
        date_value = headers.get("Date", "")
        try:
            received_dt = datetime.strptime(date_value, "%a, %d %b %Y %H:%M:%S %z")
            if received_dt.tzinfo is None:
                received_dt = received_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            received_dt = None

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
