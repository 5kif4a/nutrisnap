"""Scheduled bot jobs — three daily nudges replacing the old morning broadcast.

Triggers:
  • 10:00 Asia/Almaty — morning energizing nudge (no LLM, just motivation)
  • 13:00 Asia/Almaty — lunch check: if no meals logged yet → "go eat" (no rec)
  • 21:00 Asia/Almaty — evening summary: daily totals + AI recommendation
                        also includes variety detection (Phase 4.3)

Phase 4.2 (post-meal follow-up) lives in `handlers/meal.py` because it
hooks into the save callback, not the scheduler.
"""

from __future__ import annotations

import logging
from datetime import date as date_cls
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from telegram.error import Forbidden, TelegramError
from telegram.ext import Application, ContextTypes

from app.db.models import Meal, MealItem, User
from app.db.session import async_session_factory
from app.graph.recommender import get_recommender_graph
from app.repositories.meal_repo import fetch_daily_summary

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Almaty")

# Variety detection — same thresholds as before
_VARIETY_WINDOW_DAYS = 7
_VARIETY_MIN_ITEMS = 10
_VARIETY_RATIO_THRESHOLD = 0.40

_MORNING_MESSAGES = [
    "☀️ Доброе утро! Новый день — новый шанс питаться хорошо. Не забудь записывать еду!",
    "🌅 Доброе утро! Помни: даже маленький завтрак лучше, чем голодный старт.",
    "💪 Привет! Сегодня отличный день чтобы уложиться в норму КБЖУ. Удачи!",
    "🥗 Доброе утро! Записывай всё что ешь — так легче контролировать питание.",
    "🌞 С добрым утром! Стакан воды для начала — и ты уже молодец.",
]


def register_jobs(application: Application) -> None:
    """Wire all scheduled jobs into the PTB Application's JobQueue."""
    if application.job_queue is None:
        logger.warning("Application has no JobQueue — scheduled nudges disabled")
        return

    jobs = [
        ("morning_energizing_nudge", morning_energizing_nudge, 10, 0),
        ("noon_eat_check", noon_eat_check, 13, 0),
        ("evening_summary_nudge", evening_summary_nudge, 21, 0),
    ]
    for name, callback, hour, minute in jobs:
        application.job_queue.run_daily(
            callback,
            time=time(hour=hour, minute=minute, tzinfo=_TZ),
            name=name,
        )
        logger.info("Job '%s' scheduled at %02d:%02d %s", name, hour, minute, _TZ.key)


# ─── Morning energizing nudge (10:00) ─────────────────────────────────────────


async def morning_energizing_nudge(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simple good-morning broadcast — no LLM, no recommendation."""
    import random

    async with async_session_factory() as session:
        users = list(
            (
                await session.scalars(select(User).where(User.tdee_kcal.is_not(None)))
            ).all()
        )

    if not users:
        return

    message = random.choice(_MORNING_MESSAGES)
    logger.info("Running morning energizing nudge for %d users", len(users))

    for user in users:
        try:
            await context.bot.send_message(chat_id=user.telegram_id, text=message)
        except Forbidden:
            logger.info("User %s blocked the bot — skipping", user.telegram_id)
        except TelegramError:
            logger.exception("Morning nudge failed for user %s", user.telegram_id)


# ─── Noon eat check (13:00) ───────────────────────────────────────────────────


async def noon_eat_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """If the user hasn't logged any meals today — remind them to eat. No rec."""
    async with async_session_factory() as session:
        users = list(
            (
                await session.scalars(select(User).where(User.tdee_kcal.is_not(None)))
            ).all()
        )

    if not users:
        return

    today = datetime.now(_TZ).date()
    logger.info("Running noon eat check for %d users", len(users))

    for user in users:
        try:
            meals_today = await _count_meals_today(user, today)
            if meals_today == 0:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        "🍽 Привет! Ты ещё ничего не записал сегодня.\n"
                        "Не забудь покушать и записать — я жду 😊"
                    ),
                )
        except Forbidden:
            logger.info("User %s blocked the bot — skipping", user.telegram_id)
        except TelegramError:
            logger.exception("Noon eat check failed for user %s", user.telegram_id)


# ─── Evening summary nudge (21:00) ────────────────────────────────────────────


async def evening_summary_nudge(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Daily totals + AI recommendation. Variety-aware (Phase 4.3)."""
    async with async_session_factory() as session:
        users = list(
            (
                await session.scalars(select(User).where(User.tdee_kcal.is_not(None)))
            ).all()
        )

    if not users:
        return

    graph = get_recommender_graph()
    today = datetime.now(_TZ).date()
    logger.info("Running evening summary nudge for %d users", len(users))

    for user in users:
        try:
            summary = await _build_daily_summary_text(user, today)
            variety_ratio = await _compute_variety_ratio(user)
            is_monotonous = (
                variety_ratio is not None and variety_ratio < _VARIETY_RATIO_THRESHOLD
            )
            state = {
                "telegram_user_id": user.telegram_id,
                "intent": "variety" if is_monotonous else "deficit",
                "freeform_query": (
                    "что-то непохожее на то что ел на этой неделе — разнообразь рацион"
                    if is_monotonous
                    else ""
                ),
            }
            result = await graph.ainvoke(state)
            await _send_evening_nudge(context, user, summary, result, monotonous=is_monotonous)
        except Forbidden:
            logger.info("User %s blocked the bot — skipping nudge", user.telegram_id)
        except (TelegramError, RuntimeError):
            logger.exception("Evening nudge failed for user %s", user.telegram_id)


async def _send_evening_nudge(
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    daily_summary: str,
    result: dict,
    *,
    monotonous: bool,
) -> None:
    items = result.get("recommendations") or []
    lines = ["🌙 *Итоги дня*", ""]
    if daily_summary:
        lines.append(daily_summary)
        lines.append("")

    if items:
        header = (
            "🔄 *Завтра попробуй что-нибудь новенькое:*"
            if monotonous
            else "💡 *Идеи на завтра:*"
        )
        lines.append(header)
        for i, it in enumerate(items, 1):
            brand = f" *{it.brand}*" if it.brand else ""
            lines.append(
                f"{i}. {it.name}{brand} — {it.suggested_grams:g} г  ({it.kcal:.0f} ккал)"
            )
            if it.rationale_short:
                lines.append(f"   _{it.rationale_short}_")
        lines.append("")
        lines.append("Хорошего вечера! 🌙")
    else:
        lines.append("Хорошего вечера! Завтра продолжаем 💪")

    await context.bot.send_message(
        chat_id=user.telegram_id,
        text="\n".join(lines),
        parse_mode="Markdown",
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _count_meals_today(user: User, today: date_cls) -> int:
    """Count distinct meals logged today (UTC day aligned to Almaty date)."""
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=_TZ).astimezone(
        timezone.utc
    )
    day_end = day_start + timedelta(days=1)
    async with async_session_factory() as session:
        count = await session.scalar(
            select(func.count(Meal.id)).where(
                Meal.user_id == user.id,
                Meal.eaten_at >= day_start,
                Meal.eaten_at < day_end,
            )
        )
    return int(count or 0)


async def _build_daily_summary_text(user: User, today: date_cls) -> str:
    """Return a formatted string with today's KBJU totals and targets."""
    async with async_session_factory() as session:
        summary = await fetch_daily_summary(session, user, today)

    if summary.meals_count == 0:
        return "Сегодня ты не записал ни одного приёма пищи 😕"

    lines = [f"Приёмов пищи: {summary.meals_count}"]
    lines.append(
        f"Калории: {summary.total_kcal:.0f}"
        + (f" / {summary.target_kcal:.0f} ккал" if summary.target_kcal else " ккал")
    )
    if summary.target_protein_g:
        lines.append(
            f"Белки: {summary.total_protein_g:.0f} / {summary.target_protein_g:.0f} г"
        )
    if summary.target_fat_g:
        lines.append(
            f"Жиры: {summary.total_fat_g:.0f} / {summary.target_fat_g:.0f} г"
        )
    if summary.target_carbs_g:
        lines.append(
            f"Углеводы: {summary.total_carbs_g:.0f} / {summary.target_carbs_g:.0f} г"
        )
    return "\n".join(lines)


async def _compute_variety_ratio(user: User) -> float | None:
    """Distinct food_names ÷ total meal_items over the last 7 days."""
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
