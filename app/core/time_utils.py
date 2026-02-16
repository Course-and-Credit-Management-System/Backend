from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings


def get_app_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.APP_TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def now_in_app_timezone() -> datetime:
    return datetime.now(get_app_timezone())


def normalize_to_app_timezone(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    tz = get_app_timezone()
    if dt.tzinfo is None:
        # MongoDB commonly returns naive UTC datetimes; treat naive as UTC.
        return dt.replace(tzinfo=timezone.utc).astimezone(tz)
    return dt.astimezone(tz)
