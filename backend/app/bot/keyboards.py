"""Reusable inline keyboards for bot handlers."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import MealType

_MEAL_LABELS: dict[MealType, str] = {
    MealType.BREAKFAST: "🍳 Завтрак",
    MealType.LUNCH: "🥗 Обед",
    MealType.DINNER: "🍽 Ужин",
    MealType.SNACK: "🍪 Перекус",
}


def build_meal_type_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    """4-button inline keyboard asking which meal type to log this draft under."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(_MEAL_LABELS[MealType.BREAKFAST], callback_data=f"save:{draft_id}:breakfast"),
                InlineKeyboardButton(_MEAL_LABELS[MealType.LUNCH], callback_data=f"save:{draft_id}:lunch"),
            ],
            [
                InlineKeyboardButton(_MEAL_LABELS[MealType.DINNER], callback_data=f"save:{draft_id}:dinner"),
                InlineKeyboardButton(_MEAL_LABELS[MealType.SNACK], callback_data=f"save:{draft_id}:snack"),
            ],
            [InlineKeyboardButton("✖️ Отмена", callback_data=f"cancel:{draft_id}")],
        ]
    )
