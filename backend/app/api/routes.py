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
    QuickAddFoodOut,
    QuickAddRequest,
    RecommendationItemOut,
    RecommendationResponse,
    RecommendRequest,
    UserProfile,
)
from app.graph.recommender import get_recommender_graph
from app.db.models import Food, FoodMetric, InputSource, Meal, MealType, User
from app.db.session import get_session
from app.repositories.food_repo import (
    list_frequent_foods_per_meal_type,
    list_recent_foods_per_meal_type,
    search_foods_by_name,
)
from app.repositories.meal_repo import (
    MealItemPayload,
    delete_meal,
    fetch_daily_summary,
    fetch_meals_for_day,
    fetch_month_day_totals,
    log_meal_with_items,
)
from app.repositories.user_repo import save_user_profile
from app.services.meal_type_inference import infer_meal_type_by_clock

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
        target_weight_kg=user.target_weight_kg,
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
        target_weight_kg=payload.target_weight_kg,
        manual_targets=payload.manual_targets,
        target_kcal=payload.target_kcal,
        target_protein_g=payload.target_protein_g,
        target_fat_g=payload.target_fat_g,
        target_carbs_g=payload.target_carbs_g,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="meal not found"
        )
    if meal.user_id != user.id:
        # 404 instead of 403 — don't reveal that the id exists for another user.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="meal not found"
        )
    await delete_meal(session, meal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/foods/recent", response_model=list[QuickAddFoodOut])
async def get_recent_foods(
    meal_type: MealType | None = Query(
        default=None,
        description="Filter by meal_type. Defaults to time-of-day inference.",
    ),
    limit: int = Query(default=10, ge=1, le=30),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[QuickAddFoodOut]:
    """Last distinct foods the user logged for this meal_type."""
    mt = meal_type or infer_meal_type_by_clock()
    rows = await list_recent_foods_per_meal_type(session, user, mt, limit=limit)
    return [QuickAddFoodOut(**row.__dict__) for row in rows]


@router.get("/foods/frequent", response_model=list[QuickAddFoodOut])
async def get_frequent_foods(
    meal_type: MealType | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=180),
    limit: int = Query(default=10, ge=1, le=30),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[QuickAddFoodOut]:
    """Most-eaten foods in this meal_type over the last `days` days."""
    mt = meal_type or infer_meal_type_by_clock()
    rows = await list_frequent_foods_per_meal_type(
        session, user, mt, limit=limit, days_back=days
    )
    return [QuickAddFoodOut(**row.__dict__) for row in rows]


@router.get("/foods/search", response_model=list[QuickAddFoodOut])
async def search_foods(
    q: str = Query(..., min_length=1, max_length=100, description="Free-text query"),
    limit: int = Query(default=20, ge=1, le=50),
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[QuickAddFoodOut]:
    """Catalog search by name / brand / aliases. Returns rows with a sensible
    default portion (100g/100ml/1 piece/1 serving) so the client can render
    a single 'tap to add' button per result without a separate portion picker."""
    rows = await search_foods_by_name(session, q, limit=limit)
    return [_food_to_quick_add(f) for f in rows]


def _food_to_quick_add(food: Food) -> QuickAddFoodOut:
    """Convert a catalog Food → QuickAddFoodOut with a default portion.

    `Food` stores nutrition per 100g (or 100ml / 1 piece / 1 serving). We
    materialize a 'starter' portion the user can log with one tap.
    """
    if food.metric == FoodMetric.GRAMS:
        amount = 100.0
        weight_g = 100.0
        factor = 1.0
    elif food.metric == FoodMetric.MILLILITERS:
        amount = 100.0
        weight_g = 100.0  # treat ml ≈ g for daily-total accounting
        factor = 1.0
    elif food.metric == FoodMetric.PIECE:
        amount = 1.0
        weight_g = food.piece_weight_g or 0.0
        factor = 1.0
    else:  # SERVING
        amount = 1.0
        weight_g = food.piece_weight_g or 0.0
        factor = 1.0

    return QuickAddFoodOut(
        food_name=food.name,
        food_id=food.id,
        amount=amount,
        unit=food.metric,
        weight_g=weight_g,
        kcal=food.kcal * factor,
        protein_g=food.protein_g * factor,
        fat_g=food.fat_g * factor,
        carbs_g=food.carbs_g * factor,
        frequency=0,
    )


@router.post(
    "/meals/quick-add",
    response_model=MealOut,
    status_code=status.HTTP_201_CREATED,
)
async def quick_add_meal(
    payload: QuickAddRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MealOut:
    """One-tap logging from the 'My Foods' tab — creates a single-item Meal."""
    item = MealItemPayload(
        food_name=payload.food_name,
        amount=payload.amount,
        unit=payload.unit,
        weight_g=payload.weight_g,
        kcal=payload.kcal,
        protein_g=payload.protein_g,
        fat_g=payload.fat_g,
        carbs_g=payload.carbs_g,
        food_id=payload.food_id,
    )
    meal = await log_meal_with_items(
        session,
        user=user,
        meal_type=payload.meal_type,
        items=[item],
        eaten_at=payload.eaten_at,
        source=InputSource.QUICK_ADD,
    )
    return MealOut(
        id=meal.id,
        meal_type=meal.meal_type,
        eaten_at=meal.eaten_at,
        kcal=sum(it.kcal for it in meal.items),
        protein_g=sum(it.protein_g for it in meal.items),
        fat_g=sum(it.fat_g for it in meal.items),
        carbs_g=sum(it.carbs_g for it in meal.items),
        items=[MealItemOut.model_validate(it) for it in meal.items],
    )


@router.post("/recommendations", response_model=RecommendationResponse)
async def post_recommendations(
    payload: RecommendRequest | None = None,
    user: User = Depends(get_current_user),
) -> RecommendationResponse:
    """Run the RAG recommender for the current user. Returns 3 picks + summary."""
    state = {
        "telegram_user_id": user.telegram_id,
        "intent": "freeform" if (payload and payload.query) else "deficit",
        "freeform_query": payload.query if payload else "",
    }
    graph = get_recommender_graph()
    result = await graph.ainvoke(state)
    if result.get("error"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=result["error"],
        )
    items = result.get("recommendations") or []
    return RecommendationResponse(
        summary=result.get("summary", ""),
        items=[
            RecommendationItemOut(
                food_id=it.food_id,
                name=it.name,
                brand=it.brand,
                suggested_grams=it.suggested_grams,
                kcal=it.kcal,
                protein_g=it.protein_g,
                fat_g=it.fat_g,
                carbs_g=it.carbs_g,
                rationale_short=it.rationale_short,
            )
            for it in items
        ],
    )


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
