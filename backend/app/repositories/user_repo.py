from telegram import User as TgUser
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityLevel, Goal, Sex, User
from app.services.nutrition_targets import compute_daily_targets


async def get_user_by_tg_id(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def upsert_user_from_telegram(session: AsyncSession, tg: TgUser) -> User:
    """Idempotently create or refresh a user from incoming Telegram data."""
    stmt = (
        pg_insert(User)
        .values(
            telegram_id=tg.id,
            username=tg.username,
            first_name=tg.first_name,
            language_code=tg.language_code,
        )
        .on_conflict_do_update(
            index_elements=["telegram_id"],
            set_={
                "username": tg.username,
                "first_name": tg.first_name,
                "language_code": tg.language_code,
            },
        )
        .returning(User)
    )
    result = await session.scalars(stmt)
    user = result.one()
    await session.commit()
    return user


async def save_user_profile(
    session: AsyncSession,
    user: User,
    *,
    sex: Sex,
    weight_kg: float,
    height_cm: float,
    age: int,
    activity: ActivityLevel,
    goal: Goal,
    target_weight_kg: float | None = None,
    manual_targets: bool = False,
    target_kcal: int | None = None,
    target_protein_g: int | None = None,
    target_fat_g: int | None = None,
    target_carbs_g: int | None = None,
) -> User:
    """Persist onboarding profile and (re)set daily targets.

    `target_weight_kg` is only meaningful for LOSE / GAIN goals. For MAINTAIN
    we ignore whatever is passed and store NULL.

    Daily targets: if `manual_targets=True` and all four target_* values are
    provided, they are stored as-is. Otherwise targets are recomputed from
    sex / weight / height / age / activity / goal via Mifflin-St Jeor.
    """
    user.sex = sex
    user.weight_kg = weight_kg
    user.height_cm = height_cm
    user.age = age
    user.activity = activity
    user.goal = goal
    user.target_weight_kg = target_weight_kg if goal is not Goal.MAINTAIN else None

    manual_complete = manual_targets and all(
        v is not None
        for v in (target_kcal, target_protein_g, target_fat_g, target_carbs_g)
    )
    if manual_complete:
        user.tdee_kcal = target_kcal
        user.target_protein_g = target_protein_g
        user.target_fat_g = target_fat_g
        user.target_carbs_g = target_carbs_g
    else:
        targets = compute_daily_targets(sex, weight_kg, height_cm, age, activity, goal)
        user.tdee_kcal = targets.tdee_kcal
        user.target_protein_g = targets.protein_g
        user.target_fat_g = targets.fat_g
        user.target_carbs_g = targets.carbs_g

    await session.commit()
    await session.refresh(user)
    return user
