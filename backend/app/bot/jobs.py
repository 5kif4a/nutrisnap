"""Scheduled bot jobs — daily morning nudge with variety detection.

Uses PTB's built-in JobQueue (apscheduler under the hood) so we don't need a
separate scheduler process. Registered alongside handlers in
`build_telegram_application` and runs in both webhook (prod) and polling (dev)
modes.

Triggers covered here:
  • Phase 4.1 — daily 9:00 (Asia/Almaty) nudge per onboarded user
  • Phase 4.3 — variety alert: when a user's last-7-days diet is too
    monotonous, the morning nudge flips into 'try something different' mode

Phase 4.2 (post-meal follow-up) lives in `handlers/meal.py` because it
hooks into the save callback, not the scheduler.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from telegram.error import Forbidden, TelegramError
from telegram.ext import Application, ContextTypes

from app.db.models import Meal, MealItem, User
from app.db.session import async_session_factory
from app.graph.recommender import get_recommender_graph

logger = logging.getLogger(__name__)

# Hard-coded TZ until we add `users.timezone` — covers the dev user and the
# first wave (KZ). When we ship to other regions move this to a per-user column.
_NUDGE_TZ = ZoneInfo("Asia/Almaty")
_NUDGE_HOUR = 9
_NUDGE_MINUTE = 0

# Variety = distinct(food_name) / total meal_items over the last N days.
# Below this ratio we flip to "try something different" mode.
_VARIETY_WINDOW_DAYS = 7
_VARIETY_MIN_ITEMS = 10  # need enough signal to call a week "monotonous"
_VARIETY_RATIO_THRESHOLD = 0.40


def register_jobs(application: Application) -> None:
    """Wire all scheduled jobs into the PTB Application's JobQueue."""
    if application.job_queue is None:
        logger.warning("Application has no JobQueue — scheduled nudges disabled")
        return
    application.job_queue.run_daily(
        daily_morning_nudge,
        time=time(hour=_NUDGE_HOUR, minute=_NUDGE_MINUTE, tzinfo=_NUDGE_TZ),
        name="daily_morning_nudge",
    )
    logger.info(
        "Daily nudge scheduled at %02d:%02d %s",
        _NUDGE_HOUR,
        _NUDGE_MINUTE,
        _NUDGE_TZ.key,
    )


# ─── Daily morning nudge ──────────────────────────────────────────────────────


async def daily_morning_nudge(context: ContextTypes.DEFAULT_TYPE) -> None:
    """For every onboarded user, send yesterday's summary + a recommendation.

    Variety check: if the user ate the same foods repeatedly in the last
    7 days, flip the recommendation prompt to push variety instead of
    macro-deficit fill-in.
    """
    async with async_session_factory() as session:
        users = list(
            (
                await session.scalars(select(User).where(User.tdee_kcal.is_not(None)))
            ).all()
        )

    if not users:
        return

    graph = get_recommender_graph()
    logger.info("Running daily nudge for %d users", len(users))

    for user in users:
        try:
            variety_ratio = await _compute_variety_ratio(user)
            is_monotonous = (
                variety_ratio is not None and variety_ratio < _VARIETY_RATIO_THRESHOLD
            )
            state = {
                "telegram_user_id": user.telegram_id,
                "intent": "freeform" if is_monotonous else "variety",
                "freeform_query": (
                    "что-то непохожее на то что ел на этой неделе — разнообразь рацион"
                    if is_monotonous
                    else ""
                ),
            }
            result = await graph.ainvoke(state)
            await _send_nudge(context, user, result, monotonous=is_monotonous)
        except Forbidden:
            # User blocked the bot — silent skip, don't spam logs across many runs.
            logger.info("User %s blocked the bot — skipping nudge", user.telegram_id)
        except (TelegramError, RuntimeError):
            logger.exception("Daily nudge failed for user %s", user.telegram_id)


async def _send_nudge(
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    result: dict,
    *,
    monotonous: bool,
) -> None:
    summary = result.get("summary") or ""
    items = result.get("recommendations") or []
    if not items:
        return

    greeting = (
        "🌞 Доброе утро! Замечаю что за неделю ты ел довольно однообразно — "
        "вот пара идей разнообразить день:"
        if monotonous
        else "🌞 Доброе утро! Вот что предлагаю на сегодня:"
    )

    lines = [greeting, ""]
    if summary:
        lines.append(summary)
        lines.append("")
    lines.append("🍽 *Идеи:*")
    for i, it in enumerate(items, 1):
        brand = f" *{it.brand}*" if it.brand else ""
        lines.append(
            f"{i}. {it.name}{brand} — {it.suggested_grams:g} г  ({it.kcal:.0f} ккал)"
        )
        if it.rationale_short:
            lines.append(f"   _{it.rationale_short}_")
    lines.append("")
    lines.append("Можешь записать любую из них — /recommend для другой подборки.")

    await context.bot.send_message(
        chat_id=user.telegram_id,
        text="\n".join(lines),
    )


# ─── Variety detection ────────────────────────────────────────────────────────


async def _compute_variety_ratio(user: User) -> float | None:
    """Distinct food_names ÷ total meal_items over the last 7 days.

    Returns None if there isn't enough data to make a confident call
    (need ≥ _VARIETY_MIN_ITEMS rows). Lower ratio = more monotonous.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=_VARIETY_WINDOW_DAYS)
    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(MealItem.food_name)
                .select_from(MealItem)
                .join(Meal, Meal.id == MealItem.meal_id)
                .where(Meal.user_id == user.id, Meal.eaten_at > cutoff)
            )
        ).all()
    if len(rows) < _VARIETY_MIN_ITEMS:
        return None
    distinct = len({r.lower() for r in rows})
    return distinct / len(rows)
