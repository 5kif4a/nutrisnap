"""Compute absolute nutrition for a meal item from a Food + user-stated amount/unit."""

from dataclasses import dataclass

from app.db.models import Food, FoodMetric


@dataclass(slots=True)
class NutritionPayload:
    weight_g: float  # canonical equivalent in grams
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float


# Density assumptions for cross-unit conversions when piece_weight_g is missing.
# Values are g per ml. Default is water density 1.0.
_DENSITY_DEFAULT_G_PER_ML = 1.0


def _compute_grams_equivalent(food: Food, amount: float, unit: FoodMetric) -> float:
    """Convert user-stated `amount unit` to grams using Food metadata."""
    unit = _normalize_metric(unit)
    if unit is FoodMetric.GRAMS:
        return amount

    if unit is FoodMetric.MILLILITERS:
        # Without per-food density, assume water-like (good enough for milk, juice, water).
        return amount * _DENSITY_DEFAULT_G_PER_ML

    if unit is FoodMetric.PIECE or unit is FoodMetric.SERVING:
        piece_g = food.piece_weight_g
        if piece_g is None:
            # Unknown piece weight — caller should validate at parse time.
            # Fallback: treat 1 piece as 100g.
            piece_g = 100.0
        return amount * piece_g

    raise ValueError(f"Unsupported unit: {unit}")


def _normalize_metric(value) -> FoodMetric:
    return value if isinstance(value, FoodMetric) else FoodMetric(value)


def compute_meal_item_nutrition(
    food: Food, amount: float, unit: FoodMetric
) -> NutritionPayload:
    """Multiply Food's per-unit nutrition by the user-stated portion.

    Examples:
        food.metric = g, kcal=165 per 100g; amount=200, unit=g
            → 200/100 × 165 = 330 kcal, weight_g=200
        food.metric = piece, kcal=70 per 1 piece, piece_weight_g=50; amount=2, unit=piece
            → 2 × 70 = 140 kcal, weight_g=100
        food.metric = piece (egg), kcal=70 per 1, piece_weight_g=50; amount=200, unit=g
            → cross-convert: 200g / 50g per piece = 4 pieces → 4 × 70 = 280 kcal
    """
    # SQLAlchemy String columns return plain str — normalize back to enum.
    food_metric = _normalize_metric(food.metric)
    unit = _normalize_metric(unit)

    # Multiplier in terms of food's primary metric units
    if food_metric is FoodMetric.GRAMS:
        if unit is FoodMetric.GRAMS:
            multiplier = amount / 100.0
        elif unit is FoodMetric.MILLILITERS:
            # treat ml as g (density 1) — fine for water-like products
            multiplier = amount / 100.0
        else:
            raise ValueError(
                f"Cannot record {unit} of a weight-based food '{food.name}' without piece_weight_g"
            )
    elif food_metric is FoodMetric.MILLILITERS:
        if unit is FoodMetric.MILLILITERS:
            multiplier = amount / 100.0
        elif unit is FoodMetric.GRAMS:
            # grams ÷ density = ml (assume 1 g/ml)
            multiplier = amount / 100.0
        else:
            raise ValueError(
                f"Cannot record {unit} of a volume-based food '{food.name}'"
            )
    else:  # PIECE or SERVING — primary is 1 unit
        if unit is food_metric:
            multiplier = amount
        elif unit in (FoodMetric.PIECE, FoodMetric.SERVING) and food_metric in (
            FoodMetric.PIECE,
            FoodMetric.SERVING,
        ):
            # piece ↔ serving are interchangeable for single countable units.
            multiplier = amount
        elif unit is FoodMetric.GRAMS and food.piece_weight_g:
            # User said "200g of eggs" → convert to pieces equivalent
            multiplier = amount / food.piece_weight_g
        else:
            raise ValueError(
                f"Cannot record {unit} of a {food_metric.value}-based food '{food.name}'"
            )

    return NutritionPayload(
        weight_g=_compute_grams_equivalent(food, amount, unit),
        kcal=multiplier * food.kcal,
        protein_g=multiplier * food.protein_g,
        fat_g=multiplier * food.fat_g,
        carbs_g=multiplier * food.carbs_g,
    )
