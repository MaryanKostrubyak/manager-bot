from __future__ import annotations

from datetime import datetime, timedelta


def start_of_day(moment: datetime | None = None) -> datetime:
    moment = moment or datetime.utcnow()
    return datetime(moment.year, moment.month, moment.day)


def start_of_week(moment: datetime | None = None) -> datetime:
    moment = moment or datetime.utcnow()
    start = start_of_day(moment)
    return start - timedelta(days=start.weekday())


def start_of_month(moment: datetime | None = None) -> datetime:
    moment = moment or datetime.utcnow()
    return datetime(moment.year, moment.month, 1)