from telegram import User as TgUser
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityLevel, Goal, Sex, User
from app.services.nutrition_targets import compute_daily_targets


async def get_user_by_tg_id(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(
        select(User).where(User.telegram_id == telegram_id)
    )


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
) -> User:
    """Persist onboarding profile and recompute daily targets."""
    targets = compute_daily_targets(sex, weight_kg, height_cm, age, activity, goal)

    user.sex = sex
    user.weight_kg = weight_kg
    user.height_cm = height_cm
    user.age = age
    user.activity = activity
    user.goal = goal
    user.tdee_kcal = targets.tdee_kcal
    user.target_protein_g = targets.protein_g
    user.target_fat_g = targets.fat_g
    user.target_carbs_g = targets.carbs_g

    await session.commit()
    await session.refresh(user)
    return user
