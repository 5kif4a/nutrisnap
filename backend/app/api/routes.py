"""Mini App REST API — profile + daily diary.

All endpoints require a valid `X-Init-Data` header (see deps.get_current_user).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import (
    DayResponse,
    DayTotals,
    MacroTargets,
    MealItemOut,
    MealOut,
    ProfileUpdate,
    UserProfile,
)
from app.db.models import User
from app.db.session import get_session
from app.repositories.meal_repo import fetch_daily_summary, fetch_meals_for_day
from app.repositories.user_repo import save_user_profile

router = APIRouter(prefix="/api", tags=["miniapp"])


def _to_profile(user: User) -> UserProfile:
    return UserProfile(
        telegram_id=user.telegram_id,
        first_name=user.first_name,
        username=user.username,
        is_onboarded=user.is_onboarded,
        sex=user.sex,
        weight_kg=user.weight_kg,
        height_cm=user.height_cm,
        age=user.age,
        activity=user.activity,
        goal=user.goal,
        targets=MacroTargets(
            kcal=user.tdee_kcal,
            protein_g=user.target_protein_g,
            fat_g=user.target_fat_g,
            carbs_g=user.target_carbs_g,
        ),
    )


@router.get("/me", response_model=UserProfile)
async def get_me(user: User = Depends(get_current_user)) -> UserProfile:
    return _to_profile(user)


@router.put("/me", response_model=UserProfile)
async def update_me(
    payload: ProfileUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserProfile:
    user = await save_user_profile(
        session,
        user,
        sex=payload.sex,
        weight_kg=payload.weight_kg,
        height_cm=payload.height_cm,
        age=payload.age,
        activity=payload.activity,
        goal=payload.goal,
    )
    return _to_profile(user)


@router.get("/day", response_model=DayResponse)
async def get_day(
    date_str: str = Query(
        default="",
        alias="date",
        description="Day to fetch in YYYY-MM-DD (UTC). Defaults to today.",
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DayResponse:
    if date_str:
        try:
            day = date.fromisoformat(date_str)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date must be YYYY-MM-DD",
            ) from exc
    else:
        day = date.today()

    summary = await fetch_daily_summary(session, user, day)
    meals = await fetch_meals_for_day(session, user, day)

    meals_out: list[MealOut] = []
    for meal in meals:
        meals_out.append(
            MealOut(
                id=meal.id,
                meal_type=meal.meal_type,
                eaten_at=meal.eaten_at,
                kcal=sum(i.kcal for i in meal.items),
                protein_g=sum(i.protein_g for i in meal.items),
                fat_g=sum(i.fat_g for i in meal.items),
                carbs_g=sum(i.carbs_g for i in meal.items),
                items=[MealItemOut.model_validate(i) for i in meal.items],
            )
        )

    return DayResponse(
        date=day.isoformat(),
        totals=DayTotals(
            kcal=summary.total_kcal,
            protein_g=summary.total_protein_g,
            fat_g=summary.total_fat_g,
            carbs_g=summary.total_carbs_g,
        ),
        targets=MacroTargets(
            kcal=summary.target_kcal,
            protein_g=summary.target_protein_g,
            fat_g=summary.target_fat_g,
            carbs_g=summary.target_carbs_g,
        ),
        meals=meals_out,
    )
