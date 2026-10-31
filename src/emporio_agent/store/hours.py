"""Opening hours in Campo Grande local time (holidays are not modelled)."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

STORE_TIMEZONE = ZoneInfo("America/Campo_Grande")
WEEKDAY_NAMES = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
_WEEKDAY_HOURS = (time(9), time(18))
OPENING_HOURS: dict[int, tuple[time, time]] = {
    0: _WEEKDAY_HOURS,
    1: _WEEKDAY_HOURS,
    2: _WEEKDAY_HOURS,
    3: _WEEKDAY_HOURS,
    4: _WEEKDAY_HOURS,
    5: (time(9), time(13)),
}


@dataclass(frozen=True, slots=True)
class StoreStatus:
    now: datetime
    is_open: bool
    closes_at: datetime | None
    next_opening: datetime | None


def store_status(now: datetime) -> StoreStatus:
    if now.tzinfo is None:
        raise ValueError("store_status requires a timezone-aware datetime")
    local_now = now.astimezone(STORE_TIMEZONE)
    closes_at = _closing_time_if_open(local_now)
    return StoreStatus(
        now=local_now,
        is_open=closes_at is not None,
        closes_at=closes_at,
        next_opening=None if closes_at else _next_opening(local_now),
    )


def _closing_time_if_open(local_now: datetime) -> datetime | None:
    hours = OPENING_HOURS.get(local_now.weekday())
    if hours is None:
        return None
    opens, closes = (_at(local_now.date(), moment) for moment in hours)
    return closes if opens <= local_now < closes else None


def _next_opening(local_now: datetime) -> datetime:
    for offset in range(8):
        day = local_now.date() + timedelta(days=offset)
        hours = OPENING_HOURS.get(day.weekday())
        if hours and (opening := _at(day, hours[0])) > local_now:
            return opening
    raise AssertionError("the weekly schedule has no opening day")


def _at(day: date, moment: time) -> datetime:
    return datetime.combine(day, moment, tzinfo=STORE_TIMEZONE)
