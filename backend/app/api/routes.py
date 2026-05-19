"""Mini App REST API — profile + daily diary.

All endpoints require a valid `X-Init-Data` header (see deps.get_current_user).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import (
    DayResponse,
    DayStatus,
    DayTotals,
    MacroTargets,
    MealItemOut,
    MealOut,
    MonthDay,
    MonthResponse,
    ProfileUpdate,
    UserProfile,
)
from app.db.models import Meal, User
from app.db.session import get_session
from app.repositories.meal_repo import (
    delete_meal,
    fetch_daily_summary,
    fetch_meals_for_day,
    fetch_month_day_totals,
)
from app.repositories.user_repo import save_user_profile

router = APIRouter(prefix="/api", tags=["miniapp"])

# Day-colour thresholds = consumed kcal / daily target.
GREEN_RATIO = 0.85  # ≥ → в норме
YELLOW_RATIO = 0.50  # ≥ → немного, иначе мало


def _day_status(kcal: float, target_kcal: int | None) -> DayStatus:
    if not target_kcal or kcal <= 0:
        return DayStatus.EMPTY
    ratio = kcal / target_kcal
    if ratio >= GREEN_RATIO:
        return DayStatus.GREEN
    if ratio >= YELLOW_RATIO:
        return DayStatus.YELLOW
    return DayStatus.RED


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


@router.delete("/meal/{meal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meal_route(
    meal_id: UUID = Path(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    meal = await session.get(Meal, meal_id)
    if meal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="meal not found")
    if meal.user_id != user.id:
        # 404 instead of 403 — don't reveal that the id exists for another user.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="meal not found")
    await delete_meal(session, meal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/month", response_model=MonthResponse)
async def get_month(
    month_str: str = Query(
        default="",
        alias="month",
        description="Month to fetch in YYYY-MM (UTC). Defaults to current month.",
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MonthResponse:
    if month_str:
        try:
            year, month = (int(p) for p in month_str.split("-", 1))
            date(year, month, 1)  # validate
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="month must be YYYY-MM",
            ) from exc
    else:
        today = date.today()
        year, month = today.year, today.month

    totals = await fetch_month_day_totals(session, user, year, month)
    target = user.tdee_kcal

    days = [
        MonthDay(
            date=date(year, month, d).isoformat(),
            kcal=totals.get(date(year, month, d), 0.0),
            status=_day_status(totals.get(date(year, month, d), 0.0), target),
        )
        for d in range(1, monthrange(year, month)[1] + 1)
    ]

    return MonthResponse(
        month=f"{year:04d}-{month:02d}",
        target_kcal=target,
        days=days,
    )
