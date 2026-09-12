from datetime import datetime, timezone

from googleapiclient.discovery import build

from auth.google_auth import get_credentials


def _list_all(request_fn, **kwargs):
    """Collect every item from a paginated Google Tasks list call."""
    items = []
    page_token = None
    while True:
        result = request_fn(maxResults=100, pageToken=page_token, **kwargs).execute()
        items.extend(result.get("items", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            return items


def get_tasks(creds=None, include_completed=False):
    """Return incomplete Google Tasks grouped by overdue, due, and no-due-date buckets."""
    if creds is None:
        creds = get_credentials()

    service = build("tasks", "v1", credentials=creds)

    task_lists = _list_all(service.tasklists().list)
    grouped_tasks = {"overdue": [], "has_due_date": [], "no_due_date": []}

    for task_list in task_lists:
        list_id = task_list.get("id")
        list_title = task_list.get("title", "Untitled list")

        tasks_result = _list_all(service.tasks().list, tasklist=list_id)
        for item in tasks_result:
            if item.get("status") == "completed" and not include_completed:
                continue

            due_value = item.get("due")
            due_dt = None
            if due_value:
                try:
                    due_dt = datetime.fromisoformat(due_value.replace("Z", "+00:00"))
                except ValueError:
                    due_dt = None

            task = {
                "title": item.get("title") or "Untitled task",
                "notes": item.get("notes", ""),
                "due": due_dt,
                "list": list_title,
                "parent": item.get("parent"),
                "completed": item.get("status") == "completed",
            }

            if due_dt is None:
                grouped_tasks["no_due_date"].append(task)
            else:
                if due_dt.astimezone(timezone.utc) < datetime.now(timezone.utc):
                    grouped_tasks["overdue"].append(task)
                else:
                    grouped_tasks["has_due_date"].append(task)

    for bucket in grouped_tasks:
        grouped_tasks[bucket].sort(key=lambda item: item["due"] or datetime.max.replace(tzinfo=timezone.utc))

    return grouped_tasks
