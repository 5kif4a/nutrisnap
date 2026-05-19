"""Reusable inline keyboards for bot handlers."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import MealType

_MEAL_LABELS: dict[MealType, str] = {
    MealType.BREAKFAST: "🍳 Завтрак",
    MealType.LUNCH: "🥗 Обед",
    MealType.DINNER: "🍽 Ужин",
    MealType.SNACK: "🍪 Перекус",
}


def build_meal_type_keyboard(
    draft_id: str,
    *,
    with_recipe_option: bool = False,
) -> InlineKeyboardMarkup:
    """Inline keyboard asking which meal type to log this draft under.

    When `with_recipe_option=True` (photo input) an extra row is shown that
    starts the recipe-builder flow instead of logging the draft as a meal.
    """
    rows = [
        [
            InlineKeyboardButton(_MEAL_LABELS[MealType.BREAKFAST], callback_data=f"save:{draft_id}:breakfast"),
            InlineKeyboardButton(_MEAL_LABELS[MealType.LUNCH], callback_data=f"save:{draft_id}:lunch"),
        ],
        [
            InlineKeyboardButton(_MEAL_LABELS[MealType.DINNER], callback_data=f"save:{draft_id}:dinner"),
            InlineKeyboardButton(_MEAL_LABELS[MealType.SNACK], callback_data=f"save:{draft_id}:snack"),
        ],
    ]
    if with_recipe_option:
        rows.append(
            [InlineKeyboardButton("🍳 Сохранить как рецепт", callback_data=f"recipe:start:{draft_id}")]
        )
    rows.append([InlineKeyboardButton("✖️ Отмена", callback_data=f"cancel:{draft_id}")])
    return InlineKeyboardMarkup(rows)


def build_recipe_collecting_keyboard() -> InlineKeyboardMarkup:
    """Keyboard shown during the COLLECTING stage of the recipe builder."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Готово — посчитать", callback_data="recipe:done")],
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
            [InlineKeyboardButton("📝 Записать сколько съел", callback_data="recipe:log_portion")],
            [InlineKeyboardButton("✅ Готово, без записи в дневник", callback_data="recipe:done_no_meal")],
        ]
    )
