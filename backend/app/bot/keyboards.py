"""Reusable inline keyboards for bot handlers."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import MealType
from app.repositories.meal_repo import MealItemPayload

_MEAL_LABELS: dict[MealType, str] = {
    MealType.BREAKFAST: "🍳 Завтрак",
    MealType.LUNCH: "🥗 Обед",
    MealType.DINNER: "🍽 Ужин",
    MealType.SNACK: "🍪 Перекус",
}


def _format_quick_add_label(item: MealItemPayload) -> str:
    """Compact label for a quick-add button: '+ Гречка 150г'."""
    name = item.food_name
    if len(name) > 22:
        name = name[:21] + "…"
    return f"+ {name} {item.amount:g}{item.unit.value}"


def build_meal_type_keyboard(
    draft_id: str,
    *,
    with_recipe_option: bool = False,
    quick_add_pool: list[MealItemPayload] | None = None,
) -> InlineKeyboardMarkup:
    """Inline keyboard asking which meal type to log this draft under.

    Optional `quick_add_pool` — list of MealItemPayload (from the user's recent
    history). Up to the first 4 entries are rendered above the meal-type buttons
    as `qadd:<draft_id>:<idx>` callbacks; tapping appends that item to the draft
    (the meal-type buttons stay live for the final save).

    When `with_recipe_option=True` (photo input) an extra row is shown that
    starts the recipe-builder flow instead of logging the draft as a meal.
    """
    rows: list[list[InlineKeyboardButton]] = []

    # Quick-add rows — one button per row so long Russian names fit on phones.
    if quick_add_pool:
        for idx, item in enumerate(quick_add_pool[:4]):
            rows.append(
                [
                    InlineKeyboardButton(
                        _format_quick_add_label(item),
                        callback_data=f"qadd:{draft_id}:{idx}",
                    )
                ]
            )

    rows.extend(
        [
            [
                InlineKeyboardButton(
                    _MEAL_LABELS[MealType.BREAKFAST],
                    callback_data=f"save:{draft_id}:breakfast",
                ),
                InlineKeyboardButton(
                    _MEAL_LABELS[MealType.LUNCH],
                    callback_data=f"save:{draft_id}:lunch",
                ),
            ],
            [
                InlineKeyboardButton(
                    _MEAL_LABELS[MealType.DINNER],
                    callback_data=f"save:{draft_id}:dinner",
                ),
                InlineKeyboardButton(
                    _MEAL_LABELS[MealType.SNACK],
                    callback_data=f"save:{draft_id}:snack",
                ),
            ],
        ]
    )

    if with_recipe_option:
        rows.append(
            [
                InlineKeyboardButton(
                    "🍳 Сохранить как рецепт", callback_data=f"recipe:start:{draft_id}"
                )
            ]
        )
    rows.append([InlineKeyboardButton("✖️ Отмена", callback_data=f"cancel:{draft_id}")])
    return InlineKeyboardMarkup(rows)


def build_disambiguation_keyboard(
    token: str, candidates: list[dict]
) -> InlineKeyboardMarkup:
    """Inline keyboard asking the user to pick one of the top-k Qdrant hits.

    Each button fires `disambig:<token>:<idx>` so the handler can retrieve the
    full candidate from the stash by index without hitting 64-byte callback limit.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for idx, c in enumerate(candidates):
        name = c.get("name") or ""
        brand = c.get("brand") or ""
        kcal = c.get("kcal") or 0.0
        label = f"{name} {brand}".strip()
        if len(label) > 24:
            label = label[:23] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{label} — {kcal:.0f} ккал/100г",
                    callback_data=f"disambig:{token}:{idx}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("✖️ Отмена", callback_data=f"dcancel:{token}")])
    return InlineKeyboardMarkup(rows)


def build_recipe_collecting_keyboard() -> InlineKeyboardMarkup:
    """Keyboard shown during the COLLECTING stage of the recipe builder."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Готово — посчитать", callback_data="recipe:done"
                )
            ],
            [InlineKeyboardButton("✖️ Отменить рецепт", callback_data="recipe:cancel")],
        ]
    )


def build_recipe_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✖️ Отменить рецепт", callback_data="recipe:cancel")]]
    )


def build_recipe_post_save_keyboard() -> InlineKeyboardMarkup:
    """Shown after the recipe is persisted — let the user decide whether to
    also log a portion as a meal right now, or just keep the recipe."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📝 Записать сколько съел", callback_data="recipe:log_portion"
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ Готово, без записи в дневник",
                    callback_data="recipe:done_no_meal",
                )
            ],
        ]
    )
