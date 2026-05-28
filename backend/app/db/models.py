from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampsMixin, UuidPkMixin


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"


class ActivityLevel(StrEnum):
    SEDENTARY = "sedentary"
    LIGHT = "light"
    MODERATE = "moderate"
    ACTIVE = "active"
    VERY_ACTIVE = "very_active"


class Goal(StrEnum):
    LOSE = "lose"
    MAINTAIN = "maintain"
    GAIN = "gain"


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class InputSource(StrEnum):
    PHOTO = "photo"
    VOICE = "voice"
    TEXT = "text"
    BARCODE = "barcode"
    QUICK_ADD = "quick_add"


class FoodSource(StrEnum):
    CURATED = "curated"  # hand-seeded by team (regional cuisines, popular dishes)
    FATSECRET = "fatsecret"  # FatSecret API
    CUSTOM = "custom"  # user-generated (UGC)
    USER_RECIPE = "user_recipe"  # cooked dish saved by user via recipe-builder flow
    LLM_ESTIMATE = "llm_estimate"  # GPT-mini fallback estimate


class FoodMetric(StrEnum):
    """How a food is naturally measured.

    - GRAMS / MILLILITERS: nutrition values are stored per 100 units of this metric.
    - PIECE / SERVING: nutrition values are stored per 1 unit (one egg, one portion).
    """

    GRAMS = "g"  # per 100g (typical: meat, vegetables, grains)
    MILLILITERS = "ml"  # per 100ml (typical: milk, juice, oil)
    PIECE = "piece"  # per 1 piece (typical: egg, banana, slice of bread)
    SERVING = "serving"  # per 1 serving (typical: ready meal, fast food item)


class User(UuidPkMixin, TimestampsMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("telegram_id", name="uq_users_telegram_id"),)

    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str | None] = mapped_column(String(8))

    # Onboarding profile
    sex: Mapped[Sex | None] = mapped_column(String(16))
    weight_kg: Mapped[float | None] = mapped_column()
    height_cm: Mapped[float | None] = mapped_column()
    age: Mapped[int | None] = mapped_column(Integer)
    activity: Mapped[ActivityLevel | None] = mapped_column(String(16))
    goal: Mapped[Goal | None] = mapped_column(String(16))
    # Only filled when goal is LOSE / GAIN — the weight the user wants to reach.
    target_weight_kg: Mapped[float | None] = mapped_column()

    # Computed daily targets
    tdee_kcal: Mapped[int | None] = mapped_column(Integer)
    target_protein_g: Mapped[int | None] = mapped_column(Integer)
    target_fat_g: Mapped[int | None] = mapped_column(Integer)
    target_carbs_g: Mapped[int | None] = mapped_column(Integer)

    meals: Mapped[list["Meal"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    custom_foods: Mapped[list["Food"]] = relationship(back_populates="created_by")

    @property
    def is_onboarded(self) -> bool:
        return self.tdee_kcal is not None


class Meal(UuidPkMixin, TimestampsMixin, Base):
    __tablename__ = "meals"
    __table_args__ = (
        Index(
            "uq_meals_user_tg_msg",
            "user_id",
            "tg_message_id",
            unique=True,
            postgresql_where="tg_message_id IS NOT NULL",
        ),
        Index("ix_meals_user_type_eaten", "user_id", "meal_type", "eaten_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    meal_type: Mapped[MealType] = mapped_column(String(16), nullable=False)
    eaten_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    source: Mapped[InputSource] = mapped_column(String(16), nullable=False)
    raw_input: Mapped[str | None] = mapped_column(Text)
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)

    user: Mapped[User] = relationship(back_populates="meals")
    items: Mapped[list["MealItem"]] = relationship(
        back_populates="meal", cascade="all, delete-orphan", lazy="selectin"
    )


class MealItem(UuidPkMixin, TimestampsMixin, Base):
    __tablename__ = "meal_items"

    meal_id: Mapped[UUID] = mapped_column(
        ForeignKey("meals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    food_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # What the user said (snapshot of input)
    amount: Mapped[float] = mapped_column(nullable=False)  # e.g. 200, 1, 2.5
    unit: Mapped[FoodMetric] = mapped_column(
        String(16), nullable=False
    )  # g | ml | piece | serving

    # Canonical equivalent in grams (used for daily totals and analytics)
    weight_g: Mapped[float] = mapped_column(nullable=False)

    # Absolute nutrition for this item (already multiplied)
    kcal: Mapped[float] = mapped_column(nullable=False)
    protein_g: Mapped[float] = mapped_column(nullable=False)
    fat_g: Mapped[float] = mapped_column(nullable=False)
    carbs_g: Mapped[float] = mapped_column(nullable=False)

    food_id: Mapped[UUID | None] = mapped_column(ForeignKey("foods.id"))

    meal: Mapped[Meal] = relationship(back_populates="items")
    food: Mapped["Food | None"] = relationship()


class Food(UuidPkMixin, TimestampsMixin, Base):
    __tablename__ = "foods"
    __table_args__ = (
        # UNIQUE on barcode without WHERE — required for ON CONFLICT inference.
        # Multiple NULLs are allowed (Postgres treats each NULL as distinct).
        Index("uq_foods_barcode", "barcode", unique=True),
        Index("ix_foods_name", "name"),
        Index("ix_foods_brand", "brand"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    brand: Mapped[str | None] = mapped_column(String(128))
    barcode: Mapped[str | None] = mapped_column(String(32))
    cuisine: Mapped[str | None] = mapped_column(String(16))  # kz, ru, uz, ge, tr, ...

    # How this food is naturally measured.
    # Determines the meaning of the nutrition fields below:
    #   - g / ml  → per 100 units
    #   - piece / serving → per 1 unit
    metric: Mapped[FoodMetric] = mapped_column(String(16), nullable=False)
    kcal: Mapped[float] = mapped_column(nullable=False)
    protein_g: Mapped[float] = mapped_column(nullable=False)
    fat_g: Mapped[float] = mapped_column(nullable=False)
    carbs_g: Mapped[float] = mapped_column(nullable=False)

    # For PIECE / SERVING foods: typical grams of one piece — lets us convert
    # when the user says "200г яиц" or shows photo of half a portion.
    piece_weight_g: Mapped[float | None] = mapped_column()

    # Alternative servings (FatSecret-style), JSONB array:
    # [{"label": "1 ст.л.", "amount": 15, "unit": "g"},
    #  {"label": "1 стакан", "amount": 250, "unit": "ml"}]
    servings: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    source: Mapped[FoodSource] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(64))

    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[User | None] = relationship(back_populates="custom_foods")
