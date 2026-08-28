import re
from datetime import date, datetime, time, timedelta, timezone

pattern = re.compile(
    r"^\s*"
    r"(?:\[?(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\]?\s+)?"
    r"(?:\[?(?P<start_h>\d{1,2}):(?P<start_m>\d{2})\s*(?P<start_ampm>[Aa][Mm]|[Pp][Mm])\]?)"
    r"\s*(?:-|–|to|—)\s*"
    r"(?:\[?(?P<end_h>\d{1,2}):(?P<end_m>\d{2})\s*(?P<end_ampm>[Aa][Mm]|[Pp][Mm])\]?)?"
    r"\s*(?P<title>.+?)\s*$"
)

test_lines = [
    "[2023-04-05] [02:00 PM] - Gym",
    "[2026-08-16] [02:00 PM] - Gym",
    "[2026-08-16] [02:00 PM] - [03:00 PM] Gym",
]

for test_line in test_lines:
    match = pattern.match(test_line)
    if match:
        print(f"✓ MATCH: {test_line}")
        print(f"  Title: '{match.group('title')}'")
    else:
        print(f"✗ NO MATCH: {test_line}")
