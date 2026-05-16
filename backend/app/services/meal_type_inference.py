"""F11 — Smart meal type inference by time of day."""

from datetime import datetime, time, timezone

from app.db.models import MealType


def infer_meal_type_by_clock(now: datetime | None = None) -> MealType:
    """Map current hour to a sensible default meal_type.

    breakfast: 06:00–10:59
    lunch:     11:00–15:59
    dinner:    16:00–21:59
    snack:     everything else (late night / very early morning)
    """
    now = now or datetime.now(timezone.utc)
    t = now.time()
    if time(6, 0) <= t < time(11, 0):
        return MealType.BREAKFAST
    if time(11, 0) <= t < time(16, 0):
        return MealType.LUNCH
    if time(16, 0) <= t < time(22, 0):
        return MealType.DINNER
    return MealType.SNACK
