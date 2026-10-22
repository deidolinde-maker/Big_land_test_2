from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import json
import os
import re
import uuid


def event_file() -> Path:
    return Path(os.getenv("TELEGRAM_ALERT_EVENTS_FILE", "telegram_alert_events.jsonl"))


def normalize_host(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "unknown-site"
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or raw.split("/", 1)[0]).strip(".").lower()
    return host or "unknown-site"


def root_domain(value: str) -> str:
    host = normalize_host(value)
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    return ".".join(parts[-2:])


def canonical_details(value: str) -> str:
    text = " ".join((value or "").split()).strip()
    text = re.sub(r"https?://[^\s|]+", "<URL>", text, flags=re.IGNORECASE)
    return text[:900]


def queue_alert_event(
    *,
    alert_type: str,
    site_label: str,
    page_url: str,
    step_name: str,
    error_text: str,
    details: str,
) -> None:
    site_host = normalize_host(site_label or page_url)
    domain = root_domain(site_host)
    event = {
        "id": uuid.uuid4().hex,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "alert_type": alert_type,
        "site": site_host,
        "domain": domain,
        "page_url": page_url or site_label,
        "step": step_name,
        "error": error_text,
        "details": details,
        "canonical_details": canonical_details(details),
        "group_key": "||".join(
            [domain, alert_type, step_name, error_text, canonical_details(details)]
        ),
    }
    path = event_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"[ALERT-QUEUE] Failed to persist alert event: {exc}")
